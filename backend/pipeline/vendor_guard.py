"""[7] Vendor Guard. Owner: B (P0: domain + history). Bank changes, look-alike domains, employee banks.

Deterministic code only. Email text is scanned with fixed patterns as DATA, never as instructions,
and never copied into discrepancies (no quotes from untrusted text). Never edits the vendor master
or bank details; the only outcome is escalate + a callback via the contact on file.

`screen()` is pure and also used by the Router (which runs before this stage in the fixed order) so
the right skill is picked up front. This stage merges the signals into the case, adds history, and
keeps case.skill / case.proposal consistent if it finds something the Router did not.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from backend.core.stage import Ctx
from contracts import Case, Channel, Citation, Decision, DiscrepancyType as T, Discrepancy, DocKind, Role, Vendor

# Pieces of public suffixes we strip before comparing the "brand" part of a domain.
_SUFFIX = {"com", "co", "net", "org", "biz", "info", "io", "ltd", "inc", "us", "uk", "my", "tw", "kr", "jp",
           "cn", "sg", "hk", "de", "ac", "gov", "edu", "example", "mail", "email", "online", "site", "xyz"}
# Homoglyph / confusable folding (ASCII look-alikes and common Cyrillic/Greek letters).
_MULTI = [("rn", "m"), ("vv", "w"), ("cl", "d")]
_SINGLE = str.maketrans({"0": "o", "1": "l", "i": "l", "3": "e", "5": "s", "7": "t", "8": "b", "$": "s",
                         "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "l",
                         "ο": "o", "α": "a", "ν": "v", "ρ": "p"})

BANK_CHANGE = [
    re.compile(r"\b(new|updated|changed?|revised|different)\b[^.\n]{0,40}\b(bank|banking|account|remit(tance)?|iban|swift)\b", re.I),
    re.compile(r"\b(bank|account|remittance|payment)\s+(details|information|instructions)\b[^.\n]{0,30}\b(changed?|updated?|new)\b", re.I),
    re.compile(r"\bdo not (use|pay)[^.\n]{0,20}\bold\b", re.I),
]
LAST4 = re.compile(r"(?:ending(?: in)?|last (?:4|four)(?: digits)?|ends? (?:with|in))\D{0,6}(\d{4})\b", re.I)


def _domain(addr: Optional[str]) -> Optional[str]:
    if not addr or "@" not in addr:
        return None
    d = addr.rsplit("@", 1)[1].strip().strip(">").lower()
    if d.startswith("xn--") or ".xn--" in d:
        try:
            d = d.encode().decode("idna")
        except UnicodeError:
            pass
    return d


def _core(domain: str) -> str:
    parts = domain.split(".")
    while len(parts) > 1 and parts[-1] in _SUFFIX:
        parts.pop()
    return "".join(parts).replace("-", "")


def _skeleton(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    for a, b in _MULTI:
        s = s.replace(a, b)
    return s.translate(_SINGLE)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def lookalike_reason(sender_domain: str, vendor_domain: str) -> Optional[str]:
    """Why sender_domain looks like (but is not) vendor_domain, or None if exact / unrelated."""
    s, v = sender_domain.lower(), vendor_domain.lower()
    if s == v or s.endswith("." + v):
        return None
    cs, cv = _core(s), _core(v)
    if cs == cv:
        return "same name, different TLD / hyphen or dot inserted"
    if _skeleton(cs) == _skeleton(cv):
        return "homoglyph substitution"
    if min(len(cs), len(cv)) >= 5 and _edit_distance(cs, cv) <= 2:
        return f"edit distance {_edit_distance(cs, cv)}"
    return None


@dataclass
class Screen:
    vendor: Optional[Vendor]                 # vendor on file (bound, or claimed via a look-alike)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


def _claimed_vendor(case: Case, vendors: list[Vendor]) -> tuple[Optional[Vendor], Optional[str]]:
    by_id = {v.id: v for v in vendors}
    if case.vendor_id in by_id:
        return by_id[case.vendor_id], "bound"
    if case.invoice and case.invoice.vendor_id in by_id:
        return by_id[case.invoice.vendor_id], "invoice"
    for d in case.documents:
        dom = _domain(d.sender) if d.channel == Channel.email else None
        for v in vendors if dom else []:
            if lookalike_reason(dom, v.email_domain):
                return v, "look-alike sender domain"
    return None, None


def screen(case: Case, ctx: Ctx) -> Screen:
    """Pure: computes vendor-risk discrepancies without touching the case."""
    vendors = ctx.store.list_vendors()
    vendor, how = _claimed_vendor(case, vendors)
    out = Screen(vendor=vendor)
    if vendor is None:
        out.findings.append("no vendor on file matches this case")
        return out
    if how != "bound":
        out.findings.append(f"vendor {vendor.id} resolved via {how}, not bound by intake")

    look_cites, seen = [], set()
    bank_cites: list[Citation] = []
    new_last4: set[str] = set()
    for d in case.documents:
        if d.channel != Channel.email:
            continue
        dom = _domain(d.sender)
        if dom and dom not in seen:
            seen.add(dom)
            why = lookalike_reason(dom, vendor.email_domain)
            if why:
                look_cites.append(Citation(doc_id=d.id, locator="From header", quote=dom))
                out.findings.append(f"sender {dom} vs {vendor.email_domain} on file: {why}")
            elif dom != vendor.email_domain and not dom.endswith("." + vendor.email_domain):
                out.findings.append(f"sender {dom} is not the domain on file ({vendor.email_domain})")
        if d.kind == DocKind.email and d.text and any(p.search(d.text) for p in BANK_CHANGE):
            bank_cites.append(Citation(doc_id=d.id, locator="email body: bank-change request"))
            new_last4.update(LAST4.findall(d.text))
            out.findings.append(f"{d.id}: email body asks to change bank details")

    inv = case.invoice
    if inv and inv.bank_last4 and inv.bank_last4 != vendor.bank_last4:
        bank_cites.append(Citation(doc_id=inv.doc_id, locator="remit-to account", quote=f"ending {inv.bank_last4}"))
        new_last4.add(inv.bank_last4)
        out.findings.append(f"invoice remit account ending {inv.bank_last4} != master ending {vendor.bank_last4}")
    new_last4.discard(vendor.bank_last4)

    employees = {e.bank_last4: e for e in ctx.store.list_employees()}
    for last4 in sorted(new_last4 | ({inv.bank_last4} if inv and inv.bank_last4 else set())):
        if last4 in employees:
            bank_cites.append(Citation(doc_id=f"employee:{employees[last4].id}", locator="bank_last4"))
            out.findings.append(f"bank ending {last4} matches employee {employees[last4].id}: insider-fraud flag")

    if look_cites:
        out.discrepancies.append(Discrepancy(type=T.lookalike_domain, expected=vendor.email_domain,
                                             actual=look_cites[0].quote, citations=look_cites))
    if bank_cites:
        out.discrepancies.append(Discrepancy(type=T.bank_change, expected=f"ending {vendor.bank_last4}",
                                             actual=", ".join(f"ending {x}" for x in sorted(new_last4)) or "change requested",
                                             citations=bank_cites))
    return out


def merge(case: Case, found: list[Discrepancy]) -> list[str]:
    """Add vendor-risk discrepancies the case doesn't already have (one per type). Returns added types."""
    have = {d.type for d in case.discrepancies}
    added = [d for d in found if d.type not in have]
    case.discrepancies.extend(added)
    return [d.type.value for d in added]


