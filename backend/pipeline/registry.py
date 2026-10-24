"""[3] Case registry lookup. Owner: A. Already triaged? new / attach / skip / reopen delta.

Two-step design (the fixed stage order runs Registry before the Matcher produces discrepancies):
- here, an INVOICE-level fingerprint hash(vendor + PO + normalized invoice no + "*" + "*") is claimed
  atomically with store.claim_fingerprint (insert-or-get). It becomes case.fingerprint.
- at the end of the Matcher, every discrepancy gets its own fingerprint (type + SKU) claimed the same way;
  see registry_for_discrepancies() below, called by matcher.py. Results go into Discrepancy.fingerprint and the
  matcher step detail (sub-case keys; real sub-cases are P1).

Action table when the fingerprint is owned by another case (CLAUDE.md section 7):
  owner resolved/posted, evidence unchanged -> skip   (cite prior resolution)
  owner resolved/posted, evidence changed   -> reopen_delta
  owner in progress / new / awaiting / escalated / approved -> attach
  owner rejected                             -> keep_prior (reopen_delta if evidence changed)
  owner quarantined                          -> attach
The Registry only records facts (links, notes, actions); the Router/Approver decide.

P1 (data/FORMATS.md "P1 conventions"):
- supplier reply: a document with [REC <case_id>] (subject or quoted body) -> attached_to link to that case +
  note "supplier reply to <case_id>". Only when the target exists and belongs to the same vendor (a reply
  can't reach into another vendor's case). B's reply handler updates follow-ups.
- corrected invoice (Invoice.corrects / -R): corrected_by link to the original case (reason "corrects ...").
  The original is reopened and only the delta is triaged after this case is decided (pipeline/hooks.py).
- credit note (Invoice.credit_for): attached_to link to the credited invoice's case; closure in hooks.py.
"""
from __future__ import annotations

from typing import Optional

from backend.core.stage import Ctx
from backend.pipeline.lib.fingerprint import evidence_hash, fingerprint
from backend.pipeline.lib.ids import levenshtein, normalize_invoice_no
from backend.pipeline.lib.refs import rec_refs
from contracts import Case, CaseLink, CaseLinkType, CaseStatus, Discrepancy, StepStatus

DONE = {CaseStatus.resolved, CaseStatus.posted}


def action_for(owner: Case, evidence: str) -> str:
    changed = owner.evidence_hash is not None and owner.evidence_hash != evidence
    if owner.status in DONE:
        return "reopen_delta" if changed else "skip"
    if owner.status == CaseStatus.rejected:
        return "reopen_delta" if changed else "keep_prior"
    return "attach"


def claim(fp: str, case: Case, ctx: Ctx) -> tuple[str, Optional[Case]]:
    owner_id = ctx.store.claim_fingerprint(fp, case.id)
    if owner_id == case.id:
        return "new", None
    owner = ctx.store.get_case(owner_id)
    if owner is None:  # stale claim (owner deleted): treat as ours
        return "new", None
    return action_for(owner, case.evidence_hash or ""), owner


def find_invoice_case(ctx: Ctx, vendor_id: str, invoice_no: str, exclude: str) -> Optional[Case]:
    """The parent case (not a sub-case) holding this vendor's invoice number (normalized)."""
    n = normalize_invoice_no(invoice_no)
    hits = [c for c in ctx.store.list_cases(vendor_id)
            if c.id != exclude and not c.parent_id and c.invoice and not c.invoice.credit_for
            and normalize_invoice_no(c.invoice.invoice_no) == n]
    return hits[0] if hits else None


def link_replies(case: Case, ctx: Ctx, why_not: Optional[list[str]] = None) -> list[str]:
    linked = []
    why_not = why_not if why_not is not None else []
    lookalike = any("is a look-alike of" in n for n in case.notes)
    for ref in rec_refs(case):
        target = ctx.store.get_case(ref)
        if target is None:
            why_not.append(f"references unknown case {ref}")
        elif target.vendor_id != case.vendor_id:
            why_not.append(f"references {ref} of another vendor ({target.vendor_id})")
        elif lookalike:
            why_not.append(f"references {ref} but comes from a look-alike sender domain")
        else:
            if not any(l.type == CaseLinkType.attached_to and l.case_id == ref for l in case.links):
                case.links.append(CaseLink(type=CaseLinkType.attached_to, case_id=ref,
                                           invoice_no=target.invoice.invoice_no if target.invoice else None,
                                           reason=f"supplier reply to {ref} ([REC {ref}])"))
            note = f"supplier reply to {ref}"
            if note not in case.notes:
                case.notes.append(note)
            linked.append(ref)
    return linked


