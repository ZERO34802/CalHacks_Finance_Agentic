"""Review packet: what the reviewer gets once a background run is done. Owner: D.

Deterministic. One plain-language Finding per check. A finding is "flag" only where the pipeline recorded a
discrepancy; stub stages are "unchecked" (they pass everything through) but still show the raw facts so a
human can judge. All arithmetic here is Decimal; nothing is computed by an LLM.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from backend.core.config import Policy
from contracts import (Case, Decision, DiscrepancyType, Finding, MemoryEntry, ReviewPacket, Step, StepStatus,
                       Vendor)

MATCH_TYPES = {DiscrepancyType.qty_short, DiscrepancyType.price_over, DiscrepancyType.unapproved_freight,
               DiscrepancyType.fx_gap}
GUARD_TYPES = {DiscrepancyType.bank_change, DiscrepancyType.lookalike_domain}

SUGGESTED = [
    "Why this recommendation?",
    "Show me the 3-way match",
    "Who gets paid, and does it match the vendor master?",
    "Walk me through each step",
    "What do we know about this vendor?",
    "Which files did you audit?",
]


def money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def usd(case: Case, policy: Policy) -> Optional[Decimal]:
    inv = case.invoice
    return None if inv is None else (inv.total * policy.fx_rates[inv.currency]).quantize(Decimal("0.01"))


def needs(case: Case, policy: Policy) -> str:
    """Who has to sign. Mirrors the approval-limit matrix in config/policy.yaml."""
    if case.journal_entry is not None:
        return "nobody"
    amount = usd(case, policy)
    if amount is None:
        return "approver"
    # Lowest role whose limit covers the amount (approval matrix in policy.yaml).
    for role, limit in sorted(policy.approval_limits.items(), key=lambda kv: kv[1]):
        if amount <= limit:
            return role
    return "board"


def _lines(case: Case) -> str:
    inv, po = case.invoice, case.po
    out = []
    for line in inv.lines if inv else []:
        ordered = next((p.qty for p in po.lines if p.sku == line.sku), None) if po else None
        received = sum((r.qty_received for rc in case.receipts for r in rc.lines if r.sku == line.sku), Decimal(0))
        po_price = next((p.unit_price for p in po.lines if p.sku == line.sku), None) if po else None
        out.append(f"{line.sku}: billed {line.qty:,} @ {line.unit_price:,} · ordered {ordered:,} @ {po_price:,}"
                   f" · received {received:,}" if ordered is not None else
                   f"{line.sku}: billed {line.qty:,} @ {line.unit_price:,} · not on the PO · received {received:,}")
    return "; ".join(out)


def findings(case: Case, steps: list[Step], vendor: Optional[Vendor], policy: Policy) -> list[Finding]:
    by = {s.stage: s for s in steps if s.parent_id is None}
    stub = lambda st: bool(by.get(st) and by[st].detail.get("stub") is True)  # noqa: E731
    inv = case.invoice
    out: list[Finding] = []

    if case.status.value == "quarantined":
        out.append(Finding(check="Intake validation", agent="Intake", status="blocked",
                           detail=f"Quarantined: {case.quarantine_reason or 'failed validation'}. Nothing was read or booked."))
    if "reader" in by and inv is None and case.status.value != "quarantined":
        out.append(Finding(check="Read the invoice", agent="Reader", status="unchecked",
                           detail="No invoice could be extracted (evidence missing, or the Reader was unavailable)."))
    if "reader" in by and inv:
        hidden = "embedded_instructions" in inv.flags
        out.append(Finding(check="Read the invoice", agent="Reader", status="flag" if hidden else "ok",
                           detail=("Hidden instructions found in the document; they were ignored. " if hidden else "")
                           + f"{inv.invoice_no}: {len(inv.lines)} line(s), total {money(inv.total, inv.currency)}."))

    dup = [d for d in case.discrepancies if d.type == DiscrepancyType.duplicate_invoice]
    if "doc_dedup" in by:
        out.append(Finding(check="Seen before?", agent="Dedup",
                           status="flag" if dup else "unchecked" if stub("doc_dedup") else "ok",
                           detail="Matches an invoice already received or paid." if dup else
                           "Not checked in this build (placeholder stage)." if stub("doc_dedup") else
                           "No earlier invoice with the same number or lines."))

    match = [d for d in case.discrepancies if d.type in MATCH_TYPES]
    if "matcher" in by:
        facts = _lines(case)
        if match:
            detail = "; ".join(f"{d.type.value.replace('_', ' ')}" + (f" on {d.sku}" if d.sku else "")
                               + (f" ({money(d.delta, inv.currency)})" if d.delta is not None and inv else "") for d in match)
            out.append(Finding(check="3-way match", agent="Matcher", status="flag", detail=f"{detail}. On record: {facts}."))
        else:
            out.append(Finding(check="3-way match", agent="Matcher", status="unchecked" if stub("matcher") else "ok",
                               detail=("Not checked in this build. " if stub("matcher") else "Invoice, PO and receipt agree. ")
                               + f"On record: {facts}."))

    guard = [d for d in case.discrepancies if d.type in GUARD_TYPES]
    if "vendor_guard" in by:
        sender = next((d.sender for d in case.documents if d.sender), None)
        facts = (f"Invoice pays •••• {inv.bank_last4 if inv and inv.bank_last4 else '—'}; vendor master has "
                 f"•••• {vendor.bank_last4 if vendor else '—'}. Email from {sender.split('@')[-1] if sender else '—'}; "
                 f"domain on file {vendor.email_domain if vendor else '—'}.")
        out.append(Finding(check="Vendor & bank", agent="Vendor Guard",
                           status="flag" if guard else "unchecked" if stub("vendor_guard") else "ok",
                           detail=(", ".join(d.type.value.replace("_", " ") for d in guard) + ". " if guard else
                                   "Not checked in this build. " if stub("vendor_guard") else "Matches the vendor master. ")
                           + facts))

    if "validators" in by:
        v = by["validators"]
        out.append(Finding(check="Controls re-check", agent="Validators",
                           status="blocked" if v.status == StepStatus.blocked else "unchecked" if stub("validators") else "ok",
                           detail=v.error or ("Not checked in this build." if stub("validators") else "Numbers recomputed; citations verified.")))

    if "approver" in by:
        amount = usd(case, policy)
        limit = policy.approval_limits["approver"]
        if case.decision == Decision.escalate:
            signer = {"approver": "AP lead", "controller": "controller", "cfo": "CFO"}.get(needs(case, policy), needs(case, policy))
            why = (f"{money(amount, 'USD')} is over the AP lead's {money(limit, 'USD')} limit; the {signer} must sign"
                   if amount is not None and amount > limit else "the agents would not sign it alone")
            out.append(Finding(check="Sign-off", agent="Approver", status="flag", detail=f"Sent to a human: {why}."))
        else:
            signed = next((a for a in reversed(case.approvals) if a.decision.value == "approved"), None)
            who = (f"{signed.approver} ({signed.role.value}"
                   + (", simulated agent reviewer" if (signed.comment or "").startswith("[simulated") else "") + ")") if signed else ""
            part = " for the undisputed part only" if signed and signed.scope == "undisputed" else ""
            out.append(Finding(check="Sign-off", agent="Approver", status="ok" if signed else "flag",
                               detail=f"Signed by {who}{part}." if signed else "Waiting for a signature."))

    if "poster" in by:
        je = case.journal_entry
        refused = next((n.split("REFUSED: ", 1)[1] for n in reversed(case.notes) if "poster: REFUSED: " in n), None)
        held = (f" {money(case.disputed_amount, inv.currency)} stays held." if je and inv and case.disputed_amount
                and je.idempotency_key.endswith(":undisputed") else "")
        out.append(Finding(check="Ledger", agent="Poster", status="ok" if je else "blocked" if refused else "unchecked",
                           detail=("Booked: " + "; ".join(f"{p.account} {money(p.amount, p.currency)}" for p in je.postings) + "." + held
                                   if je else f"Not booked: {refused}" if refused else
                                   "Not booked. Nothing is paid until a human decides.")))
    for f in case.follow_ups:
        out.append(Finding(check="Follow-up", agent="ReconAI", status="ok" if f.status.value == "done" else
                           "flag" if f.status.value == "overdue" else "unchecked",
                           detail=f"{f.kind.value.replace('_', ' ')} due {f.due}: {f.status.value}. {f.note}".strip()))
    return out


def summary(case: Case, vendor: Optional[Vendor], fs: list[Finding]) -> str:
    inv = case.invoice
    head = f"{vendor.name if vendor else case.vendor_id} · {inv.invoice_no if inv else '—'} · " \
           f"{money(inv.total, inv.currency) if inv else '—'}."
    flags = [f.detail.split(". On record")[0].removeprefix("Sent to a human: ").rstrip(".") for f in fs if f.status in ("flag", "blocked")]
    verdict = {
        Decision.approve: "The agents found nothing wrong" + (" and booked it." if case.journal_entry else "."),
        Decision.hold: "Recommend holding it",
        Decision.reject: "Recommend rejecting it",
        Decision.escalate: "Needs your decision",
    }.get(case.decision, "Still running.")
    if case.decision in (Decision.hold, Decision.reject, Decision.escalate) and flags:
        verdict += ": " + "; ".join(flags) + "."
    elif case.decision in (Decision.hold, Decision.reject, Decision.escalate):
        verdict += "."
    unchecked = sum(f.status == "unchecked" and f.check != "Ledger" for f in fs)
    note = f" {unchecked} check(s) are placeholders in this build, so read the raw facts below." if unchecked else ""
    return f"{head} {verdict}{note}"


def build(case: Case, steps: list[Step], vendor: Optional[Vendor], policy: Policy, store=None) -> ReviewPacket:
    from backend.review.checks import disagreements, signals as check_signals
    ready = case.decision is not None or case.status.value in ("quarantined", "resolved", "paused")
    fs = findings(case, steps, vendor, policy) if ready else []
    sig = check_signals(case, vendor, policy, store) if ready else []
    for d in disagreements(case, sig) if ready else []:
        fs.append(Finding(check="Second line vs agents", agent="Pre-payment checks", status="flag", detail=d))
    text = summary(case, vendor, fs) if ready else "The agents are still working on this invoice."
    if sig:
        text += " Pre-payment checks flag: " + "; ".join(s.title for s in sig) + "."
    return ReviewPacket(case_id=case.id, ready=ready, summary=text,
                        recommendation=case.decision, needs=needs(case, policy) if ready else "nobody",
                        findings=fs, trace=steps, files=case.documents, signals=sig, suggested=SUGGESTED if ready else [])


def memory_for(vendor: Optional[Vendor], memory: list[MemoryEntry]) -> list[MemoryEntry]:
    """Memory lines about this vendor only (lookup by its slug, never similarity across vendors)."""
    if vendor is None:
        return []
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\s+(co\.,? ltd\.?|ltd\.?|inc\.?|sdn bhd|llc)$", "", vendor.name.lower())).strip("-")
    return [m for m in memory if m.subject == slug]


def signoff_problem(case: Case, approver: str, role: str, decision: str, policy: Policy) -> Optional[str]:
    """Controls on a human decision, enforced in code: requester can't approve; approval within limit;
    bank change / look-alike / hidden instructions need the out-of-band callback first."""
    if decision != "approved":
        return None
    if case.po and approver.lower() == case.po.requester.lower() and role not in policy.self_approve_roles():
        return f"{approver} requested this purchase and cannot approve it."
    from backend.ap.state import oob_problem
    oob = oob_problem(case)
    if oob:
        return oob
    amount = usd(case, policy)
    limit = policy.approval_limits.get(role)
    if limit is None:
        return f"Role {role} cannot approve payments."
    if amount is not None and amount > limit:
        return f"{money(amount, 'USD')} is over the {role} limit of {money(limit, 'USD')}."
    return None
