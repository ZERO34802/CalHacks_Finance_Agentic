"""Store factory. RECONAI_STORE=sqlite (default) | spacetime.

    from backend.store import get_store
    store = get_store()            # what the API, scripts and evals use
"""
from __future__ import annotations

import os
from typing import Optional

from backend.store.base import Store


def get_store(kind: Optional[str] = None, **kwargs) -> Store:
    kind = (kind or os.environ.get("RECONAI_STORE", "sqlite")).lower()
    if kind == "sqlite":
        from backend.store.sqlite import SQLiteStore
        return SQLiteStore(**kwargs)
    if kind == "spacetime":
        from backend.store.spacetime import SpacetimeStore
        return SpacetimeStore(**kwargs)
    raise ValueError(f"RECONAI_STORE must be sqlite or spacetime, got {kind!r}")
