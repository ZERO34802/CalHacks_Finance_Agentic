"""Invoice-number normalization, edit distance, line-item hash."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal as D
from typing import Iterable

_PREFIX = re.compile(r"^(INVOICE|INVNO|INV|NO)+(?=\d)")


def normalize_invoice_no(raw: str) -> str:
    """INV-0042, 42, 'inv 42', 'Invoice #42' -> '42'. KM-INV-30152 -> 'KMINV30152'."""
    s = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    s = _PREFIX.sub("", s) or s
    m = re.match(r"^0+(\d.*)$", s)
    return m.group(1) if m else s


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def line_hash(lines: Iterable[tuple[str, object, object]]) -> str:
    """sha256 of sorted (sku, qty, unit_price). Identical to data/build_seed_cases.py:line_hash."""
    canon = sorted((s, str(D(str(q)).normalize()), str(D(str(p)).quantize(D("0.01")))) for s, q, p in lines)
    return hashlib.sha256(json.dumps(canon).encode()).hexdigest()


def invoice_line_hash(invoice) -> str:
    return line_hash((li.sku, li.qty, li.unit_price) for li in invoice.lines)


def is_freight(sku: str, description: str = "") -> bool:
    s, d = (sku or "").upper(), (description or "").lower()
    return s.startswith("FRT") or any(w in d for w in ("freight", "expedite", "shipping", "courier"))
