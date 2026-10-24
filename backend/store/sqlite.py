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
from contracts import (Case, ContractTerm, Document, Employee, MemoryEntry, PaidInvoice, PO, Receipt, Scoreboard,
                       Step, Vendor)

T = TypeVar("T", bound=BaseModel)

DEFAULT_DB = os.environ.get("RECONAI_DB", str(ROOT / ".data" / "reconai.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases   (id TEXT PRIMARY KEY, vendor_id TEXT, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fingerprints (fp TEXT PRIMARY KEY, case_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (sha256 TEXT NOT NULL, case_id TEXT NOT NULL, doc_id TEXT NOT NULL,
                                      body TEXT NOT NULL, PRIMARY KEY (case_id, doc_id));
CREATE INDEX IF NOT EXISTS documents_sha ON documents(sha256);
CREATE TABLE IF NOT EXISTS world (kind TEXT NOT NULL, key TEXT NOT NULL, idx TEXT NOT NULL, body TEXT NOT NULL,
                                  PRIMARY KEY (kind, key));
CREATE INDEX IF NOT EXISTS world_idx ON world(kind, idx);
CREATE TABLE IF NOT EXISTS steps   (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, run_id TEXT NOT NULL,
                                    seq INTEGER NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS steps_case ON steps(case_id, run_id, seq);
CREATE TABLE IF NOT EXISTS vendors (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory  (id TEXT PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scoreboards (run_id TEXT PRIMARY KEY, at TEXT NOT NULL, body TEXT NOT NULL);
"""


class SQLiteStore:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
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
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO cases VALUES (?, ?, ?)", (case.id, case.vendor_id, case.model_dump_json()))
            for d in case.documents:
                self._db.execute("INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?)",
                                 (d.sha256, case.id, d.id, d.model_dump_json()))
            self._db.commit()

    def get_case(self, case_id: str) -> Optional[Case]:
        found = self._load(Case, self._exec("SELECT body FROM cases WHERE id=?", (case_id,)))
        return found[0] if found else None

    def list_cases(self, vendor_id: Optional[str] = None) -> list[Case]:
        if vendor_id:
            return self._load(Case, self._exec("SELECT body FROM cases WHERE vendor_id=? ORDER BY id", (vendor_id,)))
        return self._load(Case, self._exec("SELECT body FROM cases ORDER BY id"))

    def claim_fingerprint(self, fingerprint: str, case_id: str) -> str:
        with self._lock:  # INSERT OR IGNORE + SELECT under one lock = atomic insert-or-get
            self._db.execute("INSERT OR IGNORE INTO fingerprints VALUES (?, ?)", (fingerprint, case_id))
            owner = self._db.execute("SELECT case_id FROM fingerprints WHERE fp=?", (fingerprint,)).fetchone()[0]
            self._db.commit()
            return owner

    def find_documents(self, sha256: str) -> list[tuple[str, Document]]:
        rows = self._exec("SELECT case_id, body FROM documents WHERE sha256=? ORDER BY case_id", (sha256,))
        return [(r[0], Document.model_validate_json(r[1])) for r in rows]

    # system of record
    def _put(self, kind: str, key: str, idx: str, model: BaseModel) -> None:
        self._exec("INSERT OR REPLACE INTO world VALUES (?, ?, ?, ?)", (kind, key, idx, model.model_dump_json()))

    def _get(self, model: type[T], kind: str, key: str) -> Optional[T]:
        found = self._load(model, self._exec("SELECT body FROM world WHERE kind=? AND key=?", (kind, key)))
        return found[0] if found else None

    def _list(self, model: type[T], kind: str, idx: Optional[str] = None) -> list[T]:
        if idx is None:
            return self._load(model, self._exec("SELECT body FROM world WHERE kind=? ORDER BY key", (kind,)))
        return self._load(model, self._exec("SELECT body FROM world WHERE kind=? AND idx=? ORDER BY key", (kind, idx)))

    _RESERVED = {"po", "receipt", "term", "paid", "employee"}

    def put_record(self, kind: str, key: str, model: BaseModel, idx: str = "") -> None:
        assert kind not in self._RESERVED, kind
        self._put(kind, key, idx, model)

    def get_record(self, model: type[T], kind: str, key: str) -> Optional[T]:
        return self._get(model, kind, key)

    def list_records(self, model: type[T], kind: str, idx: Optional[str] = None) -> list[T]:
        return self._list(model, kind, idx)

    def save_po(self, po: PO) -> None: self._put("po", po.po_number, po.vendor_id, po)
    def get_po(self, po_number: str) -> Optional[PO]: return self._get(PO, "po", po_number)
    def save_receipt(self, r: Receipt) -> None: self._put("receipt", r.doc_id, r.po_number, r)
    def list_receipts(self, po_number: str) -> list[Receipt]: return self._list(Receipt, "receipt", po_number)
    def save_contract_term(self, t: ContractTerm) -> None:
        self._put("term", f"{t.doc_id}:{t.sku}", t.vendor_id, t)
    def list_contract_terms(self, vendor_id: str) -> list[ContractTerm]:
        return self._list(ContractTerm, "term", vendor_id)
    def save_paid(self, p: PaidInvoice) -> None: self._put("paid", f"{p.vendor_id}:{p.invoice_no}", p.vendor_id, p)
    def list_paid(self, vendor_id: str) -> list[PaidInvoice]: return self._list(PaidInvoice, "paid", vendor_id)
    def save_employee(self, e: Employee) -> None: self._put("employee", e.id, "", e)
    def list_employees(self) -> list[Employee]: return self._list(Employee, "employee")

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

    def delete_memory(self, entry_id: str) -> None:
        self._exec("DELETE FROM memory WHERE id=?", (entry_id,))

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

    # maintenance
    def reset(self, keep_scoreboards: bool = True) -> None:
        tables = ["cases", "steps", "fingerprints", "documents", "world", "vendors", "memory"]
        if not keep_scoreboards:
            tables.append("scoreboards")
        with self._lock:
            for t in tables:
                self._db.execute(f"DROP TABLE IF EXISTS {t}")
            self._db.executescript(_SCHEMA)  # recreate (also migrates an old-schema dev DB)
            self._db.commit()
