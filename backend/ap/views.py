"""AP workspace read models: bills, bill detail, reports, settings. Owner: D. All money in Decimal, USD at the
simulated policy FX table."""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from backend.ap.discounts import offer
from backend.ap.payments import PaymentStore, allowed_methods, is_approved, method_for
from backend.core.config import Policy
from backend.review.checks import (check_results, gl_lines, match_rows, paid_history, payment_block, risk, signals,
                                   verdict, verdict_text)
from backend.review.packet import needs
from backend.store.base import Store
from contracts import (ActivityItem, AgingBucket, ApprovalStep, ApReport, ApSettings, Bill, BillDetail, Case, CaseStatus,
                       Decision, ForecastWeek, Integration, LastPaid, SpendRow, Vendor)

SLA_HOURS = 24
ZERO = Decimal("0.00")
AUTO = "stub auto-approve"   # the pipeline's own approval (B's Approver stub)


def _usd(case: Case, policy: Policy) -> Optional[Decimal]:
    inv = case.invoice
    return None if inv is None else (inv.total * policy.fx_rates[inv.currency]).quantize(Decimal("0.01"))


def _handed_over_at(store: Store, case: Case) -> Optional[datetime]:
    step = next((s for s in store.list_steps(case.id) if s.stage == "approver"), None)
    return step.ended_at if step else None


def human_decision(case: Case):
    return next((a for a in reversed(case.approvals) if a.comment != AUTO), None)


def bill(store: Store, pay: PaymentStore, policy: Policy, case: Case, vendor: Optional[Vendor], now: datetime) -> Bill:
    inv = case.invoice
    sig = signals(case, vendor, policy)
    payment = pay.payment_for(case.id)
    block = payment_block(sig) if is_approved(case) else None
    human = human_decision(case)
    if case.decision is None:
        stage = "processing"
    elif case.status == CaseStatus.rejected:
        stage = "rejected"
    elif payment:
        stage = payment.status
    elif is_approved(case):
        stage = "blocked" if block else "ready_to_pay"
    elif human and human.decision.value == "ask":
        stage = "on_hold"
    else:
        stage = "needs_review"
    approved = next((a for a in reversed(case.approvals) if a.decision.value == "approved"), None)
    waiting = None
    breached = False
    if stage in ("needs_review", "on_hold"):
        t0 = _handed_over_at(store, case)
        if t0:
            waiting = round((now - t0).total_seconds() / 3600, 1)
            breached = waiting > SLA_HOURS
    at_risk = sum((r.amount_at_risk for r in match_rows(case)), ZERO)
    high = next((s for s in sig if s.severity == "high"), None)
    if high and high.code == "duplicate":
        warning = f"This bill may be a duplicate of {high.title.split(' of ')[-1]}. Make sure you're not paying twice."
    elif sum(s.severity == "high" for s in sig) > 1:
        warning = "Higher risk of fraud based on multiple signals: " + "; ".join(s.title.lower() for s in sig if s.severity == "high") + "."
    elif high:
        warning = high.title + "."
    elif at_risk > 0 and inv:
        warning = f"ReconAI identified {inv.currency} {at_risk:,.2f} overbilling against the PO and receipt."
    else:
        warning = None
    return Bill(case_id=case.id, vendor_id=case.vendor_id, vendor_name=vendor.name if vendor else case.vendor_id,
                invoice_no=inv.invoice_no if inv else None, invoice_date=inv.invoice_date if inv else None,
                due_date=inv.due_date if inv else None,
                days_to_due=(inv.due_date - now.date()).days if inv and inv.due_date else None,
                amount=inv.total if inv else None, currency=inv.currency if inv else None, amount_usd=_usd(case, policy),
                stage=stage, recommendation=case.decision,
                approved_by=(("ReconAI agents" if approved.comment == AUTO else approved.approver) if approved else None),
                needs=needs(case, policy) if stage == "needs_review" or stage == "on_hold" else "nobody",
                risk=risk(sig), signals=sig, waiting_hours=waiting, sla_breached=breached, payment_block=block,
                payment=payment, overbilled=at_risk if at_risk > 0 else None, warning=warning,
                discount=offer(case, vendor, policy, now.date(), stage, block, payment),
                credit_available=(pay.credit_available(case.vendor_id) or None) if vendor else None)


