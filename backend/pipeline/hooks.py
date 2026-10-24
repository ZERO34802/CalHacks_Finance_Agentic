"""A's P1 hooks (auto-loaded by backend.core.hooks). Owner: A.

after_case (runs after every non-paused case, after B's hooks):
- sub-cases: one child Case per material discrepancy, id=<parent>-<n>, parent_id, sub_case_of link, its own
  fingerprint, decision from the decision table for that one discrepancy. Parent lists them in sub_case_ids;
  the parent's decision is the strictest child's (raised if weaker, with a note). Children carry no documents
  (they reference the parent's) and are never deduped against, posted or queued.
- credit note (Invoice.credit_for), decided approve/hold: closes the credited case's open/overdue credit_note
  follow-ups (status done, closed_by=<credit note doc id>) and resolves its sub-case whose delta equals the
  credit (qty_short first). Parent resolved once every child is resolved.
- corrected invoice (Invoice.corrects), decided approve/hold: the original is reopened (status reopened,
  reopens+1) and only the delta is triaged: if (original total - corrected total) equals the original's
  disputed amount, the original's sub-cases resolve and its credit_note / corrected_invoice follow-ups close
  (closed_by=<this case id>) and it is resolved; otherwise it stays reopened with a note.
  Escalated or rejected credit notes / corrections (e.g. from a look-alike domain) close nothing.
- queue priority: case.priority = weights . features (policy.queue).
sweep "missing_files": Vendor.expected_schedule daily|weekly vs the last document received on or before as_of
  -> Alert(kind="missing_file") record (key missing_file:<vendor>:<as_of>, idempotent). No wall clock.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional

from backend.core import hooks
from backend.core.stage import Ctx
from backend.pipeline.lib.fingerprint import fingerprint
from backend.pipeline.lib.money import q2, to_usd
from backend.pipeline.lib.split import INFO, SEPARABLE
from backend.pipeline.registry import find_invoice_case
from contracts import (Alert, Case, CaseLink, CaseLinkType, CaseStatus, Decision, DiscrepancyType as T,
                       FollowUpKind, FollowUpStatus)

ESCALATE = {T.bank_change, T.lookalike_domain, T.embedded_instructions, T.unknown_po, T.missing_receipt}
RANK = {Decision.approve: 0, Decision.hold: 1, Decision.reject: 2, Decision.escalate: 3}
CHILD_STATUS = {Decision.escalate: CaseStatus.escalated, Decision.reject: CaseStatus.rejected,
                Decision.hold: CaseStatus.awaiting_vendor}
CLOSED = {CaseStatus.resolved}
OPEN_FU = {FollowUpStatus.open, FollowUpStatus.overdue}


def child_decision(t: T) -> Decision:
    if t in ESCALATE:
        return Decision.escalate
    if t == T.duplicate_invoice:
        return Decision.reject
    if t in SEPARABLE or t in {T.currency_mismatch, T.total_mismatch, T.fx_gap}:
        return Decision.hold
    return Decision.escalate  # unmapped: never guess


def children(case: Case, ctx: Ctx) -> list[Case]:
    return [c for c in ctx.store.list_cases(case.vendor_id) if c.parent_id == case.id]


# --- sub-cases --------------------------------------------------------------------------

def make_sub_cases(case: Case, ctx: Ctx) -> dict:
    if case.parent_id or case.invoice is None or case.status == CaseStatus.quarantined:
        return {}
    inv = case.invoice
    material = [d for d in case.discrepancies if d.material and d.type not in INFO]
    existing = {c.id: c for c in children(case, ctx)}
    ids: list[str] = []
    for n, d in enumerate(material, 1):
        cid = f"{case.id}-{n}"
        fp = d.fingerprint or fingerprint(case.vendor_id, inv.po_number, inv.invoice_no, d.type.value, d.sku)
        d.fingerprint = fp
        prev = existing.get(cid)
        ids.append(cid)
        if prev is not None and prev.status in CLOSED and prev.fingerprint == fp:
            continue  # resolved earlier (credit note / correction): stays resolved
        dec = child_decision(d.type)
        child = Case(id=cid, parent_id=case.id, vendor_id=case.vendor_id, status=CHILD_STATUS[dec], decision=dec,
                     invoice=inv, po=case.po, receipts=case.receipts, fingerprint=fp,
                     evidence_hash=case.evidence_hash, discrepancies=[d], as_of=case.as_of,
                     disputed_amount=d.delta if d.type in SEPARABLE else None,
                     created_at=case.created_at, updated_at=ctx.now(),
                     links=[CaseLink(type=CaseLinkType.sub_case_of, case_id=case.id, invoice_no=inv.invoice_no,
                                     reason=f"{d.type.value}{' ' + d.sku if d.sku else ''} on {inv.invoice_no}")],
                     notes=[f"sub-case {n} of {case.id}: {d.type.value} delta {d.delta}"])
        ctx.store.save_case(child)
    for cid, c in existing.items():
        if cid not in ids and c.status not in CLOSED:
            c.status = CaseStatus.resolved
            c.notes.append(f"no longer present when {case.id} was re-triaged")
            ctx.store.save_case(c)
    case.sub_case_ids = ids
    strict = max((child_decision(d.type) for d in material), key=lambda x: RANK[x], default=None)
    if strict is not None and case.decision is not None and RANK[case.decision] < RANK[strict]:
        case.notes.append(f"sub-cases: parent decision raised {case.decision.value} -> {strict.value} "
                          "(strictest child)")
        case.decision = strict
    return {"sub_cases": ids, "strictest": strict.value if strict else None}


def _resolve_parent_if_done(target: Case, ctx: Ctx, why: str) -> None:
    kids = children(target, ctx)
    if kids and all(k.status in CLOSED for k in kids):
        target.status = CaseStatus.resolved
        target.notes.append(f"resolved: every sub-case closed ({why})")


def _decided_ok(case: Case) -> bool:
    return case.decision in (Decision.approve, Decision.hold) and case.status != CaseStatus.quarantined


# --- credit notes ---------------------------------------------------------------------------

def apply_credit_note(case: Case, ctx: Ctx, force: bool = False) -> dict:
    """force: the Matcher already gated it (support document, nothing to post; see matcher.py)."""
    inv = case.invoice
    if inv is None or not inv.credit_for or not (force or _decided_ok(case)):
        return {}
    target = find_invoice_case(ctx, case.vendor_id, inv.credit_for, case.id)
    if target is None:
        return {"credit_note": "credited invoice not on file"}
    closed = []
    for f in target.follow_ups:
        if f.kind == FollowUpKind.credit_note and f.status in OPEN_FU:
            f.status, f.closed_by = FollowUpStatus.done, inv.doc_id
            closed.append(f.id)
    kids = sorted(children(target, ctx), key=lambda k: (k.discrepancies[0].type != T.qty_short, k.id))
    resolved = None
    for k in kids:
        d = k.discrepancies[0] if k.discrepancies else None
        if k.status not in CLOSED and d is not None and d.type in SEPARABLE and d.delta is not None \
                and q2(d.delta) == q2(inv.total):
            k.status = CaseStatus.resolved
            k.notes.append(f"resolved by credit note {inv.invoice_no} ({case.id}) for {inv.total} {inv.currency}")
            ctx.store.save_case(k)
            resolved = k.id
            break
    if resolved is None:
        target.notes.append(f"credit note {inv.invoice_no} ({case.id}) for {inv.total} {inv.currency} does not "
                            "equal any open disputed delta; sub-cases stay open")
    else:
        target.notes.append(f"credit note {inv.invoice_no} ({case.id}) resolved sub-case {resolved}")
        _resolve_parent_if_done(target, ctx, f"credit note {inv.invoice_no}")
    target.updated_at = ctx.now()
    ctx.store.save_case(target)
    return {"credit_note_target": target.id, "follow_ups_closed": closed, "sub_case_resolved": resolved}


# --- corrected invoices -------------------------------------------------------------------------

def apply_correction(case: Case, ctx: Ctx) -> dict:
    inv = case.invoice
    if inv is None or not inv.corrects or not _decided_ok(case):
        return {}
    orig = find_invoice_case(ctx, case.vendor_id, inv.corrects, case.id)
    if orig is None:
        return {"correction": "original not on file"}
    marker = f"corrected by {inv.invoice_no} ({case.id})"
    first = marker not in " ".join(orig.notes)
    if first:
        orig.status, orig.reopens = CaseStatus.reopened, orig.reopens + 1
        orig.notes.append(f"reopened: {marker}; triaging only the delta")
    if not any(l.type == CaseLinkType.corrected_by and l.case_id == case.id for l in orig.links):
        orig.links.append(CaseLink(type=CaseLinkType.corrected_by, case_id=case.id, invoice_no=inv.invoice_no,
                                   reason=f"corrected invoice {inv.invoice_no} replaces {orig.invoice.invoice_no}"))
    disputed = orig.disputed_amount
    if disputed is None:
        disputed = q2(sum((d.delta for d in orig.discrepancies
                           if d.material and d.type in SEPARABLE and d.delta is not None), Decimal(0)))
    reduction = q2(orig.invoice.total - inv.total)
    new_material = [d for d in case.discrepancies if d.material and d.type not in INFO]
    out = {"original": orig.id, "disputed": str(disputed), "reduction": str(reduction)}
    if reduction == disputed and not new_material:
        for k in children(orig, ctx):
            if k.status not in CLOSED:
                k.status = CaseStatus.resolved
                k.notes.append(f"resolved by corrected invoice {inv.invoice_no} ({case.id})")
                ctx.store.save_case(k)
        for f in orig.follow_ups:
            if f.kind in (FollowUpKind.corrected_invoice, FollowUpKind.credit_note) and f.status in OPEN_FU:
                f.status, f.closed_by = FollowUpStatus.done, case.id
        orig.status = CaseStatus.resolved
        orig.notes.append(f"resolved: corrected invoice {inv.invoice_no} settles the disputed "
                          f"{disputed} {inv.currency}")
        out["resolved"] = True
    elif first:
        orig.notes.append(f"delta: correction reduces the bill by {reduction}, disputed was {disputed}; "
                          f"stays open, see {case.id}")
        out["resolved"] = False
    orig.updated_at = ctx.now()
    ctx.store.save_case(orig)
    return out


# --- queue priority -------------------------------------------------------------------------

def priority(case: Case, ctx: Ctx) -> tuple[float, dict]:
    """Higher = sooner. Features in [0, 1]; weights from policy.queue."""
    q = ctx.policy.queue or {}
    inv = case.invoice
    if inv is None:
        return 0.0, {}
    as_of = case.as_of or ctx.now().date()
    due = inv.due_date or (inv.invoice_date + timedelta(days=30))
    days = (due - as_of).days
    soon = int(q.get("due_soon_days", 5))
    f_due = 1.0 if days <= 0 else (1 - days / (soon + 1) if days <= soon else 0.0)
    usd = to_usd(inv.total, inv.currency, ctx.policy) or Decimal(0)
    f_amount = min(1.0, math.log10(max(float(usd), 1.0)) / 7.0)  # USD 10M -> 1.0 (score only, never money)
    f_discount = 0.0
    for t in ctx.store.list_contract_terms(case.vendor_id):
        pct = getattr(t, "discount_pct", None) or getattr(t, "early_pay_discount_pct", None)
        if pct:
            f_discount = 1.0
    vendor = ctx.store.get_vendor(case.vendor_id)
    f_crit = 1.0 if vendor and vendor.critical else 0.0
    w = {k: float(q.get(f"weight_{k}", 1)) for k in ("due", "amount", "discount", "critical")}
    feats = {"due": f_due, "amount": f_amount, "discount": f_discount, "critical": f_crit}
    score = round(sum(w[k] * feats[k] for k in feats), 3)
    return score, {"due_date": due.isoformat(), "days_to_due": days, "amount_usd": str(usd),
                   **{f"f_{k}": round(v, 3) for k, v in feats.items()}}


@hooks.after_case
def a_after_case(case: Case, ctx: Ctx) -> None:
    detail: dict = {}
    detail.update(make_sub_cases(case, ctx))
    detail.update(apply_credit_note(case, ctx))
    detail.update(apply_correction(case, ctx))
    if not case.parent_id:
        case.priority, detail["priority"] = priority(case, ctx)
    ctx.trace.annotate(detail=detail)


# --- missing files ----------------------------------------------------------------------------

WINDOW = {"daily": 1, "weekly": 7}


def last_received(ctx: Ctx, vendor_id: str, as_of: date) -> Optional[date]:
    days = [d.received_at.date() for c in ctx.store.list_cases(vendor_id) if not c.parent_id
            for d in c.documents if d.received_at.date() <= as_of]
    return max(days) if days else None


@hooks.sweep("missing_files")
def missing_files(ctx: Ctx, as_of: date) -> list[Alert]:
    alerts = []
    for v in ctx.store.list_vendors():
        window = WINDOW.get((v.expected_schedule or "").lower())
        if window is None:
            continue
        last = last_received(ctx, v.id, as_of)
        if last is not None and (as_of - last).days <= window:
            continue
        a = Alert(id=f"missing_file:{v.id}:{as_of.isoformat()}", kind="missing_file", vendor_id=v.id,
                  at=datetime.combine(as_of, time(0), tzinfo=timezone.utc),
                  message=f"{v.name}: expected {v.expected_schedule} file, last received "
                          f"{last.isoformat() if last else 'never'} (as of {as_of.isoformat()})")
        ctx.store.put_record("alert", a.id, a, idx=v.id)
        alerts.append(a)
    ctx.trace.annotate(outputs=[a.id for a in alerts], detail={"missing_files": [a.message for a in alerts]})
    return alerts
