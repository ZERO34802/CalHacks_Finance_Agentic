"""Approval SLAs + backup approver + payment-at-risk alerts. Owner: B. Simulated clock only (sweep's as_of).

A case waiting on a human has `case.pending_approval` (set by the Approver: escalations, controller "ask",
out-of-office reviewer). The `sla` sweep:
  - at due_at (requested_at + sla.approval_hours): reminder (Alert kind sla_reminder, note);
  - after sla.escalate_after_hours: route to the backup (never the requester, never the agent, within limit).
    If the original reviewer was an agent role-play that never answered (out of office / ask), the backup reviews
    now and, if approved, the case resumes at the Poster. Escalations stay with humans (reassigned only).
  - Alert kind payment_at_risk when the invoice is due within sla.payment_at_risk_days and not yet paid.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from backend.core.stage import Ctx
from contracts import Alert, Case, CaseStatus, Decision, Role

WAITING = {CaseStatus.awaiting_approval, CaseStatus.escalated, CaseStatus.awaiting_vendor, CaseStatus.paused,
           CaseStatus.reopened, CaseStatus.in_progress}


def _alert(ctx: Ctx, kind: str, case: Case, at: datetime, msg: str) -> str:
    aid = f"{kind}_{case.id}"
    if ctx.store.get_record(Alert, "alert", aid) is None:
        ctx.store.put_record("alert", aid, Alert(id=aid, kind=kind, vendor_id=case.vendor_id, case_id=case.id, at=at,
                                                 message=msg), idx=case.id)
    return aid


def invoice_due(case: Case) -> tuple[date, bool] | None:
    """(due date, assumed?) Uses the invoice due date; otherwise assumes Net 30 (labeled)."""
    inv = case.invoice
    if inv is None:
        return None
    if inv.due_date:
        return inv.due_date, False
    return inv.invoice_date + timedelta(days=30), True


def sweep_sla(ctx: Ctx, as_of: date) -> dict:
    from backend.agents.approver import Approver, identity, requester
    from backend.core.runner import run_case

    sla = ctx.policy.sla
    now = datetime.combine(as_of, time(23, 59, 59), tzinfo=timezone.utc)
    escalate_after = timedelta(hours=float(sla.get("escalate_after_hours", 48)))
    at_risk_days = int(sla.get("payment_at_risk_days", 2))
    out: dict = {"reminded": [], "escalated": [], "backup_reviewed": [], "payment_at_risk": []}
    for case in ctx.store.list_cases():
        changed = False
        due = invoice_due(case)
        if due and case.status in WAITING and case.journal_entry is None:
            d, assumed = due
            if (d - as_of).days <= at_risk_days:
                aid = _alert(ctx, "payment_at_risk", case, now,
                             f"invoice due {d}{' (assumed Net 30)' if assumed else ''} and not approved")
                out["payment_at_risk"].append(aid)
        pa = case.pending_approval
        if pa is not None:
            if now >= pa.due_at and pa.reminded_at is None:
                pa.reminded_at = now
                _alert(ctx, "sla_reminder", case, now, f"{pa.approver} has not answered ({pa.role.value}); reminder sent")
                case.notes.append(f"SLA: reminder to {pa.approver} (due {pa.due_at.isoformat()})")
                out["reminded"].append(case.id)
                changed = True
            if now >= pa.requested_at + escalate_after and pa.escalated_to is None:
                try:
                    backup, _ = identity(pa.role, case, ctx, exclude=(pa.approver,))
                except RuntimeError:
                    backup = None
                if backup and backup != requester(case, ctx):
                    pa.escalated_to = backup
                    _alert(ctx, "sla_escalated", case, now, f"SLA breached by {pa.approver}; routed to {backup}")
                    case.notes.append(f"SLA: {pa.approver} missed the SLA; routed to backup {backup}")
                    out["escalated"].append(case.id)
                    changed = True
                    if case.status == CaseStatus.awaiting_approval and pa.role in (Role.approver, Role.controller):
                        with ctx.trace.step(case.id, "approver.backup", role=pa.role):
                            case = Approver().run(case, ctx, override=(pa.role, backup))
                        out["backup_reviewed"].append(case.id)
                        if case.decision == Decision.approve and case.approvals:
                            ctx.store.save_case(case)
                            case = run_case(case, ctx, start_at="poster")
                        if case.pending_approval is None:  # keep the SLA history (who missed it, who answered)
                            case.pending_approval = pa
                            case.notes.append(f"SLA: answered by backup {backup}")
        if changed:
            ctx.store.save_case(case)
    return out
