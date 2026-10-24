"""File type by content (magic bytes), never by extension. Owner: A."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Optional

MAX_BYTES = 20 * 1024 * 1024          # per inbound file / attachment
MAX_UNZIPPED = 100 * 1024 * 1024      # zip-bomb guard for xlsx

# extension -> sniffed kinds it may legitimately contain
EXT_KINDS = {
    "pdf": {"pdf"}, "png": {"png"}, "jpg": {"jpeg"}, "jpeg": {"jpeg"},
    "xlsx": {"xlsx"}, "xlsm": {"xlsx", "xlsm"}, "csv": {"csv", "text"}, "json": {"json"},
    "eml": {"eml"}, "txt": {"text", "csv"},
}
MIME = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg", "json": "application/json",
        "csv": "text/csv", "text": "text/plain", "eml": "message/rfc822",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12", "ole": "application/x-ole-storage",
        "zip": "application/zip", "unknown": "application/octet-stream"}


@dataclass
class Sniff:
    kind: str                      # pdf png jpeg xlsx xlsm ole zip json csv text eml unknown
    mime: str
    reject: Optional[str] = None   # quarantine reason, if any


def _decode(data: bytes) -> Optional[str]:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def sniff(data: bytes) -> Sniff:
    def mk(kind: str, reject: Optional[str] = None) -> Sniff:
        return Sniff(kind, MIME[kind], reject)

    if len(data) > MAX_BYTES:
        return mk("unknown", f"file too large ({len(data)} bytes > {MAX_BYTES})")
    if data.startswith(b"%PDF-"):
        if b"/Encrypt" in data[:4096] or b"/Encrypt" in data[-4096:]:
            return mk("pdf", "password-protected / encrypted PDF")
        return mk("pdf")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return mk("png")
    if data.startswith(b"\xff\xd8\xff"):
        return mk("jpeg")
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return mk("ole", "OLE container: password-protected spreadsheet or legacy .xls (macros possible)")
    if data.startswith(b"PK\x03\x04"):
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = z.namelist()
            unzipped = sum(i.file_size for i in z.infolist())
        except zipfile.BadZipFile:
            return mk("zip", "corrupt zip container")
        if unzipped > MAX_UNZIPPED:
            return mk("zip", f"zip bomb guard: {unzipped} bytes uncompressed")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            return mk("xlsm", "macro-enabled spreadsheet (contains vbaProject.bin)")
        if "xl/workbook.xml" in names:
            return mk("xlsx")
        return mk("zip", "unsupported zip container")
    text = _decode(data)
    if text is None:
        return mk("unknown", "unrecognized binary content")
    head = text.lstrip()[:2000]
    if head.startswith("{") or head.startswith("["):
        return mk("json")
    first = head.splitlines()[0] if head else ""
    if any(head.startswith(h) or f"\n{h}" in head for h in ("From:", "Received:", "Return-Path:", "MIME-Version:")) \
            and ("Subject:" in head or "Content-Type:" in head):
        return mk("eml")
    if first.count(",") >= 2 or first.count(";") >= 2:
        return mk("csv")
    return mk("text")


def ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def check_extension(filename: str, s: Sniff) -> Optional[str]:
    """Spoofed type: a known extension whose content is something else."""
    allowed = EXT_KINDS.get(ext_of(filename))
    if allowed is not None and s.kind not in allowed:
        return f"file type spoofing: {filename!r} has content type {s.kind}"
    return None
