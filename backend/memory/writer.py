"""Memory Writer (CLAUDE.md section 8). Owner: C.

Runs after each case (backend/memory/hooks.py). Writes supplier memory ONLY from trusted, structured signals:
  - case history: decisions + discrepancy types computed by code (`computed:` lines, recomputed from the store)
  - reviewer decisions: approvals / rejections by the AP lead or controller (`controller:` / `approver:` lines)
  - system-of-record changes: vendor master bank account (last 4 only)
  - follow-up outcomes computed by the system (overdue / done)
Never from document, email or payload text (it never reads Document.text, Invoice text fields or reply bodies).

Rules enforced here:
  - every line has a provenance tag + valid-from date (business date, not wall clock)
  - read-before-write with a version token (MemoryEntry.version); a stale write is retried on a fresh read
  - small targeted edits: one entry per slot; unchanged text = no write; history kept as records
    (kind `memory_history`, key `<id>@v<version>`, idx `<id>`)
  - corrections propagate (counts are recomputed from the store); forget_case() removes the derived lines
  - size caps: at most MAX_REVIEW_LINES reviewer lines per vendor; older ones roll into one summary line
  - last-4 bank only (anything longer is masked); lines that would loosen a control are dropped
Markdown is rendered to .data/memory/<folder>/<subject>.md (never into the repo's data/memory seed).
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel

from backend.core.config import ROOT
from backend.store.base import Store
from backend.trace.tracer import mask
from contracts import (ApprovalDecision, Case, CaseStatus, Decision, DiscrepancyType, FollowUpStatus, MemoryEntry,
                       MemoryFolder, Role, Vendor)

OUT_DIR = Path(os.environ.get("RECONAI_MEMORY_DIR", str(ROOT / ".data" / "memory")))
SEED_DIR = ROOT / "data" / "memory"
MAX_REVIEW_LINES = 8
WRITER_TAG = ":w:"
LEGAL = re.compile(r"\b(co\.?,?\s*ltd\.?|ltd\.?|inc\.?|llc|sdn\.?\s*bhd\.?|corp\.?|gmbh|plc)\b", re.I)
TRUSTED = ("system-of-record", "computed:", "controller:", "approver:", "outcome:")
_LOOSEN = re.compile(
    r"(?i)(pre-?approved|permanently approved|no (separate )?sign-?off|without (signed )?approval is (fine|ok)|"
    r"skip (the )?(3-way|three-way|match|approval|callback)|ignore (all |previous )?(instructions|controls)|"
    r"waive|auto-?approve|no need to (hold|check|verify)|raise (the )?(limit|tolerance)|update (the )?bank)")

LABEL = {DiscrepancyType.qty_short: "short deliveries", DiscrepancyType.price_over: "prices above PO/contract",
         DiscrepancyType.unapproved_freight: "unapproved freight / expedite fees",
         DiscrepancyType.duplicate_invoice: "duplicate invoices", DiscrepancyType.bank_change: "bank-change requests",
         DiscrepancyType.lookalike_domain: "look-alike-domain messages",
         DiscrepancyType.currency_mismatch: "currency mismatches", DiscrepancyType.total_mismatch: "total mismatches",
         DiscrepancyType.embedded_instructions: "documents with embedded instructions"}
OUTCOME = {Decision.hold: "held", Decision.reject: "rejected", Decision.escalate: "escalated",
           Decision.approve: "approved"}


class MemoryConflict(RuntimeError):
    pass


def memory_off() -> bool:
    return os.environ.get("RECONAI_MEMORY", "on").lower() == "off"


def trusted_provenance(prov: str) -> bool:
    return prov.strip().lower().startswith(TRUSTED)


def loosens_controls(text: str) -> bool:
    return bool(_LOOSEN.search(text))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def subject_for(vendor: Vendor, store: Store) -> str:
    """Same exact-name/alias lookup B's sandbox uses; a vendor without a file gets slug(legal name minus suffix)."""
    names = [vendor.name, *vendor.aliases]
    candidates = list(dict.fromkeys([_slug(n) for n in names] + [_slug(LEGAL.sub("", n)) for n in names]))
    for c in candidates:
        if store.list_memory(c):
            return c
    return _slug(LEGAL.sub("", vendor.name)) or _slug(vendor.id)


