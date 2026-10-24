"""Second-line pre-payment checks, plus the 3-way match table and GL suggestions. Owner: D.

An independent line of defence before money moves. They read the system of record from the store (PO,
goods receipts, contract terms, paid history, vendor master, other bills) and the parsed invoice; supplier text
is never treated as instructions. All arithmetic is Decimal. They overlap A's DocDedup, Matcher and Vendor Guard
on purpose, but are written separately. Where they disagree with the pipeline's decision, `disagreements()`
says so and the bill shows it as a warning; nothing is overridden silently.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Optional

from backend.core.config import Policy
from backend.pipeline.lib.ids import invoice_line_hash
from backend.store.base import Store
from contracts import (Case, CaseStatus, CheckResult, ContractTerm, Decision, DiscrepancyType as T, DocKind, GLLine,
                       Invoice, MatchRow, PaidInvoice, PO, Receipt, Signal, Vendor)

ZERO = Decimal(0)
CENT = Decimal("0.01")


def _norm_invoice_no(no: str) -> str:
    """INV-2291-A, inv 2291, INV2291, INV-0042 -> 2291 / 42 (vendor-scoped comparison)."""
    no = re.sub(r"[-_ ]?[A-Z]$", "", (no or "").strip().upper())
    digits = re.sub(r"[^0-9]", "", no)
    return digits.lstrip("0") or digits or no


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


# --- system of record ------------------------------------------------------------------------------------

def _po(case: Case, store: Optional[Store]) -> Optional[PO]:
    inv = case.invoice
    if store is not None and inv and inv.po_number:
        return store.get_po(inv.po_number)
    return case.po


def _receipts(case: Case, store: Optional[Store]) -> list[Receipt]:
    inv = case.invoice
    if store is not None and inv and inv.po_number:
        return store.list_receipts(inv.po_number)
    return case.receipts


def _terms(case: Case, store: Optional[Store]) -> list[ContractTerm]:
    return store.list_contract_terms(case.vendor_id) if store is not None else []


def paid_history(store: Optional[Store], vendor_id: str) -> list[PaidInvoice]:
    return store.list_paid(vendor_id) if store is not None else []


def _price_in_force(sku: str, currency: str, on: date, terms: list[ContractTerm]) -> Optional[ContractTerm]:
    """Contract / amendment price for this SKU in force on the invoice date (amendments win only from effective_from)."""
    hits = [t for t in terms if t.sku == sku and t.currency == currency and t.effective_from <= on]
    return max(hits, key=lambda t: t.effective_from) if hits else None


def match_rows(case: Case, store: Optional[Store] = None) -> list[MatchRow]:
    """One row per billed SKU: ordered (PO), received (GRN), billed. po_price is the agreed price on the invoice
    date: the contract term in force if there is one, else the PO price."""
    inv = case.invoice
    if inv is None or inv.credit_for:
        return []
    po, receipts, terms = _po(case, store), _receipts(case, store), _terms(case, store)
    rows = []
    for line in inv.lines:
        pol = next((p for p in po.lines if p.sku == line.sku), None) if po else None
        received = sum((r.qty_received for rc in receipts for r in rc.lines if r.sku == line.sku), ZERO)
        ordered = pol.qty if pol else None
        same_ccy = po is not None and po.currency == inv.currency
        term = _price_in_force(line.sku, inv.currency, inv.invoice_date, terms) if pol else None
        agreed = term.unit_price if term else (pol.unit_price if pol and same_ccy else None)
        payable_qty = min(ordered, received, line.qty) if ordered is not None else ZERO
        qty_var = line.qty - (min(ordered, received) if ordered is not None else ZERO)
        price_var = (line.unit_price - agreed) if agreed is not None else None
        fair_price = min(line.unit_price, agreed) if agreed is not None else line.unit_price
        at_risk = (line.amount - payable_qty * fair_price).quantize(CENT)
        rows.append(MatchRow(sku=line.sku, description=line.description, ordered=ordered, received=received,
                             billed=line.qty, po_price=agreed, invoice_price=line.unit_price,
                             qty_variance=qty_var, price_variance=price_var, amount_at_risk=max(at_risk, ZERO)))
    return rows


def _material(amount: Decimal, inv: Invoice, policy: Policy, strict: bool) -> bool:
    """Second-line materiality: above the policy's absolute (USD) and relative floors. Probation: no allowance."""
    if amount <= 0:
        return False
    if strict:
        return True
    usd = amount * policy.fx_rates.get(inv.currency, Decimal(1))
    return usd >= policy.materiality.abs and amount >= abs(inv.total) * policy.materiality.pct


def _probation(vendor: Optional[Vendor], case: Case) -> bool:
    if not vendor or not vendor.on_probation:
        return False
    return vendor.probation_until is None or case.as_of is None or vendor.probation_until >= case.as_of


