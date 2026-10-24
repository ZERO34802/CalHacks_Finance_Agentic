"""Early-pay discounts, advance payments, and CRS vendor onboarding (owner: D)."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.ap.discounts import offer
from backend.ap.payments import PaymentStore
from backend.core.config import load_policy
from backend.evals.fixtures import case_ids, load_case, seed
from backend.store.sqlite import SQLiteStore
from backend.vendors import onboarding as onb
from backend.vendors.crs import SimulatedCRS


def _vendor(vid):
    s = SQLiteStore(":memory:")
    seed(s)
    return s.get_vendor(vid)


def test_discount_offer_is_computed_from_terms_not_the_invoice():
    case = load_case("case_03")                                  # Kestrel 2/15 net 30, invoiced Oct 16, USD 49,600
    o = offer(case, _vendor("V-KESTREL"), load_policy(), date(2026, 10, 24), "ready_to_pay", None, None)
    assert (o.discount_amount, o.pay_by, o.days_left, o.status) == (Decimal("992.00"), date(2026, 10, 31), 7, "available")
    assert o.terms == "2/15 net 30" and 48 < o.annualized_return_pct < 50
    late = offer(case, _vendor("V-KESTREL"), load_policy(), date(2026, 11, 2), "ready_to_pay", None, None)
    assert late.status == "missed"
    assert offer(load_case("case_04"), _vendor("V-PENANG"), load_policy(), date(2026, 10, 24), "needs_review", None, None) is None
    blocked = offer(load_case("case_05"), _vendor("V-AEROLANE"), load_policy(), date(2026, 10, 24), "blocked", "dup", None)
    assert blocked.status == "blocked"


@pytest.fixture
def client(monkeypatch):
    import backend.api.app as app_module
    store = SQLiteStore(":memory:")
    seed(store)
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "payments", PaymentStore(":memory:"))
    monkeypatch.setattr(app_module, "DEMO_PACE", 0)
    monkeypatch.delenv("CRS_BASE_URL", raising=False)
    c = TestClient(app_module.app)
    for cid in case_ids():
        c.post("/intake", json=load_case(cid).model_dump(mode="json"))
    return c


def test_paying_inside_the_window_takes_the_discount(client):
    offers = {o["case_id"]: o for o in client.get("/ap/discounts").json()}
    assert "case_04" not in offers                               # Penang has no discount terms
    o = offers["case_03"]
    if o["status"] != "available":
        pytest.skip("fixture discount window has passed on this machine's date")
    run = client.post("/ap/payments", json={"case_ids": ["case_03"], "pay_date": o["pay_by"], "created_by": "ap.lead@helix.example"}).json()
    p = run["payments"][0]
    assert (p["gross_amount"], p["discount_amount"], p["amount"]) == ("49600.00", "992.00", "48608.00")


def test_advance_payment_needs_a_controller_and_credit_is_applied(client):
    q = client.get("/ap/prepayments/quote", params={"vendor_id": "V-KESTREL", "credit_amount": "100000.00"}).json()
    assert (q["cash_amount"], q["discount_amount"], q["allowed"]) == ("97000.00", "3000.00", True)
    assert client.get("/ap/prepayments/quote", params={"vendor_id": "V-PENANG", "credit_amount": "1000"}).json()["allowed"] is False
    assert client.get("/ap/prepayments/quote", params={"vendor_id": "V-KESTREL", "credit_amount": "300000"}).json()["allowed"] is False  # cap
    pre = client.post("/ap/prepayments", json={"vendor_id": "V-KESTREL", "credit_amount": "50000.00", "requested_by": "ap.lead@helix.example"}).json()
    sign = lambda who, role: client.post(f"/ap/prepayments/{pre['id']}/decide",  # noqa: E731
                                         json={"approver": who, "role": role, "decision": "approved"})
    assert sign("ap.lead@helix.example", "controller").status_code == 403      # requester
    assert sign("x@helix.example", "approver").status_code == 403              # not a controller
    assert sign("m.chen@helix.example", "controller").json()["status"] == "paid"
    run = client.post("/ap/payments", json={"case_ids": ["case_01"], "pay_date": "2099-01-01", "created_by": "ap.lead@helix.example"}).json()
    p = run["payments"][0]                                        # USD 72,500 invoice, after the discount window
    assert (p["credit_applied"], p["amount"]) == ("50000.00", "22500.00")
    assert client.get("/ap/prepayments", params={"vendor_id": "V-KESTREL"}).json()[0]["remaining"] == "0.00"


def _run(label):
    store = SQLiteStore(":memory:")
    seed(store)
    req = next(s for s in onb.samples() if s["label"] == label)["request"]
    case = onb.submit(onb.OnboardingRequestIn.model_validate(req), store, SimulatedCRS(), onb.datetime.now())
    return case, {c.name: c.status for c in case.checks}


def test_onboarding_checks_catch_each_planted_vendor():
    case, st = _run("Clean new US supplier")
    assert case.risk_tier == "low" and set(st.values()) == {"pass"}
    case, st = _run("Same tax ID as Penang Pack & Test, new bank")
    assert st["Duplicate vendor"] == "fail" and st["Business credit"] == "not_covered" and case.risk_tier == "high"
    assert _run("Watchlist (OFAC) hit")[1]["Sanctions (OFAC)"] == "fail"
    assert _run("Bank account matches an employee")[1]["Bank account vs employees"] == "fail"
    assert _run("Look-alike of an existing vendor")[1]["Email domain"] == "fail"
    assert _run("Missing tax form")[1]["Tax form"] == "fail"
    assert _run("Financially risky (liens, bankruptcy)")[1]["Liens, judgments, bankruptcies"] == "fail"
    assert set(_run("CRS times out")[1][k] for k in ("Business identity", "Sanctions (OFAC)")) == {"incomplete"}


def test_onboarding_approval_rules(client):
    sample = lambda label: next(s for s in onb.samples() if s["label"] == label)["request"]  # noqa: E731
    clean = client.post("/vendors/onboarding", json=sample("Clean new US supplier")).json()
    own = client.post(f"/vendors/onboarding/{clean['id']}/decide", json={"approver": "j.park@helix.example", "role": "controller", "decision": "approved"})
    assert own.status_code == 403                                 # requester can't approve
    ok = client.post(f"/vendors/onboarding/{clean['id']}/decide", json={"approver": "ap.lead@helix.example", "role": "approver", "decision": "approved"}).json()
    assert ok["status"] == "approved" and client.get(f"/vendors/{ok['vendor_id']}").json()["on_probation"] is True
    ofac = client.post("/vendors/onboarding", json=sample("Watchlist (OFAC) hit")).json()
    r = client.post(f"/vendors/onboarding/{ofac['id']}/decide", json={"approver": "m.chen@helix.example", "role": "cfo", "decision": "approved"})
    assert r.status_code == 403                                   # sanctions can never be approved here
