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
"""
from __future__ import annotations

from typing import Optional

from backend.core.stage import Ctx
from backend.pipeline.lib.fingerprint import evidence_hash, fingerprint
from backend.pipeline.lib.ids import levenshtein, normalize_invoice_no
from contracts import Case, CaseLink, CaseLinkType, CaseStatus, Discrepancy

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


class Registry:
    name = "registry"

    def run(self, case: Case, ctx: Ctx) -> Case:
        inv = case.invoice
        if inv is None:
            raise ValueError("registry: no invoice on case")
        case.evidence_hash = evidence_hash(d.sha256 for d in case.documents)
        case.fingerprint = fingerprint(case.vendor_id, inv.po_number, inv.invoice_no)
        action, owner = claim(case.fingerprint, case, ctx)
        case.links = [l for l in case.links if l.type != CaseLinkType.attached_to]
        if owner is not None:
            case.links.append(CaseLink(type=CaseLinkType.attached_to, case_id=owner.id, invoice_no=inv.invoice_no,
                                       reason=f"same invoice fingerprint as {owner.id} (status {owner.status.value}); "
                                              f"action {action}"))
            prior = f", prior decision {owner.decision.value}" if owner.decision else ""
            case.notes.append(f"registry: {action} -> {owner.id}{prior}")
        ctx.trace.annotate(outputs=[case.fingerprint], detail={
            "fingerprint": case.fingerprint, "evidence_hash": case.evidence_hash, "action": action,
            "owner": owner.id if owner else case.id})
        return case


def registry_for_discrepancies(case: Case, ctx: Ctx) -> list[dict]:
    """Per-discrepancy fingerprints + level 2 (corrected invoice) and level 3 (pattern) links."""
    inv = case.invoice
    out: list[dict] = []
    priors = [c for c in ctx.store.list_cases(case.vendor_id) if c.id != case.id and c.invoice is not None]
    case.links = [l for l in case.links if l.type not in (CaseLinkType.corrected_by, CaseLinkType.related_pattern)]
    linked: set[tuple] = set()
    for d in case.discrepancies:
        d.fingerprint = fingerprint(case.vendor_id, inv.po_number, inv.invoice_no, d.type.value, d.sku)
        action, owner = claim(d.fingerprint, case, ctx)
        row = {"type": d.type.value, "sku": d.sku, "fingerprint": d.fingerprint, "action": action,
               "owner": owner.id if owner else case.id}
        for c in priors:
            same = [x for x in c.discrepancies if x.type == d.type and (x.sku or "") == (d.sku or "")]
            if not same:
                continue
            a, b = normalize_invoice_no(inv.invoice_no), normalize_invoice_no(c.invoice.invoice_no)
            if a == b:
                continue  # same invoice: handled by the fingerprint above
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
