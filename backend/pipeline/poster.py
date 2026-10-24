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
from contracts import (Approval, ApprovalDecision, Case, CaseStatus, Decision, JournalEntry, Posting, Role,
                       StepStatus)

APPROVER_ROLES = {Role.approver, Role.controller}


def ap_account(ctx: Ctx, vendor_id: str) -> str:
    comp = re.sub(r"[^A-Za-z0-9-]", "-", vendor_id) or "UNKNOWN"
    if not comp[0].isupper() and not comp[0].isdigit():
        comp = "V" + comp
    return f"{ctx.policy.accounts.ap_control}:{comp}"


def idempotency_key(case: Case) -> str:
    return f"{case.vendor_id}:{normalize_invoice_no(case.invoice.invoice_no)}"


def build_entry(case: Case, ctx: Ctx, posting_date: date, approval: Approval, requester: str) -> JournalEntry:
    inv, acct = case.invoice, ctx.policy.accounts
    debits: "OrderedDict[str, Decimal]" = OrderedDict()
    for li in inv.lines:
        a = acct.freight if is_freight(li.sku, li.description) else acct.expense_default
        debits[a] = debits.get(a, Decimal(0)) + li.amount
    diff = q2(inv.total - sum(debits.values(), Decimal(0)))
    if diff:  # printed total vs lines, already accepted as below materiality
        debits[acct.expense_default] = debits.get(acct.expense_default, Decimal(0)) + diff
    postings = [Posting(account=a, amount=q2(v), currency=inv.currency) for a, v in debits.items() if v]
    postings.append(Posting(account=ap_account(ctx, case.vendor_id), amount=-q2(inv.total), currency=inv.currency))
    return JournalEntry(id=f"je_{case.id}", case_id=case.id, date=posting_date,
                        narration=f"{inv.invoice_no} PO {inv.po_number or '-'}", postings=postings,
                        requested_by=requester, approved_by=approval.approver, idempotency_key=idempotency_key(case))


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
    jes = [c.journal_entry for c in ctx.store.list_cases()
           if c.id != exclude and c.status == CaseStatus.posted and c.journal_entry is not None]
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

    def run(self, case: Case, ctx: Ctx) -> Case:
        approved = [a for a in case.approvals if a.decision == ApprovalDecision.approved]
        if case.decision != Decision.approve or not approved or case.invoice is None:
            ctx.trace.annotate(status=StepStatus.skipped, detail={
                "reason": "not approved" if case.invoice else "no invoice",
                "decision": case.decision.value if case.decision else None})
            return case
        inv, pol = case.invoice, ctx.policy
        approval = approved[-1]
        requester = case.po.requester if case.po else None
        posting_date = case.as_of or ctx.now().date()
        usd = to_usd(inv.total, inv.currency, pol)
        detail = {"approval": approval.id, "approver": approval.approver, "role": approval.role.value,
                  "requester": requester, "limit": str(approval.limit) if approval.limit is not None else None,
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
        if approval.limit is None or usd > approval.limit:
            return self._refuse(case, ctx, f"invoice USD {usd} exceeds {approval.approver}'s limit "
                                           f"{approval.limit}; route to a higher approver", detail)
        period = posting_date.strftime("%Y-%m")
        if period in pol.locked_periods:
            return self._refuse(case, ctx, f"posting period {period} is locked", detail)
        inv_period = inv.invoice_date.strftime("%Y-%m")
        if inv_period in pol.locked_periods:
            note = f"invoice dated {inv.invoice_date} is in locked period {inv_period}; posted to {period}"
            case.notes.append(f"poster: {note}")
            detail["late_invoice"] = note

        je = build_entry(case, ctx, posting_date, approval, requester)
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
                case.journal_entry, case.status = prior, CaseStatus.posted
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
        case.journal_entry, case.status = je, CaseStatus.posted
        ctx.trace.annotate(outputs=[je.id], detail={**detail, "idempotency_key": je.idempotency_key,
                                                    "postings": [f"{p.account} {p.amount} {p.currency}"
                                                                 for p in je.postings]})
        return case
