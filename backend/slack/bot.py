"""ReconAI Slack bot (Socket Mode: no public URL needed). Owner: D.

  /reconai negotiate <vendor>   start coaching in this channel; the person who runs it is the Helix owner
  (chat as usual)               on every new price / terms move, ReconAI privately (ephemeral, owner only) posts
                                the numbers to negotiate with: our PO history, the market, target, walk-away
  /reconai contract             owner only: draft the supply agreement (PDF) from what was agreed
  [Accept & start onboarding]   supplier only: opens the onboarding form; on submit every onboarding check runs and
                                a low-risk vendor is onboarded by policy + confirmation email (else a controller)
  /reconai status | onboard | stop | help
  billing cycle (backend/slack/cycle.py): role / roles, shipped, receive, invoice, PDF invoices, approve + release DMs
@ReconAI <same verbs> works too (onboarding then posts the button, since a modal needs a click).

Trust: chat text is untrusted. It is only read by Claude calls with no tools (backend/slack/negotiation.py);
web market notes use our own canonical query, never chat text. The channel is told ReconAI is assisting Helix.
Env: SLACK_BOT_TOKEN (xoxb-), SLACK_APP_TOKEN (xapp-, connections:write), RECONAI_SLACK_INTERNAL_USERS (optional
comma list of Slack user ids treated as Helix besides the owner), RECONAI_APP_URL.
"""
from __future__ import annotations

import json
from decimal import Decimal
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

from backend.core.config import ROOT, load_policy
from backend.slack import contract as ct
from backend.slack import negotiation as neg
from backend.slack.cycle import BillingCycle
from backend.slack.models import (APPLICANT_KIND, NEGOTIATION_LOG_KIND, Message, NegotiationLog, Session,
                                  VendorUser)
from backend.slack.onboard import po_for_contract, start as start_onboarding
from backend.vendors.crs import persona_options
from contracts import OnboardingCase, OnboardingRequestIn, VendorContract

