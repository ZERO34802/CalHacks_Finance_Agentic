"""The pipeline. Order is fixed in code; each stage is replaced by its owner."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.agents.approver import Approver
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
from contracts import Case, CaseFixture, CaseStatus, Decision, Event

PIPELINE: list[Stage] = [Reader(), DocDedup(), Registry(), Matcher(), Router(),
                         Investigator(), VendorGuard(), Validators(), Approver(), Poster()]

# Terminal statuses: once a stage sets one of these, later stages are skipped.
STOP = {CaseStatus.quarantined, CaseStatus.resolved}


def make_ctx(store: Store, run_id: Optional[str] = None) -> Ctx:
    ctx = Ctx(store=store, trace=None) if run_id is None else Ctx(store=store, trace=None, run_id=run_id)
    ctx.trace = Tracer(store, ctx.run_id)
    return ctx


def _save(case: Case, ctx: Ctx) -> None:
    case.updated_at = ctx.now()
    ctx.store.save_case(case)
    ctx.trace.emit(Event(type="case.updated", case_id=case.id, status=case.status, at=case.updated_at))


def run_case(case: Case, ctx: Ctx) -> Case:
    for stage in PIPELINE:
        if case.status in STOP:
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
    return case


def run_fixture(fx: CaseFixture, folder: Path, ctx: Ctx) -> Case:
    with ctx.trace.step(fx.id, "intake"):
        case = ingest(fx, folder, ctx)
    _save(case, ctx)
    return run_case(case, ctx)
