"""Trace helper. Every stage is wrapped in `with ctx.trace.step(case_id, name)`.

Records start/finish/duration/status to the store and publishes Events to
subscribers (the API forwards them over WS /events). A stage can add detail
to the current step with `ctx.trace.annotate(...)`.

A stage that raises is recorded as failed and the exception propagates.
A stage can mark a non-ok outcome without raising via annotate(status=...).
"""
from __future__ import annotations

import itertools
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional
from uuid import uuid4

from backend.store.base import Store
from contracts import Event, Role, Step, StepStatus

Subscriber = Callable[[Event], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Tracer:
    def __init__(self, store: Store, run_id: str):
        self.store = store
        self.run_id = run_id
        self._seq = itertools.count()
        self._current: Optional[Step] = None
        self._subscribers: list[Subscriber] = []

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    def emit(self, event: Event) -> None:
        for fn in self._subscribers:
            fn(event)

    @contextmanager
    def step(self, case_id: str, stage: str, role: Role = Role.system) -> Iterator[Step]:
        step = Step(id=f"step_{uuid4().hex[:10]}", case_id=case_id, run_id=self.run_id,
                    parent_id=self._current.id if self._current else None,
                    seq=next(self._seq), stage=stage, role=role, started_at=_now())
        self.store.append_step(step)
        self.emit(Event(type="step.started", case_id=case_id, step=step, at=step.started_at))
        prev, self._current = self._current, step
        try:
            yield step
            if step.status == StepStatus.running:
                step.status = StepStatus.ok
        except Exception as e:
            step.status = StepStatus.failed
            step.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            self._current = prev
            step.ended_at = _now()
            step.duration_ms = int((step.ended_at - step.started_at).total_seconds() * 1000)
            self.store.append_step(step)
            self.emit(Event(type="step.finished", case_id=case_id, step=step, at=step.ended_at))

    def annotate(self, **fields) -> None:
        """Set fields on the current step: status, skill, skill_version, inputs, outputs, detail, tokens..."""
        if self._current is None:
            raise RuntimeError("annotate() called outside a trace step")
        detail = fields.pop("detail", None)
        for k, v in fields.items():
            setattr(self._current, k, v)
        if detail:
            self._current.detail.update(detail)
