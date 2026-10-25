"""Odoo 17 Community as Helix's ERP (buyer side), over Odoo's external XML-RPC API (stdlib only). Owner: D.

  vendor  -> res.partner (supplier, ref = ReconAI vendor id)
  PO line -> product.product (default_code = SKU) + purchase.order.line; the PO is confirmed (button_confirm)
  receipt -> the PO's incoming stock.picking: counted qty on each stock.move (quantity + picked), button_validate;
             a partial count creates a backorder for the rest (stock.backorder.confirmation)
Money and quantities go over the wire as Decimal strings (Odoo float fields accept them); never Python floats.
Every failure is an ERPError with a readable message: the API turns it into a 400, nothing crashes.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import xmlrpc.client
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from contracts import PO, Receipt, Vendor

from . import ERPError

log = logging.getLogger("reconai.erp")
ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = float(os.getenv("ODOO_TIMEOUT", "8"))


class _Transport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _SafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def _ref_id(erp_ref: Optional[str], model: str) -> Optional[int]:
    m = re.match(rf"odoo:{re.escape(model)}:(\d+)", erp_ref or "")
    return int(m.group(1)) if m else None


class OdooERP:
    mode = "odoo"

    def __init__(self, url: str, db: str, user: str, password: str, timeout: float = TIMEOUT):
        self.url, self.db, self.user, self._pwd, self.timeout = url.rstrip("/"), db, user, password, timeout
        self.uid: Optional[int] = None
        self.email: Optional[str] = None

    # --- transport -------------------------------------------------------
    def _proxy(self, path: str, timeout: Optional[float] = None) -> xmlrpc.client.ServerProxy:
        t = timeout or self.timeout
        transport = _SafeTransport(t) if self.url.startswith("https") else _Transport(t)
        return xmlrpc.client.ServerProxy(f"{self.url}{path}", transport=transport, allow_none=True)  # one per call: thread-safe

    def authenticate(self, timeout: Optional[float] = None) -> int:
        try:
            uid = self._proxy("/xmlrpc/2/common", timeout).authenticate(self.db, self.user, self._pwd, {})
        except (OSError, xmlrpc.client.Error) as e:
            raise ERPError(f"Odoo at {self.url} is unreachable: {e}") from e
        if not uid:
            raise ERPError(f"Odoo rejected the login for {self.user} on database {self.db}.")
        self.uid = uid
        try:
            self.email = (self.call("res.users", "read", [uid], fields=["email"]) or [{}])[0].get("email") or None
        except ERPError:
            self.email = None
        return uid

    def call(self, model: str, method: str, *args: Any, **kw: Any) -> Any:
        if self.uid is None:
            self.authenticate()
        try:
            return self._proxy("/xmlrpc/2/object").execute_kw(self.db, self.uid, self._pwd, model, method, list(args), kw)
        except xmlrpc.client.Fault as e:
            msg = (e.faultString or "").strip().splitlines()
            raise ERPError(f"Odoo {model}.{method} failed: {msg[-1] if msg else e}") from e
        except (OSError, xmlrpc.client.Error) as e:
            raise ERPError(f"Odoo at {self.url} is unreachable: {e}") from e

    # --- ERP protocol ----------------------------------------------------
    def status(self) -> dict:
        try:
            self.authenticate(timeout=3)
            return {"mode": "odoo", "connected": True, "url": self.url, "database": self.db,
                    "note": f"Odoo 17 Community · signed in as {self.user}"}
        except ERPError as e:
            return {"mode": "odoo", "connected": False, "url": self.url, "database": self.db, "note": str(e)}

    def po_url(self, po: PO) -> Optional[str]:
        oid = _ref_id(po.erp_ref, "purchase.order")
        return f"{self.url}/web#id={oid}&model=purchase.order&view_type=form" if oid else None

    def create_po(self, po: PO, vendor: Vendor) -> Optional[str]:
        origin = f"ReconAI {po.po_number} · {po.contract_id or po.doc_id}"
        found = self.call("purchase.order", "search_read", [("origin", "=", origin)], fields=["name"], limit=1)
        if found:  # idempotent: the same PO is never created twice in Odoo
            return f"odoo:purchase.order:{found[0]['id']}:{found[0]['name']}"
        partner = self._partner(vendor)
        currency = self._currency(po.currency)
        lines = [(0, 0, {"product_id": self._product(ln.sku, ln.description), "name": ln.description or ln.sku,
                         "product_qty": str(Decimal(ln.qty)), "price_unit": str(Decimal(ln.unit_price)),
                         "taxes_id": [(6, 0, [])]})  # contract prices are tax-exclusive; keep totals equal to ours
                 for ln in po.lines]
        oid = self.call("purchase.order", "create", {
            "partner_id": partner, "currency_id": currency, "origin": origin,
            "date_order": f"{po.po_date.isoformat()} 00:00:00", "order_line": lines,
            "notes": f"Created by ReconAI from supply contract {po.contract_id or '-'}; requested by {po.requester}.",
        })
        self.call("purchase.order", "button_confirm", [oid])
        name = self.call("purchase.order", "read", [oid], fields=["name"])[0]["name"]
        log.info("Odoo PO %s (id %s) for %s", name, oid, po.po_number)
        return f"odoo:purchase.order:{oid}:{name}"

    def create_receipt(self, po: PO, receipt: Receipt) -> Optional[str]:
        oid = _ref_id(po.erp_ref, "purchase.order")
        if oid is None:
            return None  # PO was created before Odoo was connected: the store keeps the record
        picks = self.call("stock.picking", "search_read",
                          [("purchase_id", "=", oid), ("picking_type_code", "=", "incoming"),
                           ("state", "not in", ["done", "cancel"])], fields=["name", "state"], order="id asc", limit=1)
        if not picks:
            raise ERPError(f"Odoo has no open receipt for {po.po_number}: it may already be fully received in Odoo.")
        pid, pname = picks[0]["id"], picks[0]["name"]
        if picks[0]["state"] in ("draft", "confirmed", "waiting"):
            self.call("stock.picking", "action_assign", [pid])
        moves = self.call("stock.move", "search_read", [("picking_id", "=", pid), ("state", "not in", ["done", "cancel"])],
                          fields=["product_id", "product_uom_qty"])
        codes = {p["id"]: p["default_code"] for p in self.call("product.product", "read",
                                                               list({m["product_id"][0] for m in moves}), fields=["default_code"])}
        want = {ln.sku: Decimal(ln.qty_received) for ln in receipt.lines}
        missing = set(want) - {codes.get(m["product_id"][0]) for m in moves}
        if missing:
            raise ERPError(f"Odoo receipt {pname} has no open line for {', '.join(sorted(missing))}.")
        for m in moves:
            qty = want.pop(codes.get(m["product_id"][0]), Decimal(0))
            self.call("stock.move", "write", [m["id"]], {"quantity": str(qty), "picked": qty > 0})
        res = self.call("stock.picking", "button_validate", [pid])
        if isinstance(res, dict) and res.get("res_model") == "stock.backorder.confirmation":
            ctx = dict(res.get("context") or {}, button_validate_picking_ids=[pid])
            wiz = self.call("stock.backorder.confirmation", "create",
                            {"pick_ids": [(6, 0, [pid])],
                             "backorder_confirmation_line_ids": [(0, 0, {"picking_id": pid, "to_backorder": True})]},
                            context=ctx)
            self.call("stock.backorder.confirmation", "process", [wiz], context=ctx)
        elif isinstance(res, dict):
            raise ERPError(f"Odoo wants {res.get('res_model') or 'a manual step'} to validate {pname}; finish it in Odoo.")
        state = self.call("stock.picking", "read", [pid], fields=["state"])[0]["state"]
        if state != "done":
            raise ERPError(f"Odoo receipt {pname} is {state}, not done.")
        log.info("Odoo receipt %s (id %s) validated for %s", pname, pid, po.po_number)
        return f"odoo:stock.picking:{pid}:{pname}"

    def read_back(self, pos: list[PO]) -> dict[str, dict[str, Decimal]]:
        """po_number -> sku -> qty received in Odoo (catches goods counted directly in Odoo). One batch of calls."""
        by_id = {oid: p for p in pos if (oid := _ref_id(p.erp_ref, "purchase.order"))}
        if not by_id:
            return {}
        lines = self.call("purchase.order.line", "search_read", [("order_id", "in", list(by_id))],
                          fields=["order_id", "product_id", "qty_received"])
        pids = list({ln["product_id"][0] for ln in lines if ln["product_id"]})
        codes = {p["id"]: p["default_code"] for p in self.call("product.product", "read", pids, fields=["default_code"])}
        out: dict[str, dict[str, Decimal]] = {}
        for ln in lines:
            po = by_id[ln["order_id"][0]]
            sku = codes.get(ln["product_id"][0]) if ln["product_id"] else None
            if sku:  # Odoo returns floats on the wire; re-quantize through str, quantities only (never money)
                got = out.setdefault(po.po_number, {})
                got[sku] = got.get(sku, Decimal(0)) + Decimal(str(ln["qty_received"])).normalize()
        return out

    # --- master data -----------------------------------------------------
    def _partner(self, v: Vendor) -> int:
        found = self.call("res.partner", "search", [("ref", "=", v.id)], limit=1)
        if found:
            return found[0]
        return self.call("res.partner", "create", {
            "name": v.name, "ref": v.id, "is_company": True, "supplier_rank": 1,
            "email": v.contact_email or False, "website": v.email_domain or False,
            "comment": "Vendor master lives in ReconAI (bank details are never synced to the ERP).",
        })

    def _product(self, sku: str, description: str) -> int:
        found = self.call("product.product", "search", [("default_code", "=", sku)], limit=1)
        if found:
            return found[0]
        return self.call("product.product", "create", {"name": description or sku, "default_code": sku,
                                                        "purchase_ok": True, "sale_ok": False, "type": "product"})

    def _currency(self, code: str) -> int:
        found = self.call("res.currency", "search_read", [("name", "=", code)], fields=["active"], limit=1,
                          context={"active_test": False})
        if not found:
            raise ERPError(f"Odoo has no currency {code}.")
        if not found[0]["active"]:
            self.call("res.currency", "write", [found[0]["id"]], {"active": True})
        return found[0]["id"]


def make_odoo() -> Optional[OdooERP]:
    """OdooERP when ODOO_URL is set and the login works (short timeout); else None -> the local ERP.
    Under pytest Odoo is never used unless RECONAI_ERP=odoo, so test runs don't write POs into a live ERP."""
    load_dotenv(ROOT / ".env")  # does not override variables already set
    url = os.getenv("ODOO_URL", "").strip()
    flag = os.getenv("RECONAI_ERP", "").strip().lower()
    if not url or flag == "off" or ("pytest" in sys.modules and flag != "odoo"):
        return None
    erp = OdooERP(url, os.getenv("ODOO_DB", "helix"), os.getenv("ODOO_USER", "admin"), os.getenv("ODOO_PASSWORD", "admin"))
    try:
        erp.authenticate(timeout=3)
    except ERPError as e:
        log.warning("Odoo not used (%s); falling back to the built-in ERP", e)
        return None
    return erp