class Registry:
    name = "registry"

    def run(self, case: Case, ctx: Ctx) -> Case:
        inv = case.invoice
        why_not: list[str] = []
        replies = link_replies(case, ctx, why_not)
        for w in why_not:
            case.notes.append(f"registry: reply not attached: {w}")
        if inv is None:
            if replies:  # support document: attached to its case, nothing to triage (no agents, no skill)
                case.evidence_hash = evidence_hash(d.sha256 for d in case.documents)
                case.status, case.decision, case.skill = CaseStatus.resolved, None, None
                for ref in replies:
                    note = f"attached to {ref}: supplier reply"
                    if note not in case.notes:
                        case.notes.append(note)
                ctx.trace.annotate(outputs=replies, detail={"action": "supplier_reply", "reply_to": replies})
                return case
            if why_not:
                raise ValueError(f"supplier reply cannot be attached ({'; '.join(why_not)}); needs a human")
            raise ValueError("registry: no invoice on case")
        case.evidence_hash = evidence_hash(d.sha256 for d in case.documents)
        case.fingerprint = fingerprint(case.vendor_id, inv.po_number, inv.invoice_no)
        action, owner = claim(case.fingerprint, case, ctx)
        case.links = [l for l in case.links if l.type != CaseLinkType.attached_to or l.case_id in replies]
        extra: dict = {}
        if inv.corrects:
            orig = find_invoice_case(ctx, case.vendor_id, inv.corrects, case.id)
            case.links = [l for l in case.links if l.type != CaseLinkType.corrected_by]
            if orig is not None:
                case.links.append(CaseLink(type=CaseLinkType.corrected_by, case_id=orig.id,
                                           invoice_no=orig.invoice.invoice_no,
                                           reason=f"{inv.invoice_no} corrects {orig.invoice.invoice_no} ({orig.id}); "
                                                  "level 2 correction, only the delta is re-triaged"))
                case.notes.append(f"registry: corrected invoice for {orig.invoice.invoice_no} ({orig.id})")
                extra["corrects_case"] = orig.id
            else:
                case.notes.append(f"registry: says it corrects {inv.corrects}, but no such invoice on file")
        if inv.credit_for:
            target = find_invoice_case(ctx, case.vendor_id, inv.credit_for, case.id)
            if target is not None:
                case.links.append(CaseLink(type=CaseLinkType.attached_to, case_id=target.id,
                                           invoice_no=target.invoice.invoice_no,
                                           reason=f"credit note {inv.invoice_no} for {target.invoice.invoice_no}"))
                extra["credit_for_case"] = target.id
            else:
                case.notes.append(f"registry: credit note for {inv.credit_for}, but no such invoice on file")
        if owner is not None:
            case.links.append(CaseLink(type=CaseLinkType.attached_to, case_id=owner.id, invoice_no=inv.invoice_no,
                                       reason=f"same invoice fingerprint as {owner.id} (status {owner.status.value}); "
                                              f"action {action}"))
            prior = f", prior decision {owner.decision.value}" if owner.decision else ""
            case.notes.append(f"registry: {action} -> {owner.id}{prior}")
        ctx.trace.annotate(outputs=[case.fingerprint], detail={
            "fingerprint": case.fingerprint, "evidence_hash": case.evidence_hash, "action": action,
            "owner": owner.id if owner else case.id, "reply_to": replies, **extra})
        return case


def registry_for_discrepancies(case: Case, ctx: Ctx) -> list[dict]:
    """Per-discrepancy fingerprints + level 2 (corrected invoice) and level 3 (pattern) links."""
    inv = case.invoice
    out: list[dict] = []
    priors = [c for c in ctx.store.list_cases(case.vendor_id)
              if c.id != case.id and c.invoice is not None and not c.parent_id]
    case.links = [l for l in case.links  # drop only links this function made on an earlier run
                  if not (l.type in (CaseLinkType.corrected_by, CaseLinkType.related_pattern) and "(level" in l.reason)]
    linked: set[tuple] = set()
    for d in case.discrepancies:
        d.fingerprint = fingerprint(case.vendor_id, inv.po_number, inv.invoice_no, d.type.value, d.sku)
        action, owner = claim(d.fingerprint, case, ctx)
        if owner is not None and owner.parent_id == case.id:  # our own sub-case from an earlier run
            action, owner = "new", None
        row = {"type": d.type.value, "sku": d.sku, "fingerprint": d.fingerprint, "action": action,
               "owner": owner.id if owner else case.id}
        for c in priors:
            same = [x for x in c.discrepancies if x.type == d.type and (x.sku or "") == (d.sku or "")]
            if not same:
                continue
            a, b = normalize_invoice_no(inv.invoice_no), normalize_invoice_no(c.invoice.invoice_no)
            if a == b:
                continue  # same invoice: handled by the fingerprint above
            if inv.corrects and normalize_invoice_no(inv.corrects) == b:
                continue  # already linked as corrected_by in run()
            if c.invoice.po_number == inv.po_number and (levenshtein(a, b) <= 2 or a.startswith(b) or b.startswith(a)):
                lt, why = CaseLinkType.corrected_by, "corrected invoice for the same discrepancy (level 2)"
            else:
                lt, why = CaseLinkType.related_pattern, "same vendor + discrepancy type, other PO/period (level 3)"
            if (lt, c.id) not in linked:
                linked.add((lt, c.id))
                case.links.append(CaseLink(type=lt, case_id=c.id, invoice_no=c.invoice.invoice_no,
                                           reason=f"{why}: {d.type.value} {d.sku or ''}".strip()))
            row.setdefault("links", []).append({"type": lt.value, "case_id": c.id})
        out.append(row)
    return out


__all__ = ["Registry", "registry_for_discrepancies", "Discrepancy"]
