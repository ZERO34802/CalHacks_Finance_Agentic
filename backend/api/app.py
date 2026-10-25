"""Thin HTTP + WS layer for the UI. No business logic here.

Run: make api  (http://localhost:8000, docs at /docs)
The OpenAPI spec exported from this app is what the Prism mock serves.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import time
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.core.config import load_policy
from backend.core.runner import make_ctx, run_case
from backend.core.stage import utcnow
from backend.ap import state as ap_state
from backend.ap import views as ap
from backend.pipeline.lib.split import INFO, split
from backend.ap.payments import (PaymentError, PaymentStore, create_batch, decide_prepayment, quote as prepay_quote,
                                 release as release_batch, request_prepayment)
from backend.vendors import onboarding as onb
from backend.vendors.crs import make_crs
from backend.ap import coinbase
from backend.memory import timeline as memory_timeline
from backend.notify import email as mail
from backend.slack import bot as slack_bot
from backend.slack import contract as slack_contract
from backend.slack import onboard as slack_onboard
from backend.dashboard.views import approval_queue, business_metrics, failures, stage_stats
from backend.evals.fixtures import case_dir, case_ids, load_fixture, seed
from backend.intake.ingest import ingest
from backend.evals.harness import run_eval
from backend.review import chat as review_chat
from backend.review.packet import build as build_packet, memory_for, signoff_problem
from backend.store import get_store
from backend.store.sqlite import DEFAULT_DB
from contracts import (ApReport, ApSettings, EarlyPayOffer, OnboardingCase, OnboardingRequestIn, Prepayment, PrepaymentQuote,
                       PrepaymentRequest, SignOff, Approval, ApprovalRequest, Bill, BillDetail, DashboardMetrics, PaymentBatch,
                       PaymentBatchRequest, ReleaseRequest, Case, CaseDetail, CaseStatus, ChatReply, ChatRequest,
                       Decision, Event, FailureItem, IntakeAccepted, MemoryEntry, OutboundEmail, QueueItem, ReviewPacket,
                       Scoreboard, StageStat, TreasuryStatus, Vendor, VendorContract, VendorMemoryTimeline)

store = get_store()
payments = PaymentStore(getattr(store, "path", DEFAULT_DB))  # payment runs live next to the case store
seed(store)
_listeners: set[asyncio.Queue] = set()
_loop: Optional[asyncio.AbstractEventLoop] = None


@asynccontextmanager
async def _lifespan(_: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()  # pipeline threads hand WS events to this loop
    try:
        slack_bot.start(store, payments)  # Socket Mode in background threads when SLACK_* tokens are set
    except Exception as e:  # a bad Slack token must not take the API down
        print(f"Slack bot not started: {type(e).__name__}: {e}")
    yield
    import threading  # never let a slow Slack socket close block a reload / shutdown
    t = threading.Thread(target=slack_bot.stop, daemon=True)
    t.start()
    t.join(timeout=3)


app = FastAPI(title="ReconAI API", version="0.1.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _broadcast(event: Event) -> None:
    """Called from the pipeline thread; hands events to every WS client."""
    if _loop is None:
        return
    data = event.model_dump_json()
    for q in list(_listeners):
        _loop.call_soon_threadsafe(q.put_nowait, data)


# Per-team routers: backend/api/routes_a.py, routes_b.py, routes_c.py each define `router = APIRouter()`.
for _team in ("a", "b", "c"):
    _mod = f"backend.api.routes_{_team}"
    if importlib.util.find_spec(_mod) is not None:
        app.include_router(importlib.import_module(_mod).router)


@app.get("/cases", response_model=list[Case])
def list_cases() -> list[Case]:
    return store.list_cases()


@app.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str) -> CaseDetail:
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    return CaseDetail(case=case, steps=store.list_steps(case_id))


@app.post("/cases", response_model=CaseDetail, status_code=201)
def add_case(case: Case) -> CaseDetail:
    """Add a case (judges' scenario) and run it through the pipeline. Steps stream on WS /events."""
    ctx = make_ctx(store)
    ctx.human_signoff = _human_signoff()
    ctx.trace.subscribe(_broadcast)
    store.save_case(case)
    case = run_case(case, ctx)
    return CaseDetail(case=case, steps=store.list_steps(case.id, ctx.run_id))


def _human_signoff() -> bool:
    """RECONAI_HUMAN_SIGNOFF (default on): in the live app every bill waits for a real person's approval; the
    simulated reviewers only recommend. Evals and tests run their own contexts with simulated sign-off."""
    return os.environ.get("RECONAI_HUMAN_SIGNOFF", "on").lower() != "off"


# Demo pacing: stub stages finish in milliseconds; this keeps a background run visible. 0 disables.
DEMO_PACE = float(os.environ.get("RECONAI_DEMO_PACE", "0.35"))


def _run_in_background(case: Case) -> None:
    ctx = make_ctx(store)
    ctx.human_signoff = _human_signoff()
    ctx.trace.subscribe(_broadcast)
    if DEMO_PACE:
        ctx.trace.subscribe(lambda e: time.sleep(DEMO_PACE) if e.type == "step.finished" else None)
    try:
        final = run_case(case, ctx)
        _deliver(final)
        _broadcast(Event(type="run.finished", case_id=final.id, status=final.status, at=utcnow()))
    except Exception:  # the failed step is already in the trace
        _broadcast(Event(type="run.failed", case_id=case.id, at=utcnow()))


def _deliver(case: Case) -> None:
    """Send the supplier emails the agents drafted (once each; kept in the outbox either way)."""
    try:
        mail.deliver_case(store, case)
    except Exception as e:  # email trouble never blocks the AP flow
        print(f"email delivery failed for {case.id}: {e}")


@app.post("/intake", response_model=IntakeAccepted, status_code=202)
def intake(case: Case, background: BackgroundTasks) -> IntakeAccepted:
    """The trigger: an invoice arrives. Returns at once; the pipeline runs in the background and streams on WS
    /events (step.*, case.updated, then run.finished). The reviewer picks it up from GET /cases/{id}/review."""
    if case.status != CaseStatus.quarantined:  # intake already quarantined it: nothing for the agents to run
        case.status, case.decision = CaseStatus.new, None
    case.approvals, case.journal_entry = [], None
    case.created_at = utcnow()
    store.save_case(case)
    _broadcast(Event(type="run.started", case_id=case.id, status=case.status, at=utcnow()))
    background.add_task(_run_in_background, case)
    return IntakeAccepted(case_id=case.id, run_id="background")


def _packet(case_id: str):
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    steps = store.list_steps(case_id)
    vendor = store.get_vendor(case.vendor_id)
    return case, steps, vendor, build_packet(case, steps, vendor, load_policy(), store)


@app.get("/cases/{case_id}/review", response_model=ReviewPacket)
def review(case_id: str) -> ReviewPacket:
    """Summary, findings, full agent trace and files audited, for the reviewer."""
    return _packet(case_id)[3]


@app.post("/cases/{case_id}/chat", response_model=ChatReply)
def chat(case_id: str, req: ChatRequest) -> ChatReply:
    """Ask about one case. Claude without tools, answering from the case record; deterministic fallback."""
    case, steps, vendor, packet = _packet(case_id)
    memory = memory_for(vendor, store.list_memory())
    return review_chat.answer(case, steps, vendor, memory, packet, load_policy(), req.messages)


@app.post("/approvals/{case_id}", response_model=Case)
def approve(case_id: str, req: ApprovalRequest) -> Case:
    """Record a human decision on a bill. Controls in code (403): requester can't approve, approval within the
    role's limit, and bank-change / look-alike / hidden-instruction escalations need the out-of-band callback first.
    approved -> the pipeline resumes at the Poster (`run_case(start_at="poster")`), which books the AP entry: the
    full invoice, or on a hold only the undisputed part (scope "undisputed", the default on a hold). Posting
    stays in one place; payment runs only pay what was booked. rejected -> rejected; ask -> on hold."""
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    cases = store.list_cases()
    if not ap_state.is_bill(case, cases):
        target = ap_state.attachment_target(case, cases)
        raise HTTPException(409, f"{case_id} is not a bill" + (f"; decide on {target}" if target else ""))
    policy = load_policy()
    decision = req.decision.value
    disputed = [d for d in case.discrepancies if d.material and d.type not in INFO]
    scope = req.scope or ("undisputed" if case.decision == Decision.hold and split(case)["separable"] else "full")
    if scope not in ("full", "undisputed"):
        raise HTTPException(400, "scope must be full or undisputed")
    problem = signoff_problem(case, req.approver, req.role.value, decision, policy)
    if problem:
        raise HTTPException(403, problem)
    if decision == "approved":
        if case.invoice is None:
            raise HTTPException(409, "Nothing to approve: no invoice was read from what arrived. Ask the vendor to resend.")
        if case.status == CaseStatus.posted or (case.journal_entry and not ap_state.partial(case)):
            raise HTTPException(409, "Already approved and booked.")
        if case.journal_entry and ap_state.partial(case):
            raise HTTPException(409, "The undisputed part is already approved and booked; the held part settles "
                                     "through a credit note or a corrected invoice.")
        if case.decision == Decision.reject:
            raise HTTPException(409, "The agents rejected this bill (e.g. a duplicate). It can't be approved for payment.")
        if case.decision == Decision.hold and scope == "full" and disputed:
            raise HTTPException(409, "On a hold only the undisputed part can be approved; the disputed part stays held.")
        if scope == "undisputed" and not split(case)["separable"]:
            raise HTTPException(409, "The disputed part of this hold isn't separable (e.g. a currency or total "
                                     "mismatch): ask for a corrected invoice.")
    case.approvals.append(Approval(id=f"{ap_state.HUMAN_PREFIX}{case_id}_{len(case.approvals)}", case_id=case_id,
                                   approver=req.approver, role=req.role, decision=req.decision,
                                   scope=scope if decision == "approved" else None,
                                   comment=req.comment, limit=policy.approval_limits.get(req.role.value), at=utcnow()))
    case.pending_approval = None
    if decision == "rejected":
        case.status, case.decision = CaseStatus.rejected, Decision.reject
    elif decision == "ask":
        case.notes.append(f"On hold by {req.approver}: {req.comment}".rstrip(": "))
    case.updated_at = utcnow()
    store.save_case(case)
    if decision == "approved":
        if scope == "full":
            case.decision, case.status = Decision.approve, CaseStatus.approved
        elif case.status in (CaseStatus.paused, CaseStatus.resolved):
            case.status = CaseStatus.awaiting_approval  # the runner stops at these; the gate re-checks the kill switch
        ctx = make_ctx(store)
        ctx.trace.subscribe(_broadcast)
        case = run_case(case, ctx, start_at="poster")
        _deliver(case)
    _broadcast(Event(type="case.updated", case_id=case.id, status=case.status, at=utcnow()))
    return case


@app.get("/vendors", response_model=list[Vendor])
def list_vendors() -> list[Vendor]:
    return store.list_vendors()


@app.get("/vendors/{vendor_id}", response_model=Vendor)
def get_vendor(vendor_id: str) -> Vendor:
    vendor = store.get_vendor(vendor_id)
    if vendor is None:
        raise HTTPException(404, f"vendor {vendor_id} not found")
    return vendor


@app.get("/memory", response_model=list[MemoryEntry])
def list_memory(subject: Optional[str] = None) -> list[MemoryEntry]:
    return store.list_memory(subject)


@app.get("/evals/scoreboard", response_model=Scoreboard)
def scoreboard() -> Scoreboard:
    board = store.latest_scoreboard()
    if board is None:
        raise HTTPException(404, "no eval run yet; run `make eval`")
    return board


@app.post("/evals/run", response_model=Scoreboard)
def rerun_eval() -> Scoreboard:
    """Run every fixture against the answer key now (dashboard 'Run eval' button)."""
    return run_eval(store)


@app.get("/fixtures", response_model=list[Case])
def list_fixtures() -> list[Case]:
    """Fixture invoices after intake only (documents attached, nothing decided). The dashboard POSTs one to
    /intake to run the real pipeline on it live. Tick fixtures (clock advances) are not invoices; skipped."""
    ctx = make_ctx(store)
    return [ingest(fx, case_dir(cid), ctx) for cid in case_ids()
            if (fx := load_fixture(cid)).kind == "inbound"]


@app.get("/dashboard/queue", response_model=list[QueueItem])
def queue() -> list[QueueItem]:
    """Open cases by priority: due date, amount, supplier criticality."""
    return approval_queue(store, load_policy(), date.today())


@app.get("/dashboard/metrics", response_model=DashboardMetrics)
def metrics() -> DashboardMetrics:
    return business_metrics(store, load_policy())


@app.get("/dashboard/stages", response_model=list[StageStat])
def stages() -> list[StageStat]:
    """Per-stage run counts, outcomes and mean duration (Agents screen)."""
    return stage_stats(store)


@app.get("/dashboard/failures", response_model=list[FailureItem])
def list_failures(case_id: Optional[str] = None) -> list[FailureItem]:
    """Non-ok steps (failed / blocked / escalated / retried) and what ran next."""
    return failures(store, case_id)


@app.get("/ap/bills", response_model=list[Bill])
def ap_bills() -> list[Bill]:
    """Every invoice with its AP stage, risk signals, SLA, payment block and payment."""
    return ap.bills(store, payments, load_policy(), ap.utcnow())


@app.get("/ap/bills/{case_id}", response_model=BillDetail)
def ap_bill(case_id: str) -> BillDetail:
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    return ap.detail(store, payments, load_policy(), case, ap.utcnow())


@app.get("/ap/report", response_model=ApReport)
def ap_report() -> ApReport:
    return ap.report(store, payments, load_policy(), ap.utcnow())


@app.get("/ap/settings", response_model=ApSettings)
def ap_settings() -> ApSettings:
    return ap.settings(load_policy())


@app.get("/ap/payments", response_model=list[PaymentBatch])
def ap_payments() -> list[PaymentBatch]:
    return payments.batches()


@app.post("/ap/payments", response_model=PaymentBatch, status_code=201)
def ap_create_run(req: PaymentBatchRequest) -> PaymentBatch:
    """Schedule approved bills into a payment run (simulated). Payment guard and duplicate-run checks in code."""
    try:
        batch = create_batch(store, payments, load_policy(), req.case_ids, req.pay_date, req.created_by, ap.utcnow(),
                             req.methods)
    except PaymentError as e:
        raise HTTPException(400, str(e))
    for p in batch.payments:
        _broadcast(Event(type="case.updated", case_id=p.case_id, at=utcnow()))
    return batch


@app.post("/ap/payments/{batch_id}/release", response_model=PaymentBatch)
def ap_release_run(batch_id: str, req: ReleaseRequest) -> PaymentBatch:
    """Release a run (simulated settlement). The person who prepared it can't release it (403)."""
    try:
        batch = release_batch(payments, batch_id, req.released_by, ap.utcnow(), store, load_policy(), rail=req.rail)
    except PaymentError as e:
        raise HTTPException(403 if "cannot also release" in str(e) else 400, str(e))
    for p in batch.payments:
        _broadcast(Event(type="case.updated", case_id=p.case_id, at=utcnow()))
    return batch


@app.get("/ap/discounts", response_model=list[EarlyPayOffer])
def ap_discounts() -> list[EarlyPayOffer]:
    """Early-payment discounts across bills, soonest deadline first (available / needs approval / blocked / missed / captured)."""
    offers = [b.discount for b in ap.bills(store, payments, load_policy(), ap.utcnow()) if b.discount]
    return sorted(offers, key=lambda o: (o.status not in ("available", "needs_approval"), o.pay_by))


@app.get("/ap/prepayments", response_model=list[Prepayment])
def ap_prepayments(vendor_id: Optional[str] = None) -> list[Prepayment]:
    return payments.prepayments(vendor_id)


@app.get("/ap/prepayments/quote", response_model=PrepaymentQuote)
def ap_prepay_quote(vendor_id: str, credit_amount: Decimal) -> PrepaymentQuote:
    try:
        return prepay_quote(store, payments, load_policy(), vendor_id, credit_amount)
    except PaymentError as e:
        raise HTTPException(404, str(e))


@app.post("/ap/prepayments", response_model=Prepayment, status_code=201)
def ap_request_prepayment(req: PrepaymentRequest) -> Prepayment:
    try:
        return request_prepayment(store, payments, load_policy(), req.vendor_id, req.credit_amount, req.requested_by, req.note, ap.utcnow())
    except PaymentError as e:
        raise HTTPException(400, str(e))


@app.post("/ap/prepayments/{prepay_id}/decide", response_model=Prepayment)
def ap_decide_prepayment(prepay_id: str, req: SignOff) -> Prepayment:
    """Controller/CFO approval (not the requester). Approval settles it (simulated) and opens vendor credit."""
    try:
        return decide_prepayment(payments, prepay_id, req.approver, req.role.value, req.decision, ap.utcnow())
    except PaymentError as e:
        raise HTTPException(403 if "cannot approve" in str(e) or "need a" in str(e) else 400, str(e))


@app.get("/vendors/onboarding/samples")
def onboarding_samples() -> list[dict]:
    """Sample onboarding requests (fictional businesses) for the demo form."""
    return onb.samples()


@app.get("/vendors/onboarding/list", response_model=list[OnboardingCase])
def onboarding_list() -> list[OnboardingCase]:
    return payments.onboarding()


@app.post("/vendors/onboarding", response_model=OnboardingCase, status_code=201)
def onboarding_submit(req: OnboardingRequestIn) -> OnboardingCase:
    """Run every onboarding check (CRS + code) and open the request for a second person's approval."""
    case = onb.submit(req, store, make_crs(), ap.utcnow())
    payments.save_onboarding(case)
    return case


def _onb(case_id: str) -> OnboardingCase:
    c = next((x for x in payments.onboarding() if x.id == case_id), None)
    if c is None:
        raise HTTPException(404, f"onboarding {case_id} not found")
    return c


@app.post("/vendors/onboarding/{case_id}/recheck", response_model=OnboardingCase)
def onboarding_recheck(case_id: str) -> OnboardingCase:
    try:
        c = onb.recheck(_onb(case_id), store, make_crs())
    except onb.OnboardingError as e:
        raise HTTPException(400, str(e))
    payments.save_onboarding(c)
    return c


@app.post("/vendors/onboarding/{case_id}/decide", response_model=OnboardingCase)
def onboarding_decide(case_id: str, req: SignOff) -> OnboardingCase:
    """Approve (creates the vendor, on probation) or reject. Requester can't approve; medium/high risk needs a controller."""
    try:
        c = onb.decide(_onb(case_id), req.approver, req.role.value, req.decision, req.comment, store, ap.utcnow())
    except onb.OnboardingError as e:
        raise HTTPException(403, str(e))
    slack_onboard.finish(c, store, ap.utcnow())  # contract terms onto the vendor master + confirmation email
    payments.save_onboarding(c)
    if c.source == "slack" and slack_bot.BOT is not None:
        try:
            slack_bot.BOT.notify_decided(c)
        except Exception as e:
            print(f"slack notify failed: {e}")
    return c


# --- outbox (supplier emails, onboarding confirmations) -------------------------------------------

@app.get("/emails", response_model=list[OutboundEmail])
def list_emails(case_id: Optional[str] = None, vendor_id: Optional[str] = None) -> list[OutboundEmail]:
    return mail.outbox(store, case_id, vendor_id)


@app.post("/emails/{case_id}/send", response_model=list[OutboundEmail])
def send_case_emails(case_id: str) -> list[OutboundEmail]:
    """Retry delivery of this case's supplier emails (sent ones are never re-sent)."""
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    return mail.deliver_case(store, case)


# --- Coinbase rail (USDC on Base Sepolia testnet) ----------------------------------------------------

def _rail():
    rail = coinbase.get_rail()
    if rail is None:
        raise HTTPException(409, "Coinbase isn't configured: set CDP_API_KEY_ID, CDP_API_KEY_SECRET, CDP_WALLET_SECRET")
    return rail


@app.get("/ap/coinbase", response_model=TreasuryStatus)
def coinbase_status() -> TreasuryStatus:
    rail = coinbase.get_rail()
    if rail is None:
        return coinbase.not_configured()
    try:
        return rail.status()
    except coinbase.RailError as e:
        raise HTTPException(502, str(e))


@app.post("/ap/coinbase/faucet")
def coinbase_faucet() -> dict[str, str]:
    """Top the treasury up with testnet ETH (gas) and USDC from the CDP faucet."""
    try:
        return _rail().fund()
    except coinbase.RailError as e:
        raise HTTPException(502, str(e))


@app.post("/ap/coinbase/vendor-wallets", response_model=list[Vendor])
def coinbase_vendor_wallets() -> list[Vendor]:
    """Demo setup: give each vendor without one a testnet payout wallet (a CDP account), recorded in the vendor
    master. In production the vendor supplies its address at onboarding and it is verified like bank details."""
    rail, out = _rail(), []
    for v in store.list_vendors():
        if not v.wallet_address:
            try:
                v.wallet_address = rail.create_wallet(coinbase.wallet_name(v))
            except coinbase.RailError as e:
                raise HTTPException(502, str(e))
            store.save_vendor(v)
        out.append(v)
    return out


# --- contracts drafted in Slack ---------------------------------------------------------------------

@app.get("/contracts", response_model=list[VendorContract])
def list_contracts() -> list[VendorContract]:
    return sorted(store.list_records(VendorContract, slack_contract.KIND), key=lambda c: c.created_at, reverse=True)


@app.get("/contracts/{contract_id}/pdf")
def contract_pdf(contract_id: str):
    c = store.get_record(VendorContract, slack_contract.KIND, contract_id)
    if c is None:
        raise HTTPException(404, f"contract {contract_id} not found")
    path = slack_contract.OUT / f"{c.id}.pdf"
    if not path.exists():
        path = slack_contract.render_pdf(c)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


# --- per-vendor memory timeline ---------------------------------------------------------------------

@app.get("/memory/vendors/{vendor_id}/timeline", response_model=VendorMemoryTimeline)
def vendor_memory_timeline(vendor_id: str) -> VendorMemoryTimeline:
    vendor = store.get_vendor(vendor_id)
    if vendor is None:
        raise HTTPException(404, f"vendor {vendor_id} not found")
    return memory_timeline.build(store, vendor)


@app.websocket("/events")
async def events(ws: WebSocket) -> None:
    """Live Event stream (step.started / step.finished / case.updated), JSON per message."""
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    _listeners.add(q)
    try:
        while True:
            await ws.send_text(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        _listeners.discard(q)
