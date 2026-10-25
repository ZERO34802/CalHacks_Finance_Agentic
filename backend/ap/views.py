"""AP workspace read models: bills, bill detail, reports, settings. Owner: D. All money in Decimal, USD at the
simulated policy FX table.

Bills are the pipeline's parent cases (see backend/ap/state.py). Sub-cases, supplier replies, credit notes and
corrected invoices that add nothing to pay show up in their bill's activity, not as bills of their own. What a
bill may pay is what the Poster booked (`payable`), never more.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from backend.ap import state as S
from backend.ap.discounts import offer
from backend.ap.payments import PaymentStore, allowed_methods, method_for
from backend.core.config import Policy
from backend.review.checks import (check_results, disagreements, gl_lines, match_rows, paid_history, payment_block, risk,
                                   signals, verdict, verdict_text)
from backend.store.base import Store
from contracts import (ActivityItem, AgingBucket, ApprovalStep, ApReport, ApSettings, Bill, BillDetail, Case, CaseStatus,
                       Decision, ForecastWeek, Integration, LastPaid, SpendRow, Vendor)

SLA_HOURS = 24
ZERO = Decimal("0.00")
CENT = Decimal("0.01")
ROLE_TITLE = {"approver": "AP lead", "controller": "Controller", "cfo": "CFO", "cto": "CTO"}


def _fx(amount: Optional[Decimal], currency: Optional[str], policy: Policy) -> Optional[Decimal]:
    if amount is None or currency is None or currency not in policy.fx_rates:
        return None
    return (amount * policy.fx_rates[currency]).quantize(CENT)


def _usd(case: Case, policy: Policy) -> Optional[Decimal]:
    inv = case.invoice
    return None if inv is None else _fx(inv.total, inv.currency, policy)


def _handed_over_at(store: Store, case: Case) -> Optional[datetime]:
    if case.pending_approval:
        return case.pending_approval.requested_at
    step = next((s for s in reversed(store.list_steps(case.id)) if s.stage in ("approver", "gate")), None)
    return (step.ended_at or step.started_at) if step else (case.updated_at or case.created_at)


def needs_role(case: Case, policy: Policy) -> str:
    """Role whose approval limit covers this amount, for the approval chain."""
    amount = _usd(case, policy)
    if amount is None:
        return "approver"
    for role, limit in sorted(policy.approval_limits.items(), key=lambda kv: kv[1]):
        if amount <= limit:
            return role
    return "cfo"


def _stage(case: Case, payable: Optional[Decimal], payment, human, block: Optional[str]) -> str:
    if case.status == CaseStatus.quarantined:
        return "needs_review"
    if case.decision is None and case.status != CaseStatus.paused:
        return "processing"
    if payment:
        return payment.status
    if payable is not None:
        if payable <= 0:
            return "paid"
        return "blocked" if block else "ready_to_pay"
    if case.status == CaseStatus.rejected or case.decision == Decision.reject:
        return "rejected"
    if case.status in (CaseStatus.approved, CaseStatus.posted):
        return "blocked"  # approved but the Poster did not book it
    if case.status == CaseStatus.paused or (human and human.decision.value == "ask"):
        return "on_hold"
    return "needs_review"


def bill(store: Store, pay: PaymentStore, policy: Policy, case: Case, vendor: Optional[Vendor], now: datetime,
         cases: Optional[list[Case]] = None) -> Bill:
    cases = cases if cases is not None else store.list_cases()
    inv = case.invoice
    sig = signals(case, vendor, policy, store)
    payment = pay.payment_for(case.id)
    human = S.human_decision(case)
    payable = S.payable(case, cases)
    oob = S.oob_problem(case)
    block = None
    if payable is not None and payable > 0:
        block = payment_block(sig) or oob or _probation_block(case, vendor, store)
    elif case.status in (CaseStatus.approved, CaseStatus.posted) and case.journal_entry is None:
        refused = S.poster_refusal(case)
        block = f"Approved but not booked: {refused}" if refused else "Approved but not booked to the ledger yet."
    stage = _stage(case, payable, payment, human, block)
    approved = S.last_approved(case)
    waiting, breached = None, False
    if stage in ("needs_review", "on_hold"):
        t0 = _handed_over_at(store, case)
        if t0:
            waiting = round((now - t0).total_seconds() / 3600, 1)
            breached = waiting > SLA_HOURS
    rows = match_rows(case, store)
    # overbilling only where a second-line 3-way-match check fired (below materiality is logged, not flagged)
    at_risk = sum((r.amount_at_risk for r in rows), ZERO) if any(
        s.code in ("qty_short", "price_over", "not_on_po") for s in sig) else ZERO
    dis = disagreements(case, sig)
    high = next((s for s in sig if s.severity == "high"), None)
    if case.status == CaseStatus.quarantined:
        warning = f"Quarantined at intake: {case.quarantine_reason or 'failed validation'}. Nothing was read or booked."
    elif inv is None and case.decision is not None:
        warning = ("The invoice couldn't be read (evidence missing or the Reader was unavailable). "
                   "Open the documents and decide, or ask the vendor to resend.")
    elif case.status == CaseStatus.paused:
        warning = next((n for n in reversed(case.notes) if "kill switch" in n or "handed off" in n), "Paused.")
    elif dis and dis[0].startswith("Second-line"):
        warning = dis[0]
    elif high and high.code == "duplicate":
        warning = f"This bill may be a duplicate of {high.title.split(' of ')[-1]}. Make sure you're not paying twice."
    elif sum(s.severity == "high" for s in sig) > 1:
        warning = "Higher risk of fraud based on multiple signals: " + "; ".join(s.title.lower() for s in sig if s.severity == "high") + "."
    elif high:
        warning = high.title + "."
    elif S.partial(case) and inv and payable is not None:
        warning = (f"Paying the undisputed {inv.currency} {payable:,.2f}; {inv.currency} "
                   f"{(case.disputed_amount or ZERO):,.2f} stays held until the vendor credits or corrects it.")
    elif block and stage == "blocked":
        warning = block
    elif at_risk > 0 and inv:
        warning = f"ReconAI identified {inv.currency} {at_risk:,.2f} overbilling against the PO and receipt."
    elif dis:
        warning = dis[0]
    elif any(s.severity == "medium" for s in sig):
        warning = next(s for s in sig if s.severity == "medium").title + "."
    else:
        warning = None
    open_stage = stage in ("needs_review", "on_hold")
    cur = inv.currency if inv else None
    return Bill(case_id=case.id, vendor_id=case.vendor_id, vendor_name=vendor.name if vendor else case.vendor_id,
                invoice_no=inv.invoice_no if inv else None, invoice_date=inv.invoice_date if inv else None,
                due_date=_due(case, vendor),
                days_to_due=(_due(case, vendor) - now.date()).days if _due(case, vendor) else None,
                amount=inv.total if inv else None, currency=cur, amount_usd=_usd(case, policy),
                stage=stage, recommendation=case.decision,
                approved_by=(("ReconAI agents (simulated " + approved.role.value + ")") if S.is_agent_approval(approved)
                             else approved.approver) if approved else None,
                needs=needs_role(case, policy) if open_stage else "nobody",
                risk=risk(sig), signals=sig, waiting_hours=waiting, sla_breached=breached, payment_block=block,
                payment=payment, overbilled=at_risk if at_risk > 0 else None, warning=warning,
                discount=offer(case, vendor, policy, now.date(), stage, block or payment_block(sig) or oob, payment,
                               base=payable) if inv else None,
                credit_available=(pay.credit_available(case.vendor_id) or None) if vendor else None,
                payable=payable, payable_usd=_fx(payable, cur, policy),
                disputed=case.disputed_amount if case.decision == Decision.hold else None,
                case_status=case.status, disagreements=dis, sub_case_ids=case.sub_case_ids,
                po_number=inv.po_number if inv else None)


def _due(case: Case, vendor: Optional[Vendor]) -> Optional[date]:
    """Invoice due date, else invoice date + the vendor master's net days (terms never come from the invoice)."""
    inv = case.invoice
    if inv is None:
        return None
    if inv.due_date:
        return inv.due_date
    net = vendor.terms.net_days if vendor and vendor.terms else 30
    return inv.invoice_date + timedelta(days=net)