def bills(store: Store, pay: PaymentStore, policy: Policy, now: datetime) -> list[Bill]:
    vendors = {v.id: v for v in store.list_vendors()}
    out = [bill(store, pay, policy, c, vendors.get(c.vendor_id), now) for c in store.list_cases()]
    return sorted(out, key=lambda b: (b.due_date or date.max, b.case_id))


def detail(store: Store, pay: PaymentStore, policy: Policy, case: Case, now: datetime) -> BillDetail:
    vendor = store.get_vendor(case.vendor_id)
    b = bill(store, pay, policy, case, vendor, now)
    acts: list[ActivityItem] = []
    inv_doc = next((d for d in case.documents if case.invoice and d.id == case.invoice.doc_id), None)
    acts.append(ActivityItem(at=case.created_at, actor=inv_doc.sender if inv_doc and inv_doc.sender else "intake",
                             text=f"Invoice received via {inv_doc.channel.value if inv_doc else 'upload'}"))
    steps = [s for s in store.list_steps(case.id) if s.parent_id is None]
    if steps:
        acts.append(ActivityItem(at=steps[0].started_at, actor="ReconAI", text=f"Agents started ({len(steps)} steps)"))
        last = steps[-1]
        rec = {Decision.approve: "clear it", Decision.hold: "hold it", Decision.reject: "reject it",
               Decision.escalate: "send it to a human"}.get(case.decision, "—")
        acts.append(ActivityItem(at=last.ended_at or last.started_at, actor="ReconAI", text=f"Agents finished: recommend {rec}"))
    for a in case.approvals:
        who = "ReconAI Approver" if a.comment == AUTO else f"{a.approver} ({a.role.value})"
        verb = {"approved": "Approved", "rejected": "Rejected", "ask": "Put on hold"}[a.decision.value]
        acts.append(ActivityItem(at=a.at, actor=who, text=verb + (f": “{a.comment}”" if a.comment and a.comment != AUTO else "")))
    if case.journal_entry:
        acts.append(ActivityItem(at=case.updated_at or case.created_at, actor="Poster", text="Booked to the ledger (Beancount)"))
    for bt in pay.batches():
        for p in bt.payments:
            if p.case_id == case.id:
                acts.append(ActivityItem(at=bt.created_at, actor=bt.created_by,
                                         text=f"Scheduled in {bt.id} for {p.pay_date} by {p.method.upper()} to •••• {p.pay_to_last4}"))
                if bt.released_at:
                    acts.append(ActivityItem(at=bt.released_at, actor=bt.released_by or "—", text="Payment released (simulated)"))
    acts.sort(key=lambda x: x.at)
    results = check_results(case, vendor, policy)
    country = vendor.country if vendor else "US"
    paid = [p for p in paid_history() if p["vendor_id"] == case.vendor_id]
    paid += [{"invoice_no": cases_inv(store, p.case_id), "total": str(p.amount), "currency": p.currency, "paid_on": str(bt.released_at.date())}
             for bt in pay.batches() if bt.released_at for p in bt.payments if p.vendor_id == case.vendor_id and p.case_id != case.id]
    last = max(paid, key=lambda p: p["paid_on"]) if paid else None
    inv = case.invoice
    if b.payment:
        est = b.payment.pay_date
    elif inv and inv.due_date:
        est = max(now.date(), inv.due_date - timedelta(days=2))
    else:
        est = None
    return BillDetail(bill=b, verdict=verdict(results), verdict_text=verdict_text(case, vendor), checks=results,
                      match=match_rows(case), gl=gl_lines(case, policy), approval_steps=approval_steps(store, pay, policy, case, b),
                      activity=acts, est_pay_date=est,
                      last_paid=LastPaid(invoice_no=last["invoice_no"], amount=Decimal(last["total"]), currency=last["currency"],
                                         paid_on=date.fromisoformat(last["paid_on"])) if last else None,
                      pay_methods=allowed_methods(country), default_method=method_for(country),
                      statement_descriptor=f"HELIX SILICON PAYING {inv.invoice_no if inv else case.id} VIA RECONAI",
                      invoice_bank_last4=inv.bank_last4 if inv else None)


