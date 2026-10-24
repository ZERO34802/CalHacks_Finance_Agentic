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


def close_followup(case: Case, ctx: Ctx, followup_id: str, by: str, note: str = "",
                   outcome: Optional[str] = None) -> Case:
    """A human records an out-of-band follow-up result (e.g. callback to the number on the vendor master).

    Never the requester or an agent. 'denied' on a callback = security incident: Alert + case stays escalated.
    'confirmed' only clears the callback; a human still approves within limit. Vendor bank details are NEVER
    changed here (vendor-master changes are a separate two-person flow)."""
    from backend.agents.approver import requester
    from contracts import Alert, Decision, FollowUpKind, FollowUpStatus
    fu = next((f for f in case.follow_ups if f.id == followup_id), None)
    if fu is None:
        raise LookupError(f"no follow-up {followup_id} on {case.id}")
    if not by or by.startswith("agent") or by == requester(case, ctx):
        raise PermissionError("must be a human who is not the requester")
    if fu.status == FollowUpStatus.done:
        raise ValueError(f"follow-up {followup_id} is already done")
    if fu.kind == FollowUpKind.callback and outcome not in ("confirmed", "denied"):
        raise ValueError("a callback needs outcome 'confirmed' or 'denied'")
    now = ctx.now()
    fu.status, fu.closed_by = FollowUpStatus.done, by
    fu.note += f"; done by {by} at {now.isoformat()}" + (f" ({outcome})" if outcome else "") + (f": {note}" if note else "")
    detail = {"followup": fu.id, "kind": fu.kind.value, "by": by, "outcome": outcome, "note": note,
              "vendor_master_changed": False}
    if outcome == "denied":
        aid = f"security_incident_{case.id}"
        ctx.store.put_record("alert", aid, Alert(id=aid, kind="security_incident", vendor_id=case.vendor_id,
                                                 case_id=case.id, at=now,
                                                 message=f"vendor denied the change on callback by {by}: {note}"[:300]),
                             idx=case.id)
        case.decision, case.status = Decision.escalate, CaseStatus.escalated
        case.notes.append(f"callback by {by}: vendor DENIED the change -> security incident; payment stays held")
        detail["alert"] = aid
    elif outcome == "confirmed":
        case.notes.append(f"callback by {by}: vendor confirmed via contact on file; a human may now approve within "
                          "limit (bank details on the vendor master are unchanged)")
    else:
        case.notes.append(f"follow-up {fu.id} done by {by}")
    with ctx.trace.step(case.id, "followup.done"):
        ctx.trace.annotate(detail=detail)
    ctx.store.save_case(case)
    return case