def _probation_block(case: Case, vendor: Optional[Vendor], store: Store) -> Optional[str]:
    """Probation vendors: no payment before the first delivery is confirmed (a GRN exists)."""
    if not vendor or not vendor.on_probation:
        return None
    if vendor.probation_until and case.as_of and vendor.probation_until < case.as_of:
        return None
    inv = case.invoice
    if inv and inv.po_number and store.list_receipts(inv.po_number):
        return None
    return "Vendor on probation: no payment until the first delivery is confirmed (no goods receipt yet)."


def bills(store: Store, pay: PaymentStore, policy: Policy, now: datetime) -> list[Bill]:
    vendors = {v.id: v for v in store.list_vendors()}
    cases = store.list_cases()
    out = [bill(store, pay, policy, c, vendors.get(c.vendor_id), now, cases) for c in cases if S.is_bill(c, cases)]
    return sorted(out, key=lambda b: (b.due_date or date.max, b.case_id))


def _activity(store: Store, pay: PaymentStore, case: Case, cases: list[Case]) -> list[ActivityItem]:
    acts: list[ActivityItem] = []
    inv = case.invoice
    inv_doc = next((d for d in case.documents if inv and d.id == inv.doc_id), None) or \
        (case.documents[0] if case.documents else None)
    acts.append(ActivityItem(at=inv_doc.received_at if inv_doc else case.created_at,
                             actor=inv_doc.sender if inv_doc and inv_doc.sender else "intake",
                             text=f"Invoice received via {inv_doc.channel.value if inv_doc else 'upload'}"
                                  + (f" ({inv_doc.filename})" if inv_doc else "")))
    if case.status == CaseStatus.quarantined:
        acts.append(ActivityItem(at=case.updated_at or case.created_at, actor="Intake",
                                 text=f"Quarantined: {case.quarantine_reason or 'failed validation'}"))
    steps = [s for s in store.list_steps(case.id) if s.parent_id is None]
    if steps:
        acts.append(ActivityItem(at=steps[0].started_at, actor="ReconAI", text=f"Agents started ({len(steps)} steps)"))
        last = steps[-1]
        rec = {Decision.approve: "clear it", Decision.hold: "hold it", Decision.reject: "reject it",
               Decision.escalate: "send it to a human"}.get(case.decision, "—")
        acts.append(ActivityItem(at=last.ended_at or last.started_at, actor="ReconAI", text=f"Agents finished: recommend {rec}"))
    for a in case.approvals:
        agent = S.is_agent_approval(a)
        who = f"ReconAI {ROLE_TITLE.get(a.role.value, a.role.value)} (simulated)" if agent else f"{a.approver} ({a.role.value})"
        verb = {"approved": "Approved", "rejected": "Rejected", "ask": "Put on hold"}[a.decision.value]
        if a.decision.value == "approved" and a.scope == "undisputed":
            verb = "Approved the undisputed part"
        text = verb + (f": “{a.comment}”" if a.comment and not agent else "")
        acts.append(ActivityItem(at=a.at, actor=who, text=text))
    if case.journal_entry:
        je = case.journal_entry
        part = " (undisputed part)" if S.partial(case) else ""
        amt = f" {inv.currency} {case.paid_amount:,.2f}" if inv and case.paid_amount is not None else ""
        acts.append(ActivityItem(at=case.updated_at or case.created_at, actor="Poster",
                                 text=f"Booked{amt}{part} to the ledger (Beancount, {je.id}, {je.date})"))
    refused = S.poster_refusal(case)
    if refused and not case.journal_entry:
        acts.append(ActivityItem(at=case.updated_at or case.created_at, actor="Poster", text=f"Did not book: {refused}"))
    for f in case.follow_ups:
        acts.append(ActivityItem(at=f.created_at, actor="ReconAI",
                                 text=f"Follow-up: {f.kind.value.replace('_', ' ')} due {f.due} · {f.status.value}"
                                      + (f" (closed by {f.closed_by})" if f.closed_by else "")))
    for m in case.outbound:
        acts.append(ActivityItem(at=m.sent_at, actor="ReconAI", text=f"Emailed {m.to}: {m.subject} (simulated)"))
    for sc in S.sub_cases(case, cases):
        d = sc.discrepancies[0] if sc.discrepancies else None
        what = d.type.value.replace("_", " ") if d else "discrepancy"
        amt = f" {sc.invoice.currency} {abs(d.delta):,.2f}" if d and d.delta is not None and sc.invoice else ""
        acts.append(ActivityItem(at=sc.updated_at or sc.created_at, actor="ReconAI",
                                 text=f"Sub-case {sc.id}: {what}{amt} · {sc.status.value.replace('_', ' ')}"))
    for att in S.attachments(case, cases):
        ai = att.invoice
        if ai and ai.credit_for:
            text = f"Credit note {ai.invoice_no} for {ai.credit_for}: {ai.currency} {ai.total:,.2f} ({att.id})"
        elif ai and ai.corrects:
            text = f"Corrected invoice {ai.invoice_no} replaces {ai.corrects}: nothing more to pay ({att.id})"
        else:
            doc = att.documents[0] if att.documents else None
            text = f"Supplier reply{(' “' + doc.subject + '”') if doc and doc.subject else ''} ({att.id})"
        acts.append(ActivityItem(at=att.created_at, actor=(att.documents[0].sender if att.documents and att.documents[0].sender
                                                          else att.vendor_id), text=text))
    for bt in pay.batches():
        for p in bt.payments:
            if p.case_id == case.id:
                acts.append(ActivityItem(at=bt.created_at, actor=bt.created_by,
                                         text=f"Scheduled {p.currency} {p.amount:,.2f} in {bt.id} for {p.pay_date} by "
                                              f"{p.method.upper()} to •••• {p.pay_to_last4}"))
                if bt.released_at:
                    acts.append(ActivityItem(at=bt.released_at, actor=bt.released_by or "—", text="Payment released (simulated)"))
    acts.sort(key=lambda x: x.at)
    return acts


