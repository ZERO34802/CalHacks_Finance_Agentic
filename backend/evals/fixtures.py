"""Load the shared fixtures from data/. Everyone uses these."""
from __future__ import annotations

import json
from pathlib import Path

from backend.core.config import ROOT
from backend.memory.files import load_memory_dir
from backend.store.base import Store
from contracts import (CaseFixture, ContractTerm, Employee, ExpectedOutcome, PaidInvoice, PO, Receipt, Vendor)

DATA = ROOT / "data"
WORLD = DATA / "world"
CASES = DATA / "cases"


def case_dir(case_id: str) -> Path:
    return CASES / case_id


def load_fixture(case_id: str) -> CaseFixture:
    return CaseFixture.model_validate_json((case_dir(case_id) / "case.json").read_text())


def case_ids() -> list[str]:
    return sorted(p.parent.name for p in CASES.glob("*/case.json"))


def answer_key() -> dict[str, ExpectedOutcome]:
    rows = json.loads((DATA / "answer_key.json").read_text())
    return {r["case_id"]: ExpectedOutcome.model_validate(r) for r in rows}


def api_keys() -> dict[str, str]:
    """SIMULATED per-vendor API keys: key -> vendor_id."""
    return json.loads((WORLD / "api_keys.json").read_text())


def _rows(name: str) -> list[dict]:
    path = WORLD / name
    return json.loads(path.read_text()) if path.exists() else []


def seed(store: Store) -> None:
    """System of record + memory. Idempotent."""
    for v in _rows("vendors.json"):
        store.save_vendor(Vendor.model_validate(v))
    for r in _rows("pos.json"):
        store.save_po(PO.model_validate(r))
    for r in _rows("receipts.json"):
        store.save_receipt(Receipt.model_validate(r))
    for r in _rows("contract_terms.json"):
        store.save_contract_term(ContractTerm.model_validate(r))
    for r in _rows("paid_history.json"):
        store.save_paid(PaidInvoice.model_validate(r))
    for r in _rows("employees.json"):
        store.save_employee(Employee.model_validate(r))
    for m in load_memory_dir(DATA / "memory"):
        store.save_memory(m)


def load_case(case_id: str, store: Store | None = None):
    """A fixture as a Case after intake only (documents attached, nothing extracted or decided).
    Back-compat for code written against the skeleton's pre-parsed case JSON."""
    from backend.core.runner import make_ctx
    from backend.intake.ingest import ingest
    from backend.store.sqlite import SQLiteStore
    if store is None:
        store = SQLiteStore(":memory:")
        seed(store)
    return ingest(load_fixture(case_id), case_dir(case_id), make_ctx(store))
