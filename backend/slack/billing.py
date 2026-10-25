"""The billing half of the Slack cycle: the vendor's invoice form -> files for intake, and what a finished run means
for the people in Slack. Owner: D. Code only (no LLM); all money is Decimal.

- `invoice_files`: the [Submit invoice] modal -> a structured CSV (csv.invoice.v1: read by the deterministic adapter,
  no Reader LLM) + a rendered PDF copy for people. Descriptions come from OUR PO lines, never from vendor text; the
  vendor's free-text note only appears in the PDF (as data).
- `assess`: GREEN = agents recommend approve, no material discrepancy, no medium/high pre-payment signal, payment
  guard clear (bank / duplicate / hidden instructions / out-of-band / probation without a GRN). Else the reasons.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from backend.ap import state as S
from backend.ap.views import _probation_block
from backend.core.config import Policy
from backend.pipeline.lib.split import INFO
from backend.review.checks import payment_block
from backend.review.packet import money, usd
from contracts import PO, Case, Decision, DiscrepancyType as T, ReviewPacket, Vendor

CENT = Decimal("0.01")
INVOICE_NO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/.]{0,39}$")
COLUMNS = ["invoice_number", "invoice_date", "po_number", "currency", "line_no", "sku", "description", "quantity",
           "unit_price", "line_amount", "remit_last4"]


def invoice_csv(invoice_no: str, on: date, po: PO, lines: list[tuple[str, Decimal, Decimal]]) -> bytes:
    """lines: (sku, qty, unit_price) for SKUs on the PO. Line amounts computed here."""
    desc = {ln.sku: ln.description for ln in po.lines}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for i, (sku, qty, price) in enumerate(lines, 1):
        w.writerow([invoice_no, on.isoformat(), po.po_number, po.currency, i, sku, desc.get(sku, ""), qty, price,
                    (qty * price).quantize(CENT, ROUND_HALF_UP), ""])
    return out.getvalue().encode()


def invoice_pdf(path: Path, vendor: Vendor, invoice_no: str, on: date, po: PO,
                lines: list[tuple[str, Decimal, Decimal]], note: str = "") -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    desc = {ln.sku: ln.description for ln in po.lines}
    rows = [["Item code", "Description", "Qty", "Unit price", f"Amount ({po.currency})"]]
    total = Decimal(0)
    for sku, qty, price in lines:
        amt = (qty * price).quantize(CENT, ROUND_HALF_UP)
        total += amt
        rows.append([sku, desc.get(sku, "")[:40], str(qty), str(price), str(amt)])
    rows.append(["Total", "", "", "", str(total)])
    t = Table(rows, colWidths=[110, 170, 50, 80, 100])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0E6E76")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story = [Paragraph(f"Invoice {escape(invoice_no)}", ss["Title"]),
             Paragraph(f"From {escape(vendor.name)} to Helix Silicon, Inc. &middot; {on.isoformat()} &middot; "
                       f"PO {po.po_number}", ss["Italic"]),
             Paragraph("Submitted through the ReconAI Slack invoice form by the supplier's registered contact. "
                       "Payment goes only to the account on file with Helix.", ss["BodyText"]),
             Spacer(1, 10), t]
    if note.strip():
        story += [Spacer(1, 10), Paragraph(f"Supplier note: {escape(note.strip()[:500])}", ss["BodyText"])]
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=letter, title=f"Invoice {invoice_no}").build(story)
    return path


def assess(case: Case, vendor: Optional[Vendor], policy: Policy, store, packet: ReviewPacket) -> tuple[bool, list[str]]:
    """(green, reasons it isn't)."""
    why: list[str] = []
    if case.invoice is None:
        why.append(case.quarantine_reason and f"Quarantined: {case.quarantine_reason}"
                   or "No invoice could be read from what arrived")
    if case.decision != Decision.approve:
        why.append(f"Agents recommend {case.decision.value if case.decision else 'nothing yet'}")
    why += [f"{d.type.value.replace('_', ' ')}" + (f": {d.actual}" if d.actual else "")
            for d in case.discrepancies if d.material and d.type not in INFO]
    why += [s.title for s in packet.signals if s.severity in ("high", "medium")]
    block = payment_block(packet.signals) or S.oob_problem(case) or (
        _probation_block(case, vendor, store) if case.invoice else None)
    if block:
        why.append(block)
    why += [f"{f.check}: {f.detail}" for f in packet.findings  # "waiting for a signature" is what we're asking for
            if f.status in ("flag", "blocked") and f.check != "Sign-off"]
    seen, out = set(), []
    for w in why:
        if w and w not in seen:
            seen.add(w)
            out.append(w[:300])
    return not out, out


def vendor_issues(case: Case) -> list[str]:
    """What the vendor must fix, for the deal channel: invoice vs Helix's record, from the matcher's discrepancies.
    Vendor-facing types only; internal checks (bank change, look-alike domain, hidden instructions) are never named."""
    inv = case.invoice
    if inv is None:
        return []
    ccy, out = inv.currency, []
    for d in case.discrepancies:
        if not d.material or d.type in INFO:
            continue
        over = f" ({ccy} {d.delta:,.2f} over)" if d.delta else ""
        text = {T.qty_short: f"`{d.sku}`: billed {d.actual}, Helix received {d.expected}{over}",
                T.price_over: f"`{d.sku}`: unit price {d.actual}, agreed price {d.expected}{over}",
                T.unapproved_freight: f"Line {d.line_no}: {ccy} {d.actual} charge that isn't on the PO",
                T.total_mismatch: f"Total {d.actual} doesn't equal the sum of the lines ({d.expected})",
                T.currency_mismatch: f"Billed in {d.actual}, the PO is in {d.expected}",
                T.fx_gap: "The converted amount doesn't match the agreed exchange basis",
                T.unknown_po: f"PO {d.actual} isn't one of your Helix purchase orders",
                T.duplicate_invoice: f"Invoice number {inv.invoice_no} was already submitted"}.get(d.type)
        if text:
            out.append(text)
    return out


def next_invoice_no(invoice_no: str) -> str:
    """The number a corrected invoice should carry: INV-1 -> INV-1-R -> INV-1-R2 (adapters.derive_links links it)."""
    m = re.match(r"^(.*\S)-R(\d?)$", invoice_no.strip(), re.I)
    return f"{m.group(1)}-R{int(m.group(2) or 1) + 1}" if m else f"{invoice_no.strip()}-R"


def facts(case: Case, vendor: Optional[Vendor], store, policy: Policy) -> list[str]:
    inv = case.invoice
    if inv is None:
        return [f"• Vendor: {vendor.name if vendor else case.vendor_id}", "• No invoice was read."]
    out = [f"• Vendor: {vendor.name if vendor else case.vendor_id}",
           f"• Invoice: {inv.invoice_no} · {money(inv.total, inv.currency)}"
           + (f" (USD {usd(case, policy):,.2f})" if inv.currency != "USD" else "")]
    if inv.po_number:
        rec = store.list_receipts(inv.po_number)
        out.append(f"• PO: {inv.po_number} · goods receipt: "
                   + (", ".join(r.doc_id.removeprefix("erp-") + f" by {r.received_by}" for r in rec) or "none"))
    return out
