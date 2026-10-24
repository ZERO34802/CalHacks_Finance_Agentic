"""B's hooks (auto-loaded by backend.core.hooks): supplier replies, skill-evolution observer, SLA sweep."""
from __future__ import annotations

from datetime import date

from backend.agents import evolution, sla, supplier
from backend.core import hooks
from backend.core.stage import Ctx
from contracts import Case


@hooks.after_case
def supplier_reply(case: Case, ctx: Ctx) -> None:
    """A linked a supplier reply to its target case: update the target's follow-ups (untrusted text)."""
    out = supplier.handle_reply(case, ctx)
    ctx.trace.annotate(detail=out or {"skipped": "not a supplier reply"})


@hooks.after_case
def skill_feedback(case: Case, ctx: Ctx) -> None:
    ctx.trace.annotate(detail=evolution.observe(case, ctx))


@hooks.sweep("sla")
def sla_sweep(ctx: Ctx, as_of: date) -> None:
    ctx.trace.annotate(detail=sla.sweep_sla(ctx, as_of))
