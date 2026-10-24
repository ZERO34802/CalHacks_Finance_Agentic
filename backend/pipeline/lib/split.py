"""Pay what's clean: split an invoice into undisputed and disputed parts. Code only, Decimal.

Separable when every MATERIAL discrepancy is qty_short, price_over or unapproved_freight
(data/FORMATS.md P1). disputed = sum of those deltas; undisputed = total - disputed.
Per line: line amount - deltas attributed to that line (by line_no, else first line with the SKU).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from backend.pipeline.lib.money import q2
from contracts import Case, DiscrepancyType as T

SEPARABLE = {T.qty_short, T.price_over, T.unapproved_freight}
INFO = {T.below_materiality, T.over_limit, T.locked_period}


def split(case: Case) -> dict:
    inv = case.invoice
    out = {"separable": False, "disputed": None, "undisputed": None, "lines": {}}
    if inv is None or inv.credit_for:
        return out
    material = [d for d in case.discrepancies if d.material and d.type not in INFO]
    flagged = "embedded_instructions" in inv.flags
    if not material or flagged or any(d.type not in SEPARABLE or d.delta is None for d in material):
        return out
    per_line = {li.line_no: li.amount for li in inv.lines}
    for d in material:
        n = d.line_no if d.line_no in per_line else next(
            (li.line_no for li in inv.lines if li.sku == d.sku), None)
        if n is None:
            return out
        per_line[n] -= d.delta
    if any(v < 0 for v in per_line.values()):
        return out
    disputed = q2(sum((d.delta for d in material), Decimal(0)))
    undisputed = q2(inv.total - disputed)
    if undisputed < 0:
        return out
    out.update(separable=True, disputed=disputed, undisputed=undisputed,
               lines={n: q2(v) for n, v in per_line.items()})
    return out


def on_probation(vendor, as_of) -> bool:
    if vendor is None or not vendor.on_probation:
        return False
    return vendor.probation_until is None or as_of is None or vendor.probation_until >= as_of


def variance(case: Case) -> Optional[Decimal]:
    s = split(case)
    return s["disputed"]
