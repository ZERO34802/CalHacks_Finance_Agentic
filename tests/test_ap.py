"""AP workspace (owner: D): pre-payment checks, payment runs and their controls, reports."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.ap.payments import PaymentStore
from backend.core.config import load_policy
from backend.evals.fixtures import case_ids, load_case, seed
from backend.review.checks import match_rows, payment_block, signals
from backend.store.sqlite import SQLiteStore


def _sig(cid):
    store = SQLiteStore(":memory:")
    seed(store)
    case = load_case(cid)
    return {s.code for s in signals(case, store.get_vendor(case.vendor_id), load_policy())}


def test_checks_catch_every_planted_issue_and_nothing_on_the_clean_invoice():
    assert _sig("case_01") == set()
    assert _sig("case_02") == {"qty_short"}
    assert _sig("case_03") == {"price_over"}
    assert _sig("case_04") == {"bank_mismatch", "lookalike_domain"}
    assert _sig("case_05") == {"duplicate", "not_on_po"}


def test_match_variances_are_exact():
    [row] = match_rows(load_case("case_02"))
    assert (row.qty_variance, row.amount_at_risk) == (Decimal("60"), Decimal("1116000.00"))
    [row] = match_rows(load_case("case_03"))
    assert (row.price_variance, row.amount_at_risk) == (Decimal("60.00"), Decimal("2400.00"))


@pytest.fixture
def client(monkeypatch):
    import backend.api.app as app_module
    store = SQLiteStore(":memory:")
    seed(store)
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "payments", PaymentStore(":memory:"))
    monkeypatch.setattr(app_module, "DEMO_PACE", 0)
    monkeypatch.setenv("RECONAI_CHAT", "offline")
    c = TestClient(app_module.app)
    for cid in case_ids():
        assert c.post("/intake", json=load_case(cid).model_dump(mode="json")).status_code == 202
    return c


def stages(client):
    return {b["case_id"]: b["stage"] for b in client.get("/ap/bills").json()}


def test_bills_land_in_the_right_stage(client):
    s = stages(client)
    assert s["case_01"] == "ready_to_pay"                    # cleared by the agents, nothing flagged
    assert s["case_05"] == "blocked"                         # agents cleared it, payment guard stops the duplicate
    assert s["case_02"] == s["case_04"] == "needs_review"    # over the AP lead's limit


def test_payment_run_controls(client):
    run = lambda ids, who="ap.lead@helix.example": client.post(  # noqa: E731
        "/ap/payments", json={"case_ids": ids, "pay_date": date.today().isoformat(), "created_by": who})
    assert run(["case_02"]).status_code == 400               # not approved
    assert "duplicate" in run(["case_05"]).json()["detail"]  # guard
    ok = run(["case_01", "case_03"])
    assert ok.status_code == 201
    batch = ok.json()
    assert {p["pay_to_last4"] for p in batch["payments"]} == {"5150"}      # vendor master account
    assert run(["case_01"]).status_code == 400               # already in a run
    same = client.post(f"/ap/payments/{batch['id']}/release", json={"released_by": "ap.lead@helix.example"})
    assert same.status_code == 403                           # preparer can't release
    done = client.post(f"/ap/payments/{batch['id']}/release", json={"released_by": "m.chen@helix.example"})
    assert done.json()["status"] == "paid" and stages(client)["case_01"] == "paid"


def test_bank_change_is_blocked_even_after_a_human_approves(client):
    assert client.post("/approvals/case_04", json={"approver": "r.okafor@helix.example", "role": "cfo",
                                                    "decision": "approved", "comment": ""}).status_code == 200
    assert stages(client)["case_04"] == "blocked"
    r = client.post("/ap/payments", json={"case_ids": ["case_04"], "pay_date": date.today().isoformat(),
                                          "created_by": "ap.lead@helix.example"})
    assert r.status_code == 400 and "vendor master" in r.json()["detail"]


def test_report_and_settings(client):
    rep = client.get("/ap/report").json()
    assert sum(b["count"] for b in rep["aging"]) >= 4 and len(rep["forecast"]) == 6
    assert Decimal(rep["caught_usd"]) > 0
    st = client.get("/ap/settings").json()
    assert st["approval_limits"]["approver"] == "100000.00" and st["sla_hours"] == 24


def test_payment_block_only_for_high_risk():
    store = SQLiteStore(":memory:")
    seed(store)
    case = load_case("case_02")
    assert payment_block(signals(case, store.get_vendor(case.vendor_id), load_policy())) is None


def test_payment_methods_follow_the_vendor_country(client):
    body = lambda m: {"case_ids": ["case_01"], "pay_date": date.today().isoformat(),  # noqa: E731
                      "created_by": "ap.lead@helix.example", "methods": {"case_01": m}}
    assert "isn't available" in client.post("/ap/payments", json=body("ach")).json()["detail"]   # Kestrel is KR
    assert client.post("/ap/payments", json=body("intl_wire")).json()["payments"][0]["method"] == "intl_wire"


def test_detail_has_checks_chain_and_warning(client):
    d = client.get("/ap/bills/case_05").json()
    assert d["verdict"] == "risk" and "duplicate of INV-2291" in d["bill"]["warning"]
    assert [s["label"] for s in d["approval_steps"]] == ["Prepared by ReconAI", "AP lead approval", "Release payment"]
    assert d["last_paid"]["invoice_no"] == "INV-2291"
    assert client.get("/ap/bills/case_01").json()["verdict"] == "ready"
