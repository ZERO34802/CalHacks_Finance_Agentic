"""[7] Vendor Guard. Owner: A. Bank changes, look-alike domains, new vendors, probation.

STUB: no checks.
"""
from backend.core.stage import Ctx
from contracts import Case


class VendorGuard:
    name = "vendor_guard"

    def run(self, case: Case, ctx: Ctx) -> Case:
        ctx.trace.annotate(detail={"stub": True})
        return case
