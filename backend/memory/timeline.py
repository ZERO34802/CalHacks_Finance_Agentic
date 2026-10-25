"""Per-vendor memory timeline for the Memory screen (read-only). Owner: D.

Joins what C's Memory Writer keeps (current lines + `memory_history` records), what B's sandbox records in the
trace (the memory version each decision read) and skill proposals backed by this vendor's cases, so the UI can
show how a vendor's memory evolved, where every line came from, and which decisions used it.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from backend.memory.writer import WRITER_TAG, subject_for
from backend.store.base import Store
from contracts import (MemoryEntry, MemoryEvent, MemorySlot, MemoryUse, MemoryVersion, SkillProposal, Vendor,
                       VendorMemoryTimeline)

CASE = re.compile(r"\bcase_[A-Za-z0-9]+(?:-\d+)?\b")
PERSON = re.compile(r"^(?:controller|approver):\s*([^,]+)", re.I)
FORGOTTEN = re.compile(r"\s*\[forgotten: [^\]]*\]$")
COUNT_LABEL = {"qty_short": "Short deliveries", "price_over": "Prices above PO / contract",
               "unapproved_freight": "Unapproved freight / expedite fees", "duplicate_invoice": "Duplicate invoices",
               "bank_change": "Bank-change requests", "lookalike_domain": "Look-alike-domain messages",
               "currency_mismatch": "Currency mismatches", "total_mismatch": "Total mismatches",
               "embedded_instructions": "Embedded instructions"}


def source_of(provenance: str) -> str:
    p = provenance.strip().lower()
    for prefix, name in (("system-of-record", "system_of_record"), ("computed", "computed"),
                         ("controller", "controller"), ("approver", "approver"), ("outcome", "outcome")):
        if p.startswith(prefix):
            return name
    return "seed"


def label_of(entry_id: str, text: str) -> str:
    if WRITER_TAG not in entry_id:
        return text[:60] + ("…" if len(text) > 60 else "")
    slot = entry_id.split(WRITER_TAG, 1)[1]
    if slot.startswith("count:"):
        return COUNT_LABEL.get(slot[6:], slot[6:].replace("_", " ").capitalize())
    if slot == "sor:bank":
        return "Bank account on file"
    if slot.startswith("review:"):
        return f"Reviewer decision on {slot.split(':')[1]}"
    if slot.startswith("followup:"):
        return f"Follow-up {slot.split(':', 1)[1].removeprefix('fu_')}"
    if slot == "review-summary":
        return "Older reviewer decisions (summary)"
    return slot


def _version(e: MemoryEntry, change: str) -> MemoryVersion:
    forgotten = bool(FORGOTTEN.search(e.text))
    m = PERSON.match(e.provenance)
    return MemoryVersion(entry_id=e.id, version=e.version, text=FORGOTTEN.sub("", e.text),
                         provenance=e.provenance, source=source_of(e.provenance), valid_from=e.valid_from,
                         change="forgotten" if forgotten else change,
                         cases=sorted(set(CASE.findall(e.provenance + " " + e.id))),
                         people=[m.group(1).strip()] if m else [])


def build(store: Store, vendor: Vendor) -> VendorMemoryTimeline:
    subject = subject_for(vendor, store)
    current = {e.id: e for e in store.list_memory(subject)}
    history: dict[str, list[MemoryEntry]] = {}
    for h in store.list_records(MemoryEntry, "memory_history"):
        if h.subject == subject:
            history.setdefault(h.id, []).append(h)
    slots = []
    for eid in sorted(set(current) | set(history)):
        olds = sorted(history.get(eid, []), key=lambda e: (e.version, bool(FORGOTTEN.search(e.text))))
        chain = olds + ([current[eid]] if eid in current else [])
        versions = []
        for e in chain:  # a line written again after it was forgotten starts over as "added"
            versions.append(_version(e, "added" if not versions or versions[-1].change == "forgotten" else "updated"))
        cur = versions[-1] if eid in current else None
        slots.append(MemorySlot(entry_id=eid, label=label_of(eid, chain[-1].text), current=cur, versions=versions))
    slots.sort(key=lambda s: (s.current is None, min(v.valid_from for v in s.versions), s.entry_id))

    cases = store.list_cases(vendor.id)
    ids = {c.id for c in cases}
    uses = []
    for c in cases:
        mv = next((s.memory_version for s in store.list_steps(c.id) if s.memory_version), None)
        if mv:
            uses.append(MemoryUse(case_id=c.id, memory_version=mv, decision=c.decision.value if c.decision else None,
                                  at=c.as_of or c.created_at.date()))
    uses.sort(key=lambda u: (u.at, u.case_id))
    events = [MemoryEvent(kind="skill_change", at=p.created_at.date(),
                          label=f"{p.skill} {p.from_version} → {p.to_version} ({p.status.value})",
                          case_ids=[c for c in p.evidence_case_ids if c in ids])
              for p in store.list_records(SkillProposal, "skill_proposal") if ids & set(p.evidence_case_ids)]
    events += [MemoryEvent(kind="memory_use", at=u.at, label=f"{u.case_id} read memory {u.memory_version.split(':')[0]}",
                           case_ids=[u.case_id]) for u in uses]
    events.sort(key=lambda e: (e.at, e.kind))
    version = None
    if current:
        version = f"{subject}@v{max(e.version for e in current.values())}"
    return VendorMemoryTimeline(vendor_id=vendor.id, vendor_name=vendor.name, subject=subject if slots else None,
                                memory_version=version, slots=slots, uses=uses, events=events,
                                sources=dict(Counter(s.current.source for s in slots if s.current)))


def as_of(tl: VendorMemoryTimeline, on: date) -> list[MemoryVersion]:
    """What the vendor's memory said on a date (latest version valid by then, not yet forgotten)."""
    out = []
    for s in tl.slots:
        vs = [v for v in s.versions if v.valid_from <= on]
        if vs and vs[-1].change != "forgotten":
            out.append(vs[-1])
    return out
