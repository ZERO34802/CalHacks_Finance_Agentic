"""[4] Matcher. Owner: A. 3-way match, FX, tolerance, variance split. All math in code.

STUB: finds no discrepancies (so every case looks clean).
"""
from backend.core.stage import Ctx
from contracts import Case


class Matcher:
    name = "matcher"

    def run(self, case: Case, ctx: Ctx) -> Case:
        case.discrepancies = []
        ctx.trace.annotate(inputs=[case.invoice.doc_id] if case.invoice else [],
                           detail={"stub": True, "clean": True})
        return case
