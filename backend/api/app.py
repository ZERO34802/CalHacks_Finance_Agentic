"""Thin HTTP + WS layer for the UI. No business logic here.

Run: make api  (http://localhost:8000, docs at /docs)
The OpenAPI spec exported from this app is what the Prism mock serves.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.core.runner import make_ctx, run_case
from backend.core.stage import utcnow
from backend.evals.fixtures import seed
from backend.store.sqlite import SQLiteStore
from contracts import Approval, ApprovalRequest, Case, CaseDetail, Event, MemoryEntry, Scoreboard, Vendor

store = SQLiteStore()
seed(store)
_listeners: set[asyncio.Queue] = set()
_loop: Optional[asyncio.AbstractEventLoop] = None


@asynccontextmanager
async def _lifespan(_: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()  # pipeline threads hand WS events to this loop
    yield


app = FastAPI(title="ReconAI API", version="0.1.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _broadcast(event: Event) -> None:
    """Called from the pipeline thread; hands events to every WS client."""
    if _loop is None:
        return
    data = event.model_dump_json()
    for q in list(_listeners):
        _loop.call_soon_threadsafe(q.put_nowait, data)


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
    ctx.trace.subscribe(_broadcast)
    store.save_case(case)
    case = run_case(case, ctx)
    return CaseDetail(case=case, steps=store.list_steps(case.id, ctx.run_id))


@app.post("/approvals/{case_id}", response_model=Case)
def approve(case_id: str, req: ApprovalRequest) -> Case:
    """Record a human approval decision. STUB: records only; re-plan / post is B's + A's job."""
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    case.approvals.append(Approval(id=f"apr_{case_id}_{len(case.approvals)}", case_id=case_id,
                                   approver=req.approver, role=req.role, decision=req.decision,
                                   comment=req.comment, at=utcnow()))
    case.updated_at = utcnow()
    store.save_case(case)
    return case


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
