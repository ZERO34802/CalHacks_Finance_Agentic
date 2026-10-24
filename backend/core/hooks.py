"""Extension points so owners plug in P1 behavior without editing the runner.

- after_case(fn): fn(case, ctx) after a case finishes the pipeline (Memory Writer, skill-evolution observer...).
- sweep(name)(fn): fn(ctx, as_of) when the clock advances (tick fixtures, `make tick`): SLA timers,
  overdue follow-ups -> reopen. Each sweep runs in its own trace step (case_id = the tick fixture id, or "sweep").

Owners register from their own modules; HOOK_MODULES lists them. A module that doesn't exist yet is
skipped; a module that exists but fails to import raises (bugs are never hidden).
"""
from __future__ import annotations

import importlib
import importlib.util
from datetime import date
from typing import Callable

HOOK_MODULES = [
    "backend.agents.hooks",      # B: SLA sweep, skill-evolution observer
    "backend.pipeline.hooks",    # A: queue priority, sub-case bookkeeping
    "backend.memory.hooks",      # C: Memory Writer, follow-up auto-reopen
]

_after_case: list[Callable] = []
_sweeps: dict[str, Callable] = {}
_loaded = False


def after_case(fn: Callable) -> Callable:
    _after_case.append(fn)
    return fn


def sweep(name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _sweeps[name] = fn
        return fn
    return deco


def load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for mod in HOOK_MODULES:
        if importlib.util.find_spec(mod) is not None:
            importlib.import_module(mod)


def run_after_case(case, ctx) -> None:
    load()
    for fn in _after_case:
        with ctx.trace.step(case.id, f"after_case.{fn.__module__.split('.')[1]}.{fn.__name__}"):
            fn(case, ctx)


def run_sweeps(ctx, as_of: date, trace_id: str = "sweep") -> None:
    load()
    for name, fn in _sweeps.items():
        with ctx.trace.step(trace_id, f"sweep.{name}"):
            ctx.trace.annotate(detail={"as_of": as_of.isoformat()})
            fn(ctx, as_of)
