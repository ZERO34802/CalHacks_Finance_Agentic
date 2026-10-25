"""ReconAI Slack bot (Socket Mode: no public URL needed). Owner: D.

  /reconai negotiate <vendor>   start coaching in this channel; the person who runs it is the Helix owner
  (chat as usual)               on every new price / terms move, ReconAI privately (ephemeral, owner only) posts
                                the numbers to negotiate with: our PO history, the market, target, walk-away
  /reconai contract             owner only: draft the supply agreement (PDF) from what was agreed
  [Accept & start onboarding]   supplier only: opens the onboarding form; on submit every onboarding check runs and
                                a low-risk vendor is onboarded by policy + confirmation email (else a controller)
  /reconai status | onboard | stop | help
@ReconAI <same verbs> works too (onboarding then posts the button, since a modal needs a click).

Trust: chat text is untrusted. It is only read by Claude calls with no tools (backend/slack/negotiation.py);
web market notes use our own canonical query, never chat text. The channel is told ReconAI is assisting Helix.
Env: SLACK_BOT_TOKEN (xoxb-), SLACK_APP_TOKEN (xapp-, connections:write), RECONAI_SLACK_INTERNAL_USERS (optional
comma list of Slack user ids treated as Helix besides the owner), RECONAI_APP_URL.
"""
from __future__ import annotations

import json
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
from backend.slack.models import Message, Session
from backend.slack.onboard import start as start_onboarding
from contracts import OnboardingCase, OnboardingRequestIn, VendorContract

load_dotenv(ROOT / ".env")
log = logging.getLogger("reconai.slack")
SESSION = "slack_session"
TRIGGER = re.compile(r"\d|net\s*\d|discount|agree|deal|terms|price|quote|accept", re.I)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def configured() -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReconBot:
    def __init__(self, store, pay, client=None):
        """`client`: inject a Slack WebClient stand-in (tests); without one, a real Bolt app is built and routed."""
        self.store, self.pay = store, pay
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
        elif verb == "stop":
            if s and user == s.owner:
                s.active = False
                self.save(s)
                self.client.chat_postMessage(channel=channel, text="ReconAI has stopped assisting in this channel.")
        else:
            self.tell(channel, user, "Commands: `/reconai negotiate <vendor>`, `/reconai status`, "
                                     "`/reconai contract`, `/reconai onboard`, `/reconai stop`.")

    # --- coaching ---------------------------------------------------------------------------------
    def on_message(self, event: dict) -> None:
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
                             "Never type a full account number in Slack. Full details are collected by phone.")]})

    def accept(self, user: str, channel: str, contract_id: str, trigger_id: str, thread: Optional[str] = None) -> None:
        """[Accept & start onboarding]: the supplier accepts, never anyone at Helix."""
        s = self.session(channel)
        if (s and user == s.owner) or user in self.internal:
            return self.tell(channel, user, "The supplier accepts the contract, not Helix: ask them to click it.")
        c = self.store.get_record(VendorContract, ct.KIND, contract_id)
        if c:
            self.open_form(trigger_id, c, channel, thread)

    def submit_form(self, user: str, values: dict, meta: dict) -> dict:
        v = {k: (b["v"].get("value") or (b["v"].get("selected_option") or {}).get("value") or "").strip()
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
        _, name = self.person(user)
        c.status, c.accepted_by = "accepted", f"{name} (Slack {user})"
        self.store.put_record(ct.KIND, c.id, c)
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

        @app.event("app_mention")
        def _mention(event):
            text = re.sub(r"<@[^>]+>", "", event.get("text", "")).strip()
            verb, _, arg = text.partition(" ")
            verb = "onboard" if "onboard" in text.lower() else verb.lower()
            self._safe(self.handle, verb, arg, event["user"], event["channel"], None,
                       channel=event["channel"], user=event["user"])

        @app.event("message")
        def _msg(event):
            self._safe(self.on_message, event, channel=event.get("channel"), user=None)

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
                self.tell(channel, user, f"ReconAI hit an error: {type(e).__name__}: {str(e)[:200]}")


BOT: Optional[ReconBot] = None
_handler = None


def start(store, pay) -> Optional[ReconBot]:
    """Connect over Socket Mode in background threads (called from the API lifespan)."""
    global BOT, _handler
    if not configured() or BOT is not None:
        return BOT
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    BOT = ReconBot(store, pay)
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
