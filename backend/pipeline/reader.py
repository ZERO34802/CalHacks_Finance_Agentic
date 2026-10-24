"""[1] Reader. Owner: A. Claude with NO tools -> strict Invoice JSON.

STUB: fixtures arrive pre-parsed, so this passes case.invoice through.
"""
from backend.core.stage import Ctx
from contracts import Case, CaseStatus, DocKind, Role


class Reader:
    name = "reader"

    def run(self, case: Case, ctx: Ctx) -> Case:
        ctx.trace.annotate(role=Role.reader,
                           inputs=[d.id for d in case.documents if d.kind == DocKind.invoice],
                           detail={"stub": True})
        if case.invoice is None:
            raise ValueError("stub Reader needs a pre-parsed invoice in the fixture")
        case.status = CaseStatus.in_progress
        return case
