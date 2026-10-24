"""[8] Runtime validators. Owner: A. Schema, citations, recomputed numbers, invariants.

STUB: only checks a proposal exists.
"""
from backend.core.stage import Ctx
from contracts import Case, StepStatus


class Validators:
    name = "validators"

    def run(self, case: Case, ctx: Ctx) -> Case:
        if case.proposal is None:
            ctx.trace.annotate(status=StepStatus.blocked, error="no proposal")
        ctx.trace.annotate(detail={"stub": True})
        return case
