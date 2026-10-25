"""Helix ERP routes: purchase orders and goods receipts (Odoo when connected, else the built-in ERP). Owner: D.
Auto-included by backend/api/app.py. Receipts are counted by a Helix person; vendors never create them."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend import erp
from contracts import ErpStatus, PurchaseOrderView, Receipt, ReceiveRequest

router = APIRouter()


def _store():
    from backend.api import app as app_module  # late: app imports this module while it initializes
    return app_module.store


@router.get("/erp/status", response_model=ErpStatus, tags=["erp"])
def erp_status() -> ErpStatus:
    """Which ERP holds the official PO / receipt records, and whether it answers."""
    return ErpStatus(**erp.get_erp().status())


@router.get("/erp/pos", response_model=list[PurchaseOrderView], tags=["erp"])
def erp_pos() -> list[PurchaseOrderView]:
    """Purchase orders: ordered vs received vs billed, with the ERP deep link. Reads back receipts done in Odoo."""
    return erp.list_pos(_store())


@router.post("/erp/pos/{po_number}/receive", response_model=Receipt, tags=["erp"])
def erp_receive(po_number: str, req: ReceiveRequest) -> Receipt:
    """Record a goods receipt (a Helix person's count). Capped at the ordered qty; validated in Odoo when connected."""
    if req.source not in ("app", "slack"):
        raise HTTPException(400, "source must be app or slack")
    try:
        return erp.receive(po_number, dict(req.lines), req.received_by, req.source, _store())
    except erp.ERPError as e:
        raise HTTPException(400, str(e)) from e
