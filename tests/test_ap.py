"""AP workspace (owner: D): second-line checks, bills on real pipeline output, payment runs and their controls.

Real fixtures through the real pipeline, offline (see d_helpers)."""
from datetime import date, datetime, timezone
from decimal import Decimal

from d_helpers import client, fresh_store, offline, run, variant  # noqa: F401  (offline is a fixture)

from backend.ap.state import payable
from backend.core.config import load_policy
from backend.pipeline.lib.ledger import ledger_path
from backend.review.checks import disagreements, match_rows, payment_block, signals
from contracts import Case, CaseLink, CaseLinkType, CaseStatus, FollowUpKind, FollowUpStatus, Invoice, LineItem

TODAY = date.today().isoformat()


def _codes(store, case):
    return {s.code for s in signals(case, store.get_vendor(case.vendor_id), load_policy(), store)}


def test_checks_catch_every_planted_issue_and_nothing_on_clean_invoices(offline, tmp_path):
    store = fresh_store()
    clean = run(store, "case_21", "case_25", "case_33", "case_41")       # clean, or below materiality only
    for c in clean:
        assert _codes(store, c) == set(), c.id
    assert _codes(store, run(store, "case_03")) == {"price_over"}        # amendment billed before it took effect
    assert _codes(store, run(store, "case_06")) == {"qty_short"}
    assert _codes(store, run(store, "case_10")) == {"not_on_po"}         # unapproved expedite line
    assert _codes(store, run(store, "case_40")) == {"price_over", "probation"}
    alone = fresh_store()                                               # on its own, so it isn't also a resend
    bank = variant(alone, tmp_path, "case_25", "case_25b", lambda d: d.update(remit_account_last4="9902"))
    assert _codes(alone, bank) == {"bank_mismatch"}
    dup = variant(store, tmp_path, "case_25", "case_25c")               # the same file again
    assert "duplicate" in _codes(store, dup)
    paid = variant(store, tmp_path, "case_25", "case_25d", lambda d: d.update(invoice_number="KM-INV-29980-A"))
    assert "duplicate" in _codes(store, paid)                         # number of a paid invoice, resent with -A
    # no disagreement with the pipeline on any of these
    for c in clean + [dup]:
        c = store.get_case(c.id)
        assert disagreements(c, signals(c, store.get_vendor(c.vendor_id), load_policy(), store)) == [], c.id


def test_match_variances_are_exact(offline):
    store = fresh_store()
    [row] = match_rows(run(store, "case_06"), store)
    assert (row.qty_variance, row.amount_at_risk) == (Decimal("12"), Decimal("17400.00"))
    [row] = match_rows(run(store, "case_03"), store)            # price in force on the invoice date (MSA 1,180)
    assert (row.po_price, row.price_variance, row.amount_at_risk) == (Decimal("1180.00"), Decimal("60.00"), Decimal("2400.00"))


def stages(c):
    return {b["case_id"]: b for b in c.get("/ap/bills").json()}


