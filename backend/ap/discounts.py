"""Early-payment discounts ("2/15 net 30"). Owner: D. Terms come from the vendor master / contract, never from
invoice text. All money is Decimal; the annualised return is only a display figure."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from backend.core.config import Policy
from contracts import Case, EarlyPayOffer, Payment, Vendor

CENT = Decimal("0.01")


def terms_label(v: Vendor) -> str:
    t = v.terms
    if not t or not t.discount_pct:
        return f"net {t.net_days if t else 30}"
    return f"{(t.discount_pct * 100).normalize()}/{t.discount_days} net {t.net_days}"


def discount(case: Case, vendor: Optional[Vendor], base: Optional[Decimal] = None) -> Optional[tuple[Decimal, date]]:
    """(discount amount in invoice currency, last day to pay) or None if the vendor offers none.
    base: the amount actually paid (the undisputed part of a hold); defaults to the invoice total."""
    inv = case.invoice
    if inv is None or inv.credit_for or vendor is None or not vendor.terms or not vendor.terms.discount_pct \
            or not vendor.terms.discount_days:
        return None
    base = inv.total if base is None else base
    return (base * vendor.terms.discount_pct).quantize(CENT), inv.invoice_date + timedelta(days=vendor.terms.discount_days)


def offer(case: Case, vendor: Optional[Vendor], policy: Policy, today: date, stage: str,
          block: Optional[str], payment: Optional[Payment], base: Optional[Decimal] = None) -> Optional[EarlyPayOffer]:
    d = discount(case, vendor, base)
    if d is None or stage in ("rejected", "processing"):
        return None
    amount, pay_by = d
    t, inv = vendor.terms, case.invoice
    pct = t.discount_pct
    window = max(1, t.net_days - t.discount_days)
    apr = float(pct / (1 - pct) * Decimal(365) / Decimal(window) * 100)
    if payment is not None:
        status = "captured" if payment.discount_amount > 0 else "missed"
        note = (f"Saved {inv.currency} {payment.discount_amount:,.2f} by paying {payment.pay_date}." if status == "captured"
                else f"Paid {payment.pay_date}, after the discount window.")
    elif today > pay_by:
        status, note = "missed", f"Discount window closed {pay_by}."
    elif block:
        status, note = "blocked", "Payment guard: resolve the open risk first."
    elif stage in ("needs_review", "on_hold"):
        status, note = "needs_approval", f"Approve by {pay_by} to capture it."
    else:
        status, note = "available", f"Schedule for {pay_by} or earlier."
    return EarlyPayOffer(case_id=case.id, vendor_id=vendor.id, vendor_name=vendor.name, invoice_no=inv.invoice_no,
                         terms=terms_label(vendor), discount_pct=pct, discount_amount=amount, currency=inv.currency,
                         discount_usd=(amount * policy.fx_rates[inv.currency]).quantize(CENT), pay_by=pay_by,
                         days_left=(pay_by - today).days, annualized_return_pct=round(apr, 1), status=status, note=note)
