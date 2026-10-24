"""Trace helper. Every stage is wrapped in `with ctx.trace.step(case_id, name)`.

Records start/finish/duration/status to the store and publishes Events to
subscribers (the API forwards them over WS /events). A stage can add detail
to the current step with `ctx.trace.annotate(...)`.

A stage that raises is recorded as failed and the exception propagates.
A stage can mark a non-ok outcome without raising via annotate(status=...).

Also:
- `ctx.trace.record_llm(result)` adds tokens + cost (USD, Decimal) of a backend.core.llm.LLMResult
  to the current step; cached replays add tokens but cost 0.
- `ctx.trace.record_sandbox(event, **info)` appends a sandbox event (file write, command, denial...).
- Bank / account numbers in step detail and error are masked to the last 4 digits before storing.
"""
from __future__ import annotations

import itertools
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

from backend.store.base import Store
from contracts import Event, Role, Step, StepStatus

Subscriber = Callable[[Event], None]

# Claude Opus 5.5 list pricing, USD per million tokens
PRICE_IN_PER_MTOK = Decimal("4")
PRICE_OUT_PER_MTOK = Decimal("20")
_MTOK = Decimal(1_000_000)

_BANK_KEY = re.compile(r"bank|account|acct|iban|routing|swift|beneficiary", re.I)
_BANK_TEXT = re.compile(r"(?i)\b(account|acct|a/c|iban|routing)(\s*(?:no\.?|number|#)?\s*[:#]?\s*)"
                        r"([A-Z]{0,4}[\d][\d\- ]{4,}\d)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def llm_cost(input_tokens: int, output_tokens: int) -> Decimal:
    return (Decimal(input_tokens) * PRICE_IN_PER_MTOK + Decimal(output_tokens) * PRICE_OUT_PER_MTOK) / _MTOK


def _mask_digits(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    return f"****{digits[-4:]}" if len(digits) > 4 else s


def mask(value: Any, key: str = "") -> Any:
    """Mask bank/account numbers to the last 4 digits. Keys that look like bank fields are masked when the
    value has more than 4 digits; free text is masked where it says 'account no. 12345678' etc."""
    if isinstance(value, dict):
        return {k: mask(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask(v, key) for v in value]
    if isinstance(value, str):
        if key and _BANK_KEY.search(key) and len(re.sub(r"\D", "", value)) > 4 and not re.search(r"[a-z]{3,}", value):
            return _mask_digits(value)
        return _BANK_TEXT.sub(lambda m: m.group(1) + m.group(2) + _mask_digits(m.group(3)), value)
    if isinstance(value, int) and not isinstance(value, bool) and key and _BANK_KEY.search(key) and value > 9999:
        return f"****{str(value)[-4:]}"
    return value


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

    @property
    def current(self) -> Optional[Step]:
        return self._current

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
            step.detail = mask(step.detail)
            if step.error:
                step.error = mask(step.error)
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

    def record_llm(self, result: Any, role: Optional[str] = None) -> None:
        """Add an LLMResult's tokens and cost to the current step (no-op outside a step)."""
        if self._current is None:
            return
        tin, tout = int(getattr(result, "input_tokens", 0)), int(getattr(result, "output_tokens", 0))
        cached = bool(getattr(result, "cached", False))
        cost = Decimal(0) if cached else llm_cost(tin, tout)
        s = self._current
        s.tokens += tin + tout
        s.cost_usd = ((s.cost_usd or Decimal(0)) + cost).quantize(Decimal("0.000001"))
        s.detail.setdefault("llm_calls", []).append(
            {"role": role, "input_tokens": tin, "output_tokens": tout, "cached": cached, "cost_usd": str(cost)})

    def record_sandbox(self, event: str, **info: Any) -> None:
        """Append a sandbox event, e.g. record_sandbox('write', path='scratch/plan.md') or ('denied', ...)."""
        if self._current is None:
            return
        self._current.detail.setdefault("sandbox_events", []).append(mask({"event": event, "at": _now().isoformat(),
                                                                           **info}))