def cases_inv(store: Store, case_id: str) -> str:
    c = store.get_case(case_id)
    return c.invoice.invoice_no if c and c.invoice else case_id


ROLE_TITLE = {"approver": "AP lead", "controller": "Controller", "cfo": "CFO"}


def approval_steps(store: Store, pay: PaymentStore, policy: Policy, case: Case, b: Bill) -> list[ApprovalStep]:
    """The approval chain: agents prepare -> the role whose limit covers the amount approves -> someone else releases."""
    steps = [s for s in store.list_steps(case.id) if s.parent_id is None]
    out = [ApprovalStep(step=1, label="Prepared by ReconAI", who="Reader, Matcher, Vendor Guard and 7 more",
                        status="done" if case.decision else "waiting",
                        note=f"{len(steps)} steps in the background" if steps else "")]
    amount = b.amount_usd
    role = needs_role(case, policy)
    limit = policy.approval_limits.get(role)
    requester = case.po.requester if case.po else None
    human = human_decision(case)
    approved = next((a for a in reversed(case.approvals) if a.decision.value == "approved"), None)
    if case.status == CaseStatus.rejected:
        status, who = "rejected", f"Rejected by {human.approver if human else 'ReconAI'}"
    elif approved:
        status = "done"
        who = "ReconAI Approver (within the AP lead's limit)" if approved.comment == AUTO else f"Approved by {approved.approver}"
    elif human and human.decision.value == "ask":
        status, who = "on_hold", f"On hold by {human.approver}"
    else:
        status, who = ("waiting" if case.decision else "pending"), f"Any {ROLE_TITLE.get(role, role)}"
    note = (f"{ROLE_TITLE.get(role, role)} approves up to USD {limit:,.0f}" if limit is not None else "") +            (f" · {requester} removed due to separation of duties" if requester else "")
    out.append(ApprovalStep(step=2, label=f"{ROLE_TITLE.get(role, role)} approval", who=who, status=status, note=note))
    p = b.payment
    batch = pay.get(p.batch_id) if p else None
    if batch and batch.released_by:
        rel = ApprovalStep(step=3, label="Release payment", who=f"Released by {batch.released_by}", status="done", note="simulated")
    elif batch:
        rel = ApprovalStep(step=3, label="Release payment", who=f"Anyone except {batch.created_by}", status="waiting",
                           note=f"scheduled in {batch.id} for {batch.pay_date}")
    else:
        rel = ApprovalStep(step=3, label="Release payment", who="Someone other than who schedules it", status="pending",
                           note=b.payment_block or "")
    out.append(rel)
    return out


def needs_role(case: Case, policy: Policy) -> str:
    """Role whose approval limit covers this amount (even once approved), for the approval chain."""
    amount = _usd(case, policy)
    if amount is None:
        return "approver"
    for role, limit in sorted(policy.approval_limits.items(), key=lambda kv: kv[1]):
        if amount <= limit:
            return role
    return "cfo"


