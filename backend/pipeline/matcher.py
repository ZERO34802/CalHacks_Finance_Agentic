"""[4] Matcher. Owner: A. 3-way match invoice vs PO vs receipts, with contract terms. All math in code, Decimal.

Expected unit price per SKU: the latest ContractTerm (same vendor, SKU, currency) with
effective_from <= invoice_date; if none applies, the PO price. So an amendment billed before its
effective date is measured against the PO/earlier term (seed case_03: price_over, USD 2,400.00).

Emitted (each cites doc id + line):
  unknown_po        no PO, or PO belongs to another vendor              (no further matching)
  currency_mismatch invoice currency != PO currency                    (prices not compared; FX via policy only)
  missing_receipt   PO has no goods receipt at all
  qty_short         billed qty > received qty (+ tolerance)   delta = short qty x expected price
  price_over        billed price > expected price (+ tolerance) delta = (billed - expected) x billed qty
  unapproved_freight an invoice line whose SKU is not on the PO     delta = line amount
  total_mismatch    printed total != sum of lines, or printed line amount != qty x price
Differences within tolerance or below materiality (policy: abs in USD, or pct of invoice total) become below_materiality,
material=False, original_type=<the type>. Deltas are in invoice currency, to the cent.
Discrepancies from earlier stages (embedded_instructions, duplicate_invoice) are kept.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from typing import Optional

from backend.core.stage import Ctx
from backend.pipeline.lib.money import convert, q2, to_usd
from backend.pipeline.lib.refs import rec_refs
from backend.pipeline.lib.split import on_probation, split
from backend.pipeline.registry import registry_for_discrepancies
from contracts import (Case, Citation, ContractTerm, Discrepancy, DiscrepancyType as T, Invoice, PO, Receipt,
                       StepStatus)

MINE = {T.unknown_po, T.currency_mismatch, T.missing_receipt, T.qty_short, T.price_over, T.unapproved_freight,
        T.total_mismatch, T.below_materiality}
MATERIALITY_APPLIES = {T.qty_short, T.price_over, T.unapproved_freight, T.total_mismatch}


def expected_price(sku: str, inv: Invoice, po_line_price: Decimal, po: PO,
                   terms: list[ContractTerm]) -> tuple[Decimal, str, Optional[ContractTerm], list[ContractTerm]]:
    """-> (price, source, applied term, terms not yet effective)."""
    mine = [t for t in terms if t.sku == sku and t.currency == inv.currency]
    applicable = sorted((t for t in mine if t.effective_from <= inv.invoice_date), key=lambda t: t.effective_from)
    future = [t for t in mine if t.effective_from > inv.invoice_date]
    if applicable:
        t = applicable[-1]
        return t.unit_price, f"contract {t.doc_id} effective {t.effective_from}", t, future
    return po_line_price, f"PO {po.po_number}", None, future


def is_material(delta: Decimal, inv: Invoice, ctx: Ctx) -> bool:
    m = ctx.policy.materiality
    usd = to_usd(abs(delta), inv.currency, ctx.policy)
    if usd is not None and usd < m.abs:
        return False
    if inv.total and abs(delta) < abs(inv.total) * m.pct:
        return False
    return True


def match(case: Case, ctx: Ctx) -> tuple[list[Discrepancy], dict]:
    inv = case.invoice
    pol = ctx.policy
    out: list[Discrepancy] = []
    info: dict = {}
    ic = lambda li: Citation(doc_id=inv.doc_id, locator=f"line {li.line_no}",  # noqa: E731
                             quote=f"{li.sku} qty {li.qty} @ {li.unit_price} = {li.amount}")

    # totals (printed vs recomputed), independent of PO
    computed = q2(sum((li.amount for li in inv.lines), Decimal(0)))
    info["computed_total"] = str(computed)
    if computed != inv.total:
        out.append(Discrepancy(type=T.total_mismatch, expected=str(computed), actual=str(inv.total),
                               delta=q2(inv.total - computed),
                               citations=[Citation(doc_id=inv.doc_id, locator="total", quote=str(inv.total))]
                               + [ic(li) for li in inv.lines]))
    for f in inv.flags:
        if f.startswith("line_amount_mismatch:"):
            _, n, printed = f.split(":", 2)
            li = next((x for x in inv.lines if x.line_no == int(n)), None)
            if li is not None:
                out.append(Discrepancy(type=T.total_mismatch, line_no=li.line_no, sku=li.sku, expected=str(li.amount),
                                       actual=printed, delta=q2(Decimal(printed) - li.amount),
                                       citations=[Citation(doc_id=inv.doc_id, locator=f"line {li.line_no}",
                                                           quote=f"printed amount {printed}")]))

    if inv.credit_for:  # credit note: no 3-way match; it offsets the credited invoice (hooks.py closes follow-ups)
        info["credit_note_for"] = inv.credit_for
        case.po, case.receipts = None, []
        return out, info
    po = ctx.store.get_po(inv.po_number) if inv.po_number else None
    if po is None or po.vendor_id != case.vendor_id:
        why = "no PO number on invoice" if not inv.po_number else (
            f"PO {inv.po_number} not found" if po is None else f"PO {inv.po_number} belongs to {po.vendor_id}")
        out.append(Discrepancy(type=T.unknown_po, expected="PO for this vendor", actual=inv.po_number or "none",
                               citations=[Citation(doc_id=inv.doc_id, locator="header", quote=f"PO: {inv.po_number}")]))
        info["po"] = why
        case.po, case.receipts = None, []
        return out, info
    case.po = po
    receipts = ctx.store.list_receipts(po.po_number)
    case.receipts = receipts
    terms = ctx.store.list_contract_terms(case.vendor_id)
    info.update(po=po.doc_id, receipts=[r.doc_id for r in receipts])

    if inv.currency != po.currency:
        exp = sum((pl.unit_price * li.qty for li in inv.lines for pl in po.lines if pl.sku == li.sku), Decimal(0))
        conv = convert(exp, po.currency, inv.currency, pol)
        out.append(Discrepancy(type=T.currency_mismatch, expected=po.currency, actual=inv.currency,
                               delta=q2(inv.total - conv) if conv is not None else None,
                               citations=[Citation(doc_id=inv.doc_id, locator="header", quote=inv.currency),
                                          Citation(doc_id=po.doc_id, locator="header", quote=po.currency)]))
        info["fx"] = "SIMULATED policy fx_rates" if conv is not None else "no fx rate"
        return out, info

    if not receipts:
        out.append(Discrepancy(type=T.missing_receipt, expected="goods receipt for PO", actual="none",
                               citations=[Citation(doc_id=po.doc_id, locator="header", quote=po.po_number)]))
    received: dict[str, Decimal] = {}
    rcpt_doc: dict[str, Receipt] = {}
    for r in receipts:
        for rl in r.lines:
            received[rl.sku] = received.get(rl.sku, Decimal(0)) + rl.qty_received
            rcpt_doc.setdefault(rl.sku, r)

    by_sku: "OrderedDict[str, list]" = OrderedDict()
    for li in inv.lines:
        by_sku.setdefault(li.sku, []).append(li)
    po_by_sku = {pl.sku: pl for pl in po.lines}
    tol_q, tol_p = pol.tolerances.qty_pct, pol.tolerances.price_pct
    vendor = ctx.store.get_vendor(case.vendor_id)
    if on_probation(vendor, case.as_of):  # new vendor: zero tolerance, full 3-way, no pay before first GRN
        tol_q = Decimal(str(pol.probation.get("qty_pct", "0")))
        tol_p = Decimal(str(pol.probation.get("price_pct", "0")))
        info["probation"] = {"until": str(vendor.probation_until) if vendor.probation_until else None,
                             "qty_pct": str(tol_q), "price_pct": str(tol_p)}
    prices = {}
    for sku, lis in by_sku.items():
        first = lis[0]
        pl = po_by_sku.get(sku)
        if pl is None:
            for li in lis:
                out.append(Discrepancy(type=T.unapproved_freight, line_no=li.line_no, sku=sku,
                                       expected="not on PO", actual=str(li.amount), delta=li.amount,
                                       citations=[ic(li), Citation(doc_id=po.doc_id, locator="lines",
                                                                   quote=f"PO {po.po_number} has no {sku}")]))
            continue
        price, source, term, future = expected_price(sku, inv, pl.unit_price, po, terms)
        prices[sku] = {"expected": str(price), "source": source,
                       "not_yet_effective": [f"{t.doc_id} {t.unit_price} from {t.effective_from}" for t in future]}
        po_cite = Citation(doc_id=po.doc_id, locator=f"line {pl.line_no}", quote=f"{sku} qty {pl.qty} @ {pl.unit_price}")
        billed = sum((li.qty for li in lis), Decimal(0))
        # qty: billed vs received
        if receipts:
            got = received.get(sku, Decimal(0))
            if billed > got:
                short = billed - got
                r = rcpt_doc.get(sku) or receipts[0]
                out.append(Discrepancy(type=T.qty_short, line_no=first.line_no, sku=sku, expected=str(got),
                                       actual=str(billed), delta=q2(short * price),
                                       material=billed > got * (1 + tol_q),
                                       citations=[ic(first), po_cite,
                                                  Citation(doc_id=r.doc_id, locator=f"sku {sku}",
                                                           quote=f"received {got}")]))
        # price: billed vs expected (contract term at invoice date, else PO)
        for li in lis:
            if li.unit_price > price:
                cites = [ic(li), po_cite]
                if term is not None:
                    cites.append(Citation(doc_id=term.doc_id, locator=f"sku {sku}",
                                          quote=f"{term.unit_price} effective {term.effective_from}"))
                for t in future:
                    cites.append(Citation(doc_id=t.doc_id, locator=f"sku {sku}",
                                          quote=f"{t.unit_price} effective {t.effective_from} (not yet effective "
                                                f"on invoice date {inv.invoice_date})"))
                out.append(Discrepancy(type=T.price_over, line_no=li.line_no, sku=sku, expected=str(price),
                                       actual=str(li.unit_price), delta=q2((li.unit_price - price) * li.qty),
                                       material=li.unit_price > price * (1 + tol_p),
                                       citations=cites))
    info["prices"] = prices
    info["received"] = {k: str(v) for k, v in received.items()}
    return out, info


class Matcher:
    name = "matcher"

    def run(self, case: Case, ctx: Ctx) -> Case:
        if case.invoice is None:
            if rec_refs(case):  # supplier reply without an invoice: linked by the Registry, nothing to match
                ctx.trace.annotate(status=StepStatus.skipped, detail={"reason": "supplier reply, no invoice"})
                return case
            raise ValueError("matcher: no invoice on case")
        found, info = match(case, ctx)
        probation = "probation" in info  # zero tolerance AND no materiality allowance (data/FORMATS.md P1)
        for d in found:
            # within tolerance (material=False from match) or below materiality -> logged, auto-accepted
            if d.type in MATERIALITY_APPLIES and d.delta is not None and not probation and (
                    not d.material or not is_material(d.delta, case.invoice, ctx)):
                d.original_type, d.type, d.material = d.type, T.below_materiality, False
        kept = [d for d in case.discrepancies if d.type not in MINE]
        case.discrepancies = kept + found
        fps = registry_for_discrepancies(case, ctx)
        if case.invoice.corrects:  # make the delta a code fact before anyone decides (no double payment)
            from backend.pipeline.poster import ap_booked
            from backend.pipeline.registry import find_invoice_case
            orig = find_invoice_case(ctx, case.vendor_id, case.invoice.corrects, case.id)
            booked = ap_booked(orig, ctx)
            delta = q2(max(Decimal(0), case.invoice.total - booked))
            info["correction"] = {"original": orig.id if orig else None, "already_booked": str(booked),
                                  "delta_to_post": str(delta)}
            note = (f"matcher: {case.invoice.invoice_no} corrects {case.invoice.corrects}"
                    + (f" ({orig.id}); {booked} {case.invoice.currency} already booked there, so approving posts "
                       f"only the delta {delta} {case.invoice.currency} (no double payment)" if orig else
                       "; original not on file"))
            case.notes = [n for n in case.notes if not n.startswith(f"matcher: {case.invoice.invoice_no} corrects")]
            case.notes.append(note)
        sp = split(case)
        case.disputed_amount = sp["disputed"] if sp["separable"] else None
        material = [d for d in case.discrepancies if d.material]
        ctx.trace.annotate(
            inputs=[case.invoice.doc_id] + ([case.po.doc_id] if case.po else []) + [r.doc_id for r in case.receipts],
            outputs=[f"{d.type.value}:{d.sku or ''}" for d in case.discrepancies],
            detail={**info, "clean": not material,
                    "material_variance": str(q2(sum((d.delta for d in found if d.material and d.delta is not None
                                                     and d.type != T.currency_mismatch), Decimal(0)))),
                    "discrepancies": [{"type": d.type.value, "sku": d.sku, "line": d.line_no, "delta": str(d.delta),
                                       "material": d.material} for d in case.discrepancies],
                    "fingerprints": fps, "separable": sp["separable"],
                    "disputed_amount": str(sp["disputed"]) if sp["separable"] else None,
                    "undisputed_amount": str(sp["undisputed"]) if sp["separable"] else None})
        return case
