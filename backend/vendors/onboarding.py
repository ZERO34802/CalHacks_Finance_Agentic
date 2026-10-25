"""Vendor onboarding: verify a new vendor before it can ever be paid. Owner: D.

Checks (CRS for business identity, credit, public records and watchlists; code for the rest):
  1 Business identity      CRS Experian business search (US only)
  2 Business credit        CRS Intelliscore+
  3 Liens / judgments / bankruptcies   CRS public records (from the business search)
  4 Sanctions (OFAC)       CRS watchlist result
  5-8 Code checks, reused from A's backend/onboarding/checks.run_checks (the scored flow): duplicate tax ID /
      bank / domain, simulated sanctions list, bank vs employees (world employees in the store), look-alike
      domain, tax form, simulated domain age; plus a same-name duplicate check
Fail closed: a CRS timeout is retried once, then the check is "incomplete" and the vendor can't be approved
as low risk. Approvals: requester can never approve; medium/high risk needs a controller. Approved vendors
start on probation (tighter checks until their first deliveries are confirmed).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
from functools import lru_cache
from typing import Optional
from uuid import uuid4

from backend.core.config import ROOT, load_policy
from backend.store.base import Store
from backend.vendors.crs import CRS, LABEL, CRSUnavailable, personas
from contracts import Channel, OnboardingCase, OnboardingRequest, OnboardingRequestIn, VendorCheck, Vendor

DATA = ROOT / "data" / "onboarding"
HERE = Path(__file__).resolve().parent
HIGH_SPEND_USD = Decimal("1000000")


@lru_cache
def samples() -> list[dict]:
    """D's demo requests (CRS scenarios, backend/vendors/samples.json) + C's scored requests (data/onboarding/onb_*.json)."""
    out = json.loads((HERE / "samples.json").read_text())
    for s in out:  # D's demo requests: the tax form came with the tax ID
        r = s["request"]
        r.setdefault("tax_form", ("W-9" if r["country"] == "US" else "W-8BEN-E") if r.get("tax_id") else None)
    for p in sorted(DATA.glob("onb_*.json")):
        r = OnboardingRequest.model_validate_json(p.read_text())
        out.append({"label": f"{r.title} ({r.id})", "request": OnboardingRequestIn(
            legal_name=r.legal_name, country=r.country, currency=r.currency, tax_id=r.tax_id, tax_form=r.tax_form,
            trade_names=r.trade_names, email_domain=r.email_domain, website=r.email_domain, bank_last4=r.bank_last4,
            expected_annual_spend_usd=r.expected_annual_spend_usd or Decimal("0"),
            requested_by=r.requested_by).model_dump(mode="json")})
    return out


def _norm(name: str) -> str:
    """First two words of the name without legal suffixes: 'Penang Pack & Test Sdn Bhd' -> 'penang pack'."""
    return " ".join(re.sub(r"\b(inc|llc|ltd|co|corp|sdn|bhd|the)\b|[^a-z0-9 ]", " ", name.lower()).split()[:2])


IDENTITY = "Owner identity (TransUnion)"
FRAUD = "Contact fraud risk (AtData Fraud Finder)"
COURT = "Bankruptcies, liens, judgments (PitchPoint)"
PHONE = "Independent phone lookup (AccurateAppend)"
CREDIT = "Owner credit (Experian prequal, soft pull)"
IDENTITY_FAIL = {"2201", "2202", "2301"}  # SSN not this person's / DOB mismatch / deceased (TransUnion + CRS texts)


def crs_checks(req: OnboardingRequestIn, crs: CRS) -> list[VendorCheck]:
    """Verify the person behind the supplier through CRS. Thresholds in code; the vendor's text never decides."""
    label = LABEL.get(crs.mode, "CRS")
    sim = crs.mode != "sandbox"
    names = [IDENTITY, FRAUD, COURT, PHONE] + ([CREDIT] if req.credit_consent else [])
    pid = (req.principal_persona or "").upper().strip()
    if pid not in personas():
        return [VendorCheck(name=n, provider=label, status="not_covered", simulated=sim,
                            detail="No owner / authorized signer given: add one to run CRS identity, fraud and court-record "
                                   "checks (until then a controller reviews this vendor).") for n in names]
    products = ("tu_identity_verification", "fraud_finder", "pitchpoint_blj", "accurate_append") + (
        ("credit_report",) if req.credit_consent else ())
    rep, err = None, ""
    for attempt in (1, 2):  # fail closed: one retry, then "incomplete"
        try:
            rep = crs.check_principal(pid, products)
            break
        except CRSUnavailable as e:
            err = str(e)
    if rep is None:
        return [VendorCheck(name=n, provider=label, status="incomplete", simulated=sim,
                            detail=f"CRS unavailable after a retry ({err[:160]}). Verification incomplete: vendor stays on hold.")
                for n in names]
    who = f"{rep.name} (owner, sandbox persona {pid})"
    rid = lambda prod: f" · CRS RequestID {rep.request_ids[prod][:8]}" if rep.request_ids.get(prod) else ""  # noqa: E731
    out = []
    idv = rep.results.get("tu_identity_verification")
    if idv is None:
        out.append(VendorCheck(name=IDENTITY, provider=label, status="incomplete", simulated=sim, detail="No identity result."))
    else:
        codes = {m["code"] for m in idv["messages"]}
        texts = "; ".join(m["text"].capitalize() for m in idv["messages"][:3])
        status = "pass" if not codes else "fail" if codes & IDENTITY_FAIL else "warn"
        detail = (f"{who}: name, SSN, date of birth and address verify." if status == "pass" else
                  f"{who}: {texts}." + (" Step-up verification needed before approval." if "2401" in codes else ""))
        out.append(VendorCheck(name=IDENTITY, provider=label, status=status, simulated=sim, detail=detail + rid("tu_identity_verification")))
    ff = rep.results.get("fraud_finder")
    if ff is not None and ff.get("score") is not None:
        sc = int(ff["score"])
        ph = ff.get("phone") or {}
        flags = [x for x in (
            "phone not in the owner's name" if ph.get("owner_name_match") == "no_match" else "",
            f"{ph.get('line_type')} line" if ph.get("line_type") in ("voip", "nonFixedVoip") else "",
            "prepaid phone" if ph.get("prepaid") else "",
            f"IP {ff['postal']['ip_distance']} from the address" if (ff.get("postal") or {}).get("ip_distance", "").startswith(">") else "",
        ) if x]
        out.append(VendorCheck(name=FRAUD, provider=label, simulated=sim,
                               status="pass" if sc <= 40 else "warn" if sc < 70 else "fail",
                               detail=f"Risk score {sc}/100 (AtData: 70+ is high risk)" + (f"; {', '.join(flags)}" if flags else "")
                                      + "." + rid("fraud_finder")))
    blj = rep.results.get("pitchpoint_blj")
    if blj is not None:
        b, l, j = blj["bankruptcies"], blj["liens"], blj["judgments"]
        amt = ", ".join(x for x in (f"liens {blj['lien_amount']}" if blj.get("lien_amount") else "",
                                    f"judgments {blj['judgment_amount']}" if blj.get("judgment_amount") else "") if x)
        out.append(VendorCheck(name=COURT, provider=label, simulated=sim, status="fail" if b else "warn" if (l or j) else "pass",
                               detail=f"{b} bankruptcy(ies), {l} lien(s), {j} judgment(s) on civil court record"
                                      + (f" ({amt} USD)" if amt else "") + "." + rid("pitchpoint_blj")))
    aa = rep.results.get("accurate_append")
    if aa is not None:
        recs = aa.get("records") or []
        mine = [r for r in recs if r["name"].lower() == rep.name.lower()]
        out.append(VendorCheck(name=PHONE, provider=label, simulated=sim,
                               status="pass" if mine else "fail" if recs else "warn",
                               detail=(f"The owner's phone resolves to {rep.name} ({mine[0]['city']}, {mine[0]['state']}): usable for "
                                       "bank-change callbacks." if mine else
                                       f"The owner's phone belongs to {recs[0]['name']}, not {rep.name}." if recs else
                                       "No independent record for the owner's phone: verify the callback number another way.")
                                      + rid("accurate_append")))
    if req.credit_consent:
        cr = rep.results.get("credit_report")
        if cr is not None:
            score = int(cr["score"]) if cr.get("score") else None
            status = "fail" if cr.get("errors") else "warn" if score is None else \
                "pass" if score >= 670 else "warn" if score >= 580 else "fail"
            detail = (f"Bureau error: {cr['errors'][0]}" if cr.get("errors") else
                      "No credit file at Experian (thin or no history)." if score is None else
                      f"VantageScore 4.0: {score} (soft pull, owner consented).")
            out.append(VendorCheck(name=CREDIT, provider=label, status=status, simulated=sim, detail=detail + rid("credit_report")))
    return out