def report(store: Store, pay: PaymentStore, policy: Policy, now: datetime) -> ApReport:
    bs = bills(store, pay, policy, now)
    cases = {c.id: c for c in store.list_cases()}
    open_bs = [b for b in bs if b.stage not in ("paid", "rejected", "processing") and b.amount_usd is not None]
    usd = lambda xs: sum((b.amount_usd for b in xs), ZERO)  # noqa: E731

    buckets = [("Not due", lambda d: d >= 0), ("1–30 days late", lambda d: -30 <= d < 0),
               ("31–60", lambda d: -60 <= d < -30), ("61–90", lambda d: -90 <= d < -60), ("90+", lambda d: d < -90)]
    aging = []
    for label, test in buckets:
        xs = [b for b in open_bs if b.days_to_due is not None and test(b.days_to_due)]
        aging.append(AgingBucket(label=label, amount_usd=usd(xs), count=len(xs)))

    monday = now.date() - timedelta(days=now.date().weekday())
    forecast = []
    for w in range(6):
        start, end = monday + timedelta(weeks=w), monday + timedelta(weeks=w + 1)
        xs = [b for b in open_bs if b.due_date and (start <= b.due_date < end or (w == 0 and b.due_date < start))]
        forecast.append(ForecastWeek(week_start=start,
                                     approved_usd=usd([b for b in xs if b.stage in ("ready_to_pay", "scheduled")]),
                                     pending_usd=usd([b for b in xs if b.stage not in ("ready_to_pay", "scheduled")])))

    by_vendor: dict[str, list[Bill]] = defaultdict(list)
    for b in bs:
        if b.amount_usd is not None and b.stage != "rejected":
            by_vendor[b.vendor_name].append(b)
    by_gl: dict[str, list[Decimal]] = defaultdict(list)
    for b in bs:
        c = cases[b.case_id]
        if b.stage == "rejected" or c.invoice is None:
            continue
        for g in gl_lines(c, policy):
            by_gl[g.account].append((g.amount * policy.fx_rates[c.invoice.currency]).quantize(Decimal("0.01")))

    decided = [b for b in bs if b.recommendation is not None]
    touchless = [b for b in decided if cases[b.case_id].status == CaseStatus.posted and not human_decision(cases[b.case_id])]
    caught = [b for b in bs if b.stage in ("rejected", "blocked", "on_hold") or b.risk == "high"]
    offers = [b.discount for b in bs if b.discount]
    by = lambda st: sum((o.discount_usd for o in offers if o.status in st), ZERO)  # noqa: E731
    return ApReport(
        discounts_available_usd=by(("available", "needs_approval")), discounts_captured_usd=by(("captured",)),
        discounts_missed_usd=by(("missed",)),
        open_usd=usd(open_bs), due_7d_usd=usd([b for b in open_bs if b.days_to_due is not None and 0 <= b.days_to_due <= 7]),
        overdue_usd=usd([b for b in open_bs if b.days_to_due is not None and b.days_to_due < 0]),
        needs_review=sum(b.stage == "needs_review" for b in bs), blocked=sum(b.stage == "blocked" for b in bs),
        touchless_rate=round(len(touchless) / len(decided), 4) if decided else None,
        caught_usd=usd(caught), aging=aging, forecast=forecast,
        by_vendor=sorted((SpendRow(label=k, amount_usd=usd(v), count=len(v)) for k, v in by_vendor.items()), key=lambda r: -r.amount_usd),
        by_gl=sorted((SpendRow(label=k, amount_usd=sum(v, ZERO), count=len(v)) for k, v in by_gl.items()), key=lambda r: -r.amount_usd),
    )


def settings(policy: Policy) -> ApSettings:
    return ApSettings(
        approval_limits=policy.approval_limits, sla_hours=SLA_HOURS,
        materiality_abs=policy.materiality.abs, materiality_pct=policy.materiality.pct,
        qty_tolerance_pct=policy.tolerances.qty_pct, price_tolerance_pct=policy.tolerances.price_pct,
        locked_periods=policy.locked_periods, fx_rates=policy.fx_rates, accounts=policy.accounts.model_dump(),
        integrations=[
            Integration(name="Beancount ledger", status="connected", note="Double-entry ledger in ledger/; Fava as viewer"),
            Integration(name="AP inbox (email)", status="simulated", note="Invoices arrive via POST /intake; .eml folder in production"),
            Integration(name="SFTP / S3 drops", status="simulated", note="Watched folders, labelled simulated"),
            Integration(name="Bank payments (ACH / wire)", status="simulated", note="Payment runs are recorded, nothing is sent"),
            Integration(name="ERP (NetSuite / QuickBooks / Xero)", status="not_connected", note="Path to production: swap Beancount for the ERP API"),
            Integration(name="CRS Credit API (business credit, public records, OFAC)",
                        status="connected" if os.environ.get("CRS_BASE_URL") else "simulated",
                        note="Vendor onboarding checks. Set CRS_BASE_URL / CRS_USERNAME / CRS_PASSWORD for the live API; "
                             "otherwise a labelled sandbox with fictional businesses"),
        ])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
