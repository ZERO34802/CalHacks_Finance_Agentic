"""SQLite Store: one table per kind, rows are contract JSON blobs.

Use ":memory:" for tests. Default path comes from RECONAI_DB.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel

from backend.core.config import ROOT
from contracts import Case, MemoryEntry, Scoreboard, Step, Vendor

T = TypeVar("T", bound=BaseModel)

DEFAULT_DB = os.environ.get("RECONAI_DB", str(ROOT / ".data" / "reconai.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases   (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS steps   (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, run_id TEXT NOT NULL,
                                    seq INTEGER NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS steps_case ON steps(case_id, run_id, seq);
CREATE TABLE IF NOT EXISTS vendors (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory  (id TEXT PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scoreboards (run_id TEXT PRIMARY KEY, at TEXT NOT NULL, body TEXT NOT NULL);
"""


class SQLiteStore:
    def __init__(self, path: str = DEFAULT_DB):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
            self._db.commit()
            return rows

    @staticmethod
    def _load(model: type[T], rows: list[tuple]) -> list[T]:
        return [model.model_validate_json(r[0]) for r in rows]

    # cases
    def save_case(self, case: Case) -> None:
        self._exec("INSERT OR REPLACE INTO cases VALUES (?, ?)", (case.id, case.model_dump_json()))

    def get_case(self, case_id: str) -> Optional[Case]:
        found = self._load(Case, self._exec("SELECT body FROM cases WHERE id=?", (case_id,)))
        return found[0] if found else None

    def list_cases(self) -> list[Case]:
        return self._load(Case, self._exec("SELECT body FROM cases ORDER BY id"))

    # trace
    def append_step(self, step: Step) -> None:
        self._exec("INSERT OR REPLACE INTO steps VALUES (?, ?, ?, ?, ?)",
                   (step.id, step.case_id, step.run_id, step.seq, step.model_dump_json()))

    def list_steps(self, case_id: str, run_id: Optional[str] = None) -> list[Step]:
        if run_id is None:  # latest run for this case
            latest = self._exec("SELECT run_id FROM steps WHERE case_id=? ORDER BY rowid DESC LIMIT 1", (case_id,))
            if not latest:
                return []
            run_id = latest[0][0]
        return self._load(Step, self._exec(
            "SELECT body FROM steps WHERE case_id=? AND run_id=? ORDER BY seq", (case_id, run_id)))

    # vendors
    def save_vendor(self, vendor: Vendor) -> None:
        self._exec("INSERT OR REPLACE INTO vendors VALUES (?, ?)", (vendor.id, vendor.model_dump_json()))

    def get_vendor(self, vendor_id: str) -> Optional[Vendor]:
        found = self._load(Vendor, self._exec("SELECT body FROM vendors WHERE id=?", (vendor_id,)))
        return found[0] if found else None

    def list_vendors(self) -> list[Vendor]:
        return self._load(Vendor, self._exec("SELECT body FROM vendors ORDER BY id"))

    # memory
    def save_memory(self, entry: MemoryEntry) -> None:
        self._exec("INSERT OR REPLACE INTO memory VALUES (?, ?, ?)", (entry.id, entry.subject, entry.model_dump_json()))

    def list_memory(self, subject: Optional[str] = None) -> list[MemoryEntry]:
        if subject:
            return self._load(MemoryEntry, self._exec("SELECT body FROM memory WHERE subject=? ORDER BY id", (subject,)))
        return self._load(MemoryEntry, self._exec("SELECT body FROM memory ORDER BY subject, id"))

    # evals
    def save_scoreboard(self, board: Scoreboard) -> None:
        self._exec("INSERT OR REPLACE INTO scoreboards VALUES (?, ?, ?)",
                   (board.run_id, board.at.isoformat(), board.model_dump_json()))

    def latest_scoreboard(self) -> Optional[Scoreboard]:
        found = self._load(Scoreboard, self._exec("SELECT body FROM scoreboards ORDER BY at DESC LIMIT 1"))
        return found[0] if found else None
