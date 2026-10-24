"""The pipeline. Order is fixed in code; each stage is replaced by its owner."""
from __future__ import annotations

from backend.agents.approver import Approver
from backend.agents.investigator import Investigator
from backend.agents.router import Router
from backend.core.stage import Ctx, Stage
from backend.pipeline.doc_dedup import DocDedup
from backend.pipeline.matcher import Matcher
from backend.pipeline.poster import Poster
from backend.pipeline.reader import Reader
from backend.pipeline.registry import Registry
from backend.pipeline.validators import Validators
from backend.pipeline.vendor_guard import VendorGuard
from backend.store.base import Store
from backend.trace.tracer import Tracer
from contracts import Case, Event

PIPELINE: list[Stage] = [Reader(), DocDedup(), Registry(), Matcher(), Router(),
                         Investigator(), VendorGuard(), Validators(), Approver(), Poster()]


def make_ctx(store: Store, run_id: str | None = None) -> Ctx:
    ctx = Ctx(store=store, trace=None) if run_id is None else Ctx(store=store, trace=None, run_id=run_id)
    ctx.trace = Tracer(store, ctx.run_id)
    return ctx


def run_case(case: Case, ctx: Ctx) -> Case:
    for stage in PIPELINE:
        with ctx.trace.step(case.id, stage.name):
            case = stage.run(case, ctx)
        case.updated_at = ctx.now()
        ctx.store.save_case(case)
        ctx.trace.emit(Event(type="case.updated", case_id=case.id, status=case.status, at=case.updated_at))
    return case
