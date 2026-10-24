"""[2] Document dedup. Owner: A. File hash, normalized inv no, line hash, fuzzy, paid history.

STUB: reports no duplicates.
"""
from backend.core.stage import Ctx
from contracts import Case


class DocDedup:
    name = "doc_dedup"

    def run(self, case: Case, ctx: Ctx) -> Case:
        ctx.trace.annotate(detail={"stub": True, "duplicates": []})
        return case