def detail(store: Store, pay: PaymentStore, policy: Policy, case: Case, now: datetime) -> BillDetail:
    vendor = store.get_vendor(case.vendor_id)
    cases = store.list_cases()
    b = bill(store, pay, policy, case, vendor, now, cases)
    results = check_results(case, vendor, policy, store, b.signals)
    country = vendor.country if vendor else "US"
    paid = [(p.invoice_no, p.total, p.currency, p.paid_on) for p in paid_history(store, case.vendor_id)]
    paid += [(_inv_no(store, p.case_id), p.amount, p.currency, bt.released_at.date())
             for bt in pay.batches() if bt.released_at for p in bt.payments
             if p.vendor_id == case.vendor_id and p.case_id != case.id]
    last = max(paid, key=lambda p: p[3]) if paid else None
    inv = case.invoice
    if b.payment:
        est = b.payment.pay_date
    elif b.due_date and b.stage not in ("rejected", "paid"):
        est = max(now.date(), b.due_date - timedelta(days=2))
    else:
        est = None
    return BillDetail(bill=b, verdict=verdict(results) if results else "review", verdict_text=verdict_text(case, vendor),
                      checks=results, match=match_rows(case, store), gl=gl_lines(case, policy),
                      approval_steps=approval_steps(store, pay, policy, case, b),
                      activity=_activity(store, pay, case, cases), est_pay_date=est,
                      last_paid=LastPaid(invoice_no=last[0], amount=last[1], currency=last[2], paid_on=last[3]) if last else None,
                      pay_methods=allowed_methods(country), default_method=method_for(country),
                      statement_descriptor=f"HELIX SILICON PAYING {inv.invoice_no if inv else case.id} VIA RECONAI",
                      invoice_bank_last4=inv.bank_last4 if inv else None)


