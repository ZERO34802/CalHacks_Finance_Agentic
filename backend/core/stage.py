from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Protocol
from uuid import uuid4

from backend.core.config import Policy, load_policy
from contracts import Case

if TYPE_CHECKING:
    from backend.store.base import Store
    from backend.trace.tracer import Tracer


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Ctx:
    """Everything a stage may use. Stages get no other globals."""
    store: "Store"
    trace: "Tracer"
    policy: Policy = field(default_factory=load_policy)
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex[:8]}")
    now: Callable[[], datetime] = utcnow


class Stage(Protocol):
    name: str

    def run(self, case: Case, ctx: Ctx) -> Case: ...
