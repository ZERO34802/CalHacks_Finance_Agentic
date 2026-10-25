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
from backend.vendors.crs import CRS, CRSUnavailable
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


def run_checks(req: OnboardingRequestIn, store: Store, crs: CRS) -> list[VendorCheck]:
    out: list[VendorCheck] = []
    sim = crs.mode == "simulated"
    vendors = store.list_vendors()

    # 1-4: CRS
    if req.country != "US":
        for name in ("Business identity", "Business credit", "Liens, judgments, bankruptcies", "Sanctions (OFAC)"):
            out.append(VendorCheck(name=name, provider="CRS", status="not_covered", simulated=sim,
                                       detail=f"CRS business data covers US businesses; {req.country} needs a registry extract, "
                                              "bank letter and manual sanctions screening."))
    else:
        biz = None
        for attempt in (1, 2):
            try:
                biz = crs.business_search(req.legal_name, req.address, req.city, req.state, req.zip, req.contact_phone, req.tax_id)
                break
            except CRSUnavailable as e:
                err = str(e)
        if biz is None:
            for name in ("Business identity", "Business credit", "Liens, judgments, bankruptcies", "Sanctions (OFAC)"):
                out.append(VendorCheck(name=name, provider="CRS", status="incomplete", simulated=sim,
                                           detail=f"CRS unavailable after a retry ({err}). Verification incomplete: vendor stays on hold."))
        else:
            if biz.found:
                years = biz.years_in_business
                out.append(VendorCheck(name="Business identity", provider="CRS", simulated=sim,
                                           status="pass" if (years or 0) >= 2 else "warn",
                                           detail=f"Found {biz.legal_name} (BIN {biz.bin}), {years if years is not None else '?'} year(s) in business."
                                                  + (" Very new registration." if (years or 0) < 2 else "")))
                score = crs.business_score(biz.bin) if biz.bin else None
                s = score.score if score else None
                out.append(VendorCheck(name="Business credit", provider="CRS", simulated=sim,
                                           status="pass" if s is not None and s >= 70 else "warn" if s is not None and s >= 40 else "fail",
                                           detail=f"Intelliscore+ {s if s is not None else 'unavailable'}/100"
                                                  + (f" ({score.risk_class} risk)" if score and score.risk_class else "") + "."))
                pr = biz.liens + biz.judgments + biz.bankruptcies
                out.append(VendorCheck(name="Liens, judgments, bankruptcies", provider="CRS", simulated=sim,
                                           status="fail" if biz.bankruptcies else "warn" if pr else "pass",
                                           detail=f"{biz.liens} lien(s), {biz.judgments} judgment(s), {biz.bankruptcies} bankruptcy(ies) on public record."))
                out.append(VendorCheck(name="Sanctions (OFAC)", provider="CRS", simulated=sim,
                                           status="fail" if biz.ofac_hit else "pass",
                                           detail=biz.ofac_detail or ("Possible watchlist match." if biz.ofac_hit else "No watchlist match.")))
            else:
                out.append(VendorCheck(name="Business identity", provider="CRS", status="fail", simulated=sim,
                                           detail="No business on record for this name and tax ID. Possible shell or typo."))
                for name in ("Business credit", "Liens, judgments, bankruptcies"):
                    out.append(VendorCheck(name=name, provider="CRS", status="warn", simulated=sim, detail="No credit file (business not found)."))
                out.append(VendorCheck(name="Sanctions (OFAC)", provider="CRS", status="warn", simulated=sim,
                                           detail="Not screened: business not found. Screen manually."))

    # 5-8: code checks, shared with the scored onboarding flow (A's backend/onboarding/checks.py)
    out += code_checks(req, store)
    return out


CODE_LABEL = {
    "duplicate_tax_id": "Duplicate vendor: tax ID", "duplicate_bank": "Duplicate vendor: bank account",
    "duplicate_domain": "Duplicate vendor: email domain", "sanctions_hit": "Sanctions list (simulated)",
    "bank_matches_employee": "Bank account vs employees", "lookalike_domain": "Email domain",
    "missing_tax_form": "Tax form", "invalid_tax_form": "Tax form", "domain_age": "Domain age (simulated)",
}
BLOCKING = {"Sanctions (OFAC)", "Sanctions list (simulated)", "Bank account vs employees"}


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


ROLE_RANK = {"approver": 1, "controller": 2, "cfo": 3}


def decide(case: OnboardingCase, approver: str, role: str, decision: str, comment: str, store: Store, now: datetime) -> OnboardingCase:
    if case.status != "needs_review":
        raise OnboardingError("Already decided.")
    if decision == "approved":
        if approver == case.request.requested_by:
            raise OnboardingError(f"{approver} requested this vendor and cannot approve it.")
        if ROLE_RANK.get(role, 0) < ROLE_RANK[case.needs]:
            raise OnboardingError(f"{case.risk_tier.capitalize()}-risk vendors need a {case.needs} to approve.")
        if any(c.status == "fail" and c.name in BLOCKING for c in case.checks):
            raise OnboardingError("Sanctions or employee-bank matches can't be approved. Reject, or escalate to compliance.")
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
