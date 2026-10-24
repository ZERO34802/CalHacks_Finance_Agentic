"""Vendor onboarding approval flow + probation (CLAUDE.md 10d steps 4-7). Owner: B. Checks are A's (checks.py).

request -> checks (A) -> risk tier -> approvals (SoD) -> activate on probation, or hold with reasons.
- Requests start inside (OnboardingRequest.requested_by is a Helix employee); vendors never self-sign-up.
- Any failed check -> hold (no activation), callback / documents requested by a human.
- Approvals (SIMULATED people, decided by code): the requester can't approve, the agent can't approve,
  a vendor-master change always needs two different people, high risk needs the controller.
- Activate: Vendor record (aliases, contact on file, on_probation, probation_until = as_of + policy.probation.days).
- Stored as record kind 'onboarding', key = request id.
"""
from __future__ import annotations

import re
from decimal import Decimal
from datetime import timedelta
from typing import Callable, Optional

from backend.core.stage import Ctx
from contracts import (Approval, ApprovalDecision, Decision, OnboardingCheck, OnboardingRequest, OnboardingResult,
                       Role, Vendor)

AGENT = "agent:onboarding"
VENDOR_MASTER = [("vm.clerk@helix.example", Role.approver), ("d.ortiz@helix.example", Role.approver),
                 ("ap.backup@helix.example", Role.approver)]
CONTROLLERS = [("m.chen@helix.example", Role.controller), ("controller.backup@helix.example", Role.controller)]
HIGH_RISK_FLAGS = {"sanctions_hit", "duplicate_tax_id", "duplicate_bank", "bank_matches_employee",
                   "lookalike_domain", "duplicate_domain"}
HIGH_RISK_COUNTRIES: set[str] = set()   # SIMULATED; sanctions screening is a check, not a country list
Checker = Callable[[OnboardingRequest, Ctx], list[OnboardingCheck]]


def default_checks(req: OnboardingRequest, ctx: Ctx) -> list[OnboardingCheck]:
    from backend.onboarding.checks import run_checks  # A's checks
    return run_checks(req, ctx)


def risk_tier(req: OnboardingRequest, flags: list[str], ctx: Ctx) -> str:
    spend = req.expected_annual_spend_usd or Decimal(0)
    lim = ctx.policy.approval_limits
    if set(flags) & HIGH_RISK_FLAGS or req.country in HIGH_RISK_COUNTRIES or spend > lim["controller"]:
        return "high"
    if flags or spend > lim["approver"]:
        return "medium"
    return "low"


def _pick(people: list[tuple[str, Role]], exclude: set[str]) -> Optional[tuple[str, Role]]:
    return next((p for p in people if p[0] not in exclude and not p[0].startswith("agent:")), None)


def vendor_id_for(req: OnboardingRequest, ctx: Ctx) -> str:
    base = re.sub(r"[^A-Z0-9]", "", req.legal_name.split()[0].upper())[:10] or "NEW"
    vid, n = f"V-{base}", 2
    while ctx.store.get_vendor(vid) is not None:
        vid, n = f"V-{base}{n}", n + 1
    return vid


def onboard(req: OnboardingRequest, ctx: Ctx, checks: Checker = default_checks) -> OnboardingResult:
    as_of = req.received_at.date()
    res = OnboardingResult(request_id=req.id)
    res.checks = checks(req, ctx)
    res.flags = [c.name for c in res.checks if not c.passed]
    res.risk_tier = risk_tier(req, res.flags, ctx)
    if req.requested_by.startswith("agent:"):
        res.flags.append("agent_requested")
    if res.flags:
        res.decision = Decision.hold
        res.notes.append("held: " + ", ".join(res.flags) + "; no activation. Verify via callback to an independent "
                         "number and collect missing documents.")
        ctx.store.put_record("onboarding", req.id, res, idx=req.requested_by)
        return res

    used = {req.requested_by, AGENT}
    at = req.received_at
    first = _pick(VENDOR_MASTER, used)
    used.add(first[0])
    # vendor-master change: always a second person; high risk: that second person is the controller
    second = _pick(CONTROLLERS if res.risk_tier == "high" else VENDOR_MASTER + CONTROLLERS, used)
    for who, role in (first, second):
        res.approvals.append(Approval(id=f"onb_{req.id}_{len(res.approvals)}", case_id=req.id, approver=who,
                                      role=role, decision=ApprovalDecision.approved, scope="vendor_master",
                                      comment="[simulated] checks passed; requester and agent excluded", at=at))
    days = int(ctx.policy.probation.get("days", 90))
    vendor = Vendor(id=vendor_id_for(req, ctx), name=req.legal_name, aliases=req.trade_names, country=req.country,
                    currency=req.currency, email_domain=req.email_domain, bank_last4=req.bank_last4,
                    channels=req.channels, tax_id=req.tax_id, on_probation=True,
                    probation_until=as_of + timedelta(days=days), contact_email=None)
    ctx.store.save_vendor(vendor)
    res.decision, res.vendor_id, res.probation_until = Decision.approve, vendor.id, vendor.probation_until
    res.notes.append(f"activated {vendor.id} on probation until {vendor.probation_until}; channels configured by a "
                     "human; contact on file to be verified")
    ctx.store.put_record("onboarding", req.id, res, idx=req.requested_by)
    return res
