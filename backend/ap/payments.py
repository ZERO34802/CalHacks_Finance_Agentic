"""Payment runs. Owner: D. SIMULATED: nothing leaves the building; "paid" means the run was released.

Controls enforced here, in code:
- only bills the Poster booked to AP can be scheduled, for at most the booked amount (the undisputed part of a
  partial hold); payment runs never post to the ledger
- bank change / look-alike / hidden-instruction escalations need the out-of-band callback first
- the payment guard blocks bills with open high-risk signals (bank mismatch, duplicate, hidden instructions)
- payment always goes to the vendor master's bank account, never the one printed on the invoice
- a bill can't be in two active payments
- whoever prepared a run cannot release it
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import uuid4

from backend.core.config import Policy
from backend.review.checks import payment_block, signals
from backend.store.base import Store
from backend.ap import state as S
from backend.ap.discounts import discount
from contracts import Case, CaseStatus, OnboardingCase, Payment, PaymentBatch, PrepayApplication, Prepayment, PrepaymentQuote

_SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_batches (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prepayments (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS onboarding (id TEXT PRIMARY KEY, body TEXT NOT NULL);
"""


class PaymentError(Exception):
    pass


class PaymentStore:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)

    def save(self, batch: PaymentBatch) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO payment_batches VALUES (?, ?)", (batch.id, batch.model_dump_json()))
            self._db.commit()

    def batches(self) -> list[PaymentBatch]:
        with self._lock:
            rows = self._db.execute("SELECT body FROM payment_batches").fetchall()
        return sorted((PaymentBatch.model_validate_json(r[0]) for r in rows), key=lambda b: b.created_at, reverse=True)

    def get(self, batch_id: str) -> Optional[PaymentBatch]:
        return next((b for b in self.batches() if b.id == batch_id), None)

    def _put(self, table: str, id_: str, body: str) -> None:
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?)", (id_, body))
            self._db.commit()

    def _all(self, table: str) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute(f"SELECT body FROM {table}").fetchall()]

    def save_prepayment(self, p: Prepayment) -> None:
        self._put("prepayments", p.id, p.model_dump_json())

    def prepayments(self, vendor_id: Optional[str] = None) -> list[Prepayment]:
        ps = [Prepayment.model_validate_json(b) for b in self._all("prepayments")]
        return sorted((p for p in ps if vendor_id is None or p.vendor_id == vendor_id), key=lambda p: p.requested_at, reverse=True)

    def credit_available(self, vendor_id: str) -> Decimal:
        return sum((p.remaining for p in self.prepayments(vendor_id) if p.status == "paid"), Decimal("0.00"))

    def save_onboarding(self, c: OnboardingCase) -> None:
        self._put("onboarding", c.id, c.model_dump_json())

    def onboarding(self) -> list[OnboardingCase]:
        return sorted((OnboardingCase.model_validate_json(b) for b in self._all("onboarding")), key=lambda c: c.created_at, reverse=True)

    def payment_for(self, case_id: str) -> Optional[Payment]:
        for b in self.batches():
            for p in b.payments:
                if p.case_id == case_id:
                    return p
        return None


def is_approved(case: Case) -> bool:
    """Booked to AP by the Poster (in full, or the undisputed part of a hold). Only booked bills can be paid."""
    return case.journal_entry is not None


def allowed_methods(country: str) -> list[str]:
    """ACH, domestic wire and check need a US account; everyone else is paid by international wire (SWIFT)."""
    return ["ach", "wire", "check"] if country == "US" else ["intl_wire"]


def method_for(country: str) -> str:
    return allowed_methods(country)[0]


