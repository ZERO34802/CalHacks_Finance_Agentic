"""[10] Poster. Owner: A. Beancount double entry, with controls enforced in code.

Posts only if case.decision == approve and an approved Approval exists. REFUSES (step blocked + note,
no ledger entry) when:
- the approving approval is not by a human approver/controller role (the agent cannot approve itself)
- requester (PO requester) == approver (segregation of duties), or the requester is unknown
- invoice total in USD (policy fx, SIMULATED) > the approving approval's limit (or no limit / no fx rate)
- the posting period (case.as_of) is locked. An invoice dated in a locked month posts to the current
  period with a note
- the idempotency key (vendor + normalized invoice no) is already in the ledger for another case.
  Same case re-run: no new entry; the existing one is re-attached (idempotent replay, step skipped)
Entry: Dr expense (freight lines -> freight account), Cr Liabilities:AP:<vendor_id>; validated with the
beancount loader, then subledger tie-out: sum of Liabilities:AP:* in the ledger == open AP of posted
cases in the store (per currency). Loader errors or tie-out mismatch -> rollback + blocked.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date
from decimal import Decimal
from typing import Optional

from backend.core.stage import Ctx
from backend.pipeline.lib import ledger as L
from backend.pipeline.lib.ids import is_freight, normalize_invoice_no
from backend.pipeline.lib.money import q2, to_usd
from backend.pipeline.lib.split import split
from backend.pipeline.registry import find_invoice_case
from contracts import (Approval, ApprovalDecision, Case, CaseStatus, Decision, JournalEntry, Posting, Role,
                       StepStatus)

APPROVER_ROLES = {Role.approver, Role.controller, Role.cfo}  # humans; the agent never holds these


def ap_account(ctx: Ctx, vendor_id: str) -> str:
    comp = re.sub(r"[^A-Za-z0-9-]", "-", vendor_id) or "UNKNOWN"
    if not comp[0].isupper() and not comp[0].isdigit():
        comp = "V" + comp
    return f"{ctx.policy.accounts.ap_control}:{comp}"


def idempotency_key(case: Case, scope: str = "full") -> str:
    base = f"{case.vendor_id}:{normalize_invoice_no(case.invoice.invoice_no)}"
    if case.invoice.credit_for:
        base += ":CN"
    return base if scope == "full" else f"{base}:{scope}"


def debits_for(case: Case, ctx: Ctx, line_amounts: dict[int, Decimal]) -> "OrderedDict[str, Decimal]":
    acct = ctx.policy.accounts
    debits: "OrderedDict[str, Decimal]" = OrderedDict()
    for li in case.invoice.lines:
        a = acct.freight if is_freight(li.sku, li.description) else acct.expense_default
        debits[a] = debits.get(a, Decimal(0)) + line_amounts.get(li.line_no, Decimal(0))
    return debits


def build_entry(case: Case, ctx: Ctx, posting_date: date, approval: Approval, requester: str,
                amount: Optional[Decimal] = None, line_amounts: Optional[dict[int, Decimal]] = None,
                scope: str = "full", reverse: bool = False, label: str = "") -> JournalEntry:
    """Dr expense (by line; freight lines -> freight), Cr AP:<vendor> = amount. reverse: credit note."""
    inv, acct = case.invoice, ctx.policy.accounts
    amount = q2(inv.total if amount is None else amount)
    debits = debits_for(case, ctx, line_amounts or {li.line_no: li.amount for li in inv.lines})
    diff = q2(amount - sum(debits.values(), Decimal(0)))
    if diff:  # printed total vs lines (below materiality), or the already-paid part of a corrected invoice
        debits[acct.expense_default] = debits.get(acct.expense_default, Decimal(0)) + diff
    sign = Decimal(-1) if reverse else Decimal(1)
    postings = [Posting(account=a, amount=q2(v) * sign, currency=inv.currency) for a, v in debits.items() if v]
    postings.append(Posting(account=ap_account(ctx, case.vendor_id), amount=-amount * sign, currency=inv.currency))
    suffix = "" if scope == "full" else f"_{scope}"
    return JournalEntry(id=f"je_{case.id}{suffix}", case_id=case.id, date=posting_date,
                        narration=f"{inv.invoice_no} PO {inv.po_number or '-'}{(' ' + label) if label else ''}",
                        postings=postings, requested_by=requester, approved_by=approval.approver,
                        idempotency_key=idempotency_key(case, scope))


def credit_reversal(case: Case, ctx: Ctx) -> tuple[Optional[Case], Decimal]:
    """Credit note: (credited case, amount to reverse). The credit consumes the never-booked (held) part first."""
    inv = case.invoice
    target = find_invoice_case(ctx, case.vendor_id, inv.credit_for, case.id)
    unbooked = q2((target.invoice.total if target else Decimal(0)) - ap_booked(target, ctx))
    return target, q2(max(Decimal(0), inv.total - max(unbooked, Decimal(0))))


def ap_booked(c: Optional[Case], ctx: Ctx) -> Decimal:
    """AP credited for a case's invoice so far (positive)."""
    if c is None or c.journal_entry is None:
        return Decimal(0)
    prefix = ctx.policy.accounts.ap_control
    return q2(-sum((p.amount for p in c.journal_entry.postings
                    if p.account == prefix or p.account.startswith(prefix + ":")), Decimal(0)))


