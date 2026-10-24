"""Kill switch + human handoff. Owner: B. The runner's gate (lead) enforces both before every agent stage.

- set_controls: pause / unpause all agent actions or one vendor (record kind 'controls', key 'global'). Traced.
- handoff: a human takes over a case (assigned_to + Handoff record + status paused). Traced.
- release: the human hands back; the agent resumes from case state + notes at the stage the gate recorded
  ("resume at <stage>"), via run_case(start_at=...).
"""
from __future__ import annotations

import re
from typing import Optional

from backend.core.stage import Ctx
from contracts import Case, CaseStatus, Controls, Handoff, StepStatus

RESUME = re.compile(r"\(resume at (\w+)\)")
AGENT = "agent"


def get_controls(ctx: Ctx) -> Controls:
    return ctx.store.get_record(Controls, "controls", "global") or Controls()


def set_controls(ctx: Ctx, actor: str, paused: bool, vendor_id: Optional[str] = None) -> Controls:
    c = get_controls(ctx)
    if vendor_id:
        vs = set(c.paused_vendors)
        (vs.add if paused else vs.discard)(vendor_id)
        c.paused_vendors = sorted(vs)
    else:
        c.paused_global = paused
    c.updated_by, c.updated_at = actor, ctx.now()
    ctx.store.put_record("controls", "global", c)
    with ctx.trace.step("controls", "controls.update"):
        ctx.trace.annotate(detail={"actor": actor, "paused": paused, "vendor_id": vendor_id,
                                   "paused_global": c.paused_global, "paused_vendors": c.paused_vendors})
    return c


def handoff(case: Case, ctx: Ctx, to: str, by: str, note: str = "") -> Case:
    if to.startswith("agent"):
        raise ValueError("hand off to a human, not an agent")
    case.handoffs.append(Handoff(case_id=case.id, from_actor=by or AGENT, to_actor=to, at=ctx.now(), note=note))
    case.assigned_to = to
    prev = case.status
    if case.status not in (CaseStatus.posted, CaseStatus.resolved):
        case.status = CaseStatus.paused
    case.notes.append(f"handoff: {by or AGENT} -> {to}" + (f" ({note})" if note else ""))
    with ctx.trace.step(case.id, "handoff"):
        ctx.trace.annotate(status=StepStatus.blocked, detail={"from": by, "to": to, "note": note,
                                                              "status_before": prev.value})
    ctx.store.save_case(case)
    return case


def resume_stage(case: Case) -> Optional[str]:
    for n in reversed(case.notes):
        m = RESUME.search(n)
        if m:
            return m.group(1)
    return None


def release(case: Case, ctx: Ctx, by: str, note: str = "") -> Case:
    """Human hands the case back; the agent resumes where the gate stopped it (from case state + notes)."""
    from backend.core.runner import paused_reason, run_case
    human = case.assigned_to or by
    case.handoffs.append(Handoff(case_id=case.id, from_actor=human, to_actor=AGENT, at=ctx.now(), note=note))
    case.assigned_to = None
    stage = resume_stage(case) if case.status == CaseStatus.paused else None
    case.notes.append(f"release: {human} -> agent" + (f", resume at {stage}" if stage else "") +
                      (f" ({note})" if note else ""))
    with ctx.trace.step(case.id, "release"):
        ctx.trace.annotate(detail={"from": human, "by": by, "resume_at": stage, "note": note})
    if stage and paused_reason(case, ctx) is None:
        case.status = CaseStatus.in_progress
        ctx.store.save_case(case)
        return run_case(case, ctx, start_at=stage)
    if case.status == CaseStatus.paused:  # handed off after the pipeline finished: back to its decided status
        from backend.agents.approver import STATUS
        case.status = STATUS[case.decision] if case.decision else CaseStatus.in_progress
    ctx.store.save_case(case)
    return case
