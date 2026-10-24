"""Skeleton guarantees. Keep these green; add your own tests next to your code."""
from fastapi.testclient import TestClient

from backend.core.runner import make_ctx, run_case, run_fixture
from backend.evals.fixtures import answer_key, case_dir, case_ids, load_fixture, seed
from backend.evals.harness import run_eval
from backend.intake.ingest import ingest
from backend.store.sqlite import SQLiteStore
from contracts import CaseStatus, StepStatus


def _ctx():
    store = SQLiteStore(":memory:")
    seed(store)
    return make_ctx(store)


def test_every_fixture_runs_and_every_step_finishes():
    ctx = _ctx()
    key = answer_key()
    for cid in case_ids():
        fx = load_fixture(cid)
        case = run_fixture(fx, case_dir(cid), ctx)
        steps = ctx.store.list_steps(cid, ctx.run_id)
        if fx.kind == "tick":  # no intake: sweeps only
            assert all(s.stage.startswith("sweep.") for s in steps)
            continue
        assert steps[0].stage == "intake"
        assert all(s.status != StepStatus.running and s.duration_ms is not None for s in steps)
        if key[cid].decision is not None:  # supplier replies / applied credit notes end without a decision
            assert case.decision is not None


def test_answer_key_covers_every_fixture():
    assert set(answer_key()) == set(case_ids())


def test_world_seeded():
    ctx = _ctx()
    assert ctx.store.get_po("PO-5501").vendor_id == "V-FORMOSA"
    assert ctx.store.list_paid("V-AEROLANE")[0].invoice_no == "INV-2291"


def test_invariants_hold():
    assert run_eval(SQLiteStore(":memory:")).invariant_pass_rate == 1.0


def test_failing_stage_escalates_and_is_traced():
    ctx = _ctx()
    case = ingest(load_fixture("case_01"), case_dir("case_01"), ctx)
    case.invoice = None
    case = run_case(case, ctx)
    failed = [s for s in ctx.store.list_steps("case_01", ctx.run_id) if s.status == StepStatus.failed]
    if failed:  # stub or real Reader without LLM fails; with an invoice it passes
        assert case.status == CaseStatus.escalated and case.notes


def test_api_post_case_and_read_back(monkeypatch):
    import backend.api.app as app_module
    monkeypatch.setattr(app_module, "store", SQLiteStore(":memory:"))
    seed(app_module.store)
    client = TestClient(app_module.app)
    case = ingest(load_fixture("case_03"), case_dir("case_03"), make_ctx(app_module.store))
    assert client.post("/cases", json=case.model_dump(mode="json")).status_code == 201
    assert client.get("/cases/case_03").json()["steps"]
    assert client.get("/vendors/V-KESTREL").json()["bank_last4"] == "5150"
    with client.websocket_connect("/events"):
        pass


def test_kill_switch_and_handoff_pause_agent_stages():
    from contracts import Controls
    ctx = _ctx()
    ctx.store.put_record("controls", "global", Controls(paused_vendors=["V-KESTREL"], updated_by="m.chen@helix.example"))
    case = run_fixture(load_fixture("case_03"), case_dir("case_03"), ctx)  # Kestrel API invoice
    stages = [s.stage for s in ctx.store.list_steps("case_03", ctx.run_id)]
    assert case.status == CaseStatus.paused and "gate" in stages
    assert "router" not in stages and "poster" not in stages and case.journal_entry is None

    ctx.store.put_record("controls", "global", Controls())
    case.assigned_to, case.status = "d.ortiz@helix.example", CaseStatus.in_progress
    case = run_case(case, ctx, start_at="router")
    assert case.status == CaseStatus.paused and "handed off" in case.notes[-1]
