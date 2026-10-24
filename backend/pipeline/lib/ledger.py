"""Beancount ledger: append-only writer, loader validation, AP balances. Owner: A.

Path: env RECONAI_LEDGER, else next to the store's SQLite file (.data/ledger.beancount for the default DB),
else a per-store temp file for in-memory stores (tests/evals never touch ledger/ in the repo).
The ledger starts as a copy of ledger/main.beancount (opens); missing accounts are opened on demand.
"""
from __future__ import annotations

import fcntl
import os
import re
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Optional

from backend.core.config import ROOT
from contracts import JournalEntry

TEMPLATE = ROOT / "ledger" / "main.beancount"
OPEN_DATE = "2026-01-01"
_tmp_ledgers: dict[int, Path] = {}
_SAFE = re.compile(r"[^A-Za-z0-9 ._/:#&()@+-]")


def ledger_path(store) -> Path:
    env = os.environ.get("RECONAI_LEDGER")
    if env:
        return Path(env)
    explicit = getattr(store, "ledger_path", None)
    if explicit:
        return Path(explicit)
    dbfile = ""
    db = getattr(store, "_db", None)
    if db is not None:
        try:
            dbfile = next((r[2] for r in db.execute("PRAGMA database_list").fetchall() if r[1] == "main"), "")
        except Exception:
            dbfile = ""
    if dbfile:
        return Path(dbfile).parent / "ledger.beancount"
    key = id(store)
    if key not in _tmp_ledgers:
        _tmp_ledgers[key] = Path(tempfile.mkdtemp(prefix="reconai-ledger-")) / "ledger.beancount"
    return _tmp_ledgers[key]


def safe(text: str) -> str:
    """Untrusted vendor text never reaches the ledger syntax unescaped."""
    return _SAFE.sub("", text or "")[:120]


@contextmanager
def locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def ensure(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE.read_text())


def opened_accounts(text: str) -> set[str]:
    return set(re.findall(r"^\d{4}-\d{2}-\d{2}\s+open\s+(\S+)", text, re.M))


def render(je: JournalEntry, payee: str, new_accounts: list[str]) -> str:
    out = [f"\n{OPEN_DATE} open {a}" for a in new_accounts]
    out.append(f'\n{je.date.isoformat()} * "{safe(payee)}" "{safe(je.narration)}"')
    for k, v in (("case_id", je.case_id), ("je_id", je.id), ("idempotency_key", je.idempotency_key),
                 ("requested_by", je.requested_by), ("approved_by", je.approved_by or "")):
        out.append(f'  {k}: "{safe(v)}"')
    for p in je.postings:
        out.append(f"  {p.account:<40} {p.amount:>20} {p.currency}")
    return "\n".join(out) + "\n"


def load(path: Path):
    from beancount import loader
    entries, errors, _ = loader.load_file(str(path))
    return entries, errors


def find_key(entries, key: str):
    from beancount.core import data
    for e in entries:
        if isinstance(e, data.Transaction) and e.meta.get("idempotency_key") == key:
            return e
    return None


def ap_balances(entries, prefix: str) -> dict[str, Decimal]:
    """Sum of postings to `prefix:*` (and prefix itself), per currency."""
    from beancount.core import data
    out: dict[str, Decimal] = {}
    for e in entries:
        if isinstance(e, data.Transaction):
            for p in e.postings:
                if p.account == prefix or p.account.startswith(prefix + ":"):
                    out[p.units.currency] = out.get(p.units.currency, Decimal(0)) + p.units.number
    return {k: v for k, v in out.items() if v != 0}


def append(path: Path, text: str) -> str:
    """Append and return the previous content (for rollback)."""
    prev = path.read_text()
    with open(path, "a") as f:
        f.write(text)
    return prev
