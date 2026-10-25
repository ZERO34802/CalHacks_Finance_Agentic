"""Human AP actions, shared by the API (backend/api/app.py) and Slack (backend/slack/bot.py). Owner: D.

approve_bill        a person's decision on a bill (approve / reject / ask). Controls in code: requester can't approve,
                    approval within the role's limit, out-of-band callback first for bank-change / look-alike /
                    hidden-instruction escalations. Approved -> the pipeline resumes at the Poster, which books AP.
approve_and_release approve (if no human has yet) -> a payment run for today -> release on a rail. The release rule
                    (tiered maker-checker, backend/ap/payments.py) decides whether this person may release.
Errors are ActionError(status_code, detail): the API maps them 1:1 to HTTP errors, Slack shows the detail.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from backend.ap import state as ap_state
from backend.ap.payments import (PaymentError, PaymentForbidden, PaymentStore, create_batch, release,
                                 release_roles)
from backend.core.config import load_policy
from backend.core.runner import make_ctx, run_case
from backend.core.stage import utcnow
from backend.notify import email as mail
from backend.pipeline.lib.split import INFO, split
from backend.review.packet import signoff_problem
from backend.store.base import Store
from contracts import Approval, Case, CaseStatus, Decision, Event, PaymentBatch, Role

Broadcast = Optional[Callable[[Event], None]]


class ActionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def deliver(store: Store, case: Case) -> None:
    """Send the supplier emails the agents drafted (once each; kept in the outbox either way)."""
    try:
        mail.deliver_case(store, case)
    except Exception as e:  # email trouble never blocks the AP flow
        print(f"email delivery failed for {case.id}: {e}")


def _value(x) -> str:
    return x.value if hasattr(x, "value") else str(x)


def approve_bill(store: Store, case_id: str, approver: str, role, decision, comment: str = "",
                 scope: Optional[str] = None, broadcast: Broadcast = None) -> Case:
    case = store.get_case(case_id)
    if case is None:
        raise ActionError(404, f"case {case_id} not found")
    cases = store.list_cases()
    if not ap_state.is_bill(case, cases):
        target = ap_state.attachment_target(case, cases)
        raise ActionError(409, f"{case_id} is not a bill" + (f"; decide on {target}" if target else ""))
    policy = load_policy()
    role, decision = Role(_value(role)), _value(decision)
    if decision not in ("approved", "rejected", "ask"):
        raise ActionError(400, "decision must be approved, rejected or ask")
    disputed = [d for d in case.discrepancies if d.material and d.type not in INFO]
    scope = scope or ("undisputed" if case.decision == Decision.hold and split(case)["separable"] else "full")
    if scope not in ("full", "undisputed"):
        raise ActionError(400, "scope must be full or undisputed")
    problem = signoff_problem(case, approver, role.value, decision, policy)
    if problem:
        raise ActionError(403, problem)
    if decision == "approved":
        if case.invoice is None:
            raise ActionError(409, "Nothing to approve: no invoice was read from what arrived. Ask the vendor to resend.")
        if case.status == CaseStatus.posted or (case.journal_entry and not ap_state.partial(case)):
            raise ActionError(409, "Already approved and booked.")
        if case.journal_entry and ap_state.partial(case):
            raise ActionError(409, "The undisputed part is already approved and booked; the held part settles "
                                   "through a credit note or a corrected invoice.")
        if case.decision == Decision.reject:
            raise ActionError(409, "The agents rejected this bill (e.g. a duplicate). It can't be approved for payment.")
        if case.decision == Decision.hold and scope == "full" and disputed:
            raise ActionError(409, "On a hold only the undisputed part can be approved; the disputed part stays held.")
        if scope == "undisputed" and not split(case)["separable"]:
            raise ActionError(409, "The disputed part of this hold isn't separable (e.g. a currency or total "
                                   "mismatch): ask for a corrected invoice.")
    case.approvals.append(Approval(id=f"{ap_state.HUMAN_PREFIX}{case_id}_{len(case.approvals)}", case_id=case_id,
                                   approver=approver, role=role, decision=decision,
                                   scope=scope if decision == "approved" else None,
                                   comment=comment, limit=policy.approval_limits.get(role.value), at=utcnow()))
    case.pending_approval = None
    if decision == "rejected":
        case.status, case.decision = CaseStatus.rejected, Decision.reject
    elif decision == "ask":
        case.notes.append(f"On hold by {approver}: {comment}".rstrip(": "))
    case.updated_at = utcnow()
    store.save_case(case)
    if decision == "approved":
        if scope == "full":
            case.decision, case.status = Decision.approve, CaseStatus.approved
        elif case.status in (CaseStatus.paused, CaseStatus.resolved):
            case.status = CaseStatus.awaiting_approval  # the runner stops at these; the gate re-checks the kill switch
        ctx = make_ctx(store)
        if broadcast:
            ctx.trace.subscribe(broadcast)
        case = run_case(case, ctx, start_at="poster")
        deliver(store, case)
    if broadcast:
        broadcast(Event(type="case.updated", case_id=case.id, status=case.status, at=utcnow()))
    return case


def human_approved(case: Case) -> bool:
    """Booked to AP (approved by a person, or by the simulated reviewers when human sign-off is off)."""
    return case.journal_entry is not None


def approve_and_release(store: Store, payments: PaymentStore, case_id: str, person_email: str, role,
                        rail: str = "coinbase", broadcast: Broadcast = None,
                        now: Optional[datetime] = None) -> PaymentBatch:
    """One click for a controller / CFO / CTO: approve (if no one has yet), schedule today, release on `rail`.
    Also the [Release] button after an AP lead approved: then only the release runs (by this higher tier)."""
    role = _value(role)
    policy = load_policy()
    now = now or datetime.now(timezone.utc)
    if role not in release_roles(policy):  # before anything is recorded: an AP lead's click changes nothing here
        raise ActionError(403, f"{person_email} ({role}) can't release payments: AP leads approve bills, release "
                               f"needs {' / '.join(release_roles(policy))}.")
    case = store.get_case(case_id)
    if case is None:
        raise ActionError(404, f"case {case_id} not found")
    existing = payments.payment_for(case_id)
    batch = payments.get(existing.batch_id) if existing else None
    if batch is not None and batch.status == "paid":
        raise ActionError(409, f"Already paid ({batch.id}, released by {batch.released_by}).")
    if batch is None and not human_approved(case):
        case = approve_bill(store, case_id, person_email, role, "approved", "Approved in Slack", broadcast=broadcast)
        if case.journal_entry is None:
            raise ActionError(409, f"Approved, but not booked: {ap_state.poster_refusal(case) or case.status.value}.")
    try:
        if rail == "coinbase":
            _ensure_wallet(store, case.vendor_id)
        if batch is None:
            batch = create_batch(store, payments, policy, [case_id], now.astimezone().date(), person_email, now)
        batch = release(payments, batch.id, person_email, now, store, policy, rail=rail, role=role)
    except PaymentForbidden as e:
        raise ActionError(403, str(e))
    except PaymentError as e:
        raise ActionError(400, str(e))
    if broadcast:
        for p in batch.payments:
            broadcast(Event(type="case.updated", case_id=p.case_id, at=utcnow()))
    return batch


def _ensure_wallet(store: Store, vendor_id: str) -> None:
    """Demo setup, same as POST /ap/coinbase/vendor-wallets: a vendor without a payout wallet gets one created by
    our own rail and recorded in the vendor master (never an address from an invoice or a chat)."""
    from backend.ap import coinbase
    v = store.get_vendor(vendor_id)
    rail = coinbase.get_rail()
    if v is None or v.wallet_address or rail is None:
        return
    try:
        v.wallet_address = rail.create_wallet(coinbase.wallet_name(v))
    except coinbase.RailError as e:
        raise PaymentError(str(e))
    store.save_vendor(v)
