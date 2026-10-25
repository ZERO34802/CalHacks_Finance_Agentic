"""Early-pay discounts, advance payments, and CRS vendor onboarding (owner: D). Real fixtures, offline."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from d_helpers import client, fresh_store, offline, run  # noqa: F401

from backend.ap.discounts import offer
from backend.core.config import load_policy
from backend.vendors import onboarding as onb
from backend.vendors.crs import CRSUnavailable, RecordedCRS


def test_discount_offer_is_computed_from_terms_not_the_invoice(offline):
    store = fresh_store()
    case = run(store, "case_25")                                 # Kestrel 2/15 net 30, invoiced Oct 21, USD 72,500
    v = store.get_vendor("V-KESTREL")
    o = offer(case, v, load_policy(), date(2026, 10, 24), "ready_to_pay", None, None)
    assert (o.discount_amount, o.pay_by, o.days_left, o.status) == (Decimal("1450.00"), date(2026, 11, 5), 12, "available")
    assert o.terms == "2/15 net 30" and 48 < o.annualized_return_pct < 50
    assert offer(case, v, load_policy(), date(2026, 11, 6), "ready_to_pay", None, None).status == "missed"
    assert offer(case, v, load_policy(), date(2026, 10, 24), "blocked", "dup", None).status == "blocked"
    partial = run(store, "case_06")                              # hold: the discount is on the undisputed part only
    o = offer(partial, v, load_policy(), date(2026, 10, 20), "ready_to_pay", None, None, base=partial.paid_amount)
    assert o.discount_amount == Decimal("1392.00")               # 2% of 69,600, not of 87,000
    penang = run(store, "case_41")
    assert offer(penang, store.get_vendor("V-PENANG"), load_policy(), date(2026, 10, 24), "ready_to_pay", None, None) is None


def test_paying_inside_the_window_takes_the_discount(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_25", "case_41")
    c = client(monkeypatch, store)
    offers = {o["case_id"]: o for o in c.get("/ap/discounts").json()}
    assert "case_41" not in offers                               # Penang has no discount terms
    o = offers["case_25"]
    if o["status"] != "available":
        pytest.skip("fixture discount window has passed on this machine's date")
    run_ = c.post("/ap/payments", json={"case_ids": ["case_25"], "pay_date": o["pay_by"], "created_by": "ap.lead@helix.example"}).json()
    p = run_["payments"][0]
    assert (p["gross_amount"], p["discount_amount"], p["amount"]) == ("72500.00", "1450.00", "71050.00")


def test_advance_payment_needs_a_controller_and_credit_is_applied(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_25")
    c = client(monkeypatch, store)
    q = c.get("/ap/prepayments/quote", params={"vendor_id": "V-KESTREL", "credit_amount": "100000.00"}).json()
    assert (q["cash_amount"], q["discount_amount"], q["allowed"]) == ("97000.00", "3000.00", True)
    assert c.get("/ap/prepayments/quote", params={"vendor_id": "V-PENANG", "credit_amount": "1000"}).json()["allowed"] is False
    assert c.get("/ap/prepayments/quote", params={"vendor_id": "V-KESTREL", "credit_amount": "300000"}).json()["allowed"] is False  # cap
    assert c.get("/ap/prepayments/quote", params={"vendor_id": "V-TSC", "credit_amount": "1000"}).json()["allowed"] is False  # probation / no terms
    pre = c.post("/ap/prepayments", json={"vendor_id": "V-KESTREL", "credit_amount": "50000.00", "requested_by": "ap.lead@helix.example"}).json()
    sign = lambda who, role: c.post(f"/ap/prepayments/{pre['id']}/decide",  # noqa: E731
                                    json={"approver": who, "role": role, "decision": "approved"})
    assert sign("ap.lead@helix.example", "controller").status_code == 403      # requester
    assert sign("x@helix.example", "approver").status_code == 403              # not a controller
    assert sign("m.chen@helix.example", "controller").json()["status"] == "paid"
    r = c.post("/ap/payments", json={"case_ids": ["case_25"], "pay_date": "2099-01-01", "created_by": "ap.lead@helix.example"}).json()
    p = r["payments"][0]                                          # USD 72,500 booked, after the discount window
    assert (p["credit_applied"], p["amount"]) == ("50000.00", "22500.00")
    assert c.get("/ap/prepayments", params={"vendor_id": "V-KESTREL"}).json()[0]["remaining"] == "0.00"


def _run(label, crs=None):
    store = fresh_store()
    req = next(s for s in onb.samples() if s["label"] == label)["request"]
    case = onb.submit(onb.OnboardingRequestIn.model_validate(req), store, crs or RecordedCRS(), onb.datetime.now())
    return case, {c.name: c.status for c in case.checks}


def test_onboarding_checks_catch_each_planted_vendor(offline):
    case, st = _run("Clean new US supplier")                       # owner = CRS persona P19, consented to a soft pull
    assert case.risk_tier == "low" and set(st.values()) == {"pass"}, st
    assert onb.CREDIT in st and all(c.provider.startswith("CRS") for c in case.checks if c.name in (onb.IDENTITY, onb.CREDIT))
    case, st = _run("Same tax ID as Penang Pack & Test, new bank")
    assert st["Duplicate vendor: tax ID"] == "fail" and st[onb.IDENTITY] == "not_covered" and case.risk_tier == "high"
    st = _run("Synthetic identity behind the vendor (CRS)")[1]    # P13: identity + fraud fail
    assert st[onb.IDENTITY] == "fail" and st[onb.FRAUD] == "fail"
    assert _run("Bank account matches an employee")[1]["Bank account vs employees"] == "fail"   # world employees
    st = _run("Look-alike of an existing vendor")[1]               # P12: SSN not the owner's, phone is someone else's
    assert st["Email domain"] == "fail" and st[onb.IDENTITY] == "fail" and st[onb.PHONE] == "fail"
    assert _run("Missing tax form")[1]["Tax form"] == "fail"
    st = _run("Owner with a bankruptcy (CRS)")[1]                  # P06: Chapter 7 on PitchPoint, credit 580
    assert st[onb.COURT] == "fail" and st[onb.CREDIT] == "warn"

    class Down:  # CRS outage: one retry, then every CRS check is "incomplete" (fail closed)
        mode, calls = "sandbox", 0

        def check_principal(self, pid, products):
            Down.calls += 1
            raise CRSUnavailable("timeout")
    case, st = _run("Clean new US supplier", Down())
    assert Down.calls == 2 and st[onb.IDENTITY] == "incomplete" and case.risk_tier == "medium"


def test_onboarding_code_checks_agree_with_the_scored_flow(offline):
    """C's onboarding requests (scored by the eval via A's checks) give the same flags in D's UI flow."""
    import json
    from backend.evals.fixtures import DATA
    key = {r["id"]: r for r in json.loads((DATA / "onboarding" / "answer_key.json").read_text())}
    label = {"duplicate_tax_id": "Duplicate vendor: tax ID", "sanctions_hit": "Sanctions list (simulated)",
             "bank_matches_employee": "Bank account vs employees", "lookalike_domain": "Email domain",
             "missing_tax_form": "Tax form"}
    for rid, exp in key.items():
        case, st = _run(next(s["label"] for s in onb.samples() if s["label"].endswith(f"({rid})")))
        failed = {n for n, s in st.items() if s == "fail" and next(c for c in case.checks if c.name == n).provider == "code"}
        assert failed == {label[f] for f in exp["flags"]}, (rid, failed)