def run_checks(req: OnboardingRequestIn, store: Store, crs: CRS) -> list[VendorCheck]:
    out: list[VendorCheck] = []
    sim = crs.mode == "simulated"
    vendors = store.list_vendors()

    # 1-5: CRS sandbox on the owner / authorized signer
    out += crs_checks(req, crs)

    # 5-8: code checks, shared with the scored onboarding flow (A's backend/onboarding/checks.py)
    out += code_checks(req, store)
    return out


CODE_LABEL = {
    "duplicate_tax_id": "Duplicate vendor: tax ID", "duplicate_bank": "Duplicate vendor: bank account",
    "duplicate_domain": "Duplicate vendor: email domain", "sanctions_hit": "Sanctions list (simulated)",
    "bank_matches_employee": "Bank account vs employees", "lookalike_domain": "Email domain",
    "missing_tax_form": "Tax form", "invalid_tax_form": "Tax form", "domain_age": "Domain age (simulated)",
}
BLOCKING = {"Sanctions (OFAC)", "Sanctions list (simulated)", "Bank account vs employees", IDENTITY}


def _form(req: OnboardingRequestIn) -> Optional[str]:
    return req.tax_form or None


def as_request(req: OnboardingRequestIn, rid: str = "onb_ui", now: Optional[datetime] = None) -> OnboardingRequest:
    """D's UI form -> the canonical OnboardingRequest A's checks take."""
    return OnboardingRequest(id=rid, title=req.legal_name, received_at=now or datetime.now(timezone.utc),
                             requested_by=req.requested_by, legal_name=req.legal_name, trade_names=req.trade_names,
                             country=req.country, tax_id=req.tax_id, tax_form=_form(req), email_domain=req.email_domain,
                             bank_last4=req.bank_last4, currency=req.currency, channels=[Channel.email],
                             expected_annual_spend_usd=req.expected_annual_spend_usd)


