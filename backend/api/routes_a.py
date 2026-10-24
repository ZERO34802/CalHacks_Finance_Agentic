"""A's API routes (auto-included by backend/api/app.py). Owner: A."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from contracts import CaseStatus

router = APIRouter()

DONE = {CaseStatus.posted, CaseStatus.resolved, CaseStatus.rejected, CaseStatus.quarantined}


class QueueItem(BaseModel):
    case_id: str
    vendor_id: str
    status: CaseStatus
    priority: float
    invoice_no: str | None = None
    total: str | None = None
    currency: str | None = None
    detail: dict = {}


@router.get("/queue", response_model=list[QueueItem], tags=["queue"])
def get_queue() -> list[QueueItem]:
    """Open parent cases, highest priority first (due date, USD amount, early-pay discount, critical vendor)."""
    from backend.api import app as app_module  # late: app imports this module while it initializes
    from backend.core.runner import make_ctx
    from backend.pipeline.hooks import priority
    store = app_module.store
    ctx = make_ctx(store)
    out = []
    for c in store.list_cases():
        if c.parent_id or c.status in DONE:
            continue
        score, detail = priority(c, ctx)
        inv = c.invoice
        out.append(QueueItem(case_id=c.id, vendor_id=c.vendor_id, status=c.status, priority=score,
                             invoice_no=inv.invoice_no if inv else None, total=str(inv.total) if inv else None,
                             currency=inv.currency if inv else None, detail=detail))
    return sorted(out, key=lambda x: (-x.priority, x.case_id))
