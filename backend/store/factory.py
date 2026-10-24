"""Pick the Store implementation from RECONAI_STORE. Owner: D.

  RECONAI_STORE=sqlite     (default) SQLiteStore at RECONAI_DB
  RECONAI_STORE=spacetime  SpacetimeStore (see backend/store/spacetime.py)
"""
from __future__ import annotations

import os

from backend.store.base import Store


def make_store() -> Store:
    kind = os.environ.get("RECONAI_STORE", "sqlite")
    if kind == "sqlite":
        from backend.store.sqlite import SQLiteStore
        return SQLiteStore()
    if kind == "spacetime":
        from backend.store.spacetime import SpacetimeStore
        return SpacetimeStore()
    raise ValueError(f"unknown RECONAI_STORE={kind!r} (sqlite | spacetime)")
