"""[8] Runtime validators. Owner: A. Deterministic checks on the Investigator's proposal.

Blocks (step status=blocked, note, case.proposal=None so the Approver escalates) when:
- schema: proposal does not re-validate, or belongs to another case
- citations: a cited doc_id is not evidence of this case (case documents, PO, receipts, contract terms,
  paid history, or a citation produced by code stages), or a 'line N' locator does not exist in that doc
- numbers: a money-like number in the explanation or a citation quote ('1,116,000', '2400.00') is not one
  of the code-computed / system-of-record figures for this case (incl. USD equivalents via policy fx)
- proposed entry: unbalanced, wrong currency, wrong case, unexpected accounts, or debit total != invoice
  total (or invoice total minus material variance, for a partial payment)
- decision table (data/FORMATS.md): the recommendation must be in the allowed set for the facts.
  The proposal may always escalate; it may never downgrade (e.g. approve with a material discrepancy).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from backend.core.stage import Ctx
from backend.pipeline.lib.money import q2, to_usd
from contracts import Case, CaseStatus, Decision, DiscrepancyType as T, Proposal, StepStatus

ESCALATE_FACTS = {T.bank_change, T.lookalike_domain, T.embedded_instructions, T.unknown_po, T.missing_receipt}
REJECT_FACTS = {T.duplicate_invoice}
HOLD_FACTS = {T.qty_short, T.price_over, T.unapproved_freight, T.currency_mismatch, T.fx_gap, T.total_mismatch}
INFO = {T.below_materiality, T.over_limit, T.locked_period}
_NUMBER = re.compile(r"(?<![\w.,-])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2})(?![\w,]|\.\d)")


def allowed_decisions(case: Case) -> tuple[set[Decision], list[str]]:
    allowed = {Decision.approve, Decision.hold, Decision.escalate}
    why: list[str] = []
    material = {d.type for d in case.discrepancies if d.material and d.type not in INFO}
    flagged = case.invoice is not None and "embedded_instructions" in case.invoice.flags
    if material & ESCALATE_FACTS or case.vendor_id == "V-UNKNOWN" or flagged or case.invoice is None \
            or case.status == CaseStatus.quarantined or material - ESCALATE_FACTS - REJECT_FACTS - HOLD_FACTS:
        why.append("escalate-only facts present")
        return {Decision.escalate}, why
    if material & REJECT_FACTS:
        why.append("duplicate invoice -> reject or escalate")
        return {Decision.reject, Decision.escalate}, why
    if material & HOLD_FACTS:
        why.append("material exception -> hold or escalate")
        return {Decision.hold, Decision.escalate}, why
    return allowed, ["clean or below materiality"]


def _num(s: str) -> Optional[Decimal]:
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None


def known_numbers(case: Case, ctx: Ctx) -> set[Decimal]:
    vals: set[Decimal] = set()
    add = lambda x: vals.add(abs(Decimal(x)).normalize()) if x is not None else None  # noqa: E731

    def add_str(s: Optional[str]) -> None:
        for m in re.findall(r"-?\d[\d,]*(?:\.\d+)?", s or ""):
            n = _num(m)
            if n is not None:
                add(n)

    inv = case.invoice
    if inv:
        add(inv.total)
        tot = Decimal(0)
        for li in inv.lines:
            for x in (li.qty, li.unit_price, li.amount):
                add(x)
            tot += li.amount
        add(tot)
        for f in inv.flags:
            add_str(f.split(":")[-1])
    if case.po:
        po_total = Decimal(0)
        for pl in case.po.lines:
            add(pl.qty)
            add(pl.unit_price)
            add(pl.qty * pl.unit_price)
            po_total += pl.qty * pl.unit_price
        add(po_total)
    for r in case.receipts:
        for rl in r.lines:
            add(rl.qty_received)
    material = Decimal(0)
    for d in case.discrepancies:
        add(d.delta)
        add_str(d.expected)
        add_str(d.actual)
        e, a = _num(d.expected or "x"), _num(d.actual or "x")
        if e is not None and a is not None:
            add(a - e)
        if d.material and d.delta is not None:
            material += abs(d.delta)
        for c in d.citations:
            add_str(c.quote)
    add(material)
    if inv:
        add(inv.total - material)
        for t in ctx.store.list_contract_terms(case.vendor_id):
            add(t.unit_price)
        for p in ctx.store.list_paid(case.vendor_id):
            add(p.total)
    pol = ctx.policy
    for x in list(pol.approval_limits.values()) + [pol.materiality.abs, pol.materiality.pct * 100,
                                                   pol.tolerances.price_pct * 100, pol.tolerances.qty_pct * 100]:
        add(x)
    if inv and inv.currency != "USD":
        for v in list(vals):
            u = to_usd(v, inv.currency, pol)
            if u is not None:
                add(u)
                add(u.quantize(Decimal(1)))
    return vals


def _matches(n: Decimal, known: set[Decimal]) -> bool:
    n = abs(n).normalize()
    return n in known or any(abs(n - k) <= Decimal("0.01") for k in known)


def evidence(case: Case, ctx: Ctx) -> dict[str, Optional[set[str]]]:
    """doc_id -> set of valid 'line N' / 'sku X' locators (None = any locator)."""
    ev: dict[str, Optional[set[str]]] = {d.id: None for d in case.documents}
    if case.invoice:
        ev[case.invoice.doc_id] = {f"line {li.line_no}" for li in case.invoice.lines}
    if case.po:
        ev[case.po.doc_id] = {f"line {pl.line_no}" for pl in case.po.lines}
    for r in case.receipts:
        ev[r.doc_id] = {f"sku {rl.sku}" for rl in r.lines}
    for t in ctx.store.list_contract_terms(case.vendor_id):
        locs = ev.setdefault(t.doc_id, set())
        if locs is not None:
            locs.add(f"sku {t.sku}")
    from backend.pipeline.doc_dedup import paid_ref
    for p in ctx.store.list_paid(case.vendor_id):
        ev[paid_ref(p)] = None
    for d in case.discrepancies:  # produced by code stages (dedup links to prior cases etc.)
        for c in d.citations:
            ev.setdefault(c.doc_id, None)
    return ev


def check(case: Case, ctx: Ctx) -> tuple[list[str], dict]:
    p = case.proposal
    errs: list[str] = []
    detail: dict = {}
    try:
        Proposal.model_validate(p.model_dump())
    except Exception as e:
        errs.append(f"schema: {e}")
    if p.case_id != case.id:
        errs.append(f"schema: proposal is for {p.case_id}, not {case.id}")

    ev = evidence(case, ctx)
    for c in p.citations:
        if c.doc_id not in ev:
            errs.append(f"citation: doc {c.doc_id} is not evidence in this case")
            continue
        locs = ev[c.doc_id]
        m = re.match(r"^\s*(line|sku)\s+([^\s,;]+)", c.locator, re.I)
        if locs is not None and m and f"{m.group(1).lower()} {m.group(2)}" not in locs:
            errs.append(f"citation: {c.doc_id} has no {c.locator!r}")

    known = known_numbers(case, ctx)
    texts = [("explanation", p.explanation)] + [(f"citation {c.doc_id}", c.quote or "") for c in p.citations]
    unknown = sorted({m for _, t in texts for m in _NUMBER.findall(t or "") if not _matches(_num(m), known)})
    if unknown:
        errs.append(f"numbers: {unknown[:5]} do not match any code-computed or source figure")
    detail["numbers_checked"] = sum(len(_NUMBER.findall(t or "")) for _, t in texts)

    je = p.proposed_entry
    if je is not None:
        sums: dict[str, Decimal] = {}
        for post in je.postings:
            sums[post.currency] = sums.get(post.currency, Decimal(0)) + post.amount
        if any(v != 0 for v in sums.values()):
            errs.append(f"entry: unbalanced {({k: str(v) for k, v in sums.items()})}")
        if je.case_id != case.id:
            errs.append("entry: case_id mismatch")
        inv = case.invoice
        if inv is not None:
            if any(post.currency != inv.currency for post in je.postings):
                errs.append("entry: currency differs from invoice")
            bad = [post.account for post in je.postings
                   if not (post.account.startswith("Expenses:") or post.account.startswith(ctx.policy.accounts.ap_control))]
            if bad:
                errs.append(f"entry: unexpected accounts {bad}")
            debit = q2(sum((post.amount for post in je.postings if post.amount > 0), Decimal(0)))
            material = q2(sum((abs(d.delta) for d in case.discrepancies if d.material and d.delta is not None),
                              Decimal(0)))
            if debit not in {q2(inv.total), q2(inv.total - material)}:
                errs.append(f"entry: debit total {debit} != invoice total {inv.total} (recomputed)")

    allowed, why = allowed_decisions(case)
    detail.update(allowed=[d.value for d in sorted(allowed, key=lambda x: x.value)], table=why,
                  recommendation=p.recommendation.value)
    if p.recommendation not in allowed:
        errs.append(f"decision: {p.recommendation.value} not allowed by the decision table "
                    f"({'; '.join(why)}; allowed {sorted(a.value for a in allowed)})")
    if p.policy_recommendation is not None and p.policy_recommendation not in allowed:
        detail["warning"] = f"proposal policy floor {p.policy_recommendation.value} disagrees with validators"
    return errs, detail


class Validators:
    name = "validators"

    def run(self, case: Case, ctx: Ctx) -> Case:
        if case.proposal is None:
            ctx.trace.annotate(status=StepStatus.blocked, error="no proposal", detail={"checks": "skipped"})
            return case
        errs, detail = check(case, ctx)
        if errs:
            msg = "; ".join(errs)[:900]
            ctx.trace.annotate(status=StepStatus.blocked, error=msg, detail={**detail, "errors": errs})
            case.notes.append(f"validators: proposal blocked: {msg}")
            case.proposal = None
        else:
            ctx.trace.annotate(inputs=["proposal"], detail={**detail, "errors": [], "passed": True})
        return case
