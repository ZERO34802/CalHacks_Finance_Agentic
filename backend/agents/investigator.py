"""[6] Investigator. Owner: B. Factory Droid in a per-case sandbox; only exit is a Proposal.

STUB: no sandbox. Writes approve if clean, else hold. Clean cases skip investigation
but still get a proposal so the Approver always has one to act on.
"""
from backend.core.stage import Ctx
from contracts import Case, Decision, Proposal, Role, StepStatus


class Investigator:
    name = "investigator"

    def run(self, case: Case, ctx: Ctx) -> Case:
        clean = not case.discrepancies
        case.proposal = Proposal(
            case_id=case.id,
            recommendation=Decision.approve if clean else Decision.hold,
            explanation="stub: clean 3-way match" if clean else "stub: exception found",
            confidence=0.5, skill=case.skill, skill_version="stub" if case.skill else None,
        )
        ctx.trace.annotate(role=Role.investigator, status=StepStatus.skipped if clean else StepStatus.ok,
                           outputs=["proposal"], detail={"stub": True})
        return case
