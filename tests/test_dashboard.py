"""Dashboard read models (owner: D). Built on fixtures so they track the real pipeline."""
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.core.config import load_policy
from backend.core.runner import make_ctx, run_case
from backend.dashboard.views import approval_queue, business_metrics, failures, stage_stats
from backend.evals.fixtures import case_ids, load_case, seed
from backend.store.sqlite import SQLiteStore
from contracts import CaseStatus, Decision, Discrepancy, DiscrepancyType, StepStatus


def _store_with(*cases):
    store = SQLiteStore(":memory:")
    seed(store)
    for c in cases:
        store.save_case(c)
    return store


def test_queue_ranks_due_soon_critical_big_first_and_skips_closed():
    kestrel = load_case("case_01")          # critical, USD 72.5k
    kestrel.status = CaseStatus.awaiting_approval
    kestrel.invoice.due_date = date(2026, 10, 26)
    aerolane = load_case("case_05")         # not critical
    aerolane.status = CaseStatus.awaiting_approval
    aerolane.invoice.due_date = date(2026, 12, 31)
    posted = load_case("case_03")
    posted.status = CaseStatus.posted

    q = approval_queue(_store_with(kestrel, aerolane, posted), load_policy(), date(2026, 10, 24))

    assert [i.case_id for i in q] == ["case_01", "case_05"]
    top = q[0]
    assert top.at_risk and top.days_to_due == 2 and top.critical_vendor
    assert top.total_usd == Decimal("72500.00")
    assert "critical supplier" in top.reasons and "due in 2d" in top.reasons
    assert not q[1].at_risk


def test_queue_converts_with_policy_fx():
    formosa = load_case("case_02")
    q = approval_queue(_store_with(formosa), load_policy(), date(2026, 10, 24))
    inv = formosa.invoice
    assert q[0].total_usd == (inv.total * Decimal("0.031")).quantize(Decimal("0.01"))


def test_metrics_use_deltas_when_known_else_full_invoice():
    short = load_case("case_02")
    short.decision = Decision.hold
    short.discrepancies = [Discrepancy(type=DiscrepancyType.qty_short, delta=Decimal("-1116000.00"))]
    dup = load_case("case_05")
    dup.decision = Decision.reject
    clean = load_case("case_01")
    clean.decision = Decision.approve

    m = business_metrics(_store_with(short, dup, clean), load_policy())

    assert m.cases == 3 and m.exceptions == 2
    assert m.dollars_caught_usd == Decimal("34596.00") + dup.invoice.total  # 1,116,000 TWD x 0.031
    assert m.hours_saved_estimate == Decimal("3.3")                        # (90 + 90 + 15) / 60
    assert m.on_time_payment_rate is None                                  # nothing posted
    assert {v.vendor_id: v.exceptions for v in m.by_vendor}["V-KESTREL"] == 0
    assert any("ESTIMATE" in a for a in m.assumptions)


def test_failures_lists_non_ok_steps_with_next_step():
    store = _store_with()
    ctx = make_ctx(store)
    for cid in case_ids():
        run_case(load_case(cid), ctx)
    found = failures(store)
    assert all(f.status not in (StepStatus.ok, StepStatus.skipped) for f in found)
    for f in found:
        steps = store.list_steps(f.case_id)
        idx = [s.id for s in steps].index(f.step_id)
        assert f.next_stage == (steps[idx + 1].stage if idx + 1 < len(steps) else None)


def test_stage_stats_cover_every_stage_in_pipeline_order():
    from backend.core.runner import PIPELINE
    store = _store_with()
    ctx = make_ctx(store)
    for cid in case_ids():
        run_case(load_case(cid), ctx)
    stats = stage_stats(store)
    assert [s.stage for s in stats] == [st.name for st in PIPELINE]
    for s in stats:
        assert s.runs == len(case_ids()) and s.ok + s.skipped + s.flagged == s.runs


def test_dashboard_endpoints(monkeypatch):
    import backend.api.app as app_module
    monkeypatch.setattr(app_module, "store", _store_with())
    client = TestClient(app_module.app)
    fixtures = client.get("/fixtures").json()
    assert [f["id"] for f in fixtures] == case_ids()
    for f in fixtures:
        assert client.post("/cases", json=f).status_code == 201
    assert len(client.get("/vendors").json()) == 4
    assert client.get("/dashboard/queue").status_code == 200
    assert client.get("/dashboard/metrics").json()["cases"] == len(fixtures)
    assert client.get("/dashboard/failures").status_code == 200
    assert len(client.get("/dashboard/stages").json()) > 0
    assert client.post("/evals/run").json()["total"] == len(fixtures)
