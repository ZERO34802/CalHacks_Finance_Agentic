"""Person B's API: kill switch, handoff, skill proposals, onboarding, SLA sweep, alerts."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from contracts import Alert, Case, Controls, OnboardingRequest, OnboardingResult, SkillProposal

router = APIRouter()


def _ctx():
    from backend.api import app as app_module
    from backend.core.runner import make_ctx
    ctx = make_ctx(app_module.store)
    ctx.trace.subscribe(app_module._broadcast)
    return ctx


def _case(ctx, case_id: str) -> Case:
    case = ctx.store.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"no case {case_id}")
    return case


class ControlsUpdate(BaseModel):
    actor: str
    paused: bool
    vendor_id: Optional[str] = None


class HandoffRequest(BaseModel):
    to: str
    by: str
    note: str = ""


class ReleaseRequest(BaseModel):
    by: str
    note: str = ""


class FollowUpDone(BaseModel):
    by: str
    note: str = ""
    outcome: Optional[Literal["confirmed", "denied"]] = None


class SignOff(BaseModel):
    approver: str


@router.get("/controls", response_model=Controls)
def get_controls() -> Controls:
    from backend.agents.handoff import get_controls as gc
    return gc(_ctx())


@router.post("/controls", response_model=Controls)
def post_controls(body: ControlsUpdate) -> Controls:
    from backend.agents.handoff import set_controls
    return set_controls(_ctx(), body.actor, body.paused, body.vendor_id)


@router.post("/cases/{case_id}/handoff", response_model=Case)
def post_handoff(case_id: str, body: HandoffRequest) -> Case:
    from backend.agents.handoff import handoff
    ctx = _ctx()
    try:
        return handoff(_case(ctx, case_id), ctx, body.to, body.by, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/cases/{case_id}/release", response_model=Case)
def post_release(case_id: str, body: ReleaseRequest) -> Case:
    from backend.agents.handoff import release
    ctx = _ctx()
    return release(_case(ctx, case_id), ctx, body.by, body.note)


@router.post("/cases/{case_id}/followups/{followup_id}/done", response_model=Case)
def post_followup_done(case_id: str, followup_id: str, body: FollowUpDone) -> Case:
    from backend.agents.handoff import close_followup
    ctx = _ctx()
    try:
        return close_followup(_case(ctx, case_id), ctx, followup_id, body.by, body.note, body.outcome)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/skills/proposals", response_model=list[SkillProposal])
def list_proposals() -> list[SkillProposal]:
    return _ctx().store.list_records(SkillProposal, "skill_proposal")


@router.post("/skills/proposals/{pid}/approve", response_model=SkillProposal)
def approve_proposal(pid: str, body: SignOff) -> SkillProposal:
    from backend.agents import evolution
    try:
        return evolution.approve(pid, body.approver, _ctx())
    except evolution.ProposalError as e:
        raise HTTPException(400, str(e))


@router.post("/skills/proposals/{pid}/reject", response_model=SkillProposal)
def reject_proposal(pid: str, body: SignOff) -> SkillProposal:
    from backend.agents import evolution
    try:
        return evolution.reject(pid, body.approver, _ctx())
    except evolution.ProposalError as e:
        raise HTTPException(400, str(e))


@router.post("/skills/{skill}/rollback")
def rollback_skill(skill: str, body: SignOff) -> dict:
    from backend.agents import evolution
    if body.approver.startswith("agent:"):
        raise HTTPException(400, "the agent can't roll back skills")
    try:
        return {"skill": skill, "version": evolution.rollback(skill, _ctx()), "by": body.approver}
    except evolution.ProposalError as e:
        raise HTTPException(400, str(e))


@router.post("/onboarding", response_model=OnboardingResult)
def post_onboarding(req: OnboardingRequest) -> OnboardingResult:
    from backend.onboarding.flow import onboard
    return onboard(req, _ctx())


@router.post("/sla/sweep")
def post_sla_sweep(as_of: date) -> dict:
    from backend.agents.sla import sweep_sla
    ctx = _ctx()
    with ctx.trace.step("sweep", "sweep.sla"):
        return sweep_sla(ctx, as_of)


@router.get("/alerts", response_model=list[Alert])
def list_alerts() -> list[Alert]:
    return _ctx().store.list_records(Alert, "alert")