def create_batch(store: Store, pay: PaymentStore, policy: Policy, case_ids: list[str], pay_date: date,
                 created_by: str, now: datetime, methods: Optional[dict[str, str]] = None) -> PaymentBatch:
    if not case_ids:
        raise PaymentError("Pick at least one bill.")
    if pay_date < now.date():
        raise PaymentError("The pay date is in the past.")
    batch_id = f"run_{uuid4().hex[:6]}"
    payments, total = [], Decimal("0.00")
    cases = store.list_cases()
    for cid in case_ids:
        case = store.get_case(cid)
        if case is None or case.invoice is None or not S.is_bill(case, cases):
            raise PaymentError(f"{cid}: no such bill.")
        owed = S.payable(case, cases)
        if owed is None:
            refused = S.poster_refusal(case)
            raise PaymentError(f"{cid}: not approved and booked yet" + (f" ({refused})." if refused else "."))
        if owed <= 0:
            raise PaymentError(f"{cid}: nothing left to pay.")
        vendor = store.get_vendor(case.vendor_id)
        block = payment_block(signals(case, vendor, policy, store)) or S.oob_problem(case) or _probation_block(case, vendor, store)
        if block:
            raise PaymentError(f"{cid}: {block}")
        if pay.payment_for(cid):
            raise PaymentError(f"{cid}: already in a payment run.")
        inv = case.invoice
        country = vendor.country if vendor else "US"
        method = (methods or {}).get(cid) or method_for(country)
        if method not in allowed_methods(country):
            raise PaymentError(f"{cid}: {method} isn't available for a {country} vendor (use {', '.join(allowed_methods(country))}).")
        gross = owed                       # what the Poster booked (undisputed part of a hold), never the invoice total
        d = discount(case, vendor, gross)
        disc = d[0] if d and pay_date <= d[1] else Decimal("0.00")      # early-payment discount, if paid in the window
        credit = min(pay.credit_available(case.vendor_id), gross - disc) if vendor else Decimal("0.00")
        if credit > 0:
            _apply_credit(pay, case.vendor_id, cid, credit, now)
        net = gross - disc - credit
        usd = (net * policy.fx_rates[inv.currency]).quantize(Decimal("0.01"))
        payments.append(Payment(id=f"pay_{uuid4().hex[:6]}", batch_id=batch_id, case_id=cid, vendor_id=case.vendor_id,
                                amount=net, gross_amount=gross, discount_amount=disc, credit_applied=credit,
                                currency=inv.currency, amount_usd=usd,
                                method=method, pay_date=pay_date,
                                pay_to_last4=vendor.bank_last4 if vendor else "????", status="scheduled"))
        total += usd
    batch = PaymentBatch(id=batch_id, pay_date=pay_date, status="scheduled", created_by=created_by, created_at=now,
                         payments=payments, total_usd=total)
    pay.save(batch)
    return batch


def _probation_block(case, vendor, store):
    from backend.ap.views import _probation_block as pb  # one definition (views imports this module)
    return pb(case, vendor, store)


def release(pay: PaymentStore, batch_id: str, released_by: str, now: datetime,
            store: Optional[Store] = None, policy: Optional[Policy] = None) -> PaymentBatch:
    batch = pay.get(batch_id)
    if batch is None:
        raise PaymentError("No such payment run.")
    if batch.status != "scheduled":
        raise PaymentError("This run was already released.")
    if released_by == batch.created_by:
        raise PaymentError(f"{released_by} prepared this run and cannot also release it.")
    if store is not None and policy is not None:  # re-check at release: nothing changed since it was scheduled
        cases = store.list_cases()
        for p in batch.payments:
            case = store.get_case(p.case_id)
            owed = S.payable(case, cases) if case else None
            if owed is None or (p.gross_amount if p.gross_amount is not None else p.amount) > owed:
                raise PaymentError(f"{p.case_id}: the booked amount changed since this run was scheduled "
                                   f"({owed if owed is not None else 'nothing'} booked); reschedule it.")
            vendor = store.get_vendor(case.vendor_id)
            block = payment_block(signals(case, vendor, policy, store)) or S.oob_problem(case)
            if block:
                raise PaymentError(f"{p.case_id}: {block}")
    batch.status, batch.released_by, batch.released_at = "paid", released_by, now
    for p in batch.payments:
        p.status = "paid"
    pay.save(batch)
    return batch


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── advance payments ──────────────────────────────────────────────────────────────────────────────

