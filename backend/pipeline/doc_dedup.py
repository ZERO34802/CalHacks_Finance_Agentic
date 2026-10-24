"""[2] Document dedup. Owner: A. Is this invoice one we have already seen or paid?

Checks, against prior cases in the store (same vendor, other case ids) and paid history:
  file_hash     same sha256 of an invoice document (store.find_documents)
  invoice_no    same vendor + normalized invoice number (INV-0042 == 42 == inv 42)
  line_hash     same sorted (sku, qty, unit_price) -- a resend under a new number. Same PO: a duplicate
                unless the PO's receipts cover every billing of these lines (recurring fee / next
                shipment: noted, not flagged). Different PO: different goods, not a duplicate.
                No PO on either side: duplicate when numbers are within edit distance 2 or dates within
                WINDOW_DAYS
  fuzzy         same total + currency, dates within WINDOW_DAYS, invoice-number edit distance <= 2
  paid          any of the above against store.list_paid (paid_on is the date used)
Hit -> CaseLink(duplicate_of) + one Discrepancy(duplicate_invoice) with citations.
Same invoice twice inside one case is linked by the Reader and is NOT a duplicate_invoice.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import re

from backend.core.stage import Ctx
from backend.pipeline.lib.refs import rec_refs
from backend.pipeline.lib.ids import invoice_line_hash, levenshtein, normalize_invoice_no
from contracts import (Case, CaseLink, CaseLinkType, Citation, Discrepancy, DiscrepancyType, DocKind, Invoice,
                       PaidInvoice, StepStatus)

WINDOW_DAYS = 14
MAX_EDIT = 2


def paid_ref(p: PaidInvoice) -> str:
    """Citation doc id for a paid-history row (system of record)."""
    return f"erp-PAID-{p.vendor_id}-{p.invoice_no}"


def _within(a: date, b: date) -> bool:
    return abs((a - b).days) <= WINDOW_DAYS


def compare(inv: Invoice, other_no: str, other_total, other_ccy: str, other_date: Optional[date],
            other_line_hash: Optional[str], other_po: Optional[str]) -> list[str]:
    """Which dedup rules match between this invoice and another record.
    'line_hash?' = same lines on the same PO; the caller decides with the receipt-capacity check."""
    a, b = normalize_invoice_no(inv.invoice_no), normalize_invoice_no(other_no)
    near_no = levenshtein(a, b) <= MAX_EDIT and min(len(a), len(b)) >= 3
    near_date = other_date is not None and _within(inv.invoice_date, other_date)
    rules = []
    if a == b:
        rules.append("invoice_no")
    if other_line_hash and other_line_hash == invoice_line_hash(inv):
        if inv.po_number and other_po:
            if inv.po_number.strip().upper() == other_po.strip().upper():
                rules.append("line_hash?")
        elif near_no or near_date or a == b:
            rules.append("line_hash")
    if a != b and near_no and near_date and other_total == inv.total and other_ccy == inv.currency:
        rules.append("fuzzy")
    return rules


def receipts_cover(inv: Invoice, billings: int, ctx: Ctx) -> bool:
    """Do the PO's receipts cover `billings` earlier invoices with these lines plus this one?"""
    if not inv.po_number:
        return False
    got: dict[str, object] = {}
    for r in ctx.store.list_receipts(inv.po_number):
        for rl in r.lines:
            got[rl.sku] = got.get(rl.sku, 0) + rl.qty_received
    need: dict[str, object] = {}
    for li in inv.lines:
        need[li.sku] = need.get(li.sku, 0) + li.qty
    return all(got.get(sku, 0) >= q * (billings + 1) for sku, q in need.items())


def explain(inv: Invoice, hits: list[dict], ctx: Ctx) -> tuple[list[str], list[Citation]]:
    """Plain-language reasons (for the Investigator / Approver) + citations for every claim."""
    lines_txt = ", ".join(f"{li.sku} {li.qty} @ {li.unit_price}" for li in inv.lines)
    why: list[str] = []
    cites = [Citation(doc_id=inv.doc_id, locator="invoice_no", quote=inv.invoice_no)]
    cites += [Citation(doc_id=inv.doc_id, locator=f"line {li.line_no}",
                       quote=f"{li.sku} qty {li.qty} @ {li.unit_price} = {li.amount}") for li in inv.lines]
    for h in hits:
        rule = h["rule"].split(":")[-1]
        paid = h["rule"].startswith("paid:")
        other = h["invoice_no"] or h["doc_id"]
        where = f"paid invoice {other} ({h['detail'].split('(paid ', 1)[-1].rstrip(')')})" if paid else \
            f"{other} in case {h['case_id']}"
        if rule == "file_hash":
            why.append(f"byte-identical file to {h['doc_id']} in case {h['case_id']} (same sha256)")
        elif rule == "invoice_no":
            why.append(f"invoice number {inv.invoice_no} normalizes to {normalize_invoice_no(inv.invoice_no)}, "
                       f"the same as {where}")
        elif rule == "line_hash":
            why.append(f"identical lines ({lines_txt}) on the same PO {inv.po_number} as {where}; the PO's goods "
                       f"receipts cover only one billing of these lines, so this bills the same goods again")
        elif rule == "fuzzy":
            why.append(f"same total {inv.currency} {inv.total} as {where}, invoice numbers differ by at most "
                       f"{MAX_EDIT} characters, dated within {WINDOW_DAYS} days")
        cites.append(Citation(doc_id=h["doc_id"], locator="invoice_no" if h["invoice_no"] else "file",
                              quote=h["invoice_no"] or h["detail"][:120]))
    if any(h["rule"].endswith("line_hash") for h in hits) and inv.po_number:
        for r in ctx.store.list_receipts(inv.po_number):
            for rl in r.lines:
                cites.append(Citation(doc_id=r.doc_id, locator=f"sku {rl.sku}", quote=f"received {rl.qty_received}"))
    seen, uniq = set(), []
    for c in cites:
        if (c.doc_id, c.locator) not in seen:
            seen.add((c.doc_id, c.locator))
            uniq.append(c)
    return list(dict.fromkeys(why)), uniq


