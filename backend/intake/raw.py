"""Content-addressed raw blob store (sha256 -> bytes). Owner: A.

Documents carry only text; the Reader needs the original bytes (PDF, image, xlsx). Intake writes every
file and attachment here; quarantined payloads are kept raw too (stored, not processed, not dropped).
Fallback: re-scan the fixture folder data/cases/<case_id>/ by hash.
"""
from __future__ import annotations

import hashlib
import os
from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path
from typing import Optional

from backend.core.config import ROOT
from contracts import Case, Document

BLOBS = Path(os.environ.get("RECONAI_BLOBS", str(ROOT / ".data" / "blobs")))


def put_raw(data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    p = BLOBS / sha
    if not p.exists():
        BLOBS.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".tmp{os.getpid()}")
        tmp.write_bytes(data)
        tmp.replace(p)
    return sha


def _scan_folder(folder: Path, sha: str) -> Optional[bytes]:
    if not folder.is_dir():
        return None
    for f in folder.iterdir():
        if not f.is_file() or f.name == "case.json":
            continue
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha:
            return data
        if f.suffix.lower() == ".eml":
            msg = BytesParser(policy=email_policy.default).parsebytes(data)
            for part in msg.iter_attachments():
                payload = part.get_payload(decode=True) or b""
                if hashlib.sha256(payload).hexdigest() == sha:
                    return payload
    return None


def load_raw(case: Case, doc: Document) -> Optional[bytes]:
    p = BLOBS / doc.sha256
    if p.exists():
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() == doc.sha256:
            return data
    from backend.evals.fixtures import case_dir
    return _scan_folder(case_dir(case.id), doc.sha256)
