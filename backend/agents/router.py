"""[5] Router. Owner: B. Picks a skill by event type, in code. No skill = escalate.

STUB: clean -> skipped; otherwise ap-3way-match.
"""
from backend.core.stage import Ctx
from contracts import Case, StepStatus


class Router:
    name = "router"

    def run(self, case: Case, ctx: Ctx) -> Case:
        if not case.discrepancies:
            ctx.trace.annotate(status=StepStatus.skipped, detail={"stub": True, "reason": "clean"})
            return case
        case.skill = ctx.policy.skills["three_way_match"]
        ctx.trace.annotate(skill=case.skill, skill_version="stub", detail={"stub": True})
        return case
