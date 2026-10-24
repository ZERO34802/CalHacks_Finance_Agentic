"""The pipeline. Order is fixed in code; each stage is replaced by its owner."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.agents.approver import Approver
from backend.core import hooks
from backend.agents.investigator import Investigator
from backend.agents.router import Router
from backend.core.stage import Ctx, Stage
from backend.intake.ingest import ingest
from backend.pipeline.doc_dedup import DocDedup
from backend.pipeline.matcher import Matcher
from backend.pipeline.poster import Poster
from backend.pipeline.reader import Reader
from backend.pipeline.registry import Registry
from backend.pipeline.validators import Validators
from backend.pipeline.vendor_guard import VendorGuard
from backend.store.base import Store
from backend.trace.tracer import Tracer
from contracts import Case, CaseFixture, CaseStatus, Controls, Decision, Event, FixtureKind, StepStatus

PIPELINE: list[Stage] = [Reader(), DocDedup(), Registry(), Matcher(), Router(),
                         Investigator(), VendorGuard(), Validators(), Approver(), Poster()]

# Terminal statuses: once a stage sets one of these, later stages are skipped.
STOP = {CaseStatus.quarantined, CaseStatus.resolved, CaseStatus.paused}

# Kill switch / handoff gate: these stages (agents + anything after them) never run while paused.
AGENT_STAGES = {"router", "investigator", "vendor_guard", "validators", "approver", "poster"}


def controls(ctx: Ctx) -> Controls:
    return ctx.store.get_record(Controls, "controls", "global") or Controls()


def paused_reason(case: Case, ctx: Ctx) -> Optional[str]:
    c = controls(ctx)
    if c.paused_global:
        return f"kill switch: all agent actions paused by {c.updated_by}"
    if case.vendor_id in c.paused_vendors:
        return f"kill switch: vendor {case.vendor_id} paused by {c.updated_by}"
    if case.assigned_to:
        return f"handed off to {case.assigned_to}; agent stages skipped until released"
    return None


def make_ctx(store: Store, run_id: Optional[str] = None) -> Ctx:
    ctx = Ctx(store=store, trace=None) if run_id is None else Ctx(store=store, trace=None, run_id=run_id)
    ctx.trace = Tracer(store, ctx.run_id)
    return ctx


def _save(case: Case, ctx: Ctx) -> None:
    case.updated_at = ctx.now()
    ctx.store.save_case(case)
    ctx.trace.emit(Event(type="case.updated", case_id=case.id, status=case.status, at=case.updated_at))


def run_case(case: Case, ctx: Ctx, start_at: Optional[str] = None) -> Case:
    """Run the pipeline. start_at: resume from that stage (handoff release / re-triage of a delta)."""
    stages = PIPELINE
    if start_at:
        stages = PIPELINE[[s.name for s in PIPELINE].index(start_at):]
    for stage in stages:
        if case.status in STOP:
            break
        if stage.name in AGENT_STAGES and (reason := paused_reason(case, ctx)):
            with ctx.trace.step(case.id, "gate"):
                ctx.trace.annotate(status=StepStatus.blocked, detail={"reason": reason, "resume_at": stage.name})
            case.status = CaseStatus.paused
            case.notes.append(f"{reason} (resume at {stage.name})")
            _save(case, ctx)
            break
        try:
            with ctx.trace.step(case.id, stage.name):
                case = stage.run(case, ctx)
        except Exception as e:  # recorded as a failed step by the tracer; never guessed past
            case.status, case.decision = CaseStatus.escalated, Decision.escalate
            case.notes.append(f"{stage.name} failed: {type(e).__name__}: {e}")
            _save(case, ctx)
            break
        _save(case, ctx)
    if case.status != CaseStatus.paused:
        hooks.run_after_case(case, ctx)
        _save(case, ctx)
    return case


def run_fixture(fx: CaseFixture, folder: Path, ctx: Ctx) -> Case:
    if fx.kind == FixtureKind.tick:  # advance the clock: SLA timers, overdue follow-ups
        hooks.run_sweeps(ctx, fx.as_of, trace_id=fx.id)
        return Case(id=fx.id, vendor_id="SYSTEM", status=CaseStatus.resolved, as_of=fx.as_of,
                    created_at=ctx.now(), notes=[f"tick to {fx.as_of}"])
    with ctx.trace.step(fx.id, "intake"):
        case = ingest(fx, folder, ctx)
    _save(case, ctx)
    return run_case(case, ctx)
