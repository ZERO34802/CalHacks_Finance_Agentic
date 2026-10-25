"""The billing cycle in Slack, after onboarding: PO -> shipment -> goods receipt -> invoice -> match -> approve ->
release. Owner: D. Mixed into ReconBot (backend/slack/bot.py).

  /reconai role <ap_lead|controller|cfo|cto>   register your AP role (one per person); /reconai roles lists them
  /reconai shipped PO-9001 [30 | SKU=30,...]    vendor's registered user: a shipment NOTICE (a claim, never a receipt)
      -> DM to the PO requester + role holders: [All N received] [Different quantity...]
  /reconai receive PO-9001 <30 | SKU=30,...>    any Helix person: the goods receipt (backend.erp.receive, source slack)
  /reconai invoice [PO-9001]                    vendor's registered user: invoice form -> structured CSV + PDF copy
  (PDF shared in the deal channel or a DM)      vendor's registered user only: downloaded with the bot token -> intake
  after each run: GREEN -> DM approvers [Approve] (AP lead) / [Approve & release via Coinbase] (controller/CFO/CTO)
                  else  -> DM approvers what failed; the vendor hears a neutral note in the deal channel

Every button re-checks in code: the Slack user holds the role they act as, requester can't approve, limits, the
release rule (backend/ap/actions.py + payments.py). Buttons are idempotent: the second click says it's done.
Untrusted: vendor messages and files never reach a prompt with tools (files go to the Reader, which has none);
quantities and prices are parsed by code; a vendor's message never creates a receipt.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import uuid4

from backend import erp
from backend.ap import actions
from backend.ap import state as ap_state
from backend.ap.payments import release_roles
from backend.core.config import ROOT, load_policy
from backend.review.packet import build as build_packet, usd
from backend.slack import billing
from backend.slack import roles as R
from backend.slack.models import (DEAL_KIND, SESSION_KIND, SHIPMENT_KIND, VENDOR_USER_KIND, Deal, Session, Shipment,
                                  VendorUser, dec)
from contracts import PO, Case, CaseFixture, Channel, InboundItem, Role

log = logging.getLogger("reconai.slack")
INBOX = Path(os.environ.get("RECONAI_SLACK_INBOX", str(ROOT / ".data" / "slack_inbox")))
PO_RE = re.compile(r"\bP[O0]-\d+\b", re.I)  # "P0-9001" (zero) is the same PO: they look alike in Slack's code font
MAX_FILE = 10 * 1024 * 1024
# invoice files a supplier may share in Slack: Slack filetype -> extension the intake checks the content against
INVOICE_FILES = {"pdf": "pdf", "png": "png", "jpg": "jpg", "jpeg": "jpg", "csv": "csv", "xlsx": "xlsx"}
ACCEPTED_TEXT = "PDF, a PNG/JPEG photo or scan, CSV or XLSX"


def _invoice_type(f: dict) -> Optional[str]:
    ft = (f.get("filetype") or "").lower()
    ext = (f.get("name") or "").rsplit(".", 1)[-1].lower() if "." in (f.get("name") or "") else ""
    mt = (f.get("mimetype") or "").lower()
    if ft in INVOICE_FILES:
        return INVOICE_FILES[ft]
    if ext in INVOICE_FILES and ft in ("", "binary", "text"):
        return INVOICE_FILES[ext]
    return {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "text/csv": "csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx"}.get(mt)
APPROVE_ROLES = ("approver", "controller", "cfo", "cto")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def po_no(m: re.Match) -> str:
    return "PO-" + m.group(0).split("-", 1)[1]


def parse_lines(spec: str, po: PO, default_all: bool = False) -> dict[str, Decimal]:
    """'30' (single-line PO) | 'SKU=30, SKU2=5' | '' (everything ordered, when default_all). Code, never an LLM."""
    spec = PO_RE.sub("", spec or "").strip().strip(",")
    skus = {ln.sku.upper(): ln for ln in po.lines}
    if not spec:
        if default_all:
            return {ln.sku: Decimal(ln.qty) for ln in po.lines}
        raise ValueError("Give a quantity: `30`, or `SKU=30,SKU2=5` for several items.")
    if "=" not in spec:
        q = dec(spec.split()[0])
        if q is None:
            raise ValueError(f"{spec[:20]!r} isn't a quantity.")
        if len(po.lines) != 1:
            raise ValueError(f"{po.po_number} has {len(po.lines)} items: use `SKU=qty,...` "
                             f"({', '.join(ln.sku for ln in po.lines)}).")
        return {po.lines[0].sku: q}
    out: dict[str, Decimal] = {}
    for part in re.split(r"[,\s]+", spec):
        if not part:
            continue
        sku, _, qty = part.partition("=")
        q = dec(qty)
        if sku.upper() not in skus or q is None:
            raise ValueError(f"{part[:30]!r}: use an item code on {po.po_number} "
                             f"({', '.join(ln.sku for ln in po.lines)}) and a number.")
        out[skus[sku.upper()].sku] = q
    return out


def _fmt(lines: dict[str, Decimal]) -> str:
    return ", ".join(f"{q:,} × {sku}" for sku, q in lines.items())


def _button(text: str, action: str, value: str, style: Optional[str] = None) -> dict:
    b = {"type": "button", "action_id": action, "value": value, "text": {"type": "plain_text", "text": text[:75]}}
    if style:
        b["style"] = style
    return b


class BillingCycle:
    # --- who is who ---------------------------------------------------------------------------------
    def vendor_user(self, user: str) -> Optional[VendorUser]:
        u = self.store.get_record(VendorUser, VENDOR_USER_KIND, user)
        return u if u and u.vendor_id else None

    def is_helix(self, user: str) -> bool:
        if self.vendor_user(user):
            return False
        if user in self.internal or R.holder(self.store, user):
            return True
        return any(s.owner == user for s in self.store.list_records(Session, SESSION_KIND)) or any(
            d.requester_user == user for d in self.deals())

    def deals(self) -> list[Deal]:
        return self.store.list_records(Deal, DEAL_KIND)

    def deal(self, po_number: Optional[str]) -> Optional[Deal]:
        return self.store.get_record(Deal, DEAL_KIND, po_number.upper()) if po_number else None

    def vendor_deal(self, vendor_id: str) -> Optional[Deal]:
        return max((d for d in self.deals() if d.vendor_id == vendor_id), key=lambda d: d.po_number, default=None)

    def vendor_po(self, vu: VendorUser, arg: str) -> tuple[Optional[PO], str]:
        m = PO_RE.search(arg or "")
        mine = sorted((d for d in self.deals() if d.vendor_id == vu.vendor_id), key=lambda d: d.po_number)
        if m:
            po = erp.get_po(self.store, po_no(m))
            if po is None or po.vendor_id != vu.vendor_id:
                return None, f"{po_no(m)} isn't one of your purchase orders."
            return po, ""
        if not mine:
            return None, "You have no Helix purchase order yet."
        return erp.get_po(self.store, mine[-1].po_number), ""

    def dm(self, user: str, text: str, blocks: Optional[list] = None) -> None:
        try:
            kw = {"channel": user, "text": text}
            if blocks:
                kw["blocks"] = blocks
            self.client.chat_postMessage(**kw)
        except Exception as e:
            log.warning("dm to %s failed: %s", user, e)

    def say(self, channel: Optional[str], text: str) -> None:
        if channel:
            try:
                self.client.chat_postMessage(channel=channel, text=text)
            except Exception as e:
                log.warning("post to %s failed: %s", channel, e)

    def reply(self, channel: str, user: str, text: str) -> None:
        """Ephemeral in a channel; a DM (D... channel, or a user id) gets a plain message."""
        if channel and channel[0] in "DUW":
            self.say(channel, text)
        else:
            self.tell(channel, user, text)

    # --- roles ------------------------------------------------------------------------------------------
    def cmd_role(self, arg: str, user: str, channel: str) -> None:
        role = R.parse(arg)
        if role is None:
            return self.reply(channel, user, "Usage: `/reconai role ap_lead|controller|cfo|cto`")
        if self.store.get_record(VendorUser, VENDOR_USER_KIND, user):
            return self.reply(channel, user, "You're registered as a supplier contact, so you can't hold a Helix AP role.")
        email, name = self.person(user)
        h = R.register(self.store, user, name, email, role)
        limit = load_policy().approval_limits.get(role.value)
        can = ("approve bills up to USD {:,.2f}; you can never release payments".format(limit) if role == Role.approver
               else f"approve up to USD {limit:,.2f} and release payments")
        self.reply(channel, user, f"You're registered as *{R.TITLE[role]}* ({h.email}): you'll get the matching "
                                  f"approvals in a DM and can {can}. One role per person: running this again replaces it.")

    def cmd_roles(self, user: str, channel: str) -> None:
        hs = R.holders(self.store)
        text = "\n".join(f"• *{R.TITLE[h.role]}*: {h.name} ({h.email})" for h in hs) or "Nobody yet."
        self.reply(channel, user, f"*AP roles in Slack*\n{text}\nRegister with `/reconai role ap_lead|controller|cfo|cto`.")

    # --- PO announcement (after onboarding) ------------------------------------------------------------
    def announce_po(self, po: PO, contract_id: str, channel: Optional[str]) -> None:
        lines = "; ".join(f"`{ln.sku}` {ln.description} × {ln.qty:,} @ {ln.unit_price:,} {po.currency}" for ln in po.lines)
        codes = ", ".join(ln.sku for ln in po.lines)
        self.say(channel, f":package: *{po.po_number}* created in Helix ERP from contract {contract_id}: {lines}. "
                          f"Please quote {po.po_number} and the item codes ({codes}) on your invoice.\n"
                          f"Supplier: when it ships, run `/reconai shipped {po.po_number} <qty>`; to bill, run "
                          f"`/reconai invoice {po.po_number}` or share the invoice here (PDF, photo, CSV or XLSX).")
        d = self.deal(po.po_number)
        if d and d.requester_user:
            self.dm(d.requester_user, f"{po.po_number} is open in the Helix ERP for contract {contract_id} "
                                      f"({po.currency} {sum((Decimal(l.qty) * l.unit_price for l in po.lines), Decimal(0)):,.2f}). "
                                      f"When goods arrive, confirm the count with `/reconai receive {po.po_number} <qty>`.")

    # --- shipment notice + goods receipt --------------------------------------------------------------
    def cmd_shipped(self, arg: str, user: str, channel: str) -> None:
        vu = self.vendor_user(user)
        if vu is None:
            return self.reply(channel, user, "Only a supplier's registered Slack contact can send a shipment notice.")
        po, err = self.vendor_po(vu, arg)
        if po is None:
            return self.reply(channel, user, err)
        try:
            lines = parse_lines(arg, po, default_all=True)
        except ValueError as e:
            return self.reply(channel, user, str(e))
        sh = Shipment(id=f"shp_{uuid4().hex[:8]}", po_number=po.po_number, lines={k: str(v) for k, v in lines.items()},
                      vendor_user=user, at=_now())
        self.store.put_record(SHIPMENT_KIND, sh.id, sh)
        d = self.deal(po.po_number)
        self.say(d.channel if d else channel, f"Thanks {vu.name or ''}: shipment notice for {po.po_number} "
                                              f"({_fmt(lines)}) logged. Helix will count it on arrival.".replace("  ", " "))
        total = sum(lines.values(), Decimal(0))
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text":
                   f":truck: *{vu.name or 'The supplier'}* says {po.po_number} shipped: {_fmt(lines)}. "
                   "Nothing is received until someone at Helix counts it."}},
                  {"type": "actions", "elements": [
                      _button(f"All {total:,} received", "receipt_all", sh.id, "primary"),
                      _button("Different quantity…", "receipt_other", sh.id)]}]
        to = {d.requester_user} if d and d.requester_user else set()
        to |= {h.slack_user for h in R.holders(self.store)}
        for u in to - {user}:
            self.dm(u, f"{po.po_number} shipped: confirm the count", blocks)

    def _receive(self, po: PO, lines: dict[str, Decimal], user: str, channel: Optional[str]) -> tuple[Optional[str], str]:
        """The only way a Slack action creates a receipt: a Helix person's count. Returns (receipt id, error)."""
        if not self.is_helix(user):
            return None, "Only someone at Helix can record a goods receipt (the supplier's notice is not a receipt)."
        email, name = self.person(user)
        try:
            rec = erp.receive(po.po_number, lines, email, "slack", self.store)
        except erp.ERPError as e:
            return None, str(e)
        d = self.deal(po.po_number)
        self.say(d.channel if d else channel, f":white_check_mark: Goods receipt {rec.doc_id.removeprefix('erp-')} "
                                              f"recorded for {po.po_number}: {_fmt({l.sku: l.qty_received for l in rec.lines})} "
                                              f"(counted by {name}, Helix).")
        return rec.doc_id, ""

    def cmd_receive(self, arg: str, user: str, channel: str) -> None:
        m = PO_RE.search(arg or "")
        po = erp.get_po(self.store, po_no(m)) if m else None
        if po is None:
            return self.reply(channel, user, "Usage: `/reconai receive PO-9001 30` (or `SKU=30,SKU2=5`).")
        try:
            lines = parse_lines(arg, po)
        except ValueError as e:
            return self.reply(channel, user, str(e))
        _, err = self._receive(po, lines, user, None)
        if err:
            self.reply(channel, user, err)
        elif not channel.startswith("D") and self.deal(po.po_number) and self.deal(po.po_number).channel != channel:
            self.reply(channel, user, "Recorded.")

    def receipt_all(self, user: str, shipment_id: str) -> None:
        sh = self.store.get_record(Shipment, SHIPMENT_KIND, shipment_id)
        if sh is None:
            return self.dm(user, "That shipment notice no longer exists.")
        if sh.receipt_id:
            return self.dm(user, f"Already done: {sh.po_number} was counted by {sh.received_by}.")
        po = erp.get_po(self.store, sh.po_number)
        lines = {k: Decimal(v) for k, v in sh.lines.items()}
        rid, err = self._receive(po, lines, user, None) if po else (None, "The PO no longer exists.")
        if err:
            return self.dm(user, err)
        sh.receipt_id, sh.received_by = rid, self.person(user)[1]
        self.store.put_record(SHIPMENT_KIND, sh.id, sh)
        self.dm(user, f"Recorded: {_fmt(lines)} received on {sh.po_number}.")

    def open_receipt_form(self, user: str, shipment_id: str, trigger_id: str) -> None:
        sh = self.store.get_record(Shipment, SHIPMENT_KIND, shipment_id)
        po = erp.get_po(self.store, sh.po_number) if sh else None
        if po is None:
            return self.dm(user, "That shipment notice no longer exists.")
        if sh.receipt_id:
            return self.dm(user, f"Already done: {sh.po_number} was counted by {sh.received_by}.")
        if not self.is_helix(user):
            return self.dm(user, "Only someone at Helix can record a goods receipt.")
        blocks = [{"type": "input", "block_id": f"q{i}", "label": {"type": "plain_text", "text": f"{ln.sku} received"[:150]},
                   "hint": {"type": "plain_text", "text": f"{ln.description} · ordered {ln.qty:,}, notice says "
                                                          f"{sh.lines.get(ln.sku, '0')}"[:150]},
                   "element": {"type": "plain_text_input", "action_id": "v", "initial_value": sh.lines.get(ln.sku, "0")}}
                  for i, ln in enumerate(po.lines)]
        self.client.views_open(trigger_id=trigger_id, view={
            "type": "modal", "callback_id": "receipt_qty", "private_metadata": json.dumps({"shipment": sh.id}),
            "title": {"type": "plain_text", "text": f"Count {po.po_number}"[:24]},
            "submit": {"type": "plain_text", "text": "Record receipt"}, "blocks": blocks})

    def submit_receipt(self, user: str, values: dict, meta: dict) -> dict:
        """Modal submit: {errors} for Slack, else records the receipt."""
        sh = self.store.get_record(Shipment, SHIPMENT_KIND, meta.get("shipment", ""))
        po = erp.get_po(self.store, sh.po_number) if sh else None
        if po is None:
            return {"errors": {}}
        lines, errors = {}, {}
        for i, ln in enumerate(po.lines):
            q = dec(((values.get(f"q{i}") or {}).get("v") or {}).get("value"))
            if q is None:
                errors[f"q{i}"] = "Enter a number (0 if none arrived)."
            elif q > 0:
                lines[ln.sku] = q
        if errors:
            return {"errors": errors}
        if sh.receipt_id:
            self.dm(user, f"Already done: {sh.po_number} was counted by {sh.received_by}.")
            return {"errors": {}}
        rid, err = self._receive(po, lines, user, None) if lines else (None, "Nothing to receive.")
        if err:
            self.dm(user, err)
        else:
            sh.receipt_id, sh.received_by = rid, self.person(user)[1]
            self.store.put_record(SHIPMENT_KIND, sh.id, sh)
        return {"errors": {}}

    # --- invoice: form or PDF ------------------------------------------------------------------------
    def cmd_invoice(self, arg: str, user: str, channel: str, trigger_id: Optional[str]) -> None:
        vu = self.vendor_user(user)
        if vu is None:
            return self.reply(channel, user, "Only a supplier's registered Slack contact can submit an invoice.")
        po, err = self.vendor_po(vu, arg)
        if po is None:
            return self.reply(channel, user, err)
        if not trigger_id:
            return self.reply(channel, user, f"Run `/reconai invoice {po.po_number}` to open the invoice form.")
        got = erp.received(self.store, po.po_number)
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text":
                   f"Invoice Helix Silicon against *{po.po_number}*. Bill what Helix received; prices are the agreed "
                   "ones unless you changed them. Payment goes only to the account on file."}},
                  {"type": "input", "block_id": "invoice_no", "label": {"type": "plain_text", "text": "Invoice number"},
                   "element": {"type": "plain_text_input", "action_id": "v"}},
                  {"type": "input", "block_id": "invoice_date", "label": {"type": "plain_text", "text": "Invoice date"},
                   "element": {"type": "datepicker", "action_id": "v", "initial_date": date.today().isoformat()}}]
        for i, ln in enumerate(po.lines):
            blocks += [{"type": "input", "block_id": f"qty_{i}", "label": {"type": "plain_text", "text": f"{ln.sku}: quantity"[:150]},
                        "hint": {"type": "plain_text", "text": f"{ln.description} · ordered {ln.qty:,}, received {got.get(ln.sku, 0):,}"[:150]},
                        "element": {"type": "plain_text_input", "action_id": "v",
                                    "initial_value": str(got.get(ln.sku) or ln.qty)}},
                       {"type": "input", "block_id": f"price_{i}", "label": {"type": "plain_text", "text": f"{ln.sku}: unit price ({po.currency})"[:150]},
                        "element": {"type": "plain_text_input", "action_id": "v", "initial_value": str(ln.unit_price)}}]
        blocks.append({"type": "input", "block_id": "notes", "optional": True, "label": {"type": "plain_text", "text": "Notes"},
                       "element": {"type": "plain_text_input", "action_id": "v", "multiline": True}})
        self.client.views_open(trigger_id=trigger_id, view={
            "type": "modal", "callback_id": "slack_invoice", "title": {"type": "plain_text", "text": "Invoice Helix"},
            "submit": {"type": "plain_text", "text": "Send invoice"}, "blocks": blocks,
            "private_metadata": json.dumps({"po": po.po_number, "channel": channel})})

    def submit_invoice(self, user: str, values: dict, meta: dict) -> dict:
        """Validate the form in code. Returns {"errors"} for Slack, or {"errors": {}, "invoice": ...} to process."""
        v = lambda b: (((values.get(b) or {}).get("v") or {}).get("value")  # noqa: E731
                       or ((values.get(b) or {}).get("v") or {}).get("selected_date") or "").strip()
        vu = self.vendor_user(user)
        po = erp.get_po(self.store, meta.get("po", ""))
        errors: dict[str, str] = {}
        if vu is None or po is None or po.vendor_id != vu.vendor_id:
            return {"errors": {"invoice_no": "Only the supplier's registered contact can invoice this PO."}}
        no = v("invoice_no")
        if not billing.INVOICE_NO.match(no):
            errors["invoice_no"] = "Letters, digits and - _ / . only (max 40), e.g. INV-1042."
        try:
            on = date.fromisoformat(v("invoice_date"))
        except ValueError:
            errors["invoice_date"] = "Pick a date."
            on = date.today()
        lines = []
        for i, ln in enumerate(po.lines):
            q, p = dec(v(f"qty_{i}")), dec(v(f"price_{i}"))
            if q is None:
                errors[f"qty_{i}"] = "A number (0 to leave this item off)."
            if p is None:
                errors[f"price_{i}"] = "A number, e.g. 1200.00"
            if q and p is not None:
                lines.append((ln.sku, q, p))
        if not lines and not errors:
            errors["qty_0"] = "Bill at least one item."
        if errors:
            return {"errors": errors}
        return {"errors": {}, "invoice": {"no": no, "date": on.isoformat(), "po": po.po_number,
                                          "lines": [[s, str(q), str(p)] for s, q, p in lines], "notes": v("notes")[:500]}}

    def process_invoice(self, user: str, inv: dict, meta: dict) -> Optional[Case]:
        vu = self.vendor_user(user)
        po = erp.get_po(self.store, inv["po"])
        vendor = self.store.get_vendor(vu.vendor_id) if vu else None
        if vu is None or po is None or vendor is None:
            return None
        lines = [(s, Decimal(q), Decimal(p)) for s, q, p in inv["lines"]]
        on = date.fromisoformat(inv["date"])
        cid = self._case_id()
        csv_bytes = billing.invoice_csv(inv["no"], on, po, lines)
        pdf = billing.invoice_pdf(INBOX / cid / "invoice.pdf", vendor, inv["no"], on, po, lines, inv.get("notes", ""))
        return self.intake(vu, cid, [("invoice.csv", csv_bytes), (pdf.name, pdf.read_bytes())], inv["no"], po.po_number,
                           meta.get("channel"))

    def on_file(self, event: dict) -> None:
        """A file shared in a deal channel or a DM. Only the vendor's registered Slack user's invoice files (PDF,
        PNG/JPEG, CSV, XLSX) become invoices; anything else is refused with the reason."""
        user, channel = event.get("user"), event.get("channel")
        files = event.get("files") or []
        pdfs = [f for f in files if _invoice_type(f)]
        others = [f for f in files if not _invoice_type(f)]
        if not user or not channel or user == self.bot_user or not files:
            return
        vu = self.vendor_user(user)
        dealish = channel.startswith("D") or event.get("channel_type") == "im" or any(d.channel == channel for d in self.deals())
        if vu is None:
            if pdfs and dealish and not self.is_helix(user):
                log.warning("slack invoice refused: %s is not a registered vendor contact (channel %s)", user, channel)
                self.reply(channel, user, "Thanks, but I only take invoices from the supplier's registered Slack "
                                          "contact, so I haven't processed this file.")
            return
        for f in others:
            ft = (f.get("filetype") or f.get("name", "").rsplit(".", 1)[-1] or "unknown").lower()
            why = (" Macro-enabled spreadsheets are refused for security." if ft in ("xlsm", "xlsb", "xls") else
                   " iPhone HEIC photos: export as JPEG first." if ft in ("heic", "heif") else "")
            self.reply(channel, user, f"I can read invoices as {ACCEPTED_TEXT}. *{f.get('name', 'That file')}* "
                                      f"({ft}) wasn't processed.{why} Or run `/reconai invoice`.")
        if not pdfs:
            return
        mine = sorted((d for d in self.deals() if d.vendor_id == vu.vendor_id), key=lambda d: d.po_number)
        mine = [d for d in mine if d.channel == channel] or mine  # a supplier with several deals: this channel's
        po_number = mine[-1].po_number if mine else None
        for f in pdfs[:3]:
            if int(f.get("size") or 0) > MAX_FILE:
                self.reply(channel, user, f"{f.get('name', 'That file')} is over 10 MB; please send a smaller file.")
                continue
            data = self.download(f)
            ext = _invoice_type(f)
            stem = re.sub(r"[^A-Za-z0-9._-]+", "_", (f.get("name") or "invoice").rsplit(".", 1)[0])[:70] or "invoice"
            name = f"{stem}.{ext}"
            self.intake(vu, self._case_id(), [(name, data)], name, po_number, channel)

    def download(self, f: dict) -> bytes:
        if self._download:
            return self._download(f)
        import httpx
        url = f.get("url_private_download") or f.get("url_private")
        if not url or not url.startswith("https://files.slack.com/"):
            raise ValueError("not a Slack file URL")
        r = httpx.get(url, headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}, timeout=30,
                      follow_redirects=True)
        r.raise_for_status()
        if len(r.content) > MAX_FILE:
            raise ValueError("file over 10 MB")
        return r.content

    @staticmethod
    def _case_id() -> str:
        return f"slk_{uuid4().hex[:8]}"

    def intake(self, vu: VendorUser, cid: str, files: list[tuple[str, bytes]], label: str, po_number: Optional[str],
               channel: Optional[str]) -> Case:
        """Like POST /intake: files + fixture.json under .data/slack_inbox/<case_id>/, channel slack, sender = the
        vendor's Slack user (ingest binds it to the vendor), then the pipeline in the background."""
        from backend.core.runner import make_ctx
        from backend.intake.ingest import ingest
        folder = INBOX / cid
        folder.mkdir(parents=True, exist_ok=True)
        now = _now()
        for name, data in files:
            (folder / name).write_bytes(data)
        fx = CaseFixture(id=cid, title=f"Slack invoice {label}"[:120], as_of=date.today(), inbound=[
            InboundItem(channel=Channel.slack, path=name, sender=vu.slack_user, received_at=now) for name, _ in files])
        (folder / "fixture.json").write_text(fx.model_dump_json(indent=1))
        case = ingest(fx, folder, make_ctx(self.store))
        rec = erp.received(self.store, po_number) if po_number else {}
        grns = [r.doc_id.removeprefix("erp-") for r in self.store.list_receipts(po_number)] if po_number else []
        d = self.deal(po_number)
        self.say(d.channel if d else channel,
                 f"Received {label}: ReconAI is reconciling it against {po_number or 'your purchase order'}"
                 + (f" and goods receipt {', '.join(grns)}" if grns else " (no goods receipt recorded yet)")
                 + (f" ({_fmt(rec)} received)" if rec else "") + ". We'll be in touch here.")
        if channel and d and channel != d.channel:
            self.say(channel, f"Received {label}; updates follow in the deal channel.")
        run = self.runner or self._run_default
        if self.async_coach:
            threading.Thread(target=self._safe, args=(run, case), daemon=True).start()
        else:
            run(case)
        return case

    def _run_default(self, case: Case) -> None:
        from backend.core.runner import make_ctx, run_case
        from contracts import CaseStatus
        if case.status != CaseStatus.quarantined:
            case.status, case.decision = CaseStatus.new, None
        self.store.save_case(case)
        ctx = make_ctx(self.store)
        ctx.human_signoff = os.environ.get("RECONAI_HUMAN_SIGNOFF", "on").lower() != "off"
        self.notify_bill(run_case(case, ctx))

    # --- after a bill's run ------------------------------------------------------------------------------
    def _link(self, case_id: str) -> str:
        return f"{self.app_url}/#/bill/{case_id}"

    def _requester_email(self, case: Case) -> str:
        return (case.po.requester if case.po else "").lower()

    def approvers_for(self, case: Case) -> tuple[list, bool]:
        """(role holders to ask, they are AP leads). AP leads when the amount is within their limit, else the
        controller / CFO / CTO holders whose limit covers it. Never the requester, unless CFO / CTO (self-approve)."""
        policy = load_policy()
        amount = usd(case, policy) or Decimal(0)
        req = self._requester_email(case)
        hs = [h for h in R.holders(self.store, APPROVE_ROLES)
              if h.email != req or h.role.value in policy.self_approve_roles()]
        leads = [h for h in hs if h.role == Role.approver and amount <= policy.approval_limits.get("approver", 0)]
        if leads:
            return leads, True
        return [h for h in hs if h.role.value in release_roles(policy)
                and amount <= policy.approval_limits.get(h.role.value, Decimal(0))], False

    def releasers_for(self, case: Case) -> list:
        policy = load_policy()
        amount = usd(case, policy) or Decimal(0)
        approved = ap_state.last_approved(case)
        return [h for h in R.holders(self.store, release_roles(policy))
                if amount <= policy.approval_limits.get(h.role.value, Decimal(0))
                and not (approved and approved.role.value not in release_roles(policy)
                         and approved.approver.lower() == h.email)]

    def notify_bill(self, case: Case) -> None:
        if not ap_state.is_bill(case, self.store.list_cases()):
            return
        policy = load_policy()
        vendor = self.store.get_vendor(case.vendor_id)
        packet = build_packet(case, self.store.list_steps(case.id), vendor, policy, self.store)
        green, why = billing.assess(case, vendor, policy, self.store, packet)
        facts = "\n".join(billing.facts(case, vendor, self.store, policy))
        link = self._link(case.id)
        inv_no = case.invoice.invoice_no if case.invoice else case.id
        if green:
            if case.journal_entry is not None:  # already booked (simulated sign-off): only the release is left
                return self._ask_release(case, f"*{inv_no}* is approved and booked; release the payment?")
            people, leads = self.approvers_for(case)
            main = (_button("Approve", "bill_approve", case.id, "primary") if leads else
                    _button("Approve & release via Coinbase", "bill_approve_release", case.id, "primary"))
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text":
                       f":large_green_circle: *Ready to approve: {inv_no}*\n{facts}\n• Checks passed: 3-way match "
                       f"(PO = receipt = invoice), price, bank account = vendor master, no duplicate, sender bound to "
                       f"the vendor.\n<{link}|Open the bill in ReconAI>"}},
                      {"type": "actions", "elements": [main, _button("Hold", "bill_hold", case.id)]}]
            for h in people:
                self.dm(h.slack_user, f"Ready to approve: {inv_no}", blocks)
            return
        people, _ = self.approvers_for(case)
        text = (f":warning: *{inv_no} needs a look* ({case.decision.value if case.decision else 'not decided'})\n{facts}\n"
                + "\n".join(f"• {w}" for w in why[:6]) + f"\n<{link}|Review it in ReconAI>")
        for h in people:
            self.dm(h.slack_user, text)
        d = self.deal(case.invoice.po_number if case.invoice else None) or (
            None if case.invoice else self.vendor_deal(case.vendor_id))  # unreadable: the vendor's latest deal
        if d:
            to = vendor.contact_email if vendor and vendor.contact_email else "your contact on file"
            issues = billing.vendor_issues(case)
            if not issues:  # nothing the vendor can fix (e.g. a bank-change check): never say which check tripped
                return self.say(d.channel, f"We found a difference on {inv_no}; details emailed to {to}.")
            tags = " ".join(f"<@{u.slack_user}>" for u in self.store.list_records(VendorUser, VENDOR_USER_KIND)
                            if u.vendor_id == case.vendor_id)
            po = case.invoice.po_number or d.po_number
            self.say(d.channel, f"{tags} :warning: *{inv_no}* ({po}) didn't pass Helix's checks:\n"
                                + "\n".join(f"• {i}" for i in issues)
                                + f"\nPlease send a corrected invoice numbered *{billing.next_invoice_no(inv_no)}* "
                                  f"with every line fixed: run `/reconai invoice {po}` or share the file here. "
                                  f"Details also emailed to {to}.")

    def _ask_release(self, case: Case, head: str) -> None:
        policy = load_policy()
        facts = "\n".join(billing.facts(case, self.store.get_vendor(case.vendor_id), self.store, policy))
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"{head}\n{facts}\n<{self._link(case.id)}|Open the bill>"}},
                  {"type": "actions", "elements": [_button("Release via Coinbase", "bill_release", case.id, "primary"),
                                                   _button("Hold", "bill_hold", case.id)]}]
        for h in self.releasers_for(case):
            self.dm(h.slack_user, head.replace("*", ""), blocks)

    def bill_action(self, action: str, user: str, case_id: str) -> None:
        """[Approve] / [Approve & release] / [Release] / [Hold]: every permission re-checked in code."""
        h = R.holder(self.store, user)
        if h is None:
            return self.dm(user, "Register your AP role first: `/reconai role ap_lead|controller|cfo|cto`.")
        title = R.TITLE[h.role]
        try:
            if action == "bill_hold":
                actions.approve_bill(self.store, case_id, h.email, h.role, "ask", f"Held in Slack by {h.name}")
                return self.dm(user, f"On hold: {case_id}. It stays in the review queue.")
            if action == "bill_approve":
                case = self.store.get_case(case_id)
                if case and case.journal_entry is not None:
                    return self.dm(user, f"Already done: {case_id} is approved and booked.")
                case = actions.approve_bill(self.store, case_id, h.email, h.role, "approved",
                                            f"Approved in Slack by {h.name} ({title})")
                if case.journal_entry is None:
                    return self.dm(user, f"Recorded, but not booked: {ap_state.poster_refusal(case) or case.status.value}.")
                self.dm(user, f"Approved and booked: {case.invoice.invoice_no}. "
                              + ("A controller, CFO or CTO releases the payment." if h.role == Role.approver else
                                 "Release it from the bill or the [Release] message."))
                return self._ask_release(case, f"*{case.invoice.invoice_no}* approved by {h.name} ({title}); "
                                               "release the payment?")
            if h.role.value not in release_roles(load_policy()):
                return self.dm(user, f"As {title} you can approve bills but never release payments.")
            batch = actions.approve_and_release(self.store, self.pay, case_id, h.email, h.role, rail="coinbase")
        except actions.ActionError as e:
            done = e.status_code == 409 and ("Already" in e.detail)
            return self.dm(user, ("Already done: " if done else "Not done: ") + e.detail)
        self.announce_payment(case_id, batch, h)

    def announce_payment(self, case_id: str, batch, h) -> None:
        p = next(x for x in batch.payments if x.case_id == case_id)
        case = self.store.get_case(case_id)
        inv_no = case.invoice.invoice_no if case and case.invoice else case_id
        if p.status != "paid":
            return self.dm(h.slack_user, f"Payment for {inv_no} did not go through: {p.error or batch.status}. "
                                         "Retry from Bills → For payment.")
        net = "sandbox, SIMULATED (no chain)" if p.network == "sandbox" else f"{p.network} testnet"
        amount = f"{p.currency} {p.amount:,.2f}"
        tx = f"tx {p.tx_hash}" + (f" ({p.explorer_url})" if p.explorer_url else "")
        self.dm(h.slack_user, f":money_with_wings: Released {inv_no}: {amount} → {p.onchain_amount} USDC on {net}, {tx}. "
                              f"Paid to the vendor master wallet {p.payee_address}.")
        d = self.deal(case.invoice.po_number if case and case.invoice else None)
        if d and d.requester_user and d.requester_user != h.slack_user:
            self.dm(d.requester_user, f"{inv_no} for {d.po_number} was paid by {h.name}: {amount} ({tx}).")
        if d:
            self.say(d.channel, f"Payment sent: {amount} for {inv_no} ({p.onchain_amount} USDC, {net}), {tx}.")
