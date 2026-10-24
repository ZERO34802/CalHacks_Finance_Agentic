"""C's API routes (auto-included by backend/api/app.py). Thin: no business logic here."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.core.config import load_policy
from backend.evals import metrics
from contracts import BusinessMetrics, Scoreboard

router = APIRouter()


def _store():
    from backend.api import app as app_module  # the app's store (tests monkeypatch it)
    return app_module.store


@router.get("/scoreboard/latest", response_model=Scoreboard)
def scoreboard_latest() -> Scoreboard:
    board = _store().latest_scoreboard()
    if board is None:
        raise HTTPException(404, "no eval run yet; run `make eval`")
    return board


@router.get("/metrics", response_model=BusinessMetrics)
def business_metrics() -> BusinessMetrics:
    """Live business metrics over the cases in the store (hours saved is an ESTIMATE)."""
    return metrics.compute(_store().list_cases(), load_policy())