def sanitize(text: str) -> str:
    text = mask({"text": text})["text"]
    # any long digit run next to bank words -> last 4 only (belt and braces on top of the tracer mask)
    text = re.sub(r"(?i)(bank|account|acct|iban)([^0-9]{0,20})(\d[\d\- ]{4,}\d)",
                  lambda m: m.group(1) + m.group(2) + "****" + re.sub(r"\D", "", m.group(3))[-4:], text)
    return " ".join(text.split())[:240]


# --- versioned writes ---------------------------------------------------------------------

def _history(store: Store, old: MemoryEntry) -> None:
    store.put_record("memory_history", f"{old.id}@v{old.version}", old, idx=old.id)


def write_entry(store: Store, entry: MemoryEntry, expected_version: Optional[int]) -> Optional[MemoryEntry]:
    """Compare-and-set on MemoryEntry.version. Returns the stored entry, or None when nothing changed."""
    if not trusted_provenance(entry.provenance) or loosens_controls(entry.text):
        return None  # never store untrusted lines or lines that loosen controls
    entry = entry.model_copy(update={"text": sanitize(entry.text)})
    current = next((m for m in store.list_memory(entry.subject) if m.id == entry.id), None)
    cur_version = current.version if current else None
    if cur_version != expected_version:
        raise MemoryConflict(f"{entry.id}: expected v{expected_version}, store has v{cur_version}")
    if current and current.text == entry.text and current.provenance == entry.provenance:
        return None
    if current:
        _history(store, current)
    new = entry.model_copy(update={"version": (current.version + 1) if current else 1})
    store.save_memory(new)
    return new


def upsert(store: Store, entry: MemoryEntry) -> Optional[MemoryEntry]:
    """Read-before-write: read the version token, then write; one retry on a concurrent change."""
    for _ in range(2):
        current = next((m for m in store.list_memory(entry.subject) if m.id == entry.id), None)
        try:
            return write_entry(store, entry, current.version if current else None)
        except MemoryConflict:
            continue
    raise MemoryConflict(entry.id)


def delete(store: Store, entry: MemoryEntry, reason: str) -> None:
    _history(store, entry.model_copy(update={"text": f"{entry.text} [forgotten: {reason}]"}))
    store.delete_memory(entry.id)


# --- forgetting ------------------------------------------------------------------------------

class Forgotten(BaseModel):
    case_id: str
    by: str
    reason: str = ""


def forgotten_cases(store: Store) -> set[str]:
    return {f.case_id for f in store.list_records(Forgotten, "memory_forget")}


def forget_case(store: Store, case_id: str, by: str, reason: str = "") -> None:
    """Remove every line derived from this case; counts are recomputed without it."""
    store.put_record("memory_forget", case_id, Forgotten(case_id=case_id, by=by, reason=reason))
    for m in store.list_memory():
        if WRITER_TAG in m.id and re.search(rf"\b{re.escape(case_id)}\b", m.provenance + " " + m.id):
            delete(store, m, f"case {case_id} forgotten by {by}")
    for c in store.list_cases():
        if c.id == case_id:
            vendor = store.get_vendor(c.vendor_id)
            if vendor:
                refresh_vendor(store, vendor, c.as_of or date.today())


def correct(store: Store, entry_id: str, new_text: str, by: str, on: date) -> Optional[MemoryEntry]:
    """Human correction of a line. History is kept ('previously ...'); derived counts are recomputed on the next
    case, because they are always computed from the store."""
    current = next((m for m in store.list_memory() if m.id == entry_id), None)
    if current is None:
        return None
    return upsert(store, current.model_copy(update={
        "text": f"{new_text} (previously: {current.text})", "provenance": f"controller: {by}, {on.isoformat()}",
        "valid_from": on}))


# --- signals -------------------------------------------------------------------------------