def _entry_from_ledger(txn, case: Case) -> JournalEntry:
    m = txn.meta
    return JournalEntry(id=m.get("je_id", f"je_{case.id}"), case_id=case.id, date=txn.date, narration=txn.narration,
                        postings=[Posting(account=p.account, amount=p.units.number, currency=p.units.currency)
                                  for p in txn.postings],
                        requested_by=m.get("requested_by", ""), approved_by=m.get("approved_by") or None,
                        idempotency_key=m.get("idempotency_key", ""))


def store_open_ap(ctx: Ctx, current: Optional[JournalEntry], exclude: str) -> dict[str, Decimal]:
    prefix = ctx.policy.accounts.ap_control
    out: dict[str, Decimal] = {}
    jes = [c.journal_entry for c in ctx.store.list_cases()  # any case with a booked entry (incl. undisputed part)
           if c.id != exclude and c.journal_entry is not None]
    for je in jes + ([current] if current else []):
        for p in je.postings:
            if p.account == prefix or p.account.startswith(prefix + ":"):
                out[p.currency] = out.get(p.currency, Decimal(0)) + p.amount
    return {k: v for k, v in out.items() if v != 0}


def tie_out(ctx: Ctx, entries, current: Optional[JournalEntry], case_id: str) -> tuple[bool, dict]:
    gl = L.ap_balances(entries, ctx.policy.accounts.ap_control)
    sub = store_open_ap(ctx, current, case_id)
    ok = gl == sub
    return ok, {"gl_ap": {k: str(v) for k, v in gl.items()}, "subledger_ap": {k: str(v) for k, v in sub.items()},
                "tied_out": ok}