def _apply_credit(pay: PaymentStore, vendor_id: str, case_id: str, amount: Decimal, now: datetime) -> None:
    """Draw down open prepaid credit, oldest first."""
    left = amount
    for p in sorted(pay.prepayments(vendor_id), key=lambda p: p.approved_at or p.requested_at):
        if left <= 0 or p.status != "paid" or p.remaining <= 0:
            continue
        take = min(p.remaining, left)
        p.remaining -= take
        p.applied.append(PrepayApplication(case_id=case_id, amount=take, at=now))
        pay.save_prepayment(p)
        left -= take


def quote(store: Store, pay: PaymentStore, policy: Policy, vendor_id: str, credit_amount: Decimal) -> PrepaymentQuote:
    v = store.get_vendor(vendor_id)
    if v is None:
        raise PaymentError("No such vendor.")
    t = v.terms
    pct = t.prepay_discount_pct if t and t.prepay_discount_pct else Decimal("0")
    cash = (credit_amount * (1 - pct)).quantize(Decimal("0.01"))
    cash_usd = (cash * policy.fx_rates[v.currency]).quantize(Decimal("0.01"))
    open_usd = sum(((p.remaining * policy.fx_rates[p.currency]) for p in pay.prepayments(vendor_id) if p.status in ("paid", "requested")),
                   Decimal("0")).quantize(Decimal("0.01"))
    cap_left = (t.prepay_cap_usd - open_usd) if t and t.prepay_cap_usd is not None else None
    reason = ""
    if not pct:
        reason = "This vendor's contract doesn't offer an advance-payment discount."
    elif v.on_probation:
        reason = "Vendors on probation can't be prepaid."
    elif credit_amount <= 0:
        reason = "Enter an amount."
    elif cap_left is not None and cash_usd > cap_left:
        reason = f"Over the prepayment cap: USD {max(cap_left, Decimal('0')):,.2f} left of USD {t.prepay_cap_usd:,.2f}."
    return PrepaymentQuote(vendor_id=vendor_id, currency=v.currency, credit_amount=credit_amount, cash_amount=cash,
                           discount_amount=credit_amount - cash, discount_pct=pct, cash_usd=cash_usd, cap_remaining_usd=cap_left,
                           allowed=not reason, reason=reason)


def request_prepayment(store: Store, pay: PaymentStore, policy: Policy, vendor_id: str, credit_amount: Decimal,
                       requested_by: str, note: str, now: datetime) -> Prepayment:
    q = quote(store, pay, policy, vendor_id, credit_amount)
    if not q.allowed:
        raise PaymentError(q.reason)
    v = store.get_vendor(vendor_id)
    p = Prepayment(id=f"pre_{uuid4().hex[:6]}", vendor_id=vendor_id, vendor_name=v.name, currency=v.currency,
                   credit_amount=q.credit_amount, cash_amount=q.cash_amount, discount_amount=q.discount_amount,
                   discount_pct=q.discount_pct, cash_usd=q.cash_usd, status="requested", requested_by=requested_by,
                   requested_at=now, note=note, remaining=q.credit_amount)
    pay.save_prepayment(p)
    return p


def decide_prepayment(pay: PaymentStore, prepay_id: str, approver: str, role: str, decision: str, now: datetime) -> Prepayment:
    """Prepayments skip the 3-way match, so they always need a controller (or CFO) who isn't the requester."""
    p = next((x for x in pay.prepayments() if x.id == prepay_id), None)
    if p is None:
        raise PaymentError("No such prepayment.")
    if p.status != "requested":
        raise PaymentError("Already decided.")
    if decision == "approved":
        if approver == p.requested_by:
            raise PaymentError(f"{approver} requested this prepayment and cannot approve it.")
        if role not in ("controller", "cfo"):
            raise PaymentError("Advance payments need a controller or CFO.")
    p.status = "paid" if decision == "approved" else "rejected"
    p.approved_by, p.approved_at = approver, now
    if p.status == "rejected":
        p.remaining = Decimal("0.00")
    pay.save_prepayment(p)
    return p
