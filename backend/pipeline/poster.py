"""[10] Poster. Owner: A. Beancount double entry; refuses on SoD / limit / locked period.

STUB: builds a two-line entry (Dr expense, Cr AP) for approved cases. No Beancount write yet.
"""
from backend.core.stage import Ctx
from contracts import ApprovalDecision, Case, CaseStatus, Decision, JournalEntry, Posting, StepStatus


class Poster:
    name = "poster"

    def run(self, case: Case, ctx: Ctx) -> Case:
        approved = [a for a in case.approvals if a.decision == ApprovalDecision.approved]
        if case.decision != Decision.approve or not approved or case.invoice is None:
            ctx.trace.annotate(status=StepStatus.skipped, detail={"stub": True, "reason": "not approved"})
            return case
        inv, acct = case.invoice, ctx.policy.accounts
        case.journal_entry = JournalEntry(
            id=f"je_{case.id}", case_id=case.id, date=inv.invoice_date,
            narration=f"{inv.vendor_id} {inv.invoice_no}",
            postings=[Posting(account=acct.expense_default, amount=inv.total, currency=inv.currency),
                      Posting(account=acct.ap_control, amount=-inv.total, currency=inv.currency)],
            requested_by=case.po.requester if case.po else "unknown",
            approved_by=approved[-1].approver,
            idempotency_key=f"{case.id}:{inv.invoice_no}",
        )
        case.status = CaseStatus.posted
        ctx.trace.annotate(outputs=[case.journal_entry.id], detail={"stub": True})
        return case
