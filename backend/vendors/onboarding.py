"""Vendor onboarding: verify a new vendor before it can ever be paid. Owner: D.

Checks (CRS for business identity, credit, public records and watchlists; code for the rest):
  1 Business identity      CRS Experian business search (US only)
  2 Business credit        CRS Intelliscore+
  3 Liens / judgments / bankruptcies   CRS public records (from the business search)
  4 Sanctions (OFAC)       CRS watchlist result
  5 Duplicate vendor       same tax ID / bank / name as an existing vendor
  6 Bank vs employees      vendor bank account matches an employee's
  7 Email domain           look-alike of an existing vendor's domain
  8 Tax form               W-9 (US) / W-8BEN-E (non-US) identifier present
Fail closed: a CRS timeout is retried once, then the check is "incomplete" and the vendor can't be approved
as low risk. Approvals: requester can never approve; medium/high risk needs a controller. Approved vendors
start on probation (tighter checks until their first deliveries are confirmed).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Optional
from uuid import uuid4

from backend.core.config import ROOT
from backend.review.checks import _edit_distance, _root
from backend.store.base import Store
from backend.vendors.crs import CRS, CRSUnavailable
from contracts import Channel, OnboardingCase, VendorCheck, OnboardingRequestIn, Vendor

DATA = ROOT / "data" / "onboarding"
HIGH_SPEND_USD = Decimal("1000000")


@lru_cache
def employees() -> list[dict]:
    return json.loads((DATA / "employees.json").read_text())


@lru_cache
def samples() -> list[dict]:
    return json.loads((DATA / "samples.json").read_text())


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

    # 5 duplicate vendor
    dup = []
    for v in vendors:
        why = []
        if req.tax_id and v.tax_id == req.tax_id:
            why.append("same tax ID")
        if v.bank_last4 == req.bank_last4:
            why.append("same bank account")
        if _norm(v.name) == _norm(req.legal_name):
            why.append("same name")
        if why:
            dup.append(f"{v.name} ({', '.join(why)})")
    out.append(VendorCheck(name="Duplicate vendor", provider="code", status="fail" if dup else "pass",
                               detail=("Matches existing vendor " + "; ".join(dup) + ".") if dup else "No existing vendor shares this tax ID, bank or name."))

    # 6 bank vs employees
    emp = [e for e in employees() if e["bank_last4"] == req.bank_last4]
    out.append(VendorCheck(name="Bank account vs employees", provider="code", status="fail" if emp else "pass",
                               detail=(f"Bank account •••• {req.bank_last4} belongs to employee {emp[0]['name']} ({emp[0]['email']}). Possible insider fraud.")
                               if emp else "No employee uses this bank account."))

    # 7 look-alike domain
    dom = req.email_domain.lower()
    close = [v for v in vendors if dom != v.email_domain.lower()
             and _edit_distance(_root(dom).replace("-", ""), _root(v.email_domain).replace("-", "")) <= 2]
    out.append(VendorCheck(name="Email domain", provider="code", status="fail" if close else "pass",
                               detail=(f"{dom} looks like {close[0].email_domain} ({close[0].name}). Look-alike domain.") if close
                               else f"{dom} doesn't imitate an existing vendor's domain. (Domain age: check not connected.)"))

    # 8 tax form
    form = "W-9" if req.country == "US" else "W-8BEN-E"
    out.append(VendorCheck(name="Tax form", provider="code", status="pass" if req.tax_id else "fail",
                               detail=f"{form} identifier {req.tax_id} on file." if req.tax_id else f"No tax ID: {form} not received."))
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
        if any(c.status == "fail" and c.name in ("Sanctions (OFAC)", "Bank account vs employees") for c in case.checks):
            raise OnboardingError("Sanctions or employee-bank matches can't be approved. Reject, or escalate to compliance.")
        if any(c.status == "incomplete" for c in case.checks):
            raise OnboardingError("Verification incomplete (CRS unavailable). Re-run the checks first.")
        r = case.request
        vid = "V-" + re.sub(r"[^A-Z0-9]+", "", r.legal_name.upper())[:12]
        store.save_vendor(Vendor(id=vid, name=r.legal_name, aliases=[], country=r.country, currency=r.currency,
                                 email_domain=r.email_domain, bank_last4=r.bank_last4, channels=[Channel.email],
                                 tax_id=r.tax_id, critical=False, on_probation=True))
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