def gl_lines(case: Case, policy: Policy) -> list[GLLine]:
    inv = case.invoice
    if inv is None:
        return []
    out = []
    for line in inv.lines:
        freight = line.sku.upper().startswith("FRT") or any(w in line.description.lower() for w in ("freight", "expedite"))
        if freight:
            account, basis = policy.accounts.freight, "Freight line → freight expense"
        else:
            account, basis = policy.accounts.expense_default, "Direct material on a PO → COGS materials"
        out.append(GLLine(line_no=line.line_no, sku=line.sku, description=line.description, amount=line.amount,
                          account=account, basis=basis))
    return out


def _receipts_cover(inv: Invoice, billings: int, receipts: list[Receipt]) -> bool:
    got: dict[str, Decimal] = {}
    for r in receipts:
        for rl in r.lines:
            got[rl.sku] = got.get(rl.sku, ZERO) + rl.qty_received
    need: dict[str, Decimal] = {}
    for li in inv.lines:
        need[li.sku] = need.get(li.sku, ZERO) + li.qty
    return all(got.get(s, ZERO) >= q * (billings + 1) for s, q in need.items())


def duplicates(case: Case, store: Optional[Store]) -> list[tuple[str, str, str]]:
    """(other invoice no, where, why) for invoices this one repeats: paid history, or an earlier bill in process."""
    inv = case.invoice
    if inv is None or inv.credit_for or store is None:
        return []
    mine_no, mine_hash = _norm_invoice_no(inv.invoice_no), invoice_line_hash(inv)
    skip_no = _norm_invoice_no(inv.corrects) if inv.corrects else None
    receipts = _receipts(case, store)
    out, same_lines = [], []
    shas = {d.sha256 for d in case.documents if d.kind == DocKind.invoice}
    for p in paid_history(store, case.vendor_id):
        n = _norm_invoice_no(p.invoice_no)
        if n == skip_no:
            continue
        if n == mine_no:
            out.append((p.invoice_no, f"paid {p.paid_on}", f"same invoice number as {p.invoice_no}, paid {p.paid_on} "
                                                           f"({p.currency} {p.total:,.2f})"))
        elif p.line_hash == mine_hash and p.po_number and p.po_number == inv.po_number:
            same_lines.append((p.invoice_no, f"paid {p.paid_on}", f"same lines on {p.po_number} as {p.invoice_no}, "
                                                                  f"paid {p.paid_on} ({p.currency} {p.total:,.2f})"))
    for o in store.list_cases(case.vendor_id):
        oi = o.invoice
        later = o.created_at > case.created_at or (o.created_at == case.created_at and o.id > case.id)
        if (o.id == case.id or o.parent_id or oi is None or oi.credit_for or (later and o.journal_entry is None)
                or o.status in (CaseStatus.rejected, CaseStatus.quarantined) or o.decision == Decision.reject):
            continue
        n = _norm_invoice_no(oi.invoice_no)
        if n == skip_no or (oi.corrects and _norm_invoice_no(oi.corrects) == mine_no):
            continue
        same_file = bool(shas & {d.sha256 for d in o.documents if d.kind == DocKind.invoice})
        if same_file or n == mine_no:
            why = "byte-identical file" if same_file else "same invoice number"
            out.append((oi.invoice_no, f"bill {o.id}", f"{why} as {oi.invoice_no} (bill {o.id}, already in process)"))
        elif invoice_line_hash(oi) == mine_hash and oi.po_number and oi.po_number == inv.po_number:
            same_lines.append((oi.invoice_no, f"bill {o.id}", f"same lines on {oi.po_number} as {oi.invoice_no} "
                                                              f"(bill {o.id}, already in process)"))
    if same_lines and not _receipts_cover(inv, len(same_lines), receipts):
        out += same_lines  # the receipts cover only the earlier billing: the same goods billed twice
    seen, uniq = set(), []
    for x in out:
        if x[0] not in seen:
            seen.add(x[0])
            uniq.append(x)
    return uniq


