"""Draft a supply contract from an agreed Slack negotiation. Owner: D.

The clauses are a fixed template (no LLM writes legal text); only the agreed facts are filled in, and every total
is computed here. Includes the AP controls Helix needs from day one: PO number on every invoice, 3-way match,
credit notes, bank changes by verified callback only. Rendered to PDF (reportlab) under .data/contracts/.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import uuid4

from backend.core.config import ROOT
from backend.slack.models import NegotiationState, Session, dec
from contracts import PaymentTerms, VendorContract

CENT = Decimal("0.01")
OUT = Path(os.environ.get("RECONAI_CONTRACTS_DIR", str(ROOT / ".data" / "contracts")))
KIND = "vendor_contract"


def build(sess: Session, st: NegotiationState, now: datetime) -> VendorContract:
    cid = f"CT-{uuid4().hex[:6].upper()}"
    items, total = [], Decimal(0)
    for ln in st.lines:
        price = dec(ln.agreed_unit_price) or dec(ln.vendor_unit_price)
        qty = dec(ln.quantity)
        if price is None or qty is None:
            continue
        amount = (price * qty).quantize(CENT, ROUND_HALF_UP)
        total += amount
        items.append({"description": ln.description[:80], "sku": ln.sku, "qty": str(qty), "unit": ln.unit or "unit",
                      "unit_price": str(price if -price.as_tuple().exponent > 2 else price.quantize(CENT)),  # as agreed
                      "amount": str(amount)})
    pct = dec(st.discount_pct)
    terms = PaymentTerms(net_days=st.net_days or 30, discount_pct=pct if pct else None,
                         discount_days=st.discount_days if pct else None, source=f"contract {cid} (Slack negotiation)")
    return VendorContract(id=cid, vendor_name=(st.vendor_name or sess.vendor_name or "Supplier")[:120],
                          category=st.category.value, items=items, currency=st.currency.upper()[:3], total=total,
                          terms=terms, delivery=(st.delivery or st.lead_time or "")[:160],
                          warranty=(st.warranty or "")[:160], other_terms=[t[:160] for t in st.other_terms[:6]],
                          requested_by=sess.owner_email, channel=sess.channel, created_at=now)


def terms_text(t: PaymentTerms) -> str:
    if t.discount_pct and t.discount_days:
        return (f"{(t.discount_pct * 100).normalize():f}% discount if paid within {t.discount_days} days of the invoice "
                f"date; otherwise net {t.net_days} days")
    return f"Net {t.net_days} days from the invoice date"


def clauses(c: VendorContract) -> list[tuple[str, str]]:
    return [
        ("1. Parties", f"Helix Silicon, Inc. (\"Helix\") and {c.vendor_name} (\"Supplier\")."),
        ("2. Scope and price", "Supplier will supply the items in Schedule A at the unit prices shown. Prices are "
                               f"in {c.currency}, fixed for the quantities in Schedule A."),
        ("3. Payment terms", terms_text(c.terms) + ". Helix pays the undisputed part of an invoice on time; a "
                             "disputed line is paid when resolved."),
        ("4. Invoicing", "Every invoice must cite the Helix PO number and line, the quantity shipped and the unit "
                         "price in Schedule A. Invoices are matched to the PO and the receiving record (3-way "
                         "match); amounts not supported by both are disputed."),
        ("5. Delivery", c.delivery or "As stated on each purchase order."),
        ("6. Credits", "Short deliveries, price errors and unapproved charges are credited by credit note within "
                       "7 days of Helix's notice."),
        ("7. Payment details", "Supplier's bank or wallet details are set at onboarding. Any change takes effect only "
                               "after Helix verifies it by phone at the number on file; changes requested by email "
                               "or on an invoice are not accepted."),
        ("8. Warranty", c.warranty or "Items conform to the agreed specification; non-conforming items are replaced "
                                      "or credited."),
        ("9. Additional terms", "; ".join(c.other_terms) if c.other_terms else "None."),
        ("10. Onboarding", "This agreement takes effect when Supplier completes Helix vendor onboarding (identity, "
                           "credit, sanctions and tax checks). New suppliers are on probation for 90 days."),
    ]


def render_pdf(c: VendorContract) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{c.id}.pdf"
    ss = getSampleStyleSheet()
    story = [Paragraph(f"Supply Agreement {c.id}", ss["Title"]),
             Paragraph(f"Helix Silicon, Inc. and {c.vendor_name} &middot; drafted by ReconAI from the Slack "
                       f"negotiation on {c.created_at.date().isoformat()} &middot; DRAFT for review", ss["Italic"]),
             Spacer(1, 10)]
    for head, body in clauses(c):
        story += [Paragraph(f"<b>{head}</b>", ss["Heading4"]), Paragraph(body, ss["BodyText"])]
    story += [Spacer(1, 10), Paragraph("<b>Schedule A: items and prices</b>", ss["Heading4"])]
    rows = [["Item", "SKU", "Qty", "Unit price", f"Amount ({c.currency})"]]
    rows += [[i["description"], i.get("sku") or "", f"{i['qty']} {i['unit']}", i["unit_price"], i["amount"]] for i in c.items]
    rows.append(["Total", "", "", "", str(c.total)])
    t = Table(rows, colWidths=[200, 90, 70, 70, 90])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0E6E76")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story += [t, Spacer(1, 24),
              Paragraph("Accepted for Supplier: ______________________  Date: __________", ss["BodyText"]),
              Paragraph(f"For Helix Silicon: {c.requested_by}  Date: __________", ss["BodyText"])]
    SimpleDocTemplate(str(path), pagesize=letter, title=f"Supply Agreement {c.id}").build(story)
    return path


def summary(c: VendorContract) -> str:
    lines = [f"*Supply Agreement {c.id}*: Helix Silicon × {c.vendor_name}"]
    lines += [f"• {i['description']}: {i['qty']} {i['unit']} × {i['unit_price']} = {i['amount']} {c.currency}" for i in c.items]
    lines += [f"• Total: *{c.total} {c.currency}*", f"• Payment: {terms_text(c.terms)}"]
    if c.delivery:
        lines.append(f"• Delivery: {c.delivery}")
    return "\n".join(lines)
