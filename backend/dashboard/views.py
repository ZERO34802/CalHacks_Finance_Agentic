"""Dashboard read models: approval queue priority, business metrics, failures panel. Owner: D.

Pure functions over Store data; no writes. All money is Decimal, converted to USD
with the simulated policy FX table. Ranking weights are plain integers so every
position in the queue can be explained by its `reasons`.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from backend.core.config import Policy
from backend.store.base import Store
from contracts import (DashboardMetrics, Case, CaseStatus, Decision, FailureItem, QueueItem, StageStat, StepStatus,
                       VendorExceptions)

CLOSED = {CaseStatus.posted, CaseStatus.resolved, CaseStatus.rejected}
EXCEPTION_DECISIONS = {Decision.hold, Decision.reject, Decision.escalate}
FAILURE_STATUSES = {StepStatus.failed, StepStatus.blocked, StepStatus.escalated, StepStatus.retried}

AT_RISK_DAYS = 7
# ESTIMATE, shown on the dashboard: manual AP minutes per case (clean match vs exception work-up)
MINUTES_CLEAN = 15
MINUTES_EXCEPTION = 90


def _usd(amount: Decimal, currency: str, policy: Policy) -> Decimal:
    return (amount * policy.fx_rates[currency]).quantize(Decimal("0.01"))


def _due_points(days: int) -> tuple[int, str]:
    if days < 0:
        return 50, f"overdue by {-days}d"
    if days <= 3:
        return 40, f"due in {days}d"
    if days <= AT_RISK_DAYS:
        return 25, f"due in {days}d"
    if days <= 14:
        return 10, f"due in {days}d"
    return 0, ""


def _amount_points(usd: Decimal) -> tuple[int, str]:
    for floor, pts in ((Decimal(1_000_000), 30), (Decimal(100_000), 20), (Decimal(10_000), 10)):
        if usd >= floor:
            return pts, f"${usd:,.0f} USD"
    return 0, ""


def approval_queue(store: Store, policy: Policy, today: date) -> list[QueueItem]:
    """Open cases, highest priority first: due date, amount, supplier criticality, needs-a-human."""
    vendors = {v.id: v for v in store.list_vendors()}
    items = []
    for case in store.list_cases():
        if case.status in CLOSED or case.status == CaseStatus.approved:
            continue
        vendor = vendors.get(case.vendor_id)
        inv = case.invoice
        priority, reasons = 0, []
        usd = days = None
        if inv is not None:
            usd = _usd(inv.total, inv.currency, policy)
            pts, why = _amount_points(usd)
            priority += pts
            reasons += [why] if why else []
            if inv.due_date is not None:
                days = (inv.due_date - today).days
                pts, why = _due_points(days)
                priority += pts
                reasons += [why] if why else []
        if vendor and vendor.critical:
            priority += 20
            reasons.append("critical supplier")
        if case.status == CaseStatus.escalated:
            priority += 10
            reasons.append("escalated to a human")
        items.append(QueueItem(
            case_id=case.id, vendor_id=case.vendor_id, vendor_name=vendor.name if vendor else case.vendor_id,
            status=case.status, decision=case.decision,
            invoice_no=inv.invoice_no if inv else None, total=inv.total if inv else None,
            currency=inv.currency if inv else None, total_usd=usd,
            due_date=inv.due_date if inv else None, days_to_due=days,
            at_risk=days is not None and days <= AT_RISK_DAYS,
            critical_vendor=bool(vendor and vendor.critical), priority=priority, reasons=reasons))
    return sorted(items, key=lambda i: (-i.priority, i.days_to_due if i.days_to_due is not None else 10**6, i.case_id))


def _exposure_usd(case: Case, policy: Policy) -> Decimal:
    """What holding this case protects: the sum of discrepancy deltas if known, else the whole invoice."""
    inv = case.invoice
    if inv is None:
        return Decimal(0)
    deltas = [abs(d.delta) for d in case.discrepancies if d.delta is not None]
    return _usd(sum(deltas, Decimal(0)) if deltas else inv.total, inv.currency, policy)


def business_metrics(store: Store, policy: Policy) -> DashboardMetrics:
    vendors = {v.id: v for v in store.list_vendors()}
    cases = store.list_cases()
    exceptions = [c for c in cases if c.decision in EXCEPTION_DECISIONS]
    handled = [c for c in cases if c.decision is not None]

    minutes = sum(MINUTES_EXCEPTION if c.decision in EXCEPTION_DECISIONS else MINUTES_CLEAN for c in handled)

    posted = [c for c in cases if c.journal_entry and c.invoice and c.invoice.due_date]
    on_time = sum(c.journal_entry.date <= c.invoice.due_date for c in posted)

    closed = [c for c in cases if c.status in CLOSED and c.updated_at]
    hours = [(c.updated_at - c.created_at).total_seconds() / 3600 for c in closed]

    per_case = Counter(c.vendor_id for c in cases)
    per_exc = Counter(c.vendor_id for c in exceptions)
    by_vendor = [VendorExceptions(vendor_id=vid, vendor_name=vendors[vid].name if vid in vendors else vid,
                                  cases=n, exceptions=per_exc[vid])
                 for vid, n in sorted(per_case.items(), key=lambda kv: (-per_exc[kv[0]], kv[0]))]

    return DashboardMetrics(
        cases=len(cases), exceptions=len(exceptions),
        dollars_caught_usd=sum((_exposure_usd(c, policy) for c in exceptions), Decimal("0.00")),
        hours_saved_estimate=(Decimal(minutes) / 60).quantize(Decimal("0.1"), ROUND_HALF_UP),
        on_time_payment_rate=round(on_time / len(posted), 4) if posted else None,
        avg_hours_to_resolve=round(sum(hours) / len(hours), 1) if hours else None,
        by_vendor=by_vendor,
        assumptions=[
            "FX is the simulated fixed table in config/policy.yaml",
            "Dollars caught = discrepancy deltas when known, else the full invoice held",
            f"Hours saved is an ESTIMATE: {MINUTES_CLEAN} min per clean case, "
            f"{MINUTES_EXCEPTION} min per exception, done manually",
            "On-time = journal entry dated on or before the invoice due date",
        ])


def failures(store: Store, case_id: Optional[str] = None) -> list[FailureItem]:
    """Non-ok steps from each case's latest run, with the step that ran next."""
    out = []
    ids = [case_id] if case_id else [c.id for c in store.list_cases()]
    for cid in ids:
        steps = store.list_steps(cid)
        for i, s in enumerate(steps):
            if s.status not in FAILURE_STATUSES:
                continue
            nxt = steps[i + 1] if i + 1 < len(steps) else None
            out.append(FailureItem(case_id=cid, run_id=s.run_id, step_id=s.id, stage=s.stage, status=s.status,
                                   error=s.error, next_stage=nxt.stage if nxt else None,
                                   next_status=nxt.status if nxt else None, at=s.ended_at or s.started_at))
    return sorted(out, key=lambda f: f.at, reverse=True)


def stage_stats(store: Store) -> list[StageStat]:
    """Per-stage counts and mean duration over each case's latest run, in pipeline order."""
    by_stage: dict[str, list] = {}
    for c in store.list_cases():
        for s in store.list_steps(c.id):
            if s.parent_id is None:
                by_stage.setdefault(s.stage, []).append(s)
    out = []
    for stage, steps in by_stage.items():
        ms = [s.duration_ms for s in steps if s.duration_ms is not None]
        out.append(StageStat(stage=stage, runs=len(steps),
                             ok=sum(s.status == StepStatus.ok for s in steps),
                             skipped=sum(s.status == StepStatus.skipped for s in steps),
                             flagged=sum(s.status in FAILURE_STATUSES for s in steps),
                             avg_ms=round(sum(ms) / len(ms), 1) if ms else None))
    first_seq = {st: min(s.seq for s in steps) for st, steps in by_stage.items()}
    return sorted(out, key=lambda x: first_seq[x.stage])
