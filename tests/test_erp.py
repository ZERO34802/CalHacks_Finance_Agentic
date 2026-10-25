"""Helix ERP: contract -> PO, goods receipts by Helix people, ERP refs, read-back, routes. Offline by default.
The Odoo integration test runs only with RECONAI_ERP=odoo and a reachable Odoo (make erp && make erp-setup)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend import erp
from backend.erp import ERPError, LocalERP
from contracts import PaymentTerms, Vendor, VendorContract
from tests.d_helpers import client, fresh_store, offline  # noqa: F401  (fixture)

ME = "w.lead@helix.example"


@pytest.fixture(autouse=True)
def local_erp():
    erp.set_erp(LocalERP())
    yield
    erp.set_erp(None)


def contract(cid: str = "CT-T1") -> VendorContract:
    return VendorContract(
        id=cid, vendor_name="Bayline Precision Machining Inc", category="fixtures", currency="USD", total=Decimal("12500.00"),
        items=[{"sku": "FIX-A", "description": "Probe card fixture", "qty": 10, "unit_price": "1000.00"},
               {"sku": "FIX-B", "description": "Wafer chuck", "qty": "5", "unit_price": "500.00"}],
        terms=PaymentTerms(net_days=30), requested_by="j.park@helix.example", channel="C-TEST",
        created_at=datetime(2026, 10, 24, tzinfo=timezone.utc), status="onboarded")


def vendor() -> Vendor:
    return Vendor(id="V-BAYLINE", name="Bayline Precision Machining Inc", country="US", currency="USD",
                  email_domain="baylineprecision.com", bank_last4="4021", contact_email="dana@baylineprecision.com")


def setup_po(store, cid: str = "CT-T1"):
    store.save_vendor(vendor())
    return erp.po_from_contract(contract(cid), vendor(), store)


def test_po_from_contract_is_idempotent_and_saves_contract_terms():
    store = fresh_store()
    po = setup_po(store)
    again = erp.po_from_contract(contract(), vendor(), store)
    assert again.po_number == po.po_number and po.po_number.startswith("PO-")
    assert [ln.qty for ln in po.lines] == [Decimal(10), Decimal(5)] and po.lines[0].unit_price == Decimal("1000.00")
    assert store.get_po(po.po_number).contract_id == "CT-T1"
    terms = {t.sku: t.unit_price for t in store.list_contract_terms("V-BAYLINE")}
    assert terms == {"FIX-A": Decimal("1000.00"), "FIX-B": Decimal("500.00")}
    second = erp.po_from_contract(contract("CT-T2"), vendor(), store)
    assert second.po_number != po.po_number and len(erp.list_pos(store)) == 2


def test_receive_partial_then_full_and_caps_at_ordered():
    store = fresh_store()
    po = setup_po(store)
    r1 = erp.receive(po.po_number, {"FIX-A": Decimal(6)}, ME, "app", store)
    assert r1.received_by == ME and r1.source == "app"
    assert erp.get_po(store, po.po_number).status == "partially_received"
    with pytest.raises(ERPError, match="exceed"):
        erp.receive(po.po_number, {"FIX-A": Decimal(5)}, ME, "app", store)
    erp.receive(po.po_number, {"FIX-A": Decimal(4), "FIX-B": Decimal(5)}, ME, "slack", store)
    view = erp.list_pos(store)[0]
    assert view.status == "received" and view.received == {"FIX-A": Decimal(10), "FIX-B": Decimal(5)}
    assert len(view.receipts) == 2 and view.total == Decimal("12500.00")
    assert len(store.list_receipts(po.po_number)) == 2  # the Matcher reads these


@pytest.mark.parametrize("lines,who,msg", [
    ({"NOPE": Decimal(1)}, ME, "not on"),
    ({"FIX-A": Decimal(1)}, "warehouse", "Helix person"),
    ({"FIX-A": Decimal(1)}, "", "Helix person"),
    ({"FIX-A": Decimal(1)}, "dana@baylineprecision.com", "Vendors never"),
    ({"FIX-A": Decimal(1)}, "ar@aerolane.com", "Vendors never"),
    ({"FIX-A": Decimal(0)}, ME, "Nothing to receive"),
])
def test_receive_rejects(lines, who, msg):
    store = fresh_store()
    po = setup_po(store)
    with pytest.raises(ERPError, match=msg):
        erp.receive(po.po_number, lines, who, "app", store)
    assert store.list_receipts(po.po_number) == []


def test_unknown_po():
    with pytest.raises(ERPError, match="No purchase order"):
        erp.receive("PO-1", {"X": Decimal(1)}, ME, "app", fresh_store())


class FakeERP:
    mode = "fake"
    user, email = "admin", "erp.admin@helix.example"

    def __init__(self):
        self.odoo_received: dict[str, dict[str, Decimal]] = {}

    def status(self):
        return {"mode": "odoo", "connected": True, "url": "http://erp", "database": "helix", "note": "fake"}

    def create_po(self, po, vendor):
        return "odoo:purchase.order:7:P00007"

    def create_receipt(self, po, receipt):
        got = self.odoo_received.setdefault(po.po_number, {})
        for ln in receipt.lines:
            got[ln.sku] = got.get(ln.sku, Decimal(0)) + ln.qty_received
        return "odoo:stock.picking:3:WH/IN/00003"

    def po_url(self, po):
        return "http://erp/web#id=7&model=purchase.order&view_type=form"

    def read_back(self, pos):
        return self.odoo_received


def test_erp_refs_propagate_and_read_back_has_no_double_count():
    fake = FakeERP()
    erp.set_erp(fake)
    store = fresh_store()
    po = setup_po(store)
    assert po.erp_ref == "odoo:purchase.order:7:P00007"
    rec = erp.receive(po.po_number, {"FIX-A": Decimal(4)}, ME, "app", store)
    assert rec.erp_ref == "odoo:stock.picking:3:WH/IN/00003"
    view = erp.list_pos(store)[0]
    assert view.erp_url.startswith("http://erp/") and len(view.receipts) == 1  # app receipt already mirrored
    # the warehouse validates the rest directly in Odoo -> read back once, capped at the ordered qty
    fake.odoo_received[po.po_number] = {"FIX-A": Decimal(12), "FIX-B": Decimal(5)}
    view = erp.list_pos(store)[0]
    synced = [r for r in view.receipts if r.source == "erp"]
    assert len(synced) == 1 and synced[0].received_by == "erp.admin@helix.example"
    assert view.received == {"FIX-A": Decimal(10), "FIX-B": Decimal(5)} and view.status == "received"
    assert len(erp.list_pos(store)[0].receipts) == 2


def test_routes(monkeypatch, offline):  # noqa: F811
    store = fresh_store()
    po = setup_po(store)
    c = client(monkeypatch, store)
    st = c.get("/erp/status").json()
    assert st["mode"] == "simulated" and st["connected"] is True
    pos = c.get("/erp/pos").json()
    assert pos[0]["po"]["po_number"] == po.po_number and pos[0]["status"] == "ordered" and pos[0]["total"] == "12500.00"
    r = c.post(f"/erp/pos/{po.po_number}/receive", json={"received_by": ME, "lines": {"FIX-B": "2"}, "source": "app"})
    assert r.status_code == 200 and r.json()["lines"] == [{"sku": "FIX-B", "qty_received": "2"}]
    bad = c.post(f"/erp/pos/{po.po_number}/receive", json={"received_by": "dana@baylineprecision.com", "lines": {"FIX-B": "1"}})
    assert bad.status_code == 400 and "Vendors never" in bad.json()["detail"]
    over = c.post(f"/erp/pos/{po.po_number}/receive", json={"received_by": ME, "lines": {"FIX-B": "9"}})
    assert over.status_code == 400
    assert c.get("/erp/pos").json()[0]["status"] == "partially_received"


def test_make_odoo_skipped_under_pytest(monkeypatch):
    from backend.erp.odoo import make_odoo
    monkeypatch.setenv("ODOO_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("RECONAI_ERP", raising=False)
    assert make_odoo() is None  # tests never write into a live ERP by accident
    monkeypatch.setenv("RECONAI_ERP", "odoo")
    assert make_odoo() is None  # unreachable -> None -> LocalERP, never a crash


@pytest.mark.skipif(os.getenv("RECONAI_ERP") != "odoo", reason="set RECONAI_ERP=odoo with Odoo running")
def test_odoo_end_to_end():
    from backend.erp.odoo import make_odoo
    odoo = make_odoo()
    if odoo is None:
        pytest.skip("Odoo not reachable")
    erp.set_erp(odoo)
    store = fresh_store()
    po = setup_po(store, f"CT-IT-{uuid.uuid4().hex[:6]}")
    assert po.erp_ref.startswith("odoo:purchase.order:")
    r1 = erp.receive(po.po_number, {"FIX-A": Decimal(6)}, ME, "app", store)
    r2 = erp.receive(po.po_number, {"FIX-A": Decimal(4), "FIX-B": Decimal(5)}, ME, "app", store)
    assert r1.erp_ref != r2.erp_ref and r2.erp_ref.startswith("odoo:stock.picking:")
    oid = int(po.erp_ref.split(":")[2])
    assert odoo.call("purchase.order", "read", [oid], fields=["receipt_status"])[0]["receipt_status"] == "full"
    assert erp.list_pos(store)[0].status == "received"


def test_shared_mail_domain_only_blocks_the_vendor_contact_itself():
    store = fresh_store()
    v = vendor().model_copy(update={"id": "V-GMAILCO", "email_domain": "gmail.com", "contact_email": "seller@gmail.com"})
    store.save_vendor(v)
    po = setup_po(store)
    with pytest.raises(ERPError, match="Vendors never"):
        erp.receive(po.po_number, {"FIX-A": Decimal(1)}, "Seller@gmail.com", "slack", store)
    assert erp.receive(po.po_number, {"FIX-A": Decimal(1)}, "helix.teammate@gmail.com", "slack", store).source == "slack"
