"""Deterministic eval harness. Owner: C.

Runs fixtures through the pipeline, compares against the answer key, checks
control invariants, and produces a Scoreboard. Misses are reported, not hidden.
"""
from __future__ import annotations

from decimal import Decimal

from backend.core.runner import PIPELINE, make_ctx, run_case
from backend.core.stage import Ctx
from backend.evals.fixtures import answer_key, case_ids, load_case, seed
from backend.store.base import Store
from contracts import (ApprovalDecision, Case, Decision, EvalResult, ExpectedOutcome, Scoreboard, Step,
                       StepStatus)


def invariants(case: Case, steps: list[Step], ctx: Ctx) -> dict[str, bool]:
    """Control invariants. Must be 100% before merging."""
    je = case.journal_entry
    approved = [a for a in case.approvals if a.decision == ApprovalDecision.approved]
    stages_seen = {s.stage for s in steps if s.status != StepStatus.failed}
    checks = {"inv_trace_complete": all(st.name in stages_seen for st in PIPELINE)}
    if je is None:
        return checks
    checks["inv_balanced"] = sum((p.amount for p in je.postings), Decimal(0)) == 0
    checks["inv_approved_before_post"] = bool(approved) and je.approved_by == approved[-1].approver
    checks["inv_requester_ne_approver"] = je.approved_by != je.requested_by
    if case.invoice and approved:
        usd = case.invoice.total * ctx.policy.fx_rates[case.invoice.currency]
        limit = approved[-1].limit
        checks["inv_within_limit"] = limit is not None and usd <= limit
    period = je.date.strftime("%Y-%m")
    checks["inv_period_open"] = period not in ctx.policy.locked_periods
    return checks


def score(case: Case, exp: ExpectedOutcome, steps: list[Step], ctx: Ctx) -> EvalResult:
    actual_disc = sorted({d.type for d in case.discrepancies}, key=lambda t: t.value)
    checks = {
        "decision": case.decision == exp.decision,
        "discrepancies": set(actual_disc) == set(exp.discrepancies),
        "skill": case.skill == exp.skill,
        **invariants(case, steps, ctx),
    }
    return EvalResult(case_id=case.id, run_id=ctx.run_id, expected=exp, actual_decision=case.decision,
                      actual_discrepancies=actual_disc, actual_skill=case.skill,
                      checks=checks, passed=all(checks.values()))


def run_eval(store: Store) -> Scoreboard:
    seed(store)
    ctx = make_ctx(store)
    key = answer_key()
    results = []
    for cid in case_ids():
        case = run_case(load_case(cid), ctx)
        results.append(score(case, key[cid], store.list_steps(cid, ctx.run_id), ctx))

    exceptions = [r for r in results if r.expected.decision != Decision.approve]
    cleans = [r for r in results if r.expected.decision == Decision.approve]
    inv = [v for r in results for k, v in r.checks.items() if k.startswith("inv_")]
    board = Scoreboard(
        run_id=ctx.run_id, at=ctx.now(), total=len(results), passed=sum(r.passed for r in results),
        catch_rate=_rate(sum(r.actual_decision != Decision.approve for r in exceptions), len(exceptions)),
        false_alarm_rate=_rate(sum(r.actual_decision != Decision.approve for r in cleans), len(cleans)),
        invariant_pass_rate=_rate(sum(inv), len(inv)),
        results=results,
    )
    store.save_scoreboard(board)
    return board


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 1.0


def format_board(b: Scoreboard) -> str:
    out = [f"Scoreboard {b.run_id}: {b.passed}/{b.total} passed | catch {b.catch_rate:.0%} | "
           f"false alarm {b.false_alarm_rate:.0%} | invariants {b.invariant_pass_rate:.0%}", ""]
    out.append(f"{'case':<10}{'expected':<10}{'actual':<10}{'result':<7}failed checks")
    for r in b.results:
        failed = ", ".join(k for k, v in r.checks.items() if not v) or "-"
        actual = r.actual_decision.value if r.actual_decision else "none"
        out.append(f"{r.case_id:<10}{r.expected.decision.value:<10}{actual:<10}"
                   f"{'PASS' if r.passed else 'MISS':<7}{failed}")
    return "\n".join(out)
