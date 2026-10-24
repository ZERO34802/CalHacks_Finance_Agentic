"""C's hooks (auto-loaded by backend.core.hooks). Owner: C.

- after_case: Memory Writer (backend/memory/writer.py), trusted structured signals only.
- sweep "followups": open follow-ups past due at `as_of` -> overdue; the case is reopened (reopens += 1, note,
  Alert kind=follow_up_overdue). Re-triage of the delta is QUEUED, not run here: the case keeps its evidence and
  carries status=reopened + a note naming the disputed amount, so the queue / a human (or A's registry when new
  evidence arrives) re-runs only the delta. Uses the simulated clock only.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from backend.core import hooks
from backend.core.stage import Ctx
from backend.memory import writer
from contracts import Alert, Case, CaseStatus, FollowUpStatus

NO_REOPEN = {CaseStatus.quarantined, CaseStatus.paused}


@hooks.after_case
def memory_writer(case: Case, ctx: Ctx) -> None:
    written = writer.after_case(case, ctx.store)
    ctx.trace.annotate(outputs=written, detail={"memory_written": written, "memory_off": writer.memory_off()})


def overdue(case: Case, as_of: date) -> list:
    return [fu for fu in case.follow_ups if fu.status == FollowUpStatus.open and fu.due < as_of]


@hooks.sweep("followups")
def followups(ctx: Ctx, as_of: date) -> None:
    at = datetime.combine(as_of, time(0), tzinfo=timezone.utc)
    reopened = []
    for case in ctx.store.list_cases():
        late = overdue(case, as_of)
        if not late:
            continue
        for fu in late:
            fu.status = FollowUpStatus.overdue
            ctx.store.put_record("alert", f"alert_followup_{fu.id}", Alert(
                id=f"alert_followup_{fu.id}", kind="follow_up_overdue", vendor_id=case.vendor_id, case_id=case.id,
                at=at, message=f"{fu.kind.value} for {case.id} was due {fu.due.isoformat()}; not received by "
                               f"{as_of.isoformat()}"), idx=case.id)
        if case.status not in NO_REOPEN:
            case.status = CaseStatus.reopened
            case.reopens += 1
            disputed = f" (disputed {case.disputed_amount} {case.invoice.currency})" if (
                case.disputed_amount is not None and case.invoice) else ""
            case.notes.append(f"{as_of.isoformat()}: follow-up {', '.join(f.kind.value for f in late)} overdue; "
                              f"reopened, re-triage only the delta{disputed} (queued)")
        case.updated_at = at
        ctx.store.save_case(case)
        writer.after_case(case, ctx.store)  # trusted, computed signal: follow-up overdue
        reopened.append(case.id)
    ctx.trace.annotate(outputs=reopened, detail={"reopened": reopened, "as_of": as_of.isoformat()})
