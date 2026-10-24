"""Skeleton guarantees. Keep these green; add your own tests next to your code."""
from fastapi.testclient import TestClient

from backend.core.runner import PIPELINE, make_ctx, run_case
from backend.evals.fixtures import answer_key, case_ids, load_case, seed
from backend.evals.harness import run_eval
from backend.store.sqlite import SQLiteStore
from contracts import StepStatus


def test_every_fixture_runs_through_every_stage():
    store = SQLiteStore(":memory:")
    seed(store)
    ctx = make_ctx(store)
    for cid in case_ids():
        run_case(load_case(cid), ctx)
        steps = store.list_steps(cid, ctx.run_id)
        assert [s.stage for s in steps] == [st.name for st in PIPELINE]
        assert all(s.status != StepStatus.running and s.duration_ms is not None for s in steps)


def test_answer_key_covers_every_fixture():
    assert set(answer_key()) == set(case_ids())


def test_invariants_hold():
    board = run_eval(SQLiteStore(":memory:"))
    assert board.invariant_pass_rate == 1.0


def test_failing_stage_is_traced_as_failed():
    store = SQLiteStore(":memory:")
    ctx = make_ctx(store)
    case = load_case("case_01")
    case.invoice = None  # stub Reader raises without a parsed invoice
    try:
        run_case(case, ctx)
    except ValueError:
        pass
    [step] = store.list_steps("case_01", ctx.run_id)
    assert step.status == StepStatus.failed and "ValueError" in step.error


def test_api_post_case_and_read_back(monkeypatch):
    import backend.api.app as app_module
    monkeypatch.setattr(app_module, "store", SQLiteStore(":memory:"))
    seed(app_module.store)
    client = TestClient(app_module.app)
    body = load_case("case_03").model_dump(mode="json")
    assert client.post("/cases", json=body).status_code == 201
    detail = client.get("/cases/case_03").json()
    assert len(detail["steps"]) == len(PIPELINE)
    assert client.get("/vendors/V-KESTREL").json()["bank_last4"] == "5150"
    with client.websocket_connect("/events"):
        pass
