"""Helix ERP: the buyer's system of record for purchase orders and goods receipts. Owner: D.

Interface (everything else calls only these):
  get_erp()                                   -> ERP (Odoo when configured + reachable, else the local ERP)
  po_from_contract(contract, vendor, store)   -> PO   contract -> confirmed PO (+ contract prices); idempotent
  receive(po_number, lines, received_by, source, store) -> Receipt   a HELIX person's count of what arrived
  list_pos(store) -> list[PurchaseOrderView]
Every PO / receipt is mirrored into the store (store.save_po / save_receipt / save_contract_term), because the
Matcher's 3-way match reads the store. The external ERP holds the official record (erp_ref on PO / Receipt).
Receipts never come from the vendor: the vendor's shipment notice only asks a Helix person to count.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date
from decimal import Decimal
from typing import Optional, Protocol

from backend.store.base import Store
from contracts import PO, POLine, ContractTerm, PurchaseOrderView, Receipt, ReceiptLine, Vendor, VendorContract

INDEX = "erp_po"
SHARED_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com", "icloud.com",
               "me.com", "proton.me", "protonmail.com", "aol.com"}  # record kind: po_number -> PO (the store has get_po but no listing)


class ERPError(Exception):
    pass


class ERP(Protocol):
    mode: str
    def status(self) -> dict: ...
    def create_po(self, po: PO, vendor: Vendor) -> Optional[str]: ...          # returns erp_ref
    def create_receipt(self, po: PO, receipt: Receipt) -> Optional[str]: ...   # returns erp_ref
    def po_url(self, po: PO) -> Optional[str]: ...


class LocalERP:
    """No external ERP configured: the store is the ERP (labelled simulated)."""
    mode = "simulated"

    def status(self) -> dict:
        url = os.getenv("ODOO_URL", "").strip()
        note = (f"Built-in ERP (SIMULATED): Odoo at {url} is not reachable (make erp && make erp-setup)" if url
                else "Built-in ERP (SIMULATED): set ODOO_URL to use Odoo")
        return {"mode": "simulated", "connected": True, "note": note}

    def create_po(self, po: PO, vendor: Vendor) -> Optional[str]:
        return None

    def create_receipt(self, po: PO, receipt: Receipt) -> Optional[str]:
        return None

    def po_url(self, po: PO) -> Optional[str]:
        return None


_erp: Optional[ERP] = None
_auto = True          # chosen by get_erp (not injected): a fallback to LocalERP retries Odoo now and then
_checked = 0.0
RETRY_S = 30
_lock = threading.RLock()  # one receipt at a time, so an Odoo read-back never double-counts one in flight


def get_erp() -> ERP:
    """Odoo when ODOO_URL is set and reachable (backend/erp/odoo.py), else the local ERP. Tests inject with set_erp()."""
    global _erp, _checked
    stale = _auto and isinstance(_erp, LocalERP) and time.monotonic() - _checked > RETRY_S
    if _erp is None or stale:
        _checked = time.monotonic()
        try:
            from backend.erp.odoo import make_odoo  # added by the Odoo integration
            _erp = make_odoo() or LocalERP()
        except ImportError:
            _erp = LocalERP()
    return _erp


def set_erp(erp: Optional[ERP]) -> None:
    global _erp, _auto
    _erp, _auto = erp, erp is None


def _sku(contract: VendorContract, i: int, item: dict) -> str:
    return (item.get("sku") or f"{contract.id}-L{i}").upper()[:40]


def _next_po_number(store: Store) -> str:
    n = [int(m.group(1)) for p in store.list_records(PO, INDEX) if (m := re.match(r"PO-(\d+)$", p.po_number))]
    return f"PO-{max(n + [9000]) + 1}"


def po_from_contract(contract: VendorContract, vendor: Vendor, store: Store, on: Optional[date] = None) -> PO:
    """Create (once) the confirmed PO for an onboarded vendor's contract, in the ERP and the store."""
    existing = next((p for p in store.list_records(PO, INDEX) if p.contract_id == contract.id), None)
    if existing:
        return existing
    on = on or date.today()
    lines = [POLine(line_no=i, sku=_sku(contract, i, it), description=str(it.get("description", ""))[:80],
                    qty=Decimal(str(it["qty"])), unit_price=Decimal(str(it["unit_price"])))
             for i, it in enumerate(contract.items, 1)]
    num = _next_po_number(store)
    po = PO(doc_id=f"erp-{num}", po_number=num, vendor_id=vendor.id, po_date=on, currency=contract.currency,
            lines=lines, requester=contract.requested_by, contract_id=contract.id)
    po.erp_ref = get_erp().create_po(po, vendor)
    store.save_po(po)
    store.put_record(INDEX, num, po)
    for ln in lines:  # the contract price is what the Matcher checks against (amendments win from their date)
        store.save_contract_term(ContractTerm(doc_id=f"erp-{contract.id}", vendor_id=vendor.id, sku=ln.sku,
                                              unit_price=ln.unit_price, currency=contract.currency, effective_from=on))
    return po


def get_po(store: Store, po_number: str) -> Optional[PO]:
    return store.get_record(PO, INDEX, po_number) or store.get_po(po_number)