def test_bills_land_in_the_right_stage_and_show_the_truth(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_06", "case_25", "case_27", "case_43", "case_05")
    c = client(monkeypatch, store)
    bs = stages(c)
    assert bs["case_25"]["stage"] == "ready_to_pay" and bs["case_25"]["payable"] == "72500.00"
    six = bs["case_06"]                                           # hold: only the undisputed part is booked
    assert six["stage"] == "ready_to_pay" and (six["amount"], six["payable"], six["disputed"]) == \
        ("87000.00", "69600.00", "17400.00")
    assert "undisputed" in six["warning"] and six["sub_case_ids"] == ["case_06-1"]
    assert "case_06-1" not in bs                                  # sub-cases are grouped under the bill
    assert bs["case_43"]["stage"] == "needs_review" and bs["case_43"]["needs"] == "controller"
    assert bs["case_27"]["stage"] == "needs_review" and "Quarantined" in bs["case_27"]["warning"]
    assert bs["case_05"]["stage"] == "needs_review" and bs["case_05"]["amount"] is None   # PDF unread offline
    d = c.get("/ap/bills/case_06").json()
    assert any("Sub-case case_06-1" in a["text"] for a in d["activity"])
    assert any("undisputed part" in a["text"] for a in d["activity"])
    assert c.get("/ap/bills/case_27").json()["checks"] == []       # nothing read, nothing to check


def test_replies_and_credit_notes_are_activity_not_bills(offline, monkeypatch):
    store = fresh_store()
    seven = run(store, "case_07")
    inv = seven.invoice
    cn = Case(id="cn_1", vendor_id="V-FORMOSA", status=CaseStatus.resolved, created_at=datetime.now(timezone.utc),
              links=[CaseLink(type=CaseLinkType.attached_to, case_id="case_07", reason="credit note")],
              invoice=Invoice(doc_id="d", vendor_id="V-FORMOSA", invoice_no="CN-121", invoice_date=inv.invoice_date,
                              currency="TWD", credit_for=inv.invoice_no, total=Decimal("372000.00"),
                              lines=[LineItem(line_no=1, sku=inv.lines[0].sku, description="credit", qty=Decimal("20"),
                                              unit_price=Decimal("18600.00"), amount=Decimal("372000.00"))]))
    reply = Case(id="reply_1", vendor_id="V-FORMOSA", status=CaseStatus.resolved, created_at=datetime.now(timezone.utc),
                 links=[CaseLink(type=CaseLinkType.attached_to, case_id="case_07", reason="supplier reply")])
    store.save_case(cn)
    store.save_case(reply)
    c = client(monkeypatch, store)
    bs = stages(c)
    assert "cn_1" not in bs and "reply_1" not in bs
    assert bs["case_07"]["payable"] == "8928000.00"               # the credit offsets the held part: nothing reversed
    texts = [a["text"] for a in c.get("/ap/bills/case_07").json()["activity"]]
    assert any("Credit note CN-121" in t for t in texts) and any("Supplier reply" in t for t in texts)
    assert c.post("/approvals/cn_1", json={"approver": "m.chen@helix.example", "role": "controller",
                                           "decision": "approved"}).status_code == 409


def _run(c, ids, who="ap.lead@helix.example", pay_date=TODAY, **kw):
    return c.post("/ap/payments", json={"case_ids": ids, "pay_date": pay_date, "created_by": who, **kw})


def test_payment_runs_pay_only_what_was_booked_and_never_post(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_06", "case_25", "case_43")
    c = client(monkeypatch, store)
    ledger = ledger_path(store).read_text()
    assert _run(c, ["case_43"]).status_code == 400                # not approved / not booked
    ok = _run(c, ["case_06", "case_25"], pay_date="2099-01-01")   # after the discount window
    assert ok.status_code == 201
    pays = {p["case_id"]: p for p in ok.json()["payments"]}
    assert pays["case_06"]["gross_amount"] == "69600.00"          # undisputed part only, never the 87,000 invoice
    assert pays["case_25"]["amount"] == "72500.00"
    assert {p["pay_to_last4"] for p in pays.values()} == {"5150"}  # vendor master account
    assert _run(c, ["case_25"]).status_code == 400                # already in a run
    batch = ok.json()["id"]
    assert c.post(f"/ap/payments/{batch}/release", json={"released_by": "ap.lead@helix.example"}).status_code == 403
    done = c.post(f"/ap/payments/{batch}/release", json={"released_by": "m.chen@helix.example"})
    assert done.json()["status"] == "paid" and stages(c)["case_25"]["stage"] == "paid"
    assert ledger_path(store).read_text() == ledger                # payment runs never touch the ledger


def test_release_rechecks_the_guard(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_25")
    c = client(monkeypatch, store)
    batch = _run(c, ["case_25"], pay_date="2099-01-01").json()
    case = store.get_case("case_25")
    case.invoice.bank_last4 = "9902"                              # e.g. a re-read shows a new bank account
    store.save_case(case)
    r = c.post(f"/ap/payments/{batch['id']}/release", json={"released_by": "m.chen@helix.example"})
    assert r.status_code == 400 and "vendor master" in r.json()["detail"]


def test_bank_change_is_blocked_before_and_after_approval(offline, monkeypatch, tmp_path):
    store = fresh_store()
    case = variant(store, tmp_path, "case_25", "case_bank", lambda d: d.update(remit_account_last4="9902",
                                                                               invoice_number="KM-INV-39002"))
    assert case.decision.value == "escalate"
    c = client(monkeypatch, store)
    body = {"approver": "ap.lead@helix.example", "role": "approver", "decision": "approved", "comment": ""}
    r = c.post("/approvals/case_bank", json=body)
    assert r.status_code == 403 and "out of band" in r.json()["detail"]
    case = store.get_case("case_bank")                            # the callback via the number on file is done
    callbacks = [f for f in case.follow_ups if f.kind == FollowUpKind.callback]
    assert callbacks                                              # B opened the callback follow-up
    for f in callbacks:
        f.status, f.closed_by = FollowUpStatus.done, "ap.lead@helix.example (called the number on file)"
    store.save_case(case)
    ok = c.post("/approvals/case_bank", json=body)
    assert ok.status_code == 200 and ok.json()["journal_entry"] is not None   # resumed at the Poster, booked once
    b = stages(c)["case_bank"]
    assert b["stage"] == "blocked" and "vendor master" in b["payment_block"]
    r = _run(c, ["case_bank"])
    assert r.status_code == 400 and "vendor master" in r.json()["detail"]


def test_human_approval_resumes_at_the_poster(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_43")                                         # hold; the agents' controller rejected
    c = client(monkeypatch, store)
    body = lambda who, role, **kw: {"approver": who, "role": role, "decision": "approved", "comment": "", **kw}  # noqa: E731
    assert c.post("/approvals/case_43", json=body("ap.lead@helix.example", "approver")).status_code == 403  # limit
    assert c.post("/approvals/case_43", json=body("j.park@helix.example", "controller")).status_code == 403  # requester
    r = c.post("/approvals/case_43", json=body("m.chen@helix.example", "controller", scope="full"))
    assert r.status_code == 200 and r.json()["status"] == "posted" and r.json()["journal_entry"]
    assert payable(store.get_case("case_43"), store.list_cases()) == Decimal("291160.00")
    assert stages(c)["case_43"]["stage"] == "ready_to_pay"
    assert c.post("/approvals/case_43", json=body("m.chen@helix.example", "controller")).status_code == 409  # once


def test_report_and_settings(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_06", "case_10", "case_25", "case_43")
    c = client(monkeypatch, store)
    rep = c.get("/ap/report").json()
    assert sum(b["count"] for b in rep["aging"]) == 4 and len(rep["forecast"]) == 6
    assert Decimal(rep["caught_usd"]) == Decimal("17400.00") + Decimal("2800.00") + Decimal("291160.00")
    assert Decimal(rep["open_usd"]) == Decimal("69600.00") + Decimal("15200.00") + Decimal("72500.00") + Decimal("291160.00")
    st = c.get("/ap/settings").json()
    assert st["approval_limits"]["approver"] == "100000.00" and st["sla_hours"] == 24


def test_payment_block_only_for_high_risk(offline):
    store = fresh_store()
    case = run(store, "case_06")
    assert payment_block(signals(case, store.get_vendor(case.vendor_id), load_policy(), store)) is None


def test_payment_methods_follow_the_vendor_country(offline, monkeypatch):
    store = fresh_store()
    run(store, "case_25")
    c = client(monkeypatch, store)
    body = lambda m: {"case_ids": ["case_25"], "pay_date": "2099-01-01",  # noqa: E731
                      "created_by": "ap.lead@helix.example", "methods": {"case_25": m}}
    assert "isn't available" in c.post("/ap/payments", json=body("ach")).json()["detail"]   # Kestrel is KR
    assert c.post("/ap/payments", json=body("intl_wire")).json()["payments"][0]["method"] == "intl_wire"


def test_detail_has_checks_chain_and_warning(offline, monkeypatch, tmp_path):
    store = fresh_store()
    run(store, "case_25")
    variant(store, tmp_path, "case_25", "case_25c")
    c = client(monkeypatch, store)
    d = c.get("/ap/bills/case_25c").json()
    assert d["bill"]["stage"] == "rejected" and d["verdict"] == "risk" and "duplicate of KM-INV-30247" in d["bill"]["warning"]
    assert [s["label"] for s in d["approval_steps"]] == ["Prepared by ReconAI", "AP lead approval", "Release payment"]
    assert d["last_paid"]["invoice_no"] == "KM-INV-29980"
    ok = c.get("/ap/bills/case_25").json()
    assert ok["verdict"] == "ready" and ok["approval_steps"][1]["status"] == "done"


def test_human_signoff_mode_books_nothing_until_a_person_approves(offline, monkeypatch):
    from backend.core.runner import make_ctx, run_fixture
    from backend.evals.fixtures import case_dir, load_fixture
    store = fresh_store()
    ctx = make_ctx(store)
    ctx.human_signoff = True                                      # the live app's mode
    for cid in ("case_25", "case_06"):                            # clean, and a short delivery (hold)
        run_fixture(load_fixture(cid), case_dir(cid), ctx)
    c = client(monkeypatch, store)
    bs = stages(c)
    for cid in ("case_25", "case_06"):
        case = store.get_case(cid)
        assert case.journal_entry is None and not [a for a in case.approvals if a.decision.value == "approved"], cid
        assert bs[cid]["stage"] == "needs_review", cid           # waits for a person, nothing payable
    assert _run(c, ["case_25"]).status_code == 400
    ok = c.post("/approvals/case_25", json={"approver": "ap.lead@helix.example", "role": "approver",
                                            "decision": "approved", "comment": "checked"})
    assert ok.status_code == 200 and ok.json()["journal_entry"] and stages(c)["case_25"]["stage"] == "ready_to_pay"
    held = c.post("/approvals/case_06", json={"approver": "ap.lead@helix.example", "role": "approver",
                                              "decision": "approved", "comment": ""})
    assert held.status_code == 200 and stages(c)["case_06"]["payable"] == "69600.00"   # only the undisputed part