class DocDedup:
    name = "doc_dedup"

    def run(self, case: Case, ctx: Ctx) -> Case:
        inv = case.invoice
        if inv is None:
            if rec_refs(case):  # supplier reply without an invoice: nothing to dedup
                ctx.trace.annotate(status=StepStatus.skipped, detail={"reason": "supplier reply, no invoice"})
                return case
            raise ValueError("doc_dedup: no invoice on case")
        corrects = normalize_invoice_no(inv.corrects) if inv.corrects else None
        hits: list[dict] = []
        notes: list[str] = []
        my_hash = invoice_line_hash(inv)

        # file hash (any invoice doc of this case seen in another case)
        for d in case.documents:
            if d.kind not in (DocKind.invoice, DocKind.credit_note):
                continue
            for cid, other in ctx.store.find_documents(d.sha256):
                if cid != case.id and not re.match(rf"^{re.escape(case.id)}-\d+$", cid):
                    hits.append({"rule": "file_hash", "case_id": cid, "doc_id": other.id, "invoice_no": None,
                                 "mine": d.id, "detail": f"{d.filename} sha256 {d.sha256[:12]} seen in {cid}"})

        # prior cases of the same vendor
        for other in ctx.store.list_cases(case.vendor_id):
            if other.id == case.id or other.invoice is None or other.parent_id:
                continue  # sub-cases carry their parent's invoice; never compare against them
            o = other.invoice
            if bool(o.credit_for) != bool(inv.credit_for) or normalize_invoice_no(o.invoice_no) == corrects:
                continue  # credit notes vs invoices, and a corrected invoice vs the one it replaces
            rules = compare(inv, o.invoice_no, o.total, o.currency, o.invoice_date, invoice_line_hash(o), o.po_number)
            for r in rules:
                hits.append({"rule": r, "case_id": other.id, "doc_id": o.doc_id, "invoice_no": o.invoice_no,
                             "mine": inv.doc_id, "detail": f"{r}: {inv.invoice_no} vs {o.invoice_no} ({other.id})"})

        # paid history
        for p in ctx.store.list_paid(case.vendor_id):
            if inv.credit_for or normalize_invoice_no(p.invoice_no) == corrects:
                continue
            rules = compare(inv, p.invoice_no, p.total, p.currency, p.paid_on, p.line_hash, p.po_number)
            for r in rules:
                hits.append({"rule": f"paid:{r}", "case_id": None, "doc_id": paid_ref(p), "invoice_no": p.invoice_no,
                             "mine": inv.doc_id,
                             "detail": f"{r}: {inv.invoice_no} vs paid {p.invoice_no} (paid {p.paid_on}, "
                                       f"{p.currency} {p.total})"})

        # same lines on the same PO: duplicate only if the receipts cannot cover another billing
        tentative = [h for h in hits if h["rule"].endswith("line_hash?")]
        if tentative:
            billings = len({(h["case_id"], h["invoice_no"]) for h in tentative})
            covered = receipts_cover(inv, billings, ctx)
            for h in tentative:
                h["rule"] = h["rule"].rstrip("?")
            if covered:
                notes.append(f"doc_dedup: same lines as {sorted({h['invoice_no'] for h in tentative})} on PO "
                             f"{inv.po_number}, but receipts cover {billings + 1} billings: recurring / next "
                             f"shipment, not a duplicate")
                hits = [h for h in hits if h not in tentative]
        case.links = [l for l in case.links if not (l.type == CaseLinkType.duplicate_of and l.case_id != case.id)]
        case.discrepancies = [x for x in case.discrepancies if x.type != DiscrepancyType.duplicate_invoice]
        if hits:
            by_target: dict[tuple, list[dict]] = {}
            for h in hits:
                by_target.setdefault((h["case_id"], h["invoice_no"] or h["doc_id"]), []).append(h)
            for (cid, ref), hs in by_target.items():
                rules = sorted({h["rule"] for h in hs})
                case.links.append(CaseLink(type=CaseLinkType.duplicate_of, case_id=cid, invoice_no=hs[0]["invoice_no"],
                                           reason=f"{', '.join(rules)}: " + "; ".join(h["detail"] for h in hs)[:400]))
            why, cites = explain(inv, hits, ctx)
            case.discrepancies.append(Discrepancy(
                type=DiscrepancyType.duplicate_invoice, material=True,
                expected="an invoice not already billed or paid", actual="; ".join(why)[:900],
                delta=inv.total, citations=cites))
        case.notes.extend(notes)
        ctx.trace.annotate(inputs=[d.id for d in case.documents if d.kind == DocKind.invoice],
                           outputs=[l.reason[:80] for l in case.links if l.type == CaseLinkType.duplicate_of],
                           detail={"line_hash": my_hash, "normalized_invoice_no": normalize_invoice_no(inv.invoice_no),
                                   "duplicates": hits, "recurring_notes": notes})
        return case
