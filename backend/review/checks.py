"""Pre-payment checks run by code at review time, plus the 3-way match table and GL suggestions. Owner: D.

These look only at the system of record (PO, goods receipt, vendor master, paid history) and the parsed
invoice. Supplier text is never treated as instructions. All arithmetic is Decimal.
NOTE for the team: dedup / match / vendor checks overlap A's Matcher, DocDedup and Vendor Guard. When those
stages record real discrepancies, they show up in the agent findings too; these checks stay as a second,
independent line of defence before money moves.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from functools import lru_cache
from typing import Optional

from backend.core.config import ROOT, Policy
from contracts import Case, CheckResult, DocKind, GLLine, MatchRow, Signal, Vendor

ZERO = Decimal(0)


@lru_cache
def paid_history() -> list[dict]:
    return json.loads((ROOT / "data" / "paid_history.json").read_text())


def _norm_invoice_no(no: str) -> str:
    """INV-2291-A, inv 2291, INV2291 -> 2291 (vendor-scoped comparison)."""
    no = re.sub(r"[-_ ]?[A-Z]$", "", no.strip().upper())
    return re.sub(r"[^0-9]", "", no) or no


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _root(domain: str) -> str:
    """penangpacktest.com.my -> penangpacktest ; penang-packtest.com -> penang-packtest"""
    parts = domain.lower().split(".")
    tld2 = {"co", "com", "org", "net", "ac", "gov"}
    if len(parts) >= 3 and parts[-2] in tld2:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def match_rows(case: Case) -> list[MatchRow]:
    inv, po = case.invoice, case.po
    if inv is None:
        return []
    rows = []
    for line in inv.lines:
        pol = next((p for p in po.lines if p.sku == line.sku), None) if po else None
        received = sum((r.qty_received for rc in case.receipts for r in rc.lines if r.sku == line.sku), ZERO)
        ordered = pol.qty if pol else None
        payable_qty = min(ordered, received) if ordered is not None else ZERO
        qty_var = line.qty - payable_qty
        price_var = (line.unit_price - pol.unit_price) if pol else None
        fair_price = min(line.unit_price, pol.unit_price) if pol else ZERO
        at_risk = (line.amount - payable_qty * fair_price).quantize(Decimal("0.01"))
        rows.append(MatchRow(sku=line.sku, description=line.description, ordered=ordered, received=received,
                             billed=line.qty, po_price=pol.unit_price if pol else None, invoice_price=line.unit_price,
                             qty_variance=qty_var, price_variance=price_var, amount_at_risk=max(at_risk, ZERO)))
    return rows


def gl_lines(case: Case, policy: Policy) -> list[GLLine]:
    inv = case.invoice
    if inv is None:
        return []
    out = []
    for line in inv.lines:
        if line.sku.startswith("FRT"):
            account, basis = policy.accounts.freight, "Freight SKU (FRT-*) → freight expense"
        else:
            account, basis = policy.accounts.expense_default, "Direct material on a PO → COGS materials"
        out.append(GLLine(line_no=line.line_no, sku=line.sku, description=line.description, amount=line.amount,
                          account=account, basis=basis))
    return out


def signals(case: Case, vendor: Optional[Vendor], policy: Policy) -> list[Signal]:
    inv = case.invoice
    out: list[Signal] = []
    if inv is None:
        return out
    cur = inv.currency

    # payee
    if vendor and inv.bank_last4 and inv.bank_last4 != vendor.bank_last4:
        out.append(Signal(code="bank_mismatch", severity="high", title="Bank account differs from vendor master",
                          detail=f"Invoice asks for payment to •••• {inv.bank_last4}; vendor master has •••• {vendor.bank_last4}. "
                                 "Payment will only ever go to the master account; verify by calling the number on file."))
    sender = next((d.sender for d in case.documents if d.sender and d.kind in (DocKind.invoice, DocKind.email)), None)
    if vendor and sender:
        dom = sender.split("@")[-1].lower()
        if dom != vendor.email_domain.lower():
            close = _edit_distance(_root(dom).replace("-", ""), _root(vendor.email_domain).replace("-", "")) <= 2
            out.append(Signal(code="lookalike_domain", severity="high" if close else "medium",
                              title="Look-alike sender domain" if close else "Unknown sender domain",
                              detail=f"Sent from {dom}; the vendor's domain on file is {vendor.email_domain}."))

    # duplicates vs what we already paid
    skus = sorted(line.sku for line in inv.lines)
    for paid in paid_history():
        if paid["vendor_id"] != case.vendor_id:
            continue
        same_no = _norm_invoice_no(paid["invoice_no"]) == _norm_invoice_no(inv.invoice_no)
        same_lines = sorted(paid["line_skus"]) == skus and Decimal(paid["total"]) == inv.total
        if same_no or same_lines:
            why = " and ".join(x for x, on in (("same invoice number", same_no), ("same lines and total", same_lines)) if on)
            out.append(Signal(code="duplicate", severity="high", title=f"Possible duplicate of {paid['invoice_no']}",
                              detail=f"{why.capitalize()} as {paid['invoice_no']}, paid {paid['paid_on']} "
                                     f"({paid['currency']} {Decimal(paid['total']):,.2f})."))

    # 3-way match
    for r in match_rows(case):
        if r.ordered is None:
            out.append(Signal(code="not_on_po", severity="medium", title=f"{r.sku} is not on the purchase order",
                              detail=f"{r.description}: {cur} {r.amount_at_risk:,.2f} billed with no PO line or approval."))
            continue
        if r.received < r.billed and r.received <= r.ordered:
            short = r.billed - r.received
            out.append(Signal(code="qty_short", severity="medium", title=f"{short:,} {r.sku} billed but not received",
                              detail=f"Ordered {r.ordered:,}, received {r.received:,}, billed {r.billed:,}. "
                                     f"Overbilled {cur} {(short * r.invoice_price):,.2f}."))
        if r.price_variance and r.price_variance > 0:
            amend = next((d for d in case.documents if d.kind == DocKind.amendment), None)
            note = f" A price amendment is on file ({amend.filename}); check its effective date against the invoice date {inv.invoice_date}." if amend else ""
            out.append(Signal(code="price_over", severity="medium", title=f"{r.sku} billed above the PO price",
                              detail=f"PO {cur} {r.po_price:,.2f}, billed {cur} {r.invoice_price:,.2f} "
                                     f"(+{cur} {(r.price_variance * r.billed):,.2f}).{note}"))

    if "embedded_instructions" in inv.flags:
        out.append(Signal(code="embedded_instructions", severity="high", title="Hidden instructions in the document",
                          detail="The Reader found instructions inside the invoice text. They were ignored."))
    if vendor and vendor.on_probation:
        out.append(Signal(code="probation", severity="low", title="New vendor on probation",
                          detail="Tighter checks apply until probation ends."))
    return out


def risk(sig: list[Signal]) -> str:
    return "high" if any(s.severity == "high" for s in sig) else "medium" if sig else "low"


def payment_block(sig: list[Signal]) -> Optional[str]:
    """Payment guard: money never moves while one of these is open."""
    for s in sig:
        if s.code == "bank_mismatch":
            return "Bank details on the invoice don't match the vendor master. Verify by callback first."
        if s.code == "duplicate":
            return s.title + ". Confirm it isn't a duplicate first."
        if s.code == "embedded_instructions":
            return "The document contained hidden instructions. Review it first."
    return None


def check_results(case: Case, vendor: Optional[Vendor], policy: Policy) -> list[CheckResult]:
    """Every check as passed / failed with references, for the 'Ready to approve' card. Built on signals()."""
    sig = {s.code: s for s in signals(case, vendor, policy)}
    inv, po = case.invoice, case.po
    if inv is None:
        return []
    rows = match_rows(case)
    line_ref = lambda sku: [f"Line {next((l.line_no for l in inv.lines if l.sku == sku), '?')}"]  # noqa: E731
    grn = next((d.filename for d in case.documents if case.receipts and d.id == case.receipts[0].doc_id), None)
    sender = next((d.sender for d in case.documents if d.sender), None)
    out: list[CheckResult] = []

    def add(name: str, code: str, ok_detail: str, refs: list[str]):
        s = sig.get(code)
        out.append(CheckResult(name=name, passed=s is None, severity=s.severity if s else "low",
                               detail=s.detail if s else ok_detail, refs=refs))

    add("Bank account matches the vendor master", "bank_mismatch",
        f"Pays to •••• {vendor.bank_last4 if vendor else '—'}, the account on the vendor master.", ["Vendor master"])
    add("Sent from the vendor's known domain", "lookalike_domain",
        f"{sender.split('@')[-1] if sender else 'internal'} matches the domain on file." if sender else "No external sender.",
        [d.filename for d in case.documents if d.sender][:1])
    add("Not a duplicate of a paid invoice", "duplicate", "No paid invoice with the same number or the same lines and total.",
        [p["invoice_no"] for p in paid_history() if p["vendor_id"] == case.vendor_id][:2])
    short = [r for r in rows if r.ordered is not None and r.received < r.billed]
    out.append(CheckResult(name="Billed quantities were received", passed=not short, severity="medium",
                           detail=sig["qty_short"].detail if "qty_short" in sig else "Every billed quantity matches the goods receipt.",
                           refs=[x for r in (short or rows) for x in line_ref(r.sku)] + ([grn] if grn else [])))
    over = [r for r in rows if r.price_variance and r.price_variance > 0]
    out.append(CheckResult(name="Prices match the purchase order", passed=not over, severity="medium",
                           detail=sig["price_over"].detail if "price_over" in sig else "Every unit price matches the PO.",
                           refs=[x for r in (over or rows) for x in line_ref(r.sku)] + ([po.po_number] if po else [])))
    off = [r for r in rows if r.ordered is None]
    out.append(CheckResult(name="Every line is on the purchase order", passed=not off, severity="medium",
                           detail=sig["not_on_po"].detail if "not_on_po" in sig else "All lines map to a PO line.",
                           refs=[x for r in off for x in line_ref(r.sku)] + ([po.po_number] if po else [])))
    add("No hidden instructions in the document", "embedded_instructions",
        "The Reader found no instructions inside the invoice text.", [inv.invoice_no])
    out.append(CheckResult(name="GL coding suggested for every line", passed=True, severity="low",
                           detail="Each line maps to a ledger account from the policy.", refs=[f"Line {l.line_no}" for l in inv.lines]))
    return out


def verdict(results: list[CheckResult]) -> str:
    failed = [r for r in results if not r.passed]
    return "risk" if any(r.severity == "high" for r in failed) else "review" if failed else "ready"


def verdict_text(case: Case, vendor: Optional[Vendor]) -> str:
    inv = case.invoice
    if inv is None:
        return "No invoice was read."
    what = "; ".join(l.description for l in inv.lines[:3]) + ("…" if len(inv.lines) > 3 else "")
    po = f" against {case.po.po_number}" if case.po else " with no purchase order"
    return f"This {inv.currency} {inv.total:,.2f} bill from {vendor.name if vendor else case.vendor_id} is for {what}{po}."
