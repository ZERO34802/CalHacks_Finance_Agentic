"""Parse memory markdown files (section 8 format) into MemoryEntry rows. Owner: C.

STUB: read-only parser used to seed the store. Line format:
  - [provenance | YYYY-MM-DD] text
"""
from __future__ import annotations

import re
from pathlib import Path

from contracts import MemoryEntry, MemoryFolder

LINE = re.compile(r"^- \[(?P<prov>[^|\]]+)\|\s*(?P<date>\d{4}-\d{2}-\d{2})\]\s*(?P<text>.+)$")


def load_memory_dir(root: Path) -> list[MemoryEntry]:
    entries = []
    for path in sorted(root.glob("*/*.md")):
        folder, subject = MemoryFolder(path.parent.name), path.stem
        for i, m in enumerate(filter(None, map(LINE.match, path.read_text().splitlines()))):
            entries.append(MemoryEntry(id=f"{subject}:{i}", folder=folder, subject=subject,
                                       text=m["text"], provenance=m["prov"].strip(), valid_from=m["date"]))
    return entries
