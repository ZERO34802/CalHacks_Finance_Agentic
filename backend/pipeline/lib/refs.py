"""Supplier-reply case references: [REC <case_id>] in subject or quoted body (data/FORMATS.md P1)."""
from __future__ import annotations

import re

from contracts import Case

REC = re.compile(r"\[REC\s+([A-Za-z0-9][A-Za-z0-9_\-]{0,63})\]")


def rec_refs(case: Case) -> list[str]:
    """Case ids referenced by any document of this case (subject first), excluding itself."""
    out: list[str] = []
    for d in case.documents:
        for t in (d.subject or "", d.text or ""):
            for m in REC.findall(t):
                if m != case.id and m not in out:
                    out.append(m)
    return out
