"""SpacetimeDB Store: same Protocol as SQLiteStore, backed by the `reconai` module (spacetime/spacetimedb).

There is no maintained Python SDK, so this talks HTTP:
  writes  -> POST /v1/database/<db>/call/<reducer>   (JSON array of args; 200 = ok, 530 = reducer error)
  reads   -> POST /v1/database/<db>/sql              (raw SQL; rows come back as arrays in column order)
Spacetime SQL has no ORDER BY / LIMIT, so ordering is done here.

Env: RECONAI_SPACETIME_URL (default http://127.0.0.1:3000), RECONAI_SPACETIME_DB (default reconai),
     RECONAI_SPACETIME_TOKEN (optional; otherwise a fresh identity is requested).
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional, TypeVar

import httpx
from pydantic import BaseModel

from contracts import (Case, ContractTerm, Document, Employee, MemoryEntry, PaidInvoice, PO, Receipt, Scoreboard,
                       Step, Vendor)

T = TypeVar("T", bound=BaseModel)

DEFAULT_URL = os.environ.get("RECONAI_SPACETIME_URL", "http://127.0.0.1:3000")
DEFAULT_DB = os.environ.get("RECONAI_SPACETIME_DB", "reconai")


class SpacetimeError(RuntimeError):
    pass


def _q(s: str) -> str:
    """SQL string literal."""
    return "'" + s.replace("'", "''") + "'"


def reachable(url: str = DEFAULT_URL, db: str = DEFAULT_DB, timeout: float = 1.0) -> bool:
    """True if the server is up and the module is published (a trivial SQL query succeeds)."""
    try:
        with httpx.Client(base_url=url, timeout=timeout) as c:
            tok = c.post("/v1/identity").json()["token"]
            r = c.post(f"/v1/database/{db}/sql", headers={"Authorization": f"Bearer {tok}"},
                       content="SELECT fp FROM fingerprints WHERE fp = '__ping__'")
            return r.status_code == 200
    except Exception:
        return False


class SpacetimeStore:
    def __init__(self, url: str = DEFAULT_URL, db: str = DEFAULT_DB, token: Optional[str] = None,
                 timeout: float = 30.0):
        self.db = db
        self._http = httpx.Client(base_url=url, timeout=timeout)
        token = token or os.environ.get("RECONAI_SPACETIME_TOKEN")
        if not token:
            r = self._http.post("/v1/identity")
            if r.status_code != 200:
                raise SpacetimeError(f"identity: {r.status_code} {r.text}")
            token = r.json()["token"]
        self._auth = {"Authorization": f"Bearer {token}"}

    # --- transport ---------------------------------------------------------------

    def _call(self, reducer: str, *args: Any) -> None:
        r = self._http.post(f"/v1/database/{self.db}/call/{reducer}", content=json.dumps(list(args)),
                            headers={**self._auth, "Content-Type": "application/json"})
        if r.status_code != 200:
            raise SpacetimeError(f"{reducer}: {r.status_code} {r.text[:500]}")

    def _sql(self, sql: str) -> list[list[Any]]:
        r = self._http.post(f"/v1/database/{self.db}/sql", content=sql.encode(), headers=self._auth)
        if r.status_code != 200:
            raise SpacetimeError(f"sql: {r.status_code} {r.text[:500]} ({sql[:200]})")
        out: list[list[Any]] = []
        for stmt in r.json():
            out.extend(stmt.get("rows", []))
        return out

    @staticmethod
    def _load(model: type[T], bodies: list[str]) -> list[T]:
        return [model.model_validate_json(b) for b in bodies]

    # --- cases -------------------------------------------------------------------

    def save_case(self, case: Case) -> None:
        docs = [{"sha256": d.sha256, "doc_id": d.id, "body": d.model_dump_json()} for d in case.documents]
        self._call("save_case", case.id, case.vendor_id, case.status.value, case.model_dump_json(), json.dumps(docs))

    def get_case(self, case_id: str) -> Optional[Case]:
        rows = self._sql(f"SELECT body FROM cases WHERE id = {_q(case_id)}")
        return Case.model_validate_json(rows[0][0]) if rows else None

    def list_cases(self, vendor_id: Optional[str] = None) -> list[Case]:
        where = f" WHERE vendor_id = {_q(vendor_id)}" if vendor_id else ""
        rows = sorted(self._sql(f"SELECT id, body FROM cases{where}"), key=lambda r: r[0])
        return self._load(Case, [r[1] for r in rows])

    def claim_fingerprint(self, fingerprint: str, case_id: str) -> str:
        self._call("claim_fingerprint", fingerprint, case_id)  # transactional insert-if-absent
        rows = self._sql(f"SELECT case_id FROM fingerprints WHERE fp = {_q(fingerprint)}")
        return rows[0][0]

    def find_documents(self, sha256: str) -> list[tuple[str, Document]]:
        rows = sorted(self._sql(f"SELECT case_id, doc_id, body FROM documents WHERE sha256 = {_q(sha256)}"),
                      key=lambda r: (r[0], r[1]))
        return [(r[0], Document.model_validate_json(r[2])) for r in rows]

    # --- trace -------------------------------------------------------------------

    def append_step(self, step: Step) -> None:
        self._call("append_step", step.id, step.case_id, step.run_id, step.seq, step.status.value,
                   step.model_dump_json())

    def list_steps(self, case_id: str, run_id: Optional[str] = None) -> list[Step]:
        rows = self._sql(f"SELECT run_id, seq, ord, body FROM steps WHERE case_id = {_q(case_id)}")
        if not rows:
            return []
        if run_id is None:  # latest run for this case
            run_id = max(rows, key=lambda r: int(r[2]))[0]
        rows = sorted((r for r in rows if r[0] == run_id), key=lambda r: int(r[1]))
        return self._load(Step, [r[3] for r in rows])

    # --- system of record ----------------------------------------------------------

    def _put(self, kind: str, key: str, idx: str, model: BaseModel) -> None:
        self._call("put_world", json.dumps([{"kind": kind, "key": key, "idx": idx, "body": model.model_dump_json()}]))

    def _get(self, model: type[T], kind: str, key: str) -> Optional[T]:
        rows = self._sql(f"SELECT body FROM world WHERE key = {_q(f'{kind}|{key}')}")
        return model.model_validate_json(rows[0][0]) if rows else None

    def _list(self, model: type[T], kind: str, idx: Optional[str] = None) -> list[T]:
        where = f"kind = {_q(kind)}" + (f" AND idx = {_q(idx)}" if idx is not None else "")
        rows = sorted(self._sql(f"SELECT key, body FROM world WHERE {where}"), key=lambda r: r[0])
        return self._load(model, [r[1] for r in rows])

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

    # --- vendors -------------------------------------------------------------------

    def save_vendor(self, vendor: Vendor) -> None:
        self._call("put_vendor", vendor.id, vendor.model_dump_json())

    def get_vendor(self, vendor_id: str) -> Optional[Vendor]:
        rows = self._sql(f"SELECT body FROM vendors WHERE id = {_q(vendor_id)}")
        return Vendor.model_validate_json(rows[0][0]) if rows else None

    def list_vendors(self) -> list[Vendor]:
        rows = sorted(self._sql("SELECT id, body FROM vendors"), key=lambda r: r[0])
        return self._load(Vendor, [r[1] for r in rows])

    # --- memory --------------------------------------------------------------------

    def save_memory(self, entry: MemoryEntry) -> None:
        self._call("put_memory", entry.id, entry.subject, entry.model_dump_json())

    def list_memory(self, subject: Optional[str] = None) -> list[MemoryEntry]:
        if subject:
            rows = sorted(self._sql(f"SELECT id, subject, body FROM memory WHERE subject = {_q(subject)}"),
                          key=lambda r: r[0])
        else:
            rows = sorted(self._sql("SELECT id, subject, body FROM memory"), key=lambda r: (r[1], r[0]))
        return self._load(MemoryEntry, [r[2] for r in rows])

    # --- evals ---------------------------------------------------------------------

    def save_scoreboard(self, board: Scoreboard) -> None:
        self._call("put_scoreboard", board.run_id, board.at.isoformat(), board.model_dump_json())

    def latest_scoreboard(self) -> Optional[Scoreboard]:
        rows = self._sql("SELECT at, body FROM scoreboards")
        if not rows:
            return None
        return Scoreboard.model_validate_json(max(rows, key=lambda r: r[0])[1])

    # --- maintenance -----------------------------------------------------------------

    def reset(self, keep_scoreboards: bool = True) -> None:
        self._call("reset", keep_scoreboards)