def signals(case: Case, vendor: Optional[Vendor], policy: Policy, store: Optional[Store] = None) -> list[Signal]:
    inv = case.invoice
    out: list[Signal] = []
    if inv is None or inv.credit_for:
        return out
    cur = inv.currency
    strict = _probation(vendor, case)

    # payee
    if vendor and inv.bank_last4 and inv.bank_last4 != vendor.bank_last4:
        out.append(Signal(code="bank_mismatch", severity="high", title="Bank account differs from vendor master",
                          detail=f"Invoice asks for payment to •••• {inv.bank_last4}; vendor master has •••• {vendor.bank_last4}. "
                                 "Payment will only ever go to the master account; verify by calling the number on file."))
    sender = next((d.sender for d in case.documents if d.sender and "@" in d.sender
                   and d.kind in (DocKind.invoice, DocKind.email)), None)
    if vendor and sender:
        dom = sender.split("@")[-1].lower().strip(">")
        if dom != vendor.email_domain.lower():
            close = _edit_distance(_root(dom).replace("-", ""), _root(vendor.email_domain).replace("-", "")) <= 2
            out.append(Signal(code="lookalike_domain", severity="high" if close else "medium",
                              title="Look-alike sender domain" if close else "Unknown sender domain",
                              detail=f"Sent from {dom}; the vendor's domain on file is {vendor.email_domain}."))

    # duplicates vs what we already paid or have in process
    for other, _, why in duplicates(case, store):
        out.append(Signal(code="duplicate", severity="high", title=f"Possible duplicate of {other}",
                          detail=why[0].upper() + why[1:] + "."))

    # 3-way match against the system of record
    po = _po(case, store)
    if inv.po_number and po is None:
        out.append(Signal(code="no_po", severity="medium", title=f"{inv.po_number} is not in the ERP",
                          detail="No purchase order on record, so there is nothing to match against."))
    elif not inv.po_number:
        out.append(Signal(code="no_po", severity="medium", title="No purchase order on the invoice",
                          detail="No PO number, so there is nothing to match against."))
    if po and po.currency != inv.currency:
        out.append(Signal(code="currency_mismatch", severity="medium", title=f"Billed in {inv.currency}, PO is in {po.currency}",
                          detail=f"{po.po_number} and the vendor master are {po.currency}; ask for a corrected invoice."))
    line_sum = sum((li.amount for li in inv.lines), ZERO)
    if line_sum != inv.total:
        out.append(Signal(code="total_mismatch", severity="medium", title="Printed total differs from the lines",
                          detail=f"Lines add up to {cur} {line_sum:,.2f}; the invoice prints {cur} {inv.total:,.2f}."))
    if po and po.currency == inv.currency:
        for r in match_rows(case, store):
            if r.ordered is None:
                if _material(r.amount_at_risk, inv, policy, strict):
                    out.append(Signal(code="not_on_po", severity="medium", title=f"{r.sku} is not on the purchase order",
                                      detail=f"{r.description}: {cur} {r.amount_at_risk:,.2f} billed with no PO line or approval."))
                continue
            limit = min(r.ordered, r.received)
            if r.billed > limit:
                short = r.billed - limit
                amt = (short * r.invoice_price).quantize(CENT)
                tol = ZERO if strict else policy.tolerances.qty_pct
                if r.billed > limit * (1 + tol) and _material(amt, inv, policy, strict):
                    out.append(Signal(code="qty_short", severity="medium", title=f"{short:,} {r.sku} billed but not received",
                                      detail=f"Ordered {r.ordered:,}, received {r.received:,}, billed {r.billed:,}. "
                                             f"Overbilled {cur} {amt:,.2f}."))
            if r.price_variance and r.price_variance > 0:
                amt = (r.price_variance * r.billed).quantize(CENT)
                tol = ZERO if strict else policy.tolerances.price_pct
                if r.invoice_price > r.po_price * (1 + tol) and _material(amt, inv, policy, strict):
                    amend = [t for t in _terms(case, store) if t.sku == r.sku and t.effective_from > inv.invoice_date]
                    note = (f" A new price is on file from {amend[0].effective_from}, after the invoice date "
                            f"{inv.invoice_date}, so the earlier price applies.") if amend else ""
                    out.append(Signal(code="price_over", severity="medium", title=f"{r.sku} billed above the agreed price",
                                      detail=f"Agreed {cur} {r.po_price:,.2f} on {inv.invoice_date}, billed {cur} {r.invoice_price:,.2f} "
                                             f"(+{cur} {amt:,.2f}).{note}"))

    if "embedded_instructions" in inv.flags:
        out.append(Signal(code="embedded_instructions", severity="high", title="Hidden instructions in the document",
                          detail="The Reader found instructions inside the invoice text. They were ignored."))
    if strict:
        out.append(Signal(code="probation", severity="low", title="New vendor on probation",
                          detail="Zero tolerance and a full 3-way match until probation ends"
                                 + (f" ({vendor.probation_until})." if vendor.probation_until else ".")))
    return out


# second-line signal -> the pipeline discrepancy types that mean the same thing
SAME_AS = {"bank_mismatch": {T.bank_change}, "lookalike_domain": {T.lookalike_domain},
           "duplicate": {T.duplicate_invoice}, "qty_short": {T.qty_short}, "price_over": {T.price_over},
           "not_on_po": {T.unapproved_freight}, "embedded_instructions": {T.embedded_instructions},
           "no_po": {T.unknown_po, T.missing_receipt}, "currency_mismatch": {T.currency_mismatch},
           "total_mismatch": {T.total_mismatch}}