def _inv_no(store: Store, case_id: str) -> str:
    c = store.get_case(case_id)
    return c.invoice.invoice_no if c and c.invoice else case_id


def approval_steps(store: Store, pay: PaymentStore, policy: Policy, case: Case, b: Bill) -> list[ApprovalStep]:
    """The approval chain: agents prepare -> the role whose limit covers the amount approves -> a controller, CFO or CTO
    releases (an AP lead never releases; a controller/CFO/CTO may release what they approved)."""
    steps = [s for s in store.list_steps(case.id) if s.parent_id is None]
    out = [ApprovalStep(step=1, label="Prepared by ReconAI", who="Reader, Matcher, Vendor Guard and 7 more",
                        status="done" if case.decision else "waiting",
                        note=f"{len(steps)} steps in the background" if steps else "")]
    role = needs_role(case, policy)
    limit = policy.approval_limits.get(role)
    requester = case.po.requester if case.po else None
    human = S.human_decision(case)
    approved = S.last_approved(case)
    if case.status == CaseStatus.rejected or case.decision == Decision.reject:
        status, who = "rejected", f"Rejected by {human.approver if human else 'ReconAI'}"
    elif approved:
        status = "done"
        part = " (undisputed part)" if approved.scope == "undisputed" else ""
        who = (f"ReconAI {ROLE_TITLE.get(approved.role.value, approved.role.value)} (simulated, within limit){part}"
               if S.is_agent_approval(approved) else f"Approved by {approved.approver}{part}")
    elif human and human.decision.value == "ask":
        status, who = "on_hold", f"On hold by {human.approver}"
    else:
        status, who = ("waiting" if case.decision else "pending"), f"Any {ROLE_TITLE.get(role, role)}"
    note = (f"{ROLE_TITLE.get(role, role)} approves up to USD {limit:,.0f}" if limit is not None else "") + \
        (f" · {requester} removed due to separation of duties" if requester else "")
    out.append(ApprovalStep(step=2, label=f"{ROLE_TITLE.get(role, role)} approval", who=who, status=status, note=note))
    p = b.payment
    batch = pay.get(p.batch_id) if p else None
    if batch and batch.released_by:
        rel = ApprovalStep(step=3, label="Release payment", who=f"Released by {batch.released_by}", status="done",
                           note="Coinbase" if batch.rail == "coinbase" else "bank (simulated)")
    elif batch:
        rel = ApprovalStep(step=3, label="Release payment", who="A controller, CFO or CTO", status="waiting",
                           note=f"scheduled in {batch.id} for {batch.pay_date}")
    else:
        rel = ApprovalStep(step=3, label="Release payment", who="A controller, CFO or CTO (AP leads approve, never release)", status="pending",
                           note=b.payment_block or "")
    out.append(rel)
    return out