def history(case: Case, ctx: Ctx, vendor: Optional[Vendor]) -> dict:
    if vendor is None:
        return {}
    prior = [c for c in ctx.store.list_cases(vendor.id) if c.id != case.id]
    types: dict[str, int] = {}
    for c in prior:
        for d in c.discrepancies:
            types[d.type.value] = types.get(d.type.value, 0) + 1
    from backend.agents.sandbox import vendor_memory  # local: avoid import cycle at module load
    subject, lines, _ = vendor_memory(ctx, vendor)
    return {"prior_cases": [c.id for c in prior],
            "prior_decisions": {c.id: c.decision.value for c in prior if c.decision},
            "prior_discrepancy_types": types,
            "memory_subject": subject, "memory_lines": lines}


class VendorGuard:
    name = "vendor_guard"

    def run(self, case: Case, ctx: Ctx) -> Case:
        from backend.agents.policy_rules import cap, route

        sc = screen(case, ctx)
        added = merge(case, sc.discrepancies)
        hist = history(case, ctx, sc.vendor)
        risky = any(d.type in (T.bank_change, T.lookalike_domain) for d in case.discrepancies)
        detail = {"vendor": sc.vendor.id if sc.vendor else None, "findings": sc.findings, "added": added,
                  "history": hist, "vendor_master_changed": False}
        if risky:
            if added:  # Router missed it (e.g. discrepancies arrived late): keep skill + proposal consistent
                case.skill, why = route(case, ctx.policy)
                detail["rerouted"] = {"skill": case.skill, "reason": why}
            if case.proposal and case.proposal.recommendation != Decision.escalate:
                case.proposal.recommendation = cap(case.proposal.recommendation, Decision.escalate)
                case.proposal.explanation += "\nVendor Guard: vendor-risk signal; escalated by code."
            contact = f"the phone number on the vendor master for {sc.vendor.id}" if sc.vendor else "a verified contact"
            note = (f"Vendor Guard: hold payment; callback required via {contact}, never the email sender. "
                    "Bank details unchanged.")
            if note not in case.notes:
                case.notes.append(note)
            detail["callback_required"] = True
        ctx.trace.annotate(role=Role.system, tool="vendor_guard.screen",
                           inputs=[d.id for d in case.documents], outputs=added, detail=detail)
        return case
