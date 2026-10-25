"""CRS Credit API (Cal Hacks sandbox) for vendor onboarding: verify the PERSON behind a new supplier. Owner: D.

Know-your-business practice verifies the supplier's owner / authorized signer. The CRS sandbox
(https://api-sandbox.stitchcredit.com/api) offers, per person:
  TransUnion TruValidate identity   POST /transunion/identity-manager-verification/basic
  AtData Fraud Finder               POST /fraud-finder/fraud-finder           (email / phone / address risk)
  PitchPoint bankruptcies/liens/judgments  POST /pp/fcrablj/data
  AccurateAppend reverse lookup     POST /accurate-append/reverse             (independent phone -> who it belongs to)
  Experian prequal credit (soft)    POST /experian/credit-report/standard/exp-prequal-vantage4   (only with consent)
The sandbox answers with canned results for 20 fake personas (backend/vendors/crs_personas.json, from CRS's
CalHacks MCP package) and forwards anything else to the real vendor, so ReconAI only ever sends a persona's exact
request bodies: the onboarding form picks the owner as a sandbox persona. No real person is ever looked up.

Two modes behind one interface:
- SandboxCRS (live): CRS_USERNAME + CRS_PASSWORD set. Logs in ONCE per process and reuses the token (repeated failed
  logins lock the account, so a failed login is never retried); a 401 re-logs once.
- RecordedCRS (offline / tests): replays real sandbox responses recorded by scripts/crs_record.py into
  backend/vendors/crs_recorded.json. Same parsing as live. RECONAI_CRS=off forces it.
Only minimised fields are kept (identity messages, fraud score, court-record counts, lookup name, credit score):
never raw credit files.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol

import httpx
from dotenv import load_dotenv

from backend.core.config import ROOT

load_dotenv(ROOT / ".env")

HERE = Path(__file__).resolve().parent
BASE = os.environ.get("CRS_BASE_URL") or "https://api-sandbox.stitchcredit.com/api"
PRODUCTS = ("tu_identity_verification", "fraud_finder", "pitchpoint_blj", "accurate_append", "credit_report")
LABEL = {"sandbox": "CRS sandbox", "recorded": "CRS sandbox (recorded responses)"}


class CRSUnavailable(Exception):
    """Timeout / outage / auth. Onboarding fails closed: the check is 'incomplete' and the vendor stays on hold."""


@lru_cache
def personas() -> dict[str, dict]:
    data = json.loads((HERE / "crs_personas.json").read_text())
    return {p["id"]: p for p in data["personas"]}


def persona_options() -> list[dict]:
    """For the onboarding forms: id, name, profile (what each test persona is designed to show)."""
    return [{"id": p["id"], "name": p["name"].title(), "profile": p["profile"], "decision": p.get("decision", "")}
            for p in personas().values()]


def request_for(persona_id: str, product: str) -> Optional[dict]:
    p = personas().get(persona_id)
    if p is None:
        return None
    for rq in p["requests"]:
        if rq["product"] != product:
            continue
        if product == "credit_report" and rq.get("variant") != "Experian":
            continue
        return rq
    return None


def minimize(product: str, body: dict) -> dict:
    """Keep only what the checks read (responsible data handling: no SSNs, no tradelines)."""
    if product == "tu_identity_verification":
        msgs = ((body.get("addOnProducts") or [{}])[0].get("idManagerVerification") or {}).get("messages") or []
        return {"messages": [{"code": str(m.get("code")), "text": str(m.get("text", ""))[:160]} for m in msgs]}
    if product == "fraud_finder":
        r = body.get("risk") or {}
        phone, postal = r.get("phone") or {}, r.get("postal") or {}
        owner = phone.get("owner") or {}
        return {"score": r.get("score"), "domain_risk": (r.get("domain") or {}).get("domain_risk_score"),
                "phone": {"line_type": phone.get("line_type"), "status": phone.get("status"),
                          "prepaid": phone.get("prepaid"), "owner_name_match": owner.get("last_name_match")},
                "postal": {"deliverability": postal.get("deliverability"),
                           "ip_distance": postal.get("ip_postal_distance")}}
    if product == "pitchpoint_blj":
        rep = body.get("DetailedBLJReport") or {}
        res = rep.get("Results") or {}

        def total(kind: str, key: str) -> Optional[str]:
            rec = (res.get(kind) or {}).get(kind[:-1] + "Record") if isinstance(res.get(kind), dict) else None
            recs = rec if isinstance(rec, list) else [rec] if rec else []
            vals = [r.get(key) for r in recs if isinstance(r, dict) and r.get(key) is not None]
            return str(sum(float(v) for v in vals)) if vals else None
        return {"bankruptcies": int(rep.get("BankruptciesFound") or 0), "liens": int(rep.get("LiensFound") or 0),
                "judgments": int(rep.get("JudgmentsFound") or 0),
                "lien_amount": total("Liens", "TotalLienAmount"), "judgment_amount": total("Judgments", "TotalJudgmentAmount")}
    if product == "accurate_append":
        recs = ((body.get("data") or {}).get("records")) or []
        return {"records": [{"name": f"{r.get('firstName', '')} {r.get('lastName', '')}".strip(),
                             "city": r.get("city"), "state": r.get("state")} for r in recs[:3]]}
    if product == "credit_report":
        errs = [str(e.get("creditErrorMessageText", ""))[:160] for e in (body.get("errorMessages") or [])]
        scores = [s.get("scoreValue") for s in (body.get("scores") or []) if s.get("scoreValue")]
        return {"errors": errs, "score": scores[0] if scores else None}
    return {}


@dataclass
class PrincipalReport:
    persona_id: str
    name: str
    results: dict[str, dict] = field(default_factory=dict)      # product -> minimised response
    request_ids: dict[str, str] = field(default_factory=dict)   # product -> CRS RequestID (audit / debug)


class CRS(Protocol):
    mode: str
    def check_principal(self, persona_id: str, products: tuple[str, ...]) -> PrincipalReport: ...


class SandboxCRS:
    mode = "sandbox"

    def __init__(self) -> None:
        self.user, self.password = os.environ["CRS_USERNAME"], os.environ["CRS_PASSWORD"]
        self._http = httpx.Client(timeout=float(os.environ.get("CRS_TIMEOUT", "25")))
        self._token: Optional[str] = None
        self._login_failed: Optional[str] = None
        self._lock = threading.Lock()

    def _login(self) -> str:
        with self._lock:
            if self._login_failed:  # never retry a failed login: repeated failures lock the account
                raise CRSUnavailable(f"CRS login failed earlier ({self._login_failed}); fix credentials and restart")
            if self._token is None:
                try:
                    r = self._http.post(BASE + "/users/login", json={"username": self.user, "password": self.password})
                except httpx.HTTPError as e:
                    raise CRSUnavailable(f"login: {type(e).__name__}") from e
                if r.status_code != 200 or not r.json().get("token"):
                    self._login_failed = f"HTTP {r.status_code}"
                    raise CRSUnavailable(f"CRS login failed (HTTP {r.status_code}); not retrying")
                self._token = r.json()["token"]
            return self._token

    def _call(self, rq: dict) -> tuple[dict, str]:
        path = rq["path"].replace("{config}", rq.get("config") or "")
        for attempt in (1, 2):
            h = {"Authorization": f"Bearer {self._login()}", "Content-Type": "application/json", "Accept": "application/json"}
            try:
                r = self._http.request(rq["method"], BASE + path, headers=h, json=rq.get("body"))
            except httpx.HTTPError as e:
                raise CRSUnavailable(f"{path}: {type(e).__name__}") from e
            if r.status_code == 401 and attempt == 1:  # token expired: log in again once
                self._token = None
                continue
            if r.status_code >= 500 or r.status_code == 429:
                raise CRSUnavailable(f"{path}: HTTP {r.status_code}")
            if r.status_code >= 400:
                raise CRSUnavailable(f"{path}: HTTP {r.status_code} (is the product enabled on the account?)")
            return r.json(), r.headers.get("RequestID", "")
        raise CRSUnavailable(f"{path}: unauthorised")

    def check_principal(self, persona_id: str, products: tuple[str, ...] = PRODUCTS) -> PrincipalReport:
        p = personas()[persona_id]
        rep = PrincipalReport(persona_id=persona_id, name=p["name"].title())
        for prod in products:
            rq = request_for(persona_id, prod)
            if rq is None:
                continue
            body, rid = self._call(rq)
            rep.results[prod], rep.request_ids[prod] = minimize(prod, body), rid
        return rep


class RecordedCRS:
    """Offline: real sandbox responses recorded by scripts/crs_record.py (minimised)."""
    mode = "recorded"

    @staticmethod
    @lru_cache
    def _data() -> dict:
        path = HERE / "crs_recorded.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def check_principal(self, persona_id: str, products: tuple[str, ...] = PRODUCTS) -> PrincipalReport:
        p = personas()[persona_id]
        rec = self._data().get(persona_id) or {}
        rep = PrincipalReport(persona_id=persona_id, name=p["name"].title())
        for prod in products:
            if prod in rec:
                rep.results[prod] = rec[prod]["result"]
                rep.request_ids[prod] = rec[prod].get("request_id", "recorded")
        return rep


_crs: Optional[CRS] = None


def make_crs() -> CRS:
    """The live sandbox when CRS credentials are set (and RECONAI_CRS isn't 'off'), else recorded responses."""
    global _crs
    if os.environ.get("RECONAI_CRS", "").lower() == "off" or not (os.environ.get("CRS_USERNAME") and os.environ.get("CRS_PASSWORD")):
        return RecordedCRS()
    if _crs is None or not isinstance(_crs, SandboxCRS):
        _crs = SandboxCRS()
    return _crs


def set_crs(crs: Optional[CRS]) -> None:  # tests
    global _crs
    _crs = crs