def _vendor_cases(store: Store, vendor_id: str) -> list[Case]:
    gone = forgotten_cases(store)
    return [c for c in store.list_cases(vendor_id) if c.parent_id is None and c.id not in gone]


def _counts(cases: Iterable[Case]) -> dict[DiscrepancyType, list[Case]]:
    by: dict[DiscrepancyType, list[Case]] = defaultdict(list)
    for c in cases:
        if c.decision in (None, Decision.approve):
            continue
        for t in sorted({d.type for d in c.discrepancies if d.material and d.type in LABEL}, key=lambda t: t.value):
            by[t].append(c)
    return by


def refresh_vendor(store: Store, vendor: Vendor, on: date) -> list[str]:
    """Recompute this vendor's computed lines from case history + system of record. Returns written ids."""
    subject = subject_for(vendor, store)
    written: list[str] = []
    cases = _vendor_cases(store, vendor.id)
    for t, cs in _counts(cases).items():
        ids = ", ".join(c.id for c in cs)
        outcomes = defaultdict(int)
        for c in cs:
            outcomes[OUTCOME[c.decision]] += 1
        summary = ", ".join(f"{n} {o}" for o, n in sorted(outcomes.items()))
        e = MemoryEntry(id=f"{subject}{WRITER_TAG}count:{t.value}", folder=MemoryFolder.counterparties,
                        subject=subject, text=f"{len(cs)} {LABEL[t]} in case history ({summary})",
                        provenance=f"computed: cases {ids}", valid_from=max(c.as_of or on for c in cs))
        if upsert(store, e):
            written.append(e.id)
    # system of record: bank on file (last 4 only)
    lines = store.list_memory(subject)
    if not any(f"last 4: {vendor.bank_last4}" in m.text for m in lines if WRITER_TAG not in m.id):
        prev = next((m for m in lines if m.id == f"{subject}{WRITER_TAG}sor:bank"), None)
        old = re.search(r"last 4: (\d{4})", prev.text).group(1) if prev and "last 4:" in prev.text else None
        if old != vendor.bank_last4:
            seed_old = next((re.search(r"last 4: (\d{4})", m.text).group(1) for m in lines
                             if "last 4:" in m.text and WRITER_TAG not in m.id), None)
            was = old or seed_old
            e = MemoryEntry(id=f"{subject}{WRITER_TAG}sor:bank", folder=MemoryFolder.counterparties, subject=subject,
                            text=f"Approved bank account on file (last 4: {vendor.bank_last4})"
                                 + (f", previously {was}" if was else ""),
                            provenance="system-of-record", valid_from=on)
            if upsert(store, e):
                written.append(e.id)
    return written


def _reviews(store: Store, case: Case, subject: str) -> list[str]:
    written = []
    for i, a in enumerate(case.approvals):
        if a.role not in (Role.approver, Role.controller) or a.decision == ApprovalDecision.ask:
            continue
        if a.decision == ApprovalDecision.approved and a.scope != "undisputed":
            continue  # routine full approvals are case history, not memory
        verb = "approved" if a.decision == ApprovalDecision.approved else "rejected"
        scope = " (undisputed part only)" if a.scope == "undisputed" else ""
        comment = sanitize(a.comment) if a.comment and not loosens_controls(a.comment) else ""
        e = MemoryEntry(id=f"{subject}{WRITER_TAG}review:{case.id}:{i}", folder=MemoryFolder.counterparties,
                        subject=subject,
                        text=f"{a.role.value} {verb}{scope} on {case.id}"
                             + (f" ({case.invoice.invoice_no})" if case.invoice else "")
                             + (f": {comment}" if comment else ""),
                        provenance=f"{a.role.value}: {a.approver}, {a.at.date().isoformat()}",
                        valid_from=case.as_of or a.at.date())
        if upsert(store, e):
            written.append(e.id)
    return written