def disagreements(case: Case, sig: list[Signal]) -> list[str]:
    """Where the second-line checks and the pipeline's decision disagree, in plain words (never silent)."""
    if case.invoice is None or case.decision is None or case.invoice.credit_for:
        return []
    found = {d.type for d in case.discrepancies if d.material}
    out = []
    for s in sig:
        types = SAME_AS.get(s.code)
        if types and not (types & found) and s.severity in ("high", "medium"):
            verb = "cleared it" if case.decision == Decision.approve else f"decided {case.decision.value} without it"
            out.append(f"Second-line check flags “{s.title}” but the agents {verb}.")
    codes = {s.code for s in sig}
    for t in sorted(found, key=lambda t: t.value):
        if any(t in v for v in SAME_AS.values()) and not any(t in SAME_AS[c] for c in codes if c in SAME_AS):
            out.append(f"Agents recorded {t.value.replace('_', ' ')}; the second-line checks did not find it.")
    return out


def risk(sig: list[Signal]) -> str:
    return "high" if any(s.severity == "high" for s in sig) else "medium" if any(s.severity == "medium" for s in sig) \
        else "low"


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


def check_results(case: Case, vendor: Optional[Vendor], policy: Policy, store: Optional[Store] = None,
                  sig_list: Optional[list[Signal]] = None) -> list[CheckResult]:
    """Every check as passed / failed with references, for the 'Ready to approve' card. Built on signals()."""
    inv = case.invoice
    if inv is None or inv.credit_for:
        return []
    sig_list = sig_list if sig_list is not None else signals(case, vendor, policy, store)
    sig: dict[str, Signal] = {}
    for s in sig_list:
        sig.setdefault(s.code, s)
    po = _po(case, store)
    rows = match_rows(case, store)
    line_ref = lambda sku: [f"Line {next((l.line_no for l in inv.lines if l.sku == sku), '?')}"]  # noqa: E731
    receipts = _receipts(case, store)
    sender = next((d.sender for d in case.documents if d.sender and "@" in d.sender), None)
    out: list[CheckResult] = []

    def add(name: str, code: str, ok_detail: str, refs: list[str]):
        s = sig.get(code)
        out.append(CheckResult(name=name, passed=s is None, severity=s.severity if s else "low",
                               detail=s.detail if s else ok_detail, refs=refs))

    add("Bank account matches the vendor master", "bank_mismatch",
        f"Pays to •••• {vendor.bank_last4 if vendor else '—'}, the account on the vendor master.", ["Vendor master"])
    add("Sent from the vendor's known domain", "lookalike_domain",
        f"{sender.split('@')[-1]} matches the domain on file." if sender else "Not sent by email (no sender domain to check).",
        [d.filename for d in case.documents if d.sender and "@" in d.sender][:1])
    paid = paid_history(store, case.vendor_id)
    add("Not a duplicate of a paid or in-process invoice", "duplicate",
        "No paid or in-process invoice with the same number, file, or the same lines on the same PO.",
        [p.invoice_no for p in paid][:2])
    add("Purchase order on record", "no_po", f"{po.po_number} found in the ERP." if po else "—",
        [po.po_number] if po else [])
    add("Currency matches the PO", "currency_mismatch", f"Billed in {inv.currency}, same as the PO.",
        [po.po_number] if po else [])
    add("Printed total equals the lines", "total_mismatch", "The lines add up to the printed total.", [inv.invoice_no])
    short = [r for r in rows if r.ordered is not None and r.billed > min(r.ordered, r.received)]
    add("Billed quantities were received", "qty_short",
        "Every billed quantity matches the goods receipt." if not short else
        "Small quantity differences are below materiality.",
        [x for r in (short or rows) for x in line_ref(r.sku)] + [rc.doc_id for rc in receipts][:1])
    over = [r for r in rows if r.price_variance and r.price_variance > 0]
    add("Prices match the agreed price", "price_over",
        "Every unit price matches the PO / contract price in force on the invoice date." if not over else
        "Price differences are within tolerance and below materiality.",
        [x for r in (over or rows) for x in line_ref(r.sku)] + ([po.po_number] if po else []))
    off = [r for r in rows if r.ordered is None]
    add("Every line is on the purchase order", "not_on_po",
        "All lines map to a PO line." if not off else "Lines off the PO are below materiality.",
        [x for r in off for x in line_ref(r.sku)] + ([po.po_number] if po else []))
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
        why = f" Quarantined: {case.quarantine_reason}." if case.quarantine_reason else ""
        return "No invoice could be read from what arrived." + why
    what = "; ".join(l.description for l in inv.lines[:3]) + ("…" if len(inv.lines) > 3 else "")
    po = f" against {inv.po_number}" if inv.po_number else " with no purchase order"
    return f"This {inv.currency} {inv.total:,.2f} bill from {vendor.name if vendor else case.vendor_id} is for {what}{po}."
