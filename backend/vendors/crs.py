"""CRS Credit API client for vendor onboarding. Owner: D (Vendor Guard integration point for A).

Two implementations behind one interface:
- LiveCRS: talks to CRS over HTTPS. Endpoints from the CRS developer portal (crscreditapi.redoc.ly):
    POST /users/login            {username, password} -> {token, expires, refreshToken}
    POST /ccc/exp/search         Experian business search {name, street, city, state, zip, phone, taxId}
    POST /ccc/exp/score          Experian Intelliscore+ {bin}
  The portal does not publish the base URL or the auth header, so both are configuration
  (CRS_BASE_URL, CRS_AUTH_HEADER, CRS_AUTH_SCHEME). Response field mapping is best-effort and must be
  confirmed against a sandbox response before production use.
- SimulatedCRS: a deterministic sandbox with fictional test businesses, used when CRS_BASE_URL is unset.
  Everything it returns is labelled simulated in the UI.

Coverage: CRS business credit is built on US bureaus. Non-US vendors come back "not covered" and need
manual documents (registry extract, bank letter) instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx


class CRSUnavailable(Exception):
    """Timeout / outage. Onboarding fails closed: the vendor stays unverified."""


@dataclass
class BusinessResult:
    found: bool
    bin: Optional[str] = None
    legal_name: Optional[str] = None
    years_in_business: Optional[int] = None
    ofac_hit: bool = False
    ofac_detail: str = ""
    liens: int = 0
    judgments: int = 0
    bankruptcies: int = 0
    raw: dict = field(default_factory=dict)


@dataclass
class ScoreResult:
    score: Optional[int]          # Intelliscore+ 1-100, higher = lower risk
    risk_class: str = ""


class CRS(Protocol):
    mode: str
    def business_search(self, name: str, street: str, city: str, state: str, zip: str, phone: str, tax_id: Optional[str]) -> BusinessResult: ...
    def business_score(self, bin: str) -> ScoreResult: ...


class LiveCRS:
    mode = "live"

    def __init__(self) -> None:
        self.base = os.environ["CRS_BASE_URL"].rstrip("/")
        self.user = os.environ.get("CRS_USERNAME", "")
        self.password = os.environ.get("CRS_PASSWORD", "")
        self.header = os.environ.get("CRS_AUTH_HEADER", "Authorization")
        self.scheme = os.environ.get("CRS_AUTH_SCHEME", "Bearer")
        self._token: Optional[str] = None
        self._http = httpx.Client(timeout=float(os.environ.get("CRS_TIMEOUT", "15")))

    def _auth(self) -> dict:
        if self._token is None:
            r = self._post("/users/login", {"username": self.user, "password": self.password}, auth=False)
            self._token = r.get("token")
            if not self._token:
                raise CRSUnavailable("CRS login returned no token")
        return {self.header: f"{self.scheme} {self._token}".strip()}

    def _post(self, path: str, body: dict, auth: bool = True) -> dict:
        try:
            r = self._http.post(self.base + path, json=body, headers=self._auth() if auth else {})
        except httpx.HTTPError as e:
            raise CRSUnavailable(f"{path}: {type(e).__name__}") from e
        if r.status_code >= 500 or r.status_code == 429:
            raise CRSUnavailable(f"{path}: HTTP {r.status_code}")
        r.raise_for_status()
        return r.json()

    def business_search(self, name, street, city, state, zip, phone, tax_id) -> BusinessResult:
        body = {"name": name, "street": street, "city": city, "state": state, "zip": zip, "phone": phone, "taxId": tax_id or ""}
        raw = self._post("/ccc/exp/search", body)
        hit = _first(raw, ("results", "businesses", "data")) or raw
        bin_ = str(hit.get("bin") or hit.get("BIN") or "") or None
        ofac_count = int(_deep(raw, "ofacCount") or 0)
        return BusinessResult(found=bool(bin_), bin=bin_, legal_name=hit.get("businessName") or hit.get("name"),
                              years_in_business=_int(_deep(raw, "yearsInBusiness")), ofac_hit=ofac_count > 0,
                              ofac_detail=str(_deep(raw, "ofacValue") or ""), liens=_int(_deep(raw, "liensCount")) or 0,
                              judgments=_int(_deep(raw, "judgmentsCount")) or 0, bankruptcies=_int(_deep(raw, "bankruptcyCount")) or 0,
                              raw=raw)

    def business_score(self, bin: str) -> ScoreResult:
        raw = self._post("/ccc/exp/score", {"bin": bin})
        return ScoreResult(score=_int(_deep(raw, "score")), risk_class=str(_deep(raw, "riskClass") or ""))


# Fictional sandbox businesses (by tax ID). Not real companies.
_SANDBOX: dict[str, dict] = {
    "US-77-4012339": dict(bin="790011223", legal_name="Bayline Precision Machining Inc", years=14, score=81),
    "US-36-8820415": dict(bin="790044551", legal_name="Northgate Components Trading LLC", years=1, score=22, ofac=True,
                          ofac_detail="Name and address match an entry on the (simulated) SDN list"),
    "US-61-2287730": dict(bin="790077102", legal_name="Ridgeview Consulting LLC", years=2, score=48),
    "US-82-5521904": dict(bin="790088310", legal_name="Kestrel Memory Americas Inc", years=0, score=30, liens=1),
    "US-45-9900127": dict(bin="790099001", legal_name="Granite Peak Logistics LLC", years=6, score=35, liens=2, judgments=1, bankruptcies=1),
}
_TIMEOUT_IDS = {"US-00-0000000"}


class SimulatedCRS:
    mode = "simulated"

    def business_search(self, name, street, city, state, zip, phone, tax_id) -> BusinessResult:
        if tax_id in _TIMEOUT_IDS:
            raise CRSUnavailable("sandbox timeout (simulated)")
        rec = _SANDBOX.get(tax_id or "")
        if rec is None:
            return BusinessResult(found=False)
        return BusinessResult(found=True, bin=rec["bin"], legal_name=rec["legal_name"], years_in_business=rec["years"],
                              ofac_hit=rec.get("ofac", False), ofac_detail=rec.get("ofac_detail", ""),
                              liens=rec.get("liens", 0), judgments=rec.get("judgments", 0), bankruptcies=rec.get("bankruptcies", 0))

    def business_score(self, bin: str) -> ScoreResult:
        rec = next((r for r in _SANDBOX.values() if r["bin"] == bin), None)
        s = rec["score"] if rec else None
        return ScoreResult(score=s, risk_class="" if s is None else "low" if s >= 70 else "medium" if s >= 40 else "high")


def make_crs() -> CRS:
    return LiveCRS() if os.environ.get("CRS_BASE_URL") else SimulatedCRS()


def _first(d: dict, keys) -> Optional[dict]:
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, list) and v:
            return v[0]
    return None


def _deep(d, key):
    """First value for `key` anywhere in a nested JSON response."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            found = _deep(v, key)
            if found is not None:
                return found
    elif isinstance(d, list):
        for v in d:
            found = _deep(v, key)
            if found is not None:
                return found
    return None


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