def test_onboarding_approval_rules(offline, monkeypatch):
    store = fresh_store()
    c = client(monkeypatch, store)
    sample = lambda label: next(s for s in onb.samples() if s["label"] == label)["request"]  # noqa: E731
    clean = c.post("/vendors/onboarding", json=sample("Clean new US supplier")).json()
    own = c.post(f"/vendors/onboarding/{clean['id']}/decide", json={"approver": "j.park@helix.example", "role": "controller", "decision": "approved"})
    assert own.status_code == 403                                 # requester can't approve
    ok = c.post(f"/vendors/onboarding/{clean['id']}/decide", json={"approver": "ap.lead@helix.example", "role": "approver", "decision": "approved"}).json()
    assert ok["status"] == "approved"
    v = c.get(f"/vendors/{ok['vendor_id']}").json()
    assert v["on_probation"] is True and v["probation_until"] is not None
    fake = c.post("/vendors/onboarding", json=sample("Synthetic identity behind the vendor (CRS)")).json()
    r = c.post(f"/vendors/onboarding/{fake['id']}/decide", json={"approver": "m.chen@helix.example", "role": "cfo", "decision": "approved"})
    assert r.status_code == 403                                   # a failed owner identity can never be approved here
    emp = c.post("/vendors/onboarding", json=sample("Bank account matches an employee")).json()
    r = c.post(f"/vendors/onboarding/{emp['id']}/decide", json={"approver": "m.chen@helix.example", "role": "controller", "decision": "approved"})
    assert r.status_code == 403
