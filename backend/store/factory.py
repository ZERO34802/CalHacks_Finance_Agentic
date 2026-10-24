"""Back-compat alias for D's code: the one store factory is `backend.store.get_store` (RECONAI_STORE)."""
from __future__ import annotations

from backend.store import get_store
from backend.store.base import Store


def make_store() -> Store:
    return get_store()
