"""Load the shared hand-made fixtures from data/. Everyone uses these."""
from __future__ import annotations

import json

from backend.core.config import ROOT
from backend.memory.files import load_memory_dir
from backend.store.base import Store
from contracts import Case, ExpectedOutcome, Vendor

DATA = ROOT / "data"


def load_case(case_id: str) -> Case:
    return Case.model_validate_json((DATA / "cases" / f"{case_id}.json").read_text())


def case_ids() -> list[str]:
    return sorted(p.stem for p in (DATA / "cases").glob("*.json"))


def answer_key() -> dict[str, ExpectedOutcome]:
    rows = json.loads((DATA / "answer_key.json").read_text())
    return {r["case_id"]: ExpectedOutcome.model_validate(r) for r in rows}


def seed(store: Store) -> None:
    """Vendors + memory. Idempotent."""
    for v in json.loads((DATA / "vendors.json").read_text()):
        store.save_vendor(Vendor.model_validate(v))
    for m in load_memory_dir(DATA / "memory"):
        store.save_memory(m)
