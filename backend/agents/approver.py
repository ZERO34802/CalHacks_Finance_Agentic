"""[9] Approver / Controller. Owner: B. Claude role-play, separate identity; can reject -> re-plan.

STUB: AP lead rubber-stamps approve proposals; anything else waits for a human.
"""
from backend.core.stage import Ctx
from contracts import Approval, ApprovalDecision, Case, CaseStatus, Decision, Role

STUB_APPROVER = "ap.lead@helix.example"


class Approver:
    name = "approver"

    def run(self, case: Case, ctx: Ctx) -> Case:
        rec = case.proposal.recommendation if case.proposal else Decision.escalate
        limit = ctx.policy.approval_limits["approver"]
        if case.invoice and case.invoice.total * ctx.policy.fx_rates[case.invoice.currency] > limit:
            rec = Decision.escalate  # over AP lead limit -> controller
        case.decision = rec
        if rec == Decision.approve:
            case.approvals.append(Approval(
                id=f"apr_{case.id}_{len(case.approvals)}", case_id=case.id, approver=STUB_APPROVER,
                role=Role.approver, decision=ApprovalDecision.approved, comment="stub auto-approve",
                limit=limit, at=ctx.now()))
            case.status = CaseStatus.approved
        elif rec == Decision.escalate:
            case.status = CaseStatus.escalated
        else:
            case.status = CaseStatus.awaiting_approval
        ctx.trace.annotate(role=Role.approver, detail={"stub": True, "decision": rec.value})
        return case