def code_checks(req: OnboardingRequestIn, store: Store) -> list[VendorCheck]:
    """A's deterministic checks (duplicates, simulated sanctions, employee bank, look-alike domain, tax form,
    simulated domain age), shown as VendorChecks, plus a same-name duplicate check."""
    from backend.core.runner import make_ctx
    from backend.onboarding.checks import run_checks as a_checks
    out = []
    for c in a_checks(as_request(req), make_ctx(store)):
        out.append(VendorCheck(name=CODE_LABEL.get(c.name, c.name.replace("_", " ").capitalize()), provider="code",
                               status="pass" if c.passed else "fail", detail=c.detail, simulated=c.simulated))
    same = [v for v in store.list_vendors() if _norm(v.name) == _norm(req.legal_name)]
    out.append(VendorCheck(name="Duplicate vendor: name", provider="code", status="warn" if same else "pass",
                           detail=f"Similar name to existing vendor {same[0].name} ({same[0].id}); confirm it is a different company." if same
                           else "No existing vendor has this name."))
    return out


def risk_tier(checks: list[VendorCheck], req: OnboardingRequestIn) -> str:
    if any(c.status == "fail" for c in checks):
        return "high"
    if any(c.status in ("warn", "incomplete", "not_covered") for c in checks) or req.expected_annual_spend_usd >= HIGH_SPEND_USD:
        return "medium"
    return "low"


def submit(req: OnboardingRequestIn, store: Store, crs: CRS, now: datetime) -> OnboardingCase:
    checks = run_checks(req, store, crs)
    tier = risk_tier(checks, req)
    return OnboardingCase(id=f"onb_{uuid4().hex[:6]}", request=req, status="needs_review", checks=checks, risk_tier=tier,
                          needs="approver" if tier == "low" else "controller", crs_mode=crs.mode, created_at=now)


class OnboardingError(Exception):
    pass


ROLE_RANK = {"approver": 1, "controller": 2, "cfo": 3, "cto": 3}


def decide(case: OnboardingCase, approver: str, role: str, decision: str, comment: str, store: Store, now: datetime) -> OnboardingCase:
    if case.status != "needs_review":
        raise OnboardingError("Already decided.")
    if decision == "approved":
        if approver == case.request.requested_by:
            raise OnboardingError(f"{approver} requested this vendor and cannot approve it.")
        if ROLE_RANK.get(role, 0) < ROLE_RANK[case.needs]:
            raise OnboardingError(f"{case.risk_tier.capitalize()}-risk vendors need a {case.needs} to approve.")
        if any(c.status == "fail" and c.name in BLOCKING for c in case.checks):
            raise OnboardingError("Sanctions, employee-bank or owner-identity failures can't be approved. Reject, or escalate to compliance.")
        if any(c.status == "incomplete" for c in case.checks):
            raise OnboardingError("Verification incomplete (CRS unavailable). Re-run the checks first.")
        r = case.request
        base = vid = "V-" + re.sub(r"[^A-Z0-9]+", "", r.legal_name.upper())[:12]
        n = 2
        while store.get_vendor(vid) is not None:  # never overwrite an existing vendor master record (bank, terms)
            vid, n = f"{base}-{n}", n + 1
        days = int(load_policy().probation.get("days", 90))
        store.save_vendor(Vendor(id=vid, name=r.legal_name, aliases=r.trade_names, country=r.country, currency=r.currency,
                                 email_domain=r.email_domain, bank_last4=r.bank_last4, channels=[Channel.email],
                                 tax_id=r.tax_id, critical=False, on_probation=True, contact_email=r.contact_email,
                                 probation_until=(now + timedelta(days=days)).date()))
        case.vendor_id = vid
    case.status = decision
    case.decided_by, case.decided_at, case.decision_comment = approver, now, comment
    return case


def recheck(case: OnboardingCase, store: Store, crs: CRS) -> OnboardingCase:
    if case.status != "needs_review":
        raise OnboardingError("Already decided.")
    case.checks = run_checks(case.request, store, crs)
    case.risk_tier = risk_tier(case.checks, case.request)
    case.needs = "approver" if case.risk_tier == "low" else "controller"
    case.crs_mode = crs.mode
    return case