load_dotenv(ROOT / ".env")
log = logging.getLogger("reconai.slack")
SESSION = "slack_session"  # = models.SESSION_KIND
TRIGGER = re.compile(r"\d|net\s*\d|discount|agree|deal|terms|price|quote|accept", re.I)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def configured() -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReconBot(BillingCycle):
    def __init__(self, store, pay, client=None, runner=None, download=None):
        """`client`: inject a Slack WebClient stand-in (tests); without one, a real Bolt app is built and routed.
        `runner(case)`: runs an accepted intake case through the pipeline (the API's, so notifications follow).
        `download(file) -> bytes`: fetch a Slack file (tests inject one; live uses the bot token)."""
        self.store, self.pay = store, pay
        self.runner, self._download = runner, download
        self.app = None
        if client is None:
            from slack_bolt import App
            self.app = App(token=os.environ["SLACK_BOT_TOKEN"])
            client = self.app.client
        self.client = client
        self.bot_user = self.client.auth_test().get("user_id")
        self.locks: dict[str, threading.Lock] = {}
        self.coach_locks: dict[str, threading.Lock] = {}
        self.coach_pending: dict[str, threading.Event] = {}
        self.async_coach = self.app is not None  # live Slack: coach off the message thread; tests stay synchronous
        self.internal = {u.strip() for u in os.environ.get("RECONAI_SLACK_INTERNAL_USERS", "").split(",") if u.strip()}
        self.app_url = os.environ.get("RECONAI_APP_URL", "http://localhost:5173")
        if self.app is not None:
            self._routes()

    # --- state ----------------------------------------------------------------------------------
    def session(self, channel: str) -> Optional[Session]:
        s = self.store.get_record(Session, SESSION, channel)
        return s if s and s.active else None

    def save(self, s: Session) -> None:
        self.store.put_record(SESSION, s.channel, s)

    def lock(self, channel: str) -> threading.Lock:
        return self.locks.setdefault(channel, threading.Lock())

    def person(self, user: str) -> tuple[str, str]:
        try:
            u = self.client.users_info(user=user)["user"]
            return (u.get("profile", {}).get("email") or f"{user}@slack.local",
                    u.get("real_name") or u.get("name") or user)
        except Exception:
            return f"{user}@slack.local", user

    def tell(self, channel: str, user: str, text: str) -> None:
        try:
            self.client.chat_postEphemeral(channel=channel, user=user, text=text)
        except Exception as e:
            log.warning("ephemeral failed: %s", e)

    # --- commands ---------------------------------------------------------------------------------
    def handle(self, verb: str, arg: str, user: str, channel: str, trigger_id: Optional[str] = None) -> None:
        s = self.session(channel)
        if verb in ("negotiate", "watch", "start"):
            if self.vendor_user(user) is not None:  # a supplier's contact is never the Helix side of a deal
                return self.tell(channel, user, "Only Helix people can start a negotiation.")
            if s and s.owner != user:
                return self.tell(channel, user, f"A negotiation is already running here, led by {s.owner_name or s.owner}. "
                                                "They can `/reconai stop` it first.")
            email, name = self.person(user)
            s = Session(channel=channel, owner=user, owner_email=email, owner_name=name, vendor_name=arg.strip()[:120],
                        started_at=_now())
            self.save(s)
            self.client.chat_postMessage(channel=channel, text=(
                f":robot_face: ReconAI is assisting *{name}* (Helix Silicon) in this negotiation"
                + (f" with *{s.vendor_name}*" if s.vendor_name else "") + ". It reads this channel to help Helix "
                "prepare the agreement and vendor onboarding. Nothing here is shared outside Helix."))
            self.tell(channel, user, "I'll send you private negotiation notes whenever prices or terms move. "
                                     "When you've agreed, run `/reconai contract`.")
        elif verb in ("contract", "draft"):
            if not s:
                return self.tell(channel, user, "No negotiation here yet: run `/reconai negotiate <vendor>` first.")
            if user != s.owner and user not in self.internal:
                return self.tell(channel, user, "Only the Helix person running this negotiation can draft the contract.")
            self.draft_contract(s, user)
        elif verb in ("onboard", "onboarding"):
            if not s or not s.contract_id:
                return self.tell(channel, user, "There's no drafted contract in this channel yet.")
            c = self.store.get_record(VendorContract, ct.KIND, s.contract_id)
            if c is None:
                return self.tell(channel, user, "That contract no longer exists.")
            if trigger_id and user != s.owner and user not in self.internal:
                self.open_form(trigger_id, c, channel, None)
            else:
                self.post_accept(c, channel)
        elif verb == "status":
            if not s:
                return self.tell(channel, user, "No negotiation in this channel.")
            self.coach(s, force=True, to=user)
        elif verb in ("ask", "q"):
            self.cmd_ask(arg, user, channel)
        elif verb == "role":
            self.cmd_role(arg, user, channel)
        elif verb == "roles":
            self.cmd_roles(user, channel)
        elif verb in ("shipped", "ship", "shipment"):
            self.cmd_shipped(arg, user, channel)
        elif verb in ("receive", "received", "grn"):
            self.cmd_receive(arg, user, channel)
        elif verb in ("invoice", "bill"):
            self.cmd_invoice(arg, user, channel, trigger_id)
        elif verb == "stop":
            if s and user == s.owner:
                s.active = False
                self.save(s)
                self.client.chat_postMessage(channel=channel, text="ReconAI has stopped assisting in this channel.")
        elif verb not in ("", "help") and self.vendor_user(user) is None and (
                self.store.get_record(Session, SESSION, channel) or any(d.channel == channel for d in self.deals())):
            self.cmd_ask(f"{verb} {arg}".strip(), user, channel)  # a plain question: `/reconai is this deal complete?`
        else:
            self.reply(channel, user, self.help_text(user, channel))

    def cmd_ask(self, question: str, user: str, channel: str) -> None:
        """/recon <question>: private Q&A with ReconAI about this channel's deal, during the negotiation and after it
        (contract, PO, goods receipts, invoices, payments). Ephemeral: the supplier never sees the question (slash
        commands aren't posted) or the answer (only the asker sees it)."""
        from backend.slack import roles as R
        question = question.strip()
        s = self.store.get_record(Session, SESSION, channel)  # the negotiation may be over: still answer about the deal
        deals = [d for d in self.deals() if d.channel == channel]
        if self.vendor_user(user) is not None:
            return self.tell(channel, user, "Only the Helix side of this deal can ask ReconAI about it.")
        if s is None and not deals:
            return self.tell(channel, user, "No negotiation or deal in this channel yet: `/reconai negotiate <vendor>` first.")
        allowed = (s is not None and user == s.owner) or user in self.internal or \
            any(d.requester_user == user for d in deals) or R.holder(self.store, user) is not None
        if not allowed:
            return self.tell(channel, user, "Only the Helix person running this deal (or someone with an AP role) can ask "
                                            "ReconAI about it.")
        if not question:
            return self.tell(channel, user, "Ask anything about this deal, privately, e.g. `/recon is $21,800 a good "
                                            "price?`, `/recon is this deal complete?` or `/recon what's left to pay?`")
        status = self.deal_status(deals)
        msgs, state, source = self.conversation(channel, s, deals)
        extra = {"deal_status_computed": status} if status else {}
        extra["conversation_source"] = source
        answer, _ = neg.ask(question, msgs, state, (s.vendor_name if s else "") or (status.get("vendor") or ""),
                            list(s.qa) if s else [], load_policy(), self.store, extra=extra)
        if s is not None:
            with self.lock(channel):
                cur = self.store.get_record(Session, SESSION, channel) or s
                cur.qa = (cur.qa + [{"q": question[:400], "a": answer[:1500]}])[-10:]
                self.save(cur)
        self.tell(channel, user, f"*You asked ReconAI (only you see this):* {question[:400]}\n{answer}")

    def conversation(self, channel: str, s: Optional[Session], deals: list) -> tuple[list, object, str]:
        """(messages, extracted state, where they came from). The live negotiation first, then the log archived with
        the contract, then (nothing kept) the channel's own Slack history. Text stays untrusted throughout."""
        if s is not None and s.transcript:
            return list(s.transcript), s.state, "live negotiation"
        for d in deals:
            lg = self.store.get_record(NegotiationLog, NEGOTIATION_LOG_KIND, d.contract_id)
            if lg and lg.transcript:
                return list(lg.transcript), lg.state, f"negotiation log archived with contract {d.contract_id}"
        hist = self.channel_history(channel)
        if hist:
            return hist, None, "Slack channel history (no stored negotiation log)"
        return [], None, "none"

    def channel_history(self, channel: str, limit: int = 200) -> list[Message]:
        """People's messages in this channel, oldest first (bots and slash commands excluded). A supplier's
        registered contact is the VENDOR side; everyone else here is Helix."""
        try:
            res = self.client.conversations_history(channel=channel, limit=limit)
        except Exception as e:  # missing scope / not in channel: answer from records only
            log.warning("channel history unavailable for %s: %s", channel, e)
            return []
        out = []
        for m in reversed(res.get("messages") or []):
            u, text = m.get("user"), (m.get("text") or "").strip()
            if not u or not text or m.get("subtype") or m.get("bot_id") or u == self.bot_user or text.startswith("/"):
                continue
            _, name = self.person(u)
            out.append(Message(user=u, name=name, internal=self.vendor_user(u) is None, text=text[:2000],
                               ts=m.get("ts", "")))
        return out[-80:]

    def deal_status(self, deals: list) -> dict:
        """Where each of this channel's deals stands after the negotiation, computed from the ERP + AP records."""
        from backend import erp
        from backend.ap import views as ap_views
        if not deals:
            return {}
        pos = {v.po.po_number: v for v in erp.list_pos(self.store)}
        bills = ap_views.bills(self.store, self.pay, load_policy(), ap_views.utcnow()) if self.pay is not None else []
        out = []
        for d in deals:
            v = pos.get(d.po_number)
            contract = self.store.get_record(VendorContract, ct.KIND, d.contract_id)
            ordered = {ln.sku: str(ln.qty) for ln in v.po.lines} if v else {}
            received = {k: str(q) for k, q in (v.received if v else {}).items()}
            bs = [{"invoice": b.invoice_no, "amount": str(b.amount), "currency": b.currency, "stage": b.stage,
                   "paid": b.stage == "paid",
                   "payment": ({"rail": b.payment.rail, "tx": b.payment.tx_hash, "status": b.payment.status}
                               if b.payment else None)} for b in bills if v and b.case_id in v.invoices]
            fully_received = bool(v) and all(Decimal(received.get(k, "0")) >= Decimal(q) for k, q in ordered.items())
            all_paid = bool(bs) and all(x["paid"] for x in bs)
            left = [step for step, done in (("goods receipt for everything ordered", fully_received),
                                            ("an invoice from the supplier", bool(bs)),
                                            ("payment of every invoice", all_paid)) if not done]
            vendor = self.store.get_vendor(d.vendor_id)
            out.append({"po": d.po_number, "erp_ref": v.po.erp_ref if v else None, "po_status": v.status if v else None,
                        "vendor": vendor.name if vendor else d.vendor_id,
                        "contract": d.contract_id, "contract_status": contract.status if contract else None,
                        "contract_total": f"{contract.total} {contract.currency}" if contract else None,
                        "agreed_terms": {"items": contract.items, "payment_terms": ct.terms_text(contract.terms),
                                         "delivery": contract.delivery, "warranty": contract.warranty,
                                         "other_terms": contract.other_terms, "negotiated_by": contract.requested_by,
                                         "accepted_by": contract.accepted_by,
                                         "drafted": contract.created_at.isoformat()} if contract else None,
                        "ordered": ordered, "received": received, "invoices": bs,
                        "complete": not left, "still_open": left})
        return {"deals": out, "vendor": out[0]["vendor"] if out else ""}

    def help_text(self, user: str, channel: str) -> str:
        """`/reconai help`: only the commands this person can use, for who they are here."""
        from backend.slack import roles as R
        vu = self.vendor_user(user)
        if vu is not None:  # a supplier's registered contact
            v = self.store.get_vendor(vu.vendor_id)
            return "\n".join([
                f"*ReconAI for {v.name if v else 'suppliers'}* (supplier)",
                "• `/reconai shipped PO-9001 <qty>`: tell Helix a shipment is on its way (Helix counts it on arrival)",
                "• `/reconai invoice PO-9001`: send an invoice with a short form (or share the invoice here as a PDF, photo, CSV or XLSX)",
                "• *Accept & start onboarding* button on a contract: complete vendor onboarding",
                "_Quote the PO number and item codes on every invoice. Bank details change only by a verified "
                "phone callback, never in Slack._"])
        h = R.holder(self.store, user)
        s = self.session(channel)
        who = R.TITLE.get(h.role, h.role.value) if h else "Helix, no AP role yet"
        lines = [f"*ReconAI commands for you* ({who})",
                 "*Deals*",
                 "• `/reconai negotiate <vendor>`: ReconAI coaches you privately with market numbers in this channel"]
        if s and s.owner == user:
            lines += ["• `/recon <question>`: ask ReconAI anything about this deal, privately (the vendor never sees it)",
                      "• `/reconai status`: your latest negotiation notes",
                      "• `/reconai contract`: draft the supply agreement from what was agreed",
                      "• `/reconai stop`: stop assisting in this channel"]
        lines += ["*Receiving*", "• `/reconai receive PO-9001 <qty>`: record the goods receipt in the ERP (what actually arrived)"]
        if h is None:
            lines += ["*Approvals*", "• `/reconai role ap_lead | controller | cfo | cto`: register your AP role to get "
                      "approval and payment messages"]
        elif h.role.value == "approver":
            lines += ["*Approvals (AP lead)*",
                      "• You get a DM with *[Approve]* when an invoice up to the AP lead limit passes the 3-way match",
                      "• You approve; a controller, CFO or CTO then releases the payment"]
        else:
            lines += [f"*Approvals and payments ({who})*",
                      "• You get a DM with *[Approve & release via Coinbase]* for green invoices in your limit",
                      "• After an AP lead approves, you get *[Release via Coinbase]*"]
        lines += ["• `/reconai roles`: who holds which AP role", "• `/reconai help`: this list"]
        return "\n".join(lines)

    # --- coaching ---------------------------------------------------------------------------------
    def on_message(self, event: dict) -> None:
        if event.get("subtype") == "file_share" and not event.get("bot_id"):
            return self.on_file(event)
        if event.get("subtype") or event.get("bot_id") or event.get("user") == self.bot_user:
            return
        channel, user, text = event.get("channel"), event.get("user"), (event.get("text") or "").strip()
        if not channel or not user or not text or text.startswith("/"):
            return
        with self.lock(channel):
            s = self.session(channel)
            if not s:
                return
            _, name = self.person(user)
            s.transcript.append(Message(user=user, name=name, internal=user == s.owner or user in self.internal,
                                        text=text[:2000], ts=event.get("ts", "")))
            s.transcript = s.transcript[-80:]
            self.save(s)
        if TRIGGER.search(text):
            if self.async_coach:
                threading.Thread(target=self._safe, args=(self._coach_latest, channel),
                                 kwargs={"channel": channel, "user": None}, daemon=True).start()
            else:
                self._coach_latest(channel)

    def _coach_latest(self, channel: str) -> None:
        """One coaching pass at a time per channel; messages that arrive meanwhile trigger one more pass."""
        pending = self.coach_pending.setdefault(channel, threading.Event())
        pending.set()
        lk = self.coach_locks.setdefault(channel, threading.Lock())
        if not lk.acquire(blocking=False):
            return  # the running pass re-reads the transcript when it finishes
        try:
            while pending.is_set():
                pending.clear()
                s = self.session(channel)
                if s:
                    self.coach(s)
        finally:
            lk.release()

    def _merge(self, channel: str, **fields) -> None:
        """Write negotiation state onto the CURRENT session (never a stale copy: messages may have arrived)."""
        with self.lock(channel):
            cur = self.session(channel)
            if cur:
                for k, v in fields.items():
                    setattr(cur, k, v)
                self.save(cur)

    def coach(self, s: Session, force: bool = False, to: Optional[str] = None) -> None:
        st, engine = neg.extract(list(s.transcript))
        sig = neg.signature(st)
        if sig == s.last_signature and not force:
            self._merge(s.channel, state=st)
            return
        text, analysis, _ = neg.coach(st, load_policy(), self.store)
        s.suggestions += 1
        self._merge(s.channel, state=st, last_signature=sig, suggestions=s.suggestions)
        if not text:
            if force:
                self.tell(s.channel, to or s.owner, "Nothing priced yet. I'll chime in once numbers are on the table.")
            return
        head = f"*ReconAI negotiation notes* (only you see this) · {analysis.category_label}"
        tail = ("\n_Agreed? Run `/reconai contract` to draft the agreement._" if st.agreed and not s.contract_id else "")
        self.tell(s.channel, to or s.owner, f"{head}\n{text}{tail}\n_Sources: {'; '.join(analysis.sources)}_")

    # --- contract + onboarding --------------------------------------------------------------------
    def draft_contract(self, s: Session, user: str) -> None:
        st, _ = neg.extract(s.transcript)
        missing = neg.contract_ready(st)
        if missing:
            return self.tell(s.channel, user, f"Can't draft yet: {missing}")
        c = ct.build(s, st, _now())
        path = ct.render_pdf(c)
        self.store.put_record(ct.KIND, c.id, c)
        s.contract_id, s.state = c.id, st
        self.save(s)
        self.store.put_record(NEGOTIATION_LOG_KIND, c.id, NegotiationLog(
            contract_id=c.id, channel=s.channel, owner=s.owner, owner_name=s.owner_name, vendor_name=s.vendor_name,
            started_at=s.started_at, archived_at=_now(), transcript=list(s.transcript), state=st,
            suggestions=s.suggestions))
        try:
            self.client.files_upload_v2(channel=s.channel, file=str(path), filename=path.name,
                                        title=f"Supply Agreement {c.id}", initial_comment=ct.summary(c))
        except Exception as e:  # files:write missing: the summary + button still work
            log.warning("upload failed: %s", e)
            self.client.chat_postMessage(channel=s.channel, text=ct.summary(c))
        self.post_accept(c, s.channel)

    def post_accept(self, c: VendorContract, channel: str) -> None:
        self.client.chat_postMessage(channel=channel, text=f"Supply Agreement {c.id} is ready for the supplier.", blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text":
                f"*Supply Agreement {c.id}* is ready. {c.vendor_name}: review the PDF above, then accept to start "
                "vendor onboarding (company, tax and payment details)."}},
            {"type": "actions", "elements": [{"type": "button", "action_id": "accept_contract", "style": "primary",
                                              "text": {"type": "plain_text", "text": "Accept & start onboarding"},
                                              "value": c.id}]}])

    def open_form(self, trigger_id: str, c: VendorContract, channel: str, thread: Optional[str]) -> None:
        def field(bid, label, hint="", optional=False, initial=""):
            el = {"type": "plain_text_input", "action_id": "v"}
            if initial:
                el["initial_value"] = initial
            b = {"type": "input", "block_id": bid, "label": {"type": "plain_text", "text": label}, "element": el,
                 "optional": optional}
            if hint:
                b["hint"] = {"type": "plain_text", "text": hint}
            return b
        form = {"type": "input", "block_id": "tax_form", "label": {"type": "plain_text", "text": "Tax form"},
                "element": {"type": "static_select", "action_id": "v", "options": [
                    {"text": {"type": "plain_text", "text": t}, "value": t} for t in ("W-9", "W-8BEN-E", "Not yet")]}}
        self.client.views_open(trigger_id=trigger_id, view={
            "type": "modal", "callback_id": "onboard_vendor",
            "private_metadata": json.dumps({"contract": c.id, "channel": channel, "thread": thread}),
            "title": {"type": "plain_text", "text": "Helix vendor onboarding"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text":
                        f"Accepting *Supply Agreement {c.id}* ({c.total} {c.currency}). Helix will verify these details "
                        "(business registry, credit, sanctions, tax) before you can be paid."}},
                       field("legal_name", "Legal company name", initial=c.vendor_name),
                       field("country", "Country (2-letter ISO code)", "e.g. US, TW, KR", initial="US"),
                       field("tax_id", "Tax ID (EIN / registration no.)",
                             "Simulated CRS sandbox: US-77-4012339 is a clean US business"),
                       form,
                       field("address", "Street address", optional=True), field("city", "City", optional=True),
                       field("state", "State / region", optional=True), field("zip", "ZIP / postal code", optional=True),
                       field("contact_name", "Accounts-receivable contact name"),
                       field("contact_email", "Contact email (confirmation goes here)"),
                       field("contact_phone", "Contact phone (used for bank-change callbacks)"),
                       field("bank_last4", "Bank account: LAST 4 DIGITS ONLY",
                             "Never type a full account number in Slack. Full details are collected by phone."),
                       {"type": "input", "block_id": "principal_persona",
                        "label": {"type": "plain_text", "text": "Owner / authorized signer (CRS sandbox test persona)"},
                        "hint": {"type": "plain_text", "text": "Helix verifies the person behind the company with CRS (identity, "
                                 "fraud, court records). Sandbox: pick a test persona; no real person is looked up, and "
                                 "SSNs are never typed into Slack."},
                        "element": {"type": "static_select", "action_id": "v", "options": [
                            {"text": {"type": "plain_text", "text": f"{p['id']} · {p['name']} · {p['profile']}"[:75]},
                             "value": p["id"]} for p in persona_options()]}},
                       {"type": "input", "block_id": "credit_consent", "optional": True,
                        "label": {"type": "plain_text", "text": "Consent"},
                        "element": {"type": "checkboxes", "action_id": "v", "options": [
                            {"text": {"type": "plain_text", "text": "The owner consents to a soft credit check (no score impact)"},
                             "value": "yes"}]}}]})

    def accept(self, user: str, channel: str, contract_id: str, trigger_id: str, thread: Optional[str] = None) -> None:
        """[Accept & start onboarding]: the supplier accepts, never anyone at Helix."""
        s = self.session(channel)
        if (s and user == s.owner) or user in self.internal:
            return self.tell(channel, user, "The supplier accepts the contract, not Helix: ask them to click it.")
        c = self.store.get_record(VendorContract, ct.KIND, contract_id)
        if c:
            self.open_form(trigger_id, c, channel, thread)

    def submit_form(self, user: str, values: dict, meta: dict) -> dict:
        v = {k: (b["v"].get("value") or (b["v"].get("selected_option") or {}).get("value")
                 or ("yes" if b["v"].get("selected_options") else "") or "").strip()
             for k, b in values.items()}
        errors = {}
        if not re.fullmatch(r"\d{4}", v.get("bank_last4", "")):
            errors["bank_last4"] = "Exactly 4 digits, the last 4 of the account only."
        if not EMAIL.match(v.get("contact_email", "")):
            errors["contact_email"] = "Enter a valid email address."
        if not re.fullmatch(r"[A-Za-z]{2}", v.get("country", "")):
            errors["country"] = "Two letters, e.g. US."
        return {"values": v, "errors": errors}

    def process_form(self, user: str, v: dict, meta: dict) -> None:
        channel = meta["channel"]
        s = self.session(channel)
        c = self.store.get_record(VendorContract, ct.KIND, meta["contract"])
        if c is None:
            return self.tell(channel, user, "That contract no longer exists.")
        email, name = self.person(user)
        c.status, c.accepted_by = "accepted", f"{name} (Slack {user})"
        self.store.put_record(ct.KIND, c.id, c)
        # the Slack user who submits the form becomes the vendor's registered contact once it is approved
        self.store.put_record(APPLICANT_KIND, c.id, VendorUser(slack_user=user, name=name, email=email,
                                                               channel=channel, contract_id=c.id))
        from decimal import Decimal
        from backend.slack.market import _usd
        spend = _usd(c.total, c.currency, load_policy()) or Decimal("0")
        req = OnboardingRequestIn(
            legal_name=v["legal_name"][:160], country=v["country"].upper(), currency=c.currency,
            tax_id=v.get("tax_id") or None, tax_form=None if v.get("tax_form") in ("", "Not yet") else v["tax_form"],
            address=v.get("address", ""), city=v.get("city", ""), state=v.get("state", ""), zip=v.get("zip", ""),
            email_domain=v["contact_email"].rsplit("@", 1)[-1].lower(), website="", bank_last4=v["bank_last4"],
            contact_name=v.get("contact_name", ""), contact_phone=v.get("contact_phone", ""),
            contact_email=v["contact_email"], expected_annual_spend_usd=spend,
            principal_persona=v.get("principal_persona") or None, credit_consent=v.get("credit_consent") == "yes",
            requested_by=(s.owner_email if s else c.requested_by))
        case = start_onboarding(req, c, self.store, self.pay, _now())
        self.announce(case, channel, owner=s.owner if s else None)

    def announce(self, case: OnboardingCase, channel: Optional[str], owner: Optional[str] = None) -> None:
        if not channel:
            return
        r = case.request
        if case.status == "approved":
            self.client.chat_postMessage(channel=channel, text=(
                f":white_check_mark: *{r.legal_name}* is onboarded as `{case.vendor_id}` (90-day probation)"
                + (" by policy: every check passed" if case.auto_approved else f", approved by {case.decided_by}")
                + f". Confirmation email sent to {r.contact_email}."))
            po = po_for_contract(self.store, case.contract_id) if case.contract_id else None
            if po:
                self.announce_po(po, case.contract_id, channel)
        else:
            self.client.chat_postMessage(channel=channel, text=(
                f"Thanks, {r.contact_name or r.legal_name}. Your details are with Helix finance for review; "
                "you'll get an email as soon as you're set up."))
        if owner:
            flags = [f"• {c.name}: *{c.status}*: {c.detail}" for c in case.checks if c.status != "pass"]
            self.tell(channel, owner, (f"*Onboarding {case.id}*: risk *{case.risk_tier}*, status *{case.status}*\n"
                                       + ("\n".join(flags) if flags else "• Every check passed.")
                                       + f"\nReview in the app: {self.app_url}/#vendors"))

    def notify_decided(self, case: OnboardingCase) -> None:
        """A controller decided a Slack onboarding in the app: tell the channel."""
        c = self.store.get_record(VendorContract, ct.KIND, case.contract_id) if case.contract_id else None
        if c:
            self.announce(case, c.channel)

    # --- wiring -----------------------------------------------------------------------------------
    def _routes(self) -> None:
        app = self.app

        @app.command("/reconai")
        def _cmd(ack, command):
            ack()
            verb, _, arg = (command.get("text") or "help").strip().partition(" ")
            log.warning("slack /reconai %s %r from %s in %s", verb, arg[:60], command.get("user_id"), command.get("channel_id"))
            self._safe(self.handle, verb.lower(), arg, command["user_id"], command["channel_id"],
                       command.get("trigger_id"), channel=command["channel_id"], user=command["user_id"])

        @app.command("/recon")
        def _recon(ack, command):
            ack()
            log.warning("slack /recon from %s in %s", command.get("user_id"), command.get("channel_id"))
            self._safe(self.cmd_ask, command.get("text") or "", command["user_id"], command["channel_id"],
                       channel=command["channel_id"], user=command["user_id"])

        @app.event("app_mention")
        def _mention(event):
            text = re.sub(r"<@[^>]+>", "", event.get("text", "")).strip()
            verb, _, arg = text.partition(" ")
            verb = "onboard" if "onboard" in text.lower() else verb.lower()
            self._safe(self.handle, verb, arg, event["user"], event["channel"], None,
                       channel=event["channel"], user=event["user"])

        @app.event("message")
        def _msg(event):
            self._safe(self.on_message, event, channel=event.get("channel"), user=event.get("user"))

        @app.action(re.compile(r"^bill_(approve|approve_release|release|hold)$"))
        def _bill(ack, body):  # Bolt injects by parameter name: read the action id from the body
            ack()
            user, act = body["user"]["id"], body["actions"][0]
            threading.Thread(target=self._safe, args=(self.bill_action, act["action_id"], user, act["value"]),
                             kwargs={"channel": user, "user": user}, daemon=True).start()

        @app.action("receipt_all")
        def _rall(ack, body):
            ack()
            user = body["user"]["id"]
            self._safe(self.receipt_all, user, body["actions"][0]["value"], channel=user, user=user)

        @app.action("receipt_other")
        def _rother(ack, body):
            ack()
            user = body["user"]["id"]
            self._safe(self.open_receipt_form, user, body["actions"][0]["value"], body["trigger_id"],
                       channel=user, user=user)

        @app.view("receipt_qty")
        def _rsubmit(ack, body, view):
            meta = json.loads(view.get("private_metadata") or "{}")
            res = self._safe(self.submit_receipt, body["user"]["id"], view["state"]["values"], meta) or {"errors": {}}
            return ack(response_action="errors", errors=res["errors"]) if res["errors"] else ack()

        @app.view("slack_invoice")
        def _isubmit(ack, body, view):
            meta = json.loads(view.get("private_metadata") or "{}")
            user = body["user"]["id"]
            res = self.submit_invoice(user, view["state"]["values"], meta)
            if res["errors"]:
                return ack(response_action="errors", errors=res["errors"])
            ack()
            threading.Thread(target=self._safe, args=(self.process_invoice, user, res["invoice"], meta),
                             kwargs={"channel": meta.get("channel"), "user": user}, daemon=True).start()

        @app.action("accept_contract")
        def _accept(ack, body):
            ack()
            user, channel = body["user"]["id"], body["channel"]["id"]
            self._safe(self.accept, user, channel, body["actions"][0]["value"], body["trigger_id"],
                       body.get("message", {}).get("ts"), channel=channel, user=user)

        @app.view("onboard_vendor")
        def _submit(ack, body, view):
            meta = json.loads(view.get("private_metadata") or "{}")
            res = self.submit_form(body["user"]["id"], view["state"]["values"], meta)
            if res["errors"]:
                return ack(response_action="errors", errors=res["errors"])
            ack()
            threading.Thread(target=self._safe, args=(self.process_form, body["user"]["id"], res["values"], meta),
                             kwargs={"channel": meta.get("channel"), "user": body["user"]["id"]}, daemon=True).start()

    def _safe(self, fn, *args, channel=None, user=None):
        try:
            return fn(*args)
        except Exception as e:  # never crash the socket; tell the person what failed
            log.exception("slack handler failed")
            if channel and user:
                self.reply(channel, user, f"ReconAI hit an error: {type(e).__name__}: {str(e)[:200]}")


BOT: Optional[ReconBot] = None
_handler = None


def start(store, pay, runner=None) -> Optional[ReconBot]:
    """Connect over Socket Mode in background threads (called from the API lifespan)."""
    global BOT, _handler
    if not configured() or BOT is not None:
        return BOT
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    BOT = ReconBot(store, pay, runner=runner)
    _handler = SocketModeHandler(BOT.app, os.environ["SLACK_APP_TOKEN"])
    _handler.connect()
    log.warning("ReconAI Slack bot connected (Socket Mode) as %s", BOT.bot_user)
    return BOT


def stop() -> None:
    global BOT, _handler
    if _handler is not None:
        try:
            _handler.close()
        except Exception:
            pass
    BOT, _handler = None, None