def _followups(store: Store, case: Case, subject: str) -> list[str]:
    written = []
    for fu in case.follow_ups:
        if fu.status == FollowUpStatus.open:
            continue
        state = "overdue (not received)" if fu.status == FollowUpStatus.overdue else "received"
        e = MemoryEntry(id=f"{subject}{WRITER_TAG}followup:{fu.id}", folder=MemoryFolder.counterparties,
                        subject=subject, text=f"{case.id}: {fu.kind.value} due {fu.due.isoformat()} {state}",
                        provenance=f"computed: case {case.id}, follow-up {fu.id}", valid_from=case.as_of or fu.due)
        if upsert(store, e):
            written.append(e.id)
    return written


def _cap(store: Store, subject: str, on: date) -> list[str]:
    reviews = sorted((m for m in store.list_memory(subject) if f"{WRITER_TAG}review:" in m.id),
                     key=lambda m: (m.valid_from, m.id))
    if len(reviews) <= MAX_REVIEW_LINES:
        return []
    old, keep = reviews[:-MAX_REVIEW_LINES], reviews[-MAX_REVIEW_LINES:]
    summary_id = f"{subject}{WRITER_TAG}review-summary"
    prev = next((m for m in store.list_memory(subject) if m.id == summary_id), None)
    n_prev = int(re.match(r"(\d+)", prev.text).group(1)) if prev else 0
    for m in old:
        delete(store, m, "rolled into summary (size cap)")
    cases = sorted({re.search(r"on (\S+)", m.text).group(1) for m in old if re.search(r"on (\S+)", m.text)})
    upsert(store, MemoryEntry(id=summary_id, folder=MemoryFolder.counterparties, subject=subject,
                              text=f"{n_prev + len(old)} older reviewer decisions summarized (latest rolled: "
                                   f"{', '.join(cases)})", provenance="computed: size cap",
                              valid_from=keep[0].valid_from if keep else on))
    return [summary_id]


def after_case(case: Case, store: Store) -> list[str]:
    """Hook body. Returns the ids written (for the trace)."""
    if memory_off() or case.parent_id is not None or case.vendor_id in ("SYSTEM", "V-UNKNOWN"):
        return []
    vendor = store.get_vendor(case.vendor_id)
    if vendor is None or case.status == CaseStatus.quarantined:
        return []
    on = case.as_of or case.created_at.date()
    subject = subject_for(vendor, store)
    written = refresh_vendor(store, vendor, on) + _reviews(store, case, subject) + _followups(store, case, subject)
    written += _cap(store, subject, on)
    if written and getattr(store, "path", None) != ":memory:":  # replay/test stores never touch .data/memory
        render(store, subject, vendor)
    return written


# --- markdown ---------------------------------------------------------------------------------

def _seed_frontmatter(folder: str, subject: str) -> Optional[str]:
    p = SEED_DIR / folder / f"{subject}.md"
    if not p.exists():
        return None
    text = p.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else None


def render(store: Store, subject: str, vendor: Optional[Vendor] = None, out_dir: Optional[Path] = None) -> Path:
    entries = store.list_memory(subject)
    folder = entries[0].folder.value if entries else MemoryFolder.counterparties.value
    updated = max((e.valid_from for e in entries), default=date(2026, 1, 1)).isoformat()
    fm = _seed_frontmatter(folder, subject)
    if fm:
        fm = re.sub(r"^updated: .*$", f"updated: {updated}", fm, flags=re.M)
        if "memory-writer" not in fm:
            fm = re.sub(r"^sources: \[(.*)\]$", lambda m: f"sources: [{m.group(1)}, memory-writer]", fm, flags=re.M)
    else:
        name = vendor.name if vendor else subject
        aliases = ", ".join(vendor.aliases) if vendor else ""
        fm = (f"name: {subject}\ndescription: {name}; memory created by the Memory Writer from case history\n"
              f"aliases: [{aliases}]\nsources: [memory-writer]\nupdated: {updated}")
    lines = [f"- [{e.provenance} | {e.valid_from.isoformat()}] {e.text}" for e in entries]
    path = (out_dir or OUT_DIR) / folder / f"{subject}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}\n---\n" + "\n".join(lines) + "\n")
    return path