class Poster:
    name = "poster"

    def _refuse(self, case: Case, ctx: Ctx, reason: str, detail: dict) -> Case:
        ctx.trace.annotate(status=StepStatus.blocked, error=reason, detail={**detail, "refused": reason})
        case.notes.append(f"poster: REFUSED: {reason}")
        return case

    @staticmethod
    def _booked(case: Case, je: JournalEntry, scope: str, amount: Decimal) -> None:
        case.journal_entry = je
        case.paid_amount = q2(amount)
        if scope == "full":
            case.status = CaseStatus.posted  # an undisputed part keeps the hold status: the rest is still disputed
        else:
            case.notes.append(f"poster: posted undisputed {amount} {case.invoice.currency}; "
                              f"{case.disputed_amount} held")

    def _skip(self, case: Case, ctx: Ctx, reason: str, **extra) -> Case:
        ctx.trace.annotate(status=StepStatus.skipped, detail={
            "reason": reason, "decision": case.decision.value if case.decision else None, **extra})
        return case

    def run(self, case: Case, ctx: Ctx) -> Case:
        approved = [a for a in case.approvals if a.decision == ApprovalDecision.approved]
        if case.invoice is None:
            return self._skip(case, ctx, "no invoice")
        full = [a for a in approved if (a.scope or "full") == "full"]
        partial = [a for a in approved if a.scope == "undisputed"]
        inv, pol = case.invoice, ctx.policy
        scope, amount, line_amounts, reverse, label = "full", inv.total, None, False, ""
        if case.decision == Decision.approve and full:
            approval = full[-1]
            if case.journal_entry and case.journal_entry.idempotency_key.endswith(":undisputed"):
                return self._refuse(case, ctx, "undisputed part already booked; the held part settles through a "
                                               "credit note or a corrected invoice, never a second full posting", {})
        elif case.decision == Decision.hold and partial:
            sp = split(case)
            if not sp["separable"] or not sp["undisputed"]:
                return self._refuse(case, ctx, "undisputed-part approval, but the disputed part is not separable",
                                    {"split": {k: str(v) for k, v in sp.items() if k != "lines"}})
            approval, scope, amount, line_amounts = partial[-1], "undisputed", sp["undisputed"], sp["lines"]
            label = f"undisputed part; {sp['disputed']} {inv.currency} held"
            case.disputed_amount = sp["disputed"]
        else:
            return self._skip(case, ctx, "not approved")

        requester = case.po.requester if case.po else None
        if inv.credit_for:  # credit note: offsets the credited invoice; only what was booked gets reversed
            target, amount = credit_reversal(case, ctx)
            requester = requester or (target.po.requester if target and target.po else None)
            reverse = True
            label = f"credit note for {inv.credit_for}"
            if amount == 0:
                case.paid_amount = Decimal("0.00")
                case.notes.append(f"poster: credit note {inv.invoice_no} offsets the held (never booked) part of "
                                  f"{inv.credit_for}; nothing to post")
                return self._skip(case, ctx, "credit note offsets an unbooked disputed amount",
                                  target=target.id if target else None)
            line_amounts = {li.line_no: q2(li.amount * amount / inv.total) for li in inv.lines} if inv.total else None
        elif inv.corrects:  # corrected invoice: post only the delta over what the original already booked
            orig = find_invoice_case(ctx, case.vendor_id, inv.corrects, case.id)
            already = ap_booked(orig, ctx)
            if already:
                amount = q2(amount - already)
                label = f"corrects {inv.corrects}; {already} already booked on {orig.id}"
                if amount <= 0:
                    case.paid_amount = Decimal("0.00")
                    case.notes.append(f"poster: {inv.invoice_no} corrects {inv.corrects}; {already} {inv.currency} "
                                      f"already booked on {orig.id} covers it; nothing more to post")
                    return self._skip(case, ctx, "correction already covered by the original's booking",
                                      original=orig.id, already_booked=str(already))
        posting_date = case.as_of or ctx.now().date()
        usd = to_usd(amount, inv.currency, pol)
        detail = {"approval": approval.id, "approver": approval.approver, "role": approval.role.value,
                  "scope": scope, "amount": str(amount), "requester": requester,
                  "limit": str(approval.limit) if approval.limit is not None else None,
                  "total_usd": str(usd) if usd is not None else None, "posting_date": posting_date.isoformat()}

        # --- controls ---------------------------------------------------------------
        if approval.role not in APPROVER_ROLES:
            return self._refuse(case, ctx, f"approval by role {approval.role.value} cannot authorize posting", detail)
        if not requester:
            return self._refuse(case, ctx, "requester unknown (no PO): segregation of duties cannot be checked", detail)
        if any(a.approver.lower() == requester.lower() for a in approved):
            return self._refuse(case, ctx, f"requester {requester} cannot approve their own purchase", detail)
        if usd is None:
            return self._refuse(case, ctx, f"no fx rate for {inv.currency}", detail)
        # effective limit: the approval's own limit capped by the policy limit for its role (cfo: approval_limits.cfo)
        limits = [x for x in (approval.limit, pol.approval_limits.get(approval.role.value)) if x is not None]
        limit = min(limits) if limits and (approval.limit is not None or approval.role == Role.cfo) else None
        detail["effective_limit"] = str(limit) if limit is not None else None
        if limit is None or usd > limit:
            return self._refuse(case, ctx, f"amount USD {usd} exceeds {approval.approver}'s limit "
                                           f"{limit}; route to a higher approver", detail)
        period = posting_date.strftime("%Y-%m")
        if period in pol.locked_periods:
            return self._refuse(case, ctx, f"posting period {period} is locked", detail)
        inv_period = inv.invoice_date.strftime("%Y-%m")
        if inv_period in pol.locked_periods:
            note = f"invoice dated {inv.invoice_date} is in locked period {inv_period}; posted to {period}"
            case.notes.append(f"poster: {note}")
            detail["late_invoice"] = note

        je = build_entry(case, ctx, posting_date, approval, requester, amount=amount, line_amounts=line_amounts,
                         scope=scope, reverse=reverse, label=label)
        if sum((p.amount for p in je.postings), Decimal(0)) != 0:
            return self._refuse(case, ctx, "entry does not balance", detail)

        path = L.ledger_path(ctx.store)
        detail["ledger"] = str(path)
        with L.locked(path):
            L.ensure(path)
            entries, errors = L.load(path)
            if errors:
                return self._refuse(case, ctx, f"ledger invalid before posting: {errors[0].message}", detail)
            existing = L.find_key(entries, je.idempotency_key)
            if existing is not None:
                if existing.meta.get("case_id") != case.id:
                    return self._refuse(case, ctx, f"idempotency key {je.idempotency_key} already posted by case "
                                                   f"{existing.meta.get('case_id')}", detail)
                prior = _entry_from_ledger(existing, case)
                ok, tie = tie_out(ctx, entries, prior, case.id)
                detail.update(tie, idempotent_replay=True)
                if not ok:
                    return self._refuse(case, ctx, "subledger tie-out mismatch (AP subledger != GL control)", detail)
                self._booked(case, prior, scope, amount)
                case.notes.append(f"poster: already posted ({je.idempotency_key}); no duplicate entry written")
                ctx.trace.annotate(status=StepStatus.skipped, outputs=[prior.id], detail=detail)
                return case
            text = L.render(je, case.vendor_id, sorted({p.account for p in je.postings}
                                                       - L.opened_accounts(path.read_text())))
            prev = L.append(path, text)
            entries, errors = L.load(path)
            if errors:
                path.write_text(prev)
                return self._refuse(case, ctx, f"beancount rejected the entry: {errors[0].message}", detail)
            ok, tie = tie_out(ctx, entries, je, case.id)
            detail.update(tie)
            if not ok:
                path.write_text(prev)
                return self._refuse(case, ctx, "subledger tie-out mismatch (AP subledger != GL control); "
                                               "entry rolled back", detail)
        self._booked(case, je, scope, amount)
        ctx.trace.annotate(outputs=[je.id], detail={**detail, "idempotency_key": je.idempotency_key,
                                                    "postings": [f"{p.account} {p.amount} {p.currency}"
                                                                 for p in je.postings]})
        return case
