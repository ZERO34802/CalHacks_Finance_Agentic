"""[3] Case registry lookup. Owner: A. Fingerprint -> new / attach / reopen / skip.

STUB: placeholder fingerprint, always a new case.
"""
from backend.core.stage import Ctx
from contracts import Case


class Registry:
    name = "registry"

    def run(self, case: Case, ctx: Ctx) -> Case:
        case.fingerprint = f"stub:{case.id}"
        ctx.trace.annotate(detail={"stub": True, "action": "new_case"})
        return case
