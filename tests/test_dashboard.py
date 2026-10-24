"""Dashboard read models (owner: D), on real pipeline output (offline)."""
from datetime import date, timedelta
from decimal import Decimal

from d_helpers import OFFLINE, client, fresh_store, offline, run  # noqa: F401

from backend.core.config import load_policy
from backend.dashboard.views import approval_queue, business_metrics, failures, stage_stats
from backend.evals.fixtures import case_ids, load_fixture
from contracts import FixtureKind, StepStatus


def test_queue_ranks_due_soon_critical_big_first_and_skips_closed(offline):
    store = fresh_store()
    run(store, "case_25", "case_43", "case_27")       # posted (closed) / Kestrel hold, USD 291k / quarantined
    q = approval_queue(store, load_policy(), date(2026, 11, 18))   # case_43: invoice date + net 30 is close
    ids = [i.case_id for i in q]
    assert "case_25" not in ids                        # booked: nothing to approve
    assert ids[0] == "case_43"
    top = q[0]
    assert top.critical_vendor and top.total_usd == Decimal("291160.00") and "critical supplier" in top.reasons
    assert top.at_risk and top.days_to_due is not None and top.days_to_due <= 7
    assert q[-1].case_id == "case_27" and q[-1].total is None and not q[-1].at_risk


def test_queue_converts_with_policy_fx(offline):
    store = fresh_store()
    case = run(store, "case_11")                       # TWD, partially booked hold -> not in the queue
    assert approval_queue(store, load_policy(), date(2026, 10, 24)) == []
    case.journal_entry = None                          # as if nothing were booked yet
    store.save_case(case)
    [item] = approval_queue(store, load_policy(), date(2026, 10, 24))
    assert item.total_usd == (case.invoice.total * Decimal("0.031")).quantize(Decimal("0.01"))


def test_metrics_count_bills_with_deltas_when_known(offline):
    store = fresh_store()
    run(store, "case_06", "case_10", "case_25", "case_27")
    m = business_metrics(store, load_policy())
    assert m.cases == 4 and m.exceptions == 3          # sub-cases aren't counted as bills
    # held deltas (USD 17,400 + 2,800); the quarantined case has no invoice, so nothing measurable
    assert m.dollars_caught_usd == Decimal("20200.00")
    assert m.on_time_payment_rate is None or 0 <= m.on_time_payment_rate <= 1
    assert {v.vendor_id: v.exceptions for v in m.by_vendor}["V-KESTREL"] == 1
    assert any("ESTIMATE" in a for a in m.assumptions)


def test_failures_lists_non_ok_steps_with_next_step(offline):
    store = fresh_store()
    run(store, *OFFLINE, "case_02")
    found = failures(store)
    assert found and all(f.status not in (StepStatus.ok, StepStatus.skipped) for f in found)
    for f in found:
        steps = store.list_steps(f.case_id)
        idx = [s.id for s in steps].index(f.step_id)
        assert f.next_stage == (steps[idx + 1].stage if idx + 1 < len(steps) else None)


def test_stage_stats_cover_every_stage_in_pipeline_order(offline):
    from backend.core.runner import PIPELINE
    store = fresh_store()
    run(store, *OFFLINE)
    stats = stage_stats(store)
    names = [s.stage for s in stats]
    order = [st.name for st in PIPELINE]
    assert [n for n in names if n in order] == [n for n in order if n in names]   # pipeline order
    assert {"reader", "matcher", "poster"} <= set(names)
    for s in stats:
        assert s.ok + s.skipped + s.flagged <= s.runs


def test_dashboard_endpoints(offline, monkeypatch):
    store = fresh_store()
    c = client(monkeypatch, store)
    fixtures = c.get("/fixtures").json()
    inbound = [cid for cid in case_ids() if load_fixture(cid).kind == FixtureKind.inbound]
    assert [f["id"] for f in fixtures] == inbound      # ingested only: documents, nothing decided
    assert all(f["decision"] is None or f["status"] == "quarantined" for f in fixtures)
    for f in fixtures:
        if f["id"] in OFFLINE:
            assert c.post("/intake", json=f).status_code == 202
    assert len(c.get("/vendors").json()) == 5
    assert c.get("/dashboard/queue").status_code == 200
    assert c.get("/dashboard/metrics").json()["cases"] == len(OFFLINE)
    assert c.get("/dashboard/failures").status_code == 200
    assert len(c.get("/dashboard/stages").json()) > 0
    assert len(c.get("/ap/bills").json()) == len(OFFLINE)
