"""Shared setup for D's tests: real fixtures through the real pipeline, offline (LLM + Droid off).

Offline, structured fixtures (API JSON, CSV, XLSX, ERP export) get real invoices; PDF / image / email
invoices escalate as "evidence missing". `variant()` copies a structured fixture with an edited payload, e.g.
a changed bank account, so the bank-change / duplicate paths can be exercised offline too.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable, Optional

import pytest
from fastapi.testclient import TestClient

from backend.ap.payments import PaymentStore
from backend.core.runner import make_ctx, run_fixture
from backend.evals.fixtures import case_dir, case_ids, load_fixture, seed
from backend.store.sqlite import SQLiteStore

# structured fixtures that read offline (no LLM)
OFFLINE = ["case_03", "case_06", "case_07", "case_10", "case_11", "case_21", "case_25", "case_27", "case_33",
           "case_39", "case_40", "case_41", "case_43"]


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("RECONAI_LLM", "off")
    monkeypatch.setenv("RECONAI_DROID", "off")
    monkeypatch.setenv("RECONAI_CHAT", "offline")
    monkeypatch.setenv("RECONAI_LEDGER", str(tmp_path / "ledger.beancount"))
    monkeypatch.delenv("CRS_BASE_URL", raising=False)
    return tmp_path


def fresh_store() -> SQLiteStore:
    store = SQLiteStore(":memory:")
    seed(store)
    return store


def run(store, *ids: str):
    ctx = make_ctx(store)
    out = [run_fixture(load_fixture(cid), case_dir(cid), ctx) for cid in (ids or case_ids())]
    return out[-1] if len(out) == 1 else out


def variant(store, tmp: Path, cid: str, new_id: str, edit: Optional[Callable[[dict], None]] = None):
    """Run a copy of a structured fixture under a new id, with its JSON payload edited."""
    src, dst = case_dir(cid), tmp / new_id
    shutil.copytree(src, dst)
    fx = load_fixture(cid)
    fx.id = new_id
    if edit:
        payload = dst / fx.inbound[0].path
        data = json.loads(payload.read_text())
        edit(data)
        payload.write_text(json.dumps(data))
    return run_fixture(fx, dst, make_ctx(store))


def client(monkeypatch, store) -> TestClient:
    import backend.api.app as app_module
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "payments", PaymentStore(":memory:"))
    monkeypatch.setattr(app_module, "DEMO_PACE", 0)
    return TestClient(app_module.app)
