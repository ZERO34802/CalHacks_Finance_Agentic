"""Decision logic in code (data/FORMATS.md "Decision semantics"). Owner: B.

The agent explains; this module decides. Router, Investigator, Approver and Vendor Guard
all use the same table so they never disagree.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from backend.core.config import Policy
from contracts import Case, CaseStatus, Decision, Discrepancy, DiscrepancyType as T

UNKNOWN_VENDOR = "V-UNKNOWN"

HOLD_TYPES = {T.qty_short, T.price_over, T.unapproved_freight, T.currency_mismatch, T.fx_gap, T.total_mismatch}
REJECT_TYPES = {T.duplicate_invoice}
VENDOR_RISK_TYPES = {T.bank_change, T.lookalike_domain}
ESCALATE_TYPES = VENDOR_RISK_TYPES | {T.embedded_instructions, T.unknown_po, T.missing_receipt}
# Logged, never an exception by themselves: below materiality auto-accepts, over_limit routes to
# the controller, locked_period posts to the current period with a note (Poster).
INFO_TYPES = {T.below_materiality, T.over_limit, T.locked_period}

# Severity order. The agent may only move a recommendation up this list, never down.
RANK = {Decision.approve: 0, Decision.hold: 1, Decision.reject: 2, Decision.escalate: 3}

SKILL_EVENTS = {"three_way_match": HOLD_TYPES, "bank_change": VENDOR_RISK_TYPES}


def material(case: Case) -> list[Discrepancy]:
    return [d for d in case.discrepancies if d.material and d.type not in INFO_TYPES]


def embedded_instructions(case: Case) -> bool:
    flagged = bool(case.invoice and "embedded_instructions" in case.invoice.flags)
    return flagged or any(d.type == T.embedded_instructions for d in case.discrepancies)


def policy_recommendation(case: Case) -> tuple[Decision, list[str]]:
    """The floor every proposal starts from. Highest severity wins."""
    reasons: list[tuple[Decision, str]] = []
    if case.status == CaseStatus.quarantined:
        reasons.append((Decision.escalate, f"quarantined: {case.quarantine_reason or 'ingest validation'}"))
    if embedded_instructions(case):
        reasons.append((Decision.escalate, "embedded instructions in a document"))
    if case.vendor_id == UNKNOWN_VENDOR:
        reasons.append((Decision.escalate, "unknown vendor"))
    if case.invoice is None:
        reasons.append((Decision.escalate, "evidence missing: no extracted invoice"))
    for d in material(case):
        if d.type in ESCALATE_TYPES:
            reasons.append((Decision.escalate, d.type.value))
        elif d.type in REJECT_TYPES:
            reasons.append((Decision.reject, d.type.value))
        elif d.type in HOLD_TYPES:
            reasons.append((Decision.hold, d.type.value))
        else:  # a type nobody mapped: never guess
            reasons.append((Decision.escalate, f"unmapped discrepancy {d.type.value}"))
    if not reasons:
        return Decision.approve, ["clean or below materiality"]
    top = max(reasons, key=lambda r: RANK[r[0]])[0]
    return top, [r for d, r in reasons if d == top]


def cap(policy_rec: Decision, agent_rec: Optional[Decision]) -> Decision:
    """Cannot-downgrade rule. The agent may escalate further, never lower the floor.

    An agent 'reject' on a non-duplicate is not a policy outcome; it becomes 'escalate' (needs a human).
    """
    if agent_rec is None:
        return policy_rec
    if agent_rec == Decision.reject and policy_rec != Decision.reject:
        agent_rec = Decision.escalate
    if policy_rec == Decision.reject and agent_rec == Decision.hold:
        return policy_rec
    return agent_rec if RANK[agent_rec] > RANK[policy_rec] else policy_rec


def route(case: Case, policy: Policy, extra: list[Discrepancy] = ()) -> tuple[Optional[str], str]:
    """Pick a skill by event type, in code. Returns (skill or None, reason). Documents never choose."""
    types = {d.type for d in material(case)} | {d.type for d in extra if d.material}
    if case.status == CaseStatus.quarantined:
        return None, "quarantined: no skill, escalate"
    if embedded_instructions(case):
        return None, "embedded instructions: no agent touches this case, escalate"
    if types & VENDOR_RISK_TYPES:
        return policy.skills.get("bank_change"), "vendor risk (bank change / look-alike domain)"
    if case.vendor_id == UNKNOWN_VENDOR:
        return None, "unknown vendor: no skill, escalate"
    if types & REJECT_TYPES:
        return None, "duplicate invoice: no skill, reject path"
    if not types:
        return None, "clean"
    if types <= HOLD_TYPES:
        return policy.skills.get("three_way_match"), "3-way match exception"
    return None, f"no skill for {sorted(t.value for t in types - HOLD_TYPES)}: escalate"


def usd(amount: Decimal, currency: str, policy: Policy) -> Optional[Decimal]:
    rate = policy.fx_rates.get(currency)
    return None if rate is None else amount * rate