def received(store: Store, po_number: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for r in store.list_receipts(po_number):
        for ln in r.lines:
            out[ln.sku] = out.get(ln.sku, Decimal(0)) + Decimal(ln.qty_received)
    return out


def receive(po_number: str, lines: dict[str, Decimal], received_by: str, source: str, store: Store,
            on: Optional[date] = None) -> Receipt:
    """Record a goods receipt counted by a Helix person (app or Slack). Never more than ordered."""
    with _lock:
        return _receive(po_number, lines, received_by, source, store, on)


def _receive(po_number: str, lines: dict[str, Decimal], received_by: str, source: str, store: Store,
             on: Optional[date]) -> Receipt:
    po = get_po(store, po_number)
    if po is None:
        raise ERPError(f"No purchase order {po_number}.")
    if not received_by or "@" not in received_by:
        raise ERPError("A goods receipt needs the Helix person who counted it.")
    who, domain = received_by.strip().lower(), received_by.rsplit("@", 1)[1].strip().lower()
    shared = domain in SHARED_MAIL or domain.endswith(".edu")  # a vendor's domain only identifies it if not shared
    if any(who == (v.contact_email or "").lower() or (not shared and domain == (v.email_domain or "").lower())
           for v in store.list_vendors()):
        raise ERPError("Vendors never record goods receipts: a Helix person counts what arrived.")
    ordered = {ln.sku: Decimal(ln.qty) for ln in po.lines}
    have = received(store, po_number)
    clean: list[ReceiptLine] = []
    for sku, qty in lines.items():
        qty = Decimal(str(qty))
        if sku not in ordered:
            raise ERPError(f"{sku} is not on {po_number}.")
        if qty <= 0:
            continue
        if have.get(sku, Decimal(0)) + qty > ordered[sku]:
            raise ERPError(f"{sku}: {have.get(sku, 0) + qty} would exceed the {ordered[sku]} ordered on {po_number}.")
        clean.append(ReceiptLine(sku=sku, qty_received=qty))
    if not clean:
        raise ERPError("Nothing to receive.")
    n = len(store.list_receipts(po_number)) + 1
    rec = Receipt(doc_id=f"erp-GRN-{po_number}-{n}", po_number=po_number, received_date=on or date.today(),
                  lines=clean, received_by=received_by, source=source)
    rec.erp_ref = get_erp().create_receipt(po, rec)
    store.save_receipt(rec)
    _set_status(store, po)
    return rec


def _set_status(store: Store, po: PO) -> None:
    have = received(store, po.po_number)
    po.status = "received" if all(have.get(ln.sku, 0) >= ln.qty for ln in po.lines) else "partially_received"
    store.save_po(po)
    store.put_record(INDEX, po.po_number, po)


def sync_from_erp(store: Store) -> list[Receipt]:
    """Goods counted directly in the ERP (e.g. validated in Odoo) become receipts in the store, so the Matcher sees
    them. Only the delta beyond what the store already has, capped at the ordered qty. ERP down = no-op."""
    erp = get_erp()
    read_back = getattr(erp, "read_back", None)
    if read_back is None:
        return []
    with _lock:
        pos = store.list_records(PO, INDEX)
        try:
            got = read_back(pos)
        except ERPError:
            return []
        out = []
        for po in pos:
            have, odoo = received(store, po.po_number), got.get(po.po_number, {})
            delta = [ReceiptLine(sku=ln.sku, qty_received=min(odoo[ln.sku], Decimal(ln.qty)) - have.get(ln.sku, Decimal(0)))
                     for ln in po.lines if ln.sku in odoo and min(odoo[ln.sku], Decimal(ln.qty)) > have.get(ln.sku, Decimal(0))]
            if not delta:
                continue
            n = len(store.list_receipts(po.po_number)) + 1
            who = getattr(erp, "email", None) or f"{getattr(erp, 'user', 'erp')} (ERP user)"
            rec = Receipt(doc_id=f"erp-GRN-{po.po_number}-{n}", po_number=po.po_number, received_date=date.today(),
                          lines=delta, received_by=who, source="erp", erp_ref=po.erp_ref)
            store.save_receipt(rec)
            _set_status(store, po)
            out.append(rec)
        return out


def list_pos(store: Store) -> list[PurchaseOrderView]:
    sync_from_erp(store)
    out = []
    vendors = {v.id: v for v in store.list_vendors()}
    cases = store.list_cases()
    for po in sorted(store.list_records(PO, INDEX), key=lambda p: p.po_number, reverse=True):
        bills = [c.id for c in cases if c.parent_id is None and c.invoice and c.invoice.po_number == po.po_number]
        status = po.status
        if bills and status in ("received", "partially_received", "ordered"):
            status = "invoiced"
        if bills and all(c.status.value == "posted" for c in cases if c.id in bills):
            status = "invoiced"
        out.append(PurchaseOrderView(po=po, vendor_name=vendors[po.vendor_id].name if po.vendor_id in vendors else po.vendor_id,
                                     receipts=store.list_receipts(po.po_number), received=received(store, po.po_number),
                                     invoices=bills, total=sum((Decimal(l.qty) * l.unit_price for l in po.lines), Decimal(0)),
                                     status=status, erp_url=get_erp().po_url(po)))
    return out
