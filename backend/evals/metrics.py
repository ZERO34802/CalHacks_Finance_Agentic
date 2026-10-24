"""Business metrics panel (CLAUDE.md section 10c P1). Owner: C.

Computed by code from the cases in the store, on the SIMULATED business clock (fixture dates), never wall time:
- dollars caught: USD (policy fx, SIMULATED) of material disputed deltas on held cases, plus the full total of
  rejected duplicates.
- hours saved: ESTIMATE = policy.metrics minutes per clean / exception case.
- on-time payment rate: posted entries dated on/before the due date (invoice.due_date, else invoice_date + 30 days).
- exceptions per vendor: top-level cases whose decision is not approve.
- average time to resolve: hours from receipt (created_at) to the posting / resolution date (as_of), for cases
  that reached posted / rejected / resolved. Day granularity.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from backend.core.config import Policy
from contracts import BusinessMetrics, Case, CaseStatus, Decision, DiscrepancyType

CENT = Decimal("0.01")
DEFAULT_TERMS_DAYS = 30
TERMINAL = {CaseStatus.posted, CaseStatus.rejected, CaseStatus.resolved}


def _usd(amount: Decimal, currency: str, policy: Policy) -> Optional[Decimal]:
    rate = policy.fx_rates.get(currency)
    return None if rate is None else amount * rate


def top_level(cases: Iterable[Case]) -> list[Case]:
    return [c for c in cases if c.parent_id is None and c.vendor_id != "SYSTEM"]


def compute(cases: Iterable[Case], policy: Policy) -> BusinessMetrics:
    cases = top_level(cases)
    notes = ["SIMULATED fx table; hours saved is an ESTIMATE (policy.metrics)"]
    caught = Decimal(0)
    for c in cases:
        inv = c.invoice
        if inv is None:
            continue
        if c.decision == Decision.reject and any(d.type == DiscrepancyType.duplicate_invoice for d in c.discrepancies):
            amt = inv.total
        elif c.decision == Decision.hold:
            amt = c.disputed_amount if c.disputed_amount is not None else sum(
                (abs(d.delta) for d in c.discrepancies if d.material and d.delta is not None
                 and d.type != DiscrepancyType.below_materiality), Decimal(0))
        else:
            continue
        usd = _usd(amt, inv.currency, policy)
        if usd is not None:
            caught += usd

    m = policy.metrics or {}
    clean_min = Decimal(str(m.get("minutes_saved_clean", 0)))
    exc_min = Decimal(str(m.get("minutes_saved_exception", 0)))
    decided = [c for c in cases if c.decision is not None]
    minutes = sum((clean_min if c.decision == Decision.approve else exc_min for c in decided), Decimal(0))

    posted = [c for c in cases if c.journal_entry is not None and c.invoice is not None]
    on_time = 0
    for c in posted:
        due = c.invoice.due_date or (c.invoice.invoice_date + timedelta(days=DEFAULT_TERMS_DAYS))
        on_time += c.journal_entry.date <= due
    if any(c.invoice.due_date is None for c in posted):
        notes.append(f"due date defaults to invoice date + {DEFAULT_TERMS_DAYS} days when the invoice has none")

    exceptions = Counter(c.vendor_id for c in decided if c.decision != Decision.approve)

    durations = []
    for c in cases:
        if c.status not in TERMINAL:
            continue
        end: Optional[date] = c.journal_entry.date if c.journal_entry else c.as_of
        if end is None:
            continue
        durations.append(max((end - c.created_at.date()).days, 0) * 24)
    return BusinessMetrics(
        dollars_caught_usd=caught.quantize(CENT),
        hours_saved_est=(minutes / 60).quantize(CENT),
        on_time_payment_rate=round(on_time / len(posted), 4) if posted else 1.0,
        exceptions_per_vendor=dict(sorted(exceptions.items())),
        avg_time_to_resolve_hours=round(sum(durations) / len(durations), 1) if durations else None,
        notes=notes,
    )