def report(store: Store, pay: PaymentStore, policy: Policy, now: datetime) -> ApReport:
    bs = bills(store, pay, policy, now)
    cases = {c.id: c for c in store.list_cases()}
    open_bs = [b for b in bs if b.stage not in ("paid", "rejected", "processing") and b.amount_usd is not None]
    # what is still owed on a bill: the booked part once booked, else the whole invoice
    owed = lambda b: b.payable_usd if b.payable_usd is not None else b.amount_usd  # noqa: E731
    usd = lambda xs: sum((owed(b) or ZERO for b in xs), ZERO)  # noqa: E731

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
        if b.stage == "rejected" or c.invoice is None or c.invoice.currency not in policy.fx_rates:
            continue
        for g in gl_lines(c, policy):
            by_gl[g.account].append((g.amount * policy.fx_rates[c.invoice.currency]).quantize(CENT))

    decided = [b for b in bs if b.recommendation is not None]
    touchless = [b for b in decided if cases[b.case_id].journal_entry is not None
                 and not S.human_decision(cases[b.case_id])]
    caught = [b for b in bs if b.stage in ("rejected", "blocked", "on_hold") or b.risk == "high"
              or b.recommendation in (Decision.hold, Decision.reject, Decision.escalate)]
    caught_usd = sum(((_fx(b.disputed, b.currency, policy) if b.disputed else b.amount_usd) or ZERO for b in caught), ZERO)
    offers = [b.discount for b in bs if b.discount]
    by = lambda st: sum((o.discount_usd for o in offers if o.status in st), ZERO)  # noqa: E731
    return ApReport(
        discounts_available_usd=by(("available", "needs_approval")), discounts_captured_usd=by(("captured",)),
        discounts_missed_usd=by(("missed",)),
        open_usd=usd(open_bs), due_7d_usd=usd([b for b in open_bs if b.days_to_due is not None and 0 <= b.days_to_due <= 7]),
        overdue_usd=usd([b for b in open_bs if b.days_to_due is not None and b.days_to_due < 0]),
        needs_review=sum(b.stage == "needs_review" for b in bs), blocked=sum(b.stage == "blocked" for b in bs),
        touchless_rate=round(len(touchless) / len(decided), 4) if decided else None,
        caught_usd=caught_usd, aging=aging, forecast=forecast,
        by_vendor=sorted((SpendRow(label=k, amount_usd=sum((b.amount_usd or ZERO for b in v), ZERO), count=len(v))
                          for k, v in by_vendor.items()), key=lambda r: -r.amount_usd),
        by_gl=sorted((SpendRow(label=k, amount_usd=sum(v, ZERO), count=len(v)) for k, v in by_gl.items()), key=lambda r: -r.amount_usd),
    )


