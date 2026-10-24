"""What a pipeline case means for accounts payable. Owner: D. Read-only over the store; Decimal only.

The pipeline (A/B) decides and books; this module only reads the result:
- a *bill* is a parent case for an invoice. Sub-cases (`parent_id`) are grouped under their parent; supplier
  replies, credit notes and corrected invoices that add nothing to pay are shown in the target bill's activity.
- the *payable* amount is what the Poster booked to AP for the case (`paid_amount` once a journal entry
  exists: the full total, or only the undisputed part of a hold), less AP reversed by credit notes against it.
  Payment runs never pay more than that and never post to the ledger themselves.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from backend.pipeline.lib.ids import normalize_invoice_no
from contracts import Approval, Case, CaseLinkType, CaseStatus, DiscrepancyType, FollowUpKind, FollowUpStatus

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# Approvals written by the agents' role-play reviewers (B) or the old skeleton stub.
AGENT_TAGS = ("[simulated", "stub auto-approve")
HUMAN_PREFIX = "hum_"  # ids of approvals recorded by POST /approvals/{id}

# Escalations that need an out-of-band step (callback via the contact on file) before anyone can approve or pay.
OUT_OF_BAND = {DiscrepancyType.bank_change, DiscrepancyType.lookalike_domain, DiscrepancyType.embedded_instructions}


def is_agent_approval(a: Approval) -> bool:
    return not a.id.startswith(HUMAN_PREFIX) and (a.comment or "").startswith(AGENT_TAGS)


def human_decision(case: Case) -> Optional[Approval]:
    return next((a for a in reversed(case.approvals) if not is_agent_approval(a)), None)


def last_approved(case: Case) -> Optional[Approval]:
    return next((a for a in reversed(case.approvals) if a.decision.value == "approved"), None)


def is_reply(case: Case) -> bool:
    """Supplier reply / applied support document: no invoice, attached to another case."""
    return case.invoice is None and any(l.type == CaseLinkType.attached_to and l.case_id for l in case.links)


def attachment_target(case: Case, cases: list[Case]) -> Optional[str]:
    """The bill this case belongs to when it is not a bill itself (reply, credit note, zero-delta correction)."""
    if case.parent_id:
        return case.parent_id
    linked = next((l.case_id for l in case.links if l.type == CaseLinkType.attached_to and l.case_id), None)
    if case.invoice is None:
        return linked
    inv = case.invoice
    if inv.credit_for:
        return linked or _find(cases, case, inv.credit_for)
    if inv.corrects and case.paid_amount is not None and case.paid_amount == 0:
        return next((l.case_id for l in case.links if l.type == CaseLinkType.corrected_by and l.case_id), None) \
            or _find(cases, case, inv.corrects)
    return None


def _find(cases: list[Case], case: Case, invoice_no: str) -> Optional[str]:
    n = normalize_invoice_no(invoice_no)
    return next((c.id for c in cases if c.vendor_id == case.vendor_id and c.id != case.id and not c.parent_id and c.invoice
                 and not c.invoice.credit_for and normalize_invoice_no(c.invoice.invoice_no) == n), None)


def is_bill(case: Case, cases: list[Case]) -> bool:
    if case.parent_id or case.vendor_id == "SYSTEM":
        return False
    if case.invoice is None:
        return not is_reply(case)  # quarantined / unreadable invoices still need a human
    return attachment_target(case, cases) is None


def attachments(case: Case, cases: list[Case]) -> list[Case]:
    """Replies, credit notes and zero-delta corrections that belong to this bill."""
    return [c for c in cases if c.id != case.id and not c.parent_id and attachment_target(c, cases) == case.id]


def sub_cases(case: Case, cases: list[Case]) -> list[Case]:
    ids = set(case.sub_case_ids)
    return sorted((c for c in cases if c.parent_id == case.id or c.id in ids), key=lambda c: c.id)


def _ap_credit(case: Case) -> Decimal:
    """AP credited (positive) by this case's journal entry."""
    je = case.journal_entry
    if je is None:
        return ZERO
    return -sum((p.amount for p in je.postings if p.account.startswith("Liabilities:AP")), ZERO)


def credits_applied(case: Case, cases: list[Case]) -> Decimal:
    """AP reversed by credit notes posted against this bill (positive)."""
    out = ZERO
    for c in attachments(case, cases):
        if c.invoice and c.invoice.credit_for and c.journal_entry:
            out += -_ap_credit(c)  # a credit note debits AP
    return out


def payable(case: Case, cases: list[Case]) -> Optional[Decimal]:
    """What may be paid: AP booked by the Poster for this case, net of credit notes. None if nothing booked."""
    if case.journal_entry is None:
        return None
    booked = case.paid_amount if case.paid_amount is not None else _ap_credit(case)
    return max(ZERO, (booked - credits_applied(case, cases))).quantize(CENT)


def partial(case: Case) -> bool:
    """Only the undisputed part was booked; the rest stays held."""
    return bool(case.journal_entry and case.journal_entry.idempotency_key.endswith(":undisputed"))


def oob_problem(case: Case) -> Optional[str]:
    """Bank change, look-alike domain or hidden instructions: nobody approves until a callback is done."""
    hits = {d.type for d in case.discrepancies if d.type in OUT_OF_BAND and d.material}
    if case.invoice and "embedded_instructions" in case.invoice.flags:
        hits.add(DiscrepancyType.embedded_instructions)
    if not hits:
        return None
    done = any(f.kind == FollowUpKind.callback and f.status == FollowUpStatus.done for f in case.follow_ups)
    if done:
        return None
    what = ", ".join(sorted(t.value.replace("_", " ") for t in hits))
    return (f"{what}: verify out of band first (call the vendor on the number in the vendor master, not the one "
            f"in the email). Nobody can approve or pay this bill until that callback is recorded.")


def poster_refusal(case: Case) -> Optional[str]:
    return next((n.split("REFUSED: ", 1)[1] for n in reversed(case.notes) if "poster: REFUSED: " in n), None)


def open_statuses() -> set[CaseStatus]:
    return {CaseStatus.awaiting_approval, CaseStatus.escalated, CaseStatus.reopened, CaseStatus.awaiting_vendor,
            CaseStatus.in_progress, CaseStatus.new, CaseStatus.paused, CaseStatus.quarantined}
