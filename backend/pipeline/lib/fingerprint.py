"""Case fingerprints (CLAUDE.md section 7, layer 2)."""
from __future__ import annotations

import hashlib
import json
from typing import Iterable, Optional

from backend.pipeline.lib.ids import normalize_invoice_no

INVOICE_LEVEL = "*"   # discrepancy-type / SKU placeholder for the invoice-level fingerprint


def fingerprint(vendor_id: str, po_number: Optional[str], invoice_no: str, dtype: str = INVOICE_LEVEL,
                sku: Optional[str] = None) -> str:
    """hash(canonical vendor id + PO + normalized invoice no + discrepancy type + SKU)."""
    key = [vendor_id, (po_number or "").strip().upper(), normalize_invoice_no(invoice_no), dtype,
           (sku or INVOICE_LEVEL).strip().upper()]
    return "fp_" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:32]


def evidence_hash(doc_hashes: Iterable[str]) -> str:
    """Sorted hashes of every attached source document."""
    return "ev_" + hashlib.sha256("\n".join(sorted(set(doc_hashes))).encode()).hexdigest()[:32]