def settings(policy: Policy) -> ApSettings:
    return ApSettings(
        approval_limits=policy.approval_limits, sla_hours=SLA_HOURS,
        materiality_abs=policy.materiality.abs, materiality_pct=policy.materiality.pct,
        qty_tolerance_pct=policy.tolerances.qty_pct, price_tolerance_pct=policy.tolerances.price_pct,
        locked_periods=policy.locked_periods, fx_rates=policy.fx_rates, accounts=policy.accounts.model_dump(),
        integrations=[
            Integration(name="Beancount ledger", status="connected", note="Double-entry ledger; the Poster books AP, payment runs never post"),
            Integration(name="AP inbox (email)", status="simulated", note="Invoices arrive via POST /intake; .eml folder in production"),
            Integration(name="SFTP / S3 drops", status="simulated", note="Watched folders, labelled simulated"),
            Integration(name="Bank payments (ACH / wire)", status="simulated", note="Payment runs are recorded, nothing is sent"),
            Integration(name="ERP (NetSuite / QuickBooks / Xero)", status="not_connected", note="Path to production: swap Beancount for the ERP API"),
            Integration(name="CRS Credit API sandbox (identity, fraud, court records, phone, credit)",
                        status="connected" if os.environ.get("CRS_USERNAME") and os.environ.get("CRS_PASSWORD")
                        and os.environ.get("RECONAI_CRS", "").lower() != "off" else "simulated",
                        note="Vendor onboarding verifies the owner / authorized signer: TransUnion identity, AtData Fraud "
                             "Finder, PitchPoint bankruptcies/liens/judgments, AccurateAppend phone lookup, Experian soft "
                             "pull with consent. CRS sandbox test personas only. Without credentials: recorded sandbox responses"),
            Integration(name="Coinbase (USDC on Base Sepolia testnet)",
                        status="connected" if all(os.environ.get(k) for k in ("CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET"))
                        else "simulated" if os.environ.get("COINBASE_MODE", "sandbox").lower() == "sandbox" else "not_connected",
                        note="Release payment runs as on-chain USDC from a CDP server wallet; amounts scaled down for testnet. "
                             "Without CDP keys: a local sandbox ledger (simulated, same controls)"),
            Integration(name="Email (Resend)",
                        status="connected" if os.environ.get("RESEND_API_KEY") else "simulated",
                        note="Supplier discrepancy emails + onboarding confirmations; always kept in the outbox"
                             + (f"; demo redirect to {os.environ['RECONAI_EMAIL_REDIRECT']}" if os.environ.get("RECONAI_EMAIL_REDIRECT") else "")),
            Integration(name="Slack (negotiation coach + onboarding)",
                        status="connected" if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN") else "not_connected",
                        note="/reconai negotiate in a channel: private market-based coaching, contract drafting, vendor onboarding"),
        ])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
