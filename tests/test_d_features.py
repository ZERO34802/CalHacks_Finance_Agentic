"""D's new features, end to end and offline (no network at all): supplier email outbox + Resend delivery,
the Coinbase USDC rail, the per-vendor memory timeline, and the Slack negotiation bot + onboarding.

Resend, CDP and Slack are replaced by fakes; LLM is off (the repo .env may hold real keys, so every env var that
could reach a live service is removed for every test here)."""
from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from d_helpers import client, fresh_store, offline, run  # noqa: F401  (offline is a fixture)

from backend.ap import coinbase
from backend.ap.payments import PaymentStore
from backend.core.config import ROOT, load_policy
from backend.memory import timeline, writer
from backend.notify import email as mail
from backend.slack import bot as slack_bot
from backend.slack import contract as ct
from backend.slack import market, negotiation as neg
from backend.slack import onboard
from backend.slack.models import Category, Line, Message, NegotiationState, Session
from backend.vendors import onboarding as onb
from contracts import (Approval, ApprovalDecision, Case, CaseStatus, Decision, Discrepancy, DiscrepancyType, Invoice,
                       LineItem, MemoryEntry, OnboardingRequestIn, Role, TreasuryStatus, VendorContract)

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
LIVE_ENV = ("RESEND_API_KEY", "RESEND_FROM", "RECONAI_EMAIL_REDIRECT", "CDP_API_KEY_ID", "CDP_API_KEY_SECRET",
            "CDP_WALLET_SECRET", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "RECONAI_SLACK_INTERNAL_USERS",
            "COINBASE_USD_SCALE", "CRS_BASE_URL")


@pytest.fixture(autouse=True)
def no_network(monkeypatch, offline, tmp_path):  # noqa: F811
    monkeypatch.setenv("RECONAI_LLM", "off")
    monkeypatch.setenv("RECONAI_MARKET_WEB", "off")
    monkeypatch.setenv("COINBASE_MODE", "off")  # the sandbox rail is tested explicitly below
    for k in LIVE_ENV:
        monkeypatch.delenv(k, raising=False)

    def no_http(*a, **k):
        raise AssertionError("no real HTTP in tests")
    monkeypatch.setattr(mail.httpx, "post", no_http)
    monkeypatch.setattr(coinbase.httpx, "post", no_http)
    monkeypatch.setattr(ct, "OUT", tmp_path / "contracts")
    coinbase.set_rail(None)
    assert not market.web_enabled()
    yield
    coinbase.set_rail(None)
    slack_bot.BOT = None


# --- 1. supplier discrepancy email --------------------------------------------------------------------

class FakeResend:
    def __init__(self, fail: int = 0):
        self.calls, self.fail = [], fail

    def __call__(self, to, subject, text, key):
        self.calls.append({"to": to, "subject": subject, "text": text, "key": key})
        if self.fail:
            self.fail -= 1
            raise RuntimeError("Resend HTTP 503: try later")
        return f"re_{len(self.calls)}"


def _held(store):
    case = run(store, "case_06")                     # Kestrel short delivery: a hold that asks for a credit note
    assert case.decision == Decision.hold and len(case.outbound) == 1
    return case


def test_supplier_email_body_is_detailed_and_cites_the_record(offline):  # noqa: F811
    store = fresh_store()
    case = _held(store)
    em = case.outbound[0]
    assert em.to == "finance@kestrelmemory.co.kr" and f"[REC {case.id}]" in em.subject
    assert case.invoice.invoice_no in em.body and str(case.invoice.total) in em.body
    delta = next(d.delta for d in case.discrepancies if d.type == DiscrepancyType.qty_short)
    assert str(delta) in em.body and "What we found:" in em.body
    assert f"keep [REC {case.id}] in the subject" in em.body
    assert "invoice 60, our record 48" in em.body and "erp-PO-7003 line 1" in em.body
    assert "paying the undisputed 69600.00 USD" in em.body and "17400.00 USD is on hold" in em.body
    internal = em.body.split("\n", 1)[1].lower()                   # past the greeting (the vendor is Kestrel *Memory*)
    assert not any(w in internal for w in ("controller", "approver", "memory", "fraud", "risk"))


def test_email_without_resend_key_stays_in_the_outbox(offline):  # noqa: F811
    store = fresh_store()
    case = _held(store)
    [rec] = mail.deliver_case(store, case)
    assert (rec.status, rec.provider, rec.kind) == ("outbox", "outbox", "supplier_discrepancy")
    assert "RESEND_API_KEY" in rec.error and rec.to == "finance@kestrelmemory.co.kr" and rec.delivered_to is None
    assert [e.id for e in mail.outbox(store, case_id=case.id)] == [rec.id]


def test_fixture_domain_is_never_mailed_without_a_redirect(offline, monkeypatch):  # noqa: F811
    store = fresh_store()
    case = _held(store)
    fake = FakeResend()
    monkeypatch.setattr(mail, "_resend", fake)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_fake")
    [rec] = mail.deliver_case(store, case)
    assert rec.status == "outbox" and "RECONAI_EMAIL_REDIRECT" in rec.error and fake.calls == []
    # a real (non-fixture) address goes straight to the recipient, body unchanged
    real = mail.send(store, kind="onboarding_confirmation", to="dana@baylineprecision.com", subject="s", body="hello",
                     key="k-real")
    assert real.status == "sent" and real.delivered_to == "dana@baylineprecision.com"
    assert fake.calls == [{"to": "dana@baylineprecision.com", "subject": "s", "text": "hello", "key": "k-real"}]


def test_redirect_delivers_once_with_the_intended_recipient_on_top(offline, monkeypatch):  # noqa: F811
    store = fresh_store()
    case = _held(store)
    fake = FakeResend()
    monkeypatch.setattr(mail, "_resend", fake)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_fake")
    monkeypatch.setenv("RECONAI_EMAIL_REDIRECT", "demo-inbox@test.dev")
    [rec] = mail.deliver_case(store, case)
    assert (rec.status, rec.provider, rec.provider_id) == ("sent", "resend", "re_1")
    assert rec.delivered_to == "demo-inbox@test.dev" and rec.to == "finance@kestrelmemory.co.kr"
    call = fake.calls[0]
    assert call["to"] == "demo-inbox@test.dev"
    assert call["text"].startswith("[ReconAI demo: intended for finance@kestrelmemory.co.kr]\n\n")
    assert call["text"].endswith(case.outbound[0].body) and call["key"] == f"supplier:{case.outbound[0].idempotency_key}"
    again = mail.deliver_case(store, case)                         # idempotent: same record, no second send
    assert [e.model_dump() for e in again] == [rec.model_dump()] and len(fake.calls) == 1


def test_failed_send_is_kept_and_retried(offline, monkeypatch):  # noqa: F811
    store = fresh_store()
    case = _held(store)
    fake = FakeResend(fail=1)
    monkeypatch.setattr(mail, "_resend", fake)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_fake")
    monkeypatch.setenv("RECONAI_EMAIL_REDIRECT", "demo-inbox@test.dev")
    [bad] = mail.deliver_case(store, case)
    assert bad.status == "failed" and "503" in bad.error
    c = client(monkeypatch, store)
    assert c.get("/emails", params={"case_id": case.id}).json()[0]["status"] == "failed"
    [ok] = c.post(f"/emails/{case.id}/send").json()
    assert ok["status"] == "sent" and ok["id"] == bad.id and ok["created_at"].startswith(bad.created_at.isoformat()[:19])
    assert len(fake.calls) == 2
    assert c.post(f"/emails/{case.id}/send").json()[0]["provider_id"] == "re_2" and len(fake.calls) == 2
    assert c.post("/emails/nope/send").status_code == 404


# --- 2. Coinbase rail ---------------------------------------------------------------------------------

class FakeRail:
    def __init__(self, usdc="10", fail_transfers=0, pending=0):
        self.usdc, self.fail_transfers, self.pending = usdc, fail_transfers, pending
        self.transfers, self.confirms = [], []

    def status(self):
        return TreasuryStatus(mode="live", network="base-sepolia", address="0xTREASURY",
                              balances={"USDC": self.usdc, "ETH": "0.01"}, usd_scale=coinbase.usd_scale(), note="fake")

    def fund(self):
        return {"eth": "ok", "usdc": "ok"}

    def create_wallet(self, name):
        return f"0x{name}"

    def transfer(self, to, units):
        self.transfers.append((to, units))
        if self.fail_transfers:
            self.fail_transfers -= 1
            raise coinbase.RailError("nonce too low")
        return f"0xtx{len(self.transfers)}"

    def confirmed(self, tx_hash):
        self.confirms.append(tx_hash)
        if self.pending:
            self.pending -= 1
            raise coinbase.RailError(f"no receipt for {tx_hash} after 90s")
        return True


def _coinbase_run(monkeypatch, wallet="0xKESTRELWALLET"):
    store = fresh_store()
    run(store, "case_06", "case_25")                               # two booked Kestrel bills
    if wallet:
        v = store.get_vendor("V-KESTREL")
        store.save_vendor(v.model_copy(update={"wallet_address": wallet}))
    c = client(monkeypatch, store)
    r = c.post("/ap/payments", json={"case_ids": ["case_06", "case_25"], "pay_date": "2099-01-01",
                                     "created_by": "ap.lead@helix.example"})
    assert r.status_code == 201, r.text
    return store, c, r.json()


def _release(c, batch, rail="coinbase", who="m.chen@helix.example"):
    return c.post(f"/ap/payments/{batch['id']}/release", json={"released_by": who, "rail": rail})


def test_usdc_amounts_are_scaled_decimals():
    assert coinbase.usdc_for(Decimal("72500.00")) == Decimal("0.072500")
    assert coinbase.usdc_for(Decimal("0.10")) == Decimal("0.000001")        # never below one unit
    assert coinbase.to_units(Decimal("0.0725")) == 72500


def test_coinbase_release_pays_the_vendor_master_wallet(offline, monkeypatch):  # noqa: F811
    store, c, batch = _coinbase_run(monkeypatch)
    fake = FakeRail()
    coinbase.set_rail(fake)
    assert _release(c, batch, who="ap.lead@helix.example").status_code == 403   # the preparer can't release
    assert fake.transfers == []
    out = _release(c, batch).json()
    assert out["status"] == "paid" and out["rail"] == "coinbase" and out["released_by"] == "m.chen@helix.example"
    for p in out["payments"]:
        want = coinbase.usdc_for(Decimal(p["amount_usd"]))
        assert p["status"] == "paid" and p["payee_address"] == "0xKESTRELWALLET" and p["rail"] == "coinbase"
        assert Decimal(p["onchain_amount"]) == want and p["onchain_token"] == "USDC" and p["network"] == "base-sepolia"
        assert p["tx_hash"].startswith("0xtx") and p["explorer_url"] == f"https://sepolia.basescan.org/tx/{p['tx_hash']}"
    assert fake.transfers == [("0xKESTRELWALLET", coinbase.to_units(coinbase.usdc_for(Decimal(p["amount_usd"]))))
                              for p in out["payments"]]
    assert _release(c, batch).status_code == 400                    # already released


def test_coinbase_refuses_vendor_without_wallet_or_funds(offline, monkeypatch):  # noqa: F811
    store, c, batch = _coinbase_run(monkeypatch, wallet=None)
    fake = FakeRail()
    coinbase.set_rail(fake)
    r = _release(c, batch)
    assert r.status_code == 400 and "no payout wallet" in r.json()["detail"] and fake.transfers == []
    v = store.get_vendor("V-KESTREL")
    store.save_vendor(v.model_copy(update={"wallet_address": "0xKESTRELWALLET"}))
    coinbase.set_rail(poor := FakeRail(usdc="0.0001"))
    r = _release(c, batch)
    assert r.status_code == 400 and "Fund the treasury" in r.json()["detail"] and poor.transfers == []
    import backend.api.app as app_module
    left = app_module.payments.get(batch["id"])
    assert left.status == "scheduled" and all(p.status == "scheduled" and p.tx_hash is None for p in left.payments)


def test_coinbase_partial_failure_retries_only_unpaid_lines(offline, monkeypatch):  # noqa: F811
    store, c, batch = _coinbase_run(monkeypatch)
    fake = FakeRail(fail_transfers=1)
    coinbase.set_rail(fake)
    out = _release(c, batch).json()
    first, second = out["payments"]
    assert out["status"] == "partially_paid"
    assert first["status"] == "failed" and "nonce" in first["error"] and first["tx_hash"] is None
    assert second["status"] == "paid"
    assert _release(c, batch, rail="bank").status_code == 400        # retry only on the rail it was released on
    done = _release(c, batch).json()
    assert done["status"] == "paid" and all(p["status"] == "paid" for p in done["payments"])
    assert len(fake.transfers) == 3                                  # 2 at release + 1 retry of the failed line only
    assert done["payments"][1]["tx_hash"] == second["tx_hash"]


def test_coinbase_pending_transfer_is_never_sent_twice(offline, monkeypatch):  # noqa: F811
    store, c, batch = _coinbase_run(monkeypatch)
    fake = FakeRail(pending=1)                                       # first receipt poll times out
    coinbase.set_rail(fake)
    out = _release(c, batch).json()
    assert out["status"] == "partially_paid" and out["payments"][0]["tx_hash"] == "0xtx1"
    done = _release(c, batch).json()                                 # the receipt has landed by now
    assert done["status"] == "paid" and len(fake.transfers) == 2     # 0xtx1 confirmed, not re-sent


def test_coinbase_not_configured(offline, monkeypatch):  # noqa: F811
    store, c, batch = _coinbase_run(monkeypatch)
    s = c.get("/ap/coinbase").json()
    assert s["mode"] == "not_configured" and s["usd_scale"] == "0.000001"
    r = _release(c, batch)
    assert r.status_code == 400 and "isn't configured" in r.json()["detail"]
    assert c.post("/ap/coinbase/faucet").status_code == 409
    coinbase.set_rail(FakeRail(usdc="5"))
    s = c.get("/ap/coinbase").json()
    assert (s["mode"], s["address"], s["balances"]["USDC"]) == ("live", "0xTREASURY", "5")
    vendors = c.post("/ap/coinbase/vendor-wallets").json()
    assert {v["id"]: v["wallet_address"] for v in vendors}["V-FORMOSA"] == "0xreconai-vendor-v-formosa"
    assert store.get_vendor("V-KESTREL").wallet_address == "0xKESTRELWALLET"   # an existing wallet is kept


def test_coinbase_sandbox_runs_the_full_release_without_keys(offline, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("COINBASE_MODE", "sandbox")
    monkeypatch.setenv("RECONAI_COINBASE_SANDBOX", str(tmp_path / "sandbox.json"))
    coinbase.set_rail(None)
    store, c, batch = _coinbase_run(monkeypatch)
    s = c.get("/ap/coinbase").json()
    assert s["mode"] == "sandbox" and s["balances"]["USDC"] == "0" and s["explorer_url"] is None
    assert _release(c, batch).status_code == 400                     # unfunded: refused, nothing paid
    c.post("/ap/coinbase/faucet")
    for v in store.list_vendors():                                    # the payout wallet comes from the vendor master
        v.wallet_address = None
        store.save_vendor(v)
    assert all(v["wallet_address"].startswith("0x") for v in c.post("/ap/coinbase/vendor-wallets").json())
    r = _release(c, batch)
    assert r.status_code == 200 and r.json()["status"] == "paid" and r.json()["rail"] == "coinbase"
    p = r.json()["payments"][0]
    assert p["network"] == "sandbox" and p["explorer_url"] is None and p["tx_hash"].startswith("0x")
    assert p["payee_address"] == store.get_vendor(p["vendor_id"]).wallet_address
    sent = sum(Decimal(x["onchain_amount"]) for x in r.json()["payments"])
    assert Decimal(c.get("/ap/coinbase").json()["balances"]["USDC"]) == Decimal("1") - sent


# --- 3. memory timeline ---------------------------------------------------------------------------

def _aerolane_hold(cid: str, day: int) -> Case:
    at = datetime(2026, 10, day, 9, tzinfo=timezone.utc)
    inv = Invoice(doc_id=f"d_{cid}", vendor_id="V-AEROLANE", invoice_no=f"INV-{cid}", invoice_date=at.date(),
                  currency="USD", po_number="PO-8801", total=Decimal("18000.00"),
                  lines=[LineItem(line_no=1, sku="FRT-AIR-EXP", description="expedite", qty=Decimal("1"),
                                  unit_price=Decimal("18000.00"), amount=Decimal("18000.00"))])
    return Case(id=cid, vendor_id="V-AEROLANE", created_at=at, as_of=at.date(), decision=Decision.hold,
                status=CaseStatus.awaiting_vendor, invoice=inv,
                discrepancies=[Discrepancy(type=DiscrepancyType.unapproved_freight, delta=Decimal("2800.00"))],
                approvals=[Approval(id="a", case_id=cid, approver="m.chen@helix.example", role=Role.controller,
                                    decision=ApprovalDecision.rejected, comment="Expedite not approved", at=at)])


def test_memory_timeline_versions_sources_uses_and_as_of(offline, monkeypatch):  # noqa: F811
    store = fresh_store()
    run(store, "case_10", "case_21")                               # Aerolane through the real pipeline
    extra = _aerolane_hold("case_32", 17)
    store.save_case(extra)
    writer.after_case(extra, store)                                # count line -> v2
    writer.forget_case(store, "case_32", by="m.chen@helix.example")  # count -> v3, case_32 review forgotten

    c = client(monkeypatch, store)
    assert c.get("/memory/vendors/V-NOPE/timeline").status_code == 404
    tl = timeline.VendorMemoryTimeline.model_validate(c.get("/memory/vendors/V-AEROLANE/timeline").json())
    assert tl.subject == "aerolane-freight" and tl.memory_version.startswith("aerolane-freight@v")
    slots = {s.entry_id: s for s in tl.slots}

    count = slots["aerolane-freight:w:count:unapproved_freight"]
    assert count.label == "Unapproved freight / expedite fees"
    # v1 (case_10) -> v2 (case_10 + case_32) -> forgotten with case_32 -> recomputed from case_10 alone
    assert [(v.version, v.change) for v in count.versions] == [(1, "added"), (2, "forgotten"), (1, "added")]
    assert count.versions[1].cases == ["case_10", "case_32"] and count.versions[1].text.startswith("2 unapproved")
    assert count.current.cases == ["case_10"] and count.current.source == "computed"
    assert count.current.text.startswith("1 unapproved")

    gone = slots["aerolane-freight:w:review:case_32:0"]
    assert gone.current is None and gone.versions[-1].change == "forgotten"
    assert "[forgotten" not in gone.versions[-1].text and gone.versions[-1].people == ["m.chen@helix.example"]
    assert gone.versions[-1].source == "controller"

    seed_line = next(s for s in tl.slots if s.entry_id == "aerolane-freight:2")    # seeded controller rule
    assert seed_line.current.source == "controller" and seed_line.current.people == ["M. Chen"]
    assert sum(tl.sources.values()) == sum(1 for s in tl.slots if s.current)

    uses = {u.case_id: u for u in tl.uses}
    assert set(uses) >= {"case_10", "case_21"} and uses["case_10"].decision == "hold"
    assert uses["case_10"].memory_version.startswith("aerolane-freight@v")
    assert any(e.kind == "memory_use" and e.case_ids == ["case_10"] for e in tl.events)
    assert [e.at for e in tl.events] == sorted(e.at for e in tl.events)

    before = {v.entry_id: v for v in timeline.as_of(tl, date(2026, 10, 9))}
    assert "aerolane-freight:w:count:unapproved_freight" not in before and "aerolane-freight:2" in before
    later = {v.entry_id: v for v in timeline.as_of(tl, date(2026, 10, 30))}
    assert later["aerolane-freight:w:count:unapproved_freight"].text.startswith("1 unapproved")
    assert "aerolane-freight:w:review:case_32:0" not in later


def test_memory_timeline_for_vendor_without_memory(offline):  # noqa: F811
    store = fresh_store()
    tl = timeline.build(store, store.get_vendor("V-TSC"))
    assert tl.slots == [] and tl.subject is None and tl.memory_version is None and tl.uses == []


# --- 4. Slack negotiation ------------------------------------------------------------------------

def _msgs(*rows):
    return [Message(user="U_HELIX" if who == "H" else "U_VENDOR", name=who, internal=who == "H", text=t, ts=str(i))
            for i, (who, t) in enumerate(rows)]


TRANSCRIPT = [
    ("V", "Thanks for having us. For 2,000 stacks of HBM3E 12-high we can do $1,520 per stack, net 30."),
    ("H", "That's well above what we pay today. We could do $1,350 per stack, and we'd want 2/15 net 30."),
    ("V", "We can meet you at $1,450 per stack with 2/15 net 30."),
    ("H", "Agreed: $1,450 per stack, 2/15 net 30."),
    ("V", "Deal, agreed. Send the paperwork."),
]


def test_negotiation_fallback_extracts_the_deal():
    st, engine = neg.extract(_msgs(*TRANSCRIPT))
    assert engine == "deterministic" and st.category == Category.hbm_memory
    [ln] = st.lines
    assert (ln.quantity, ln.vendor_unit_price, ln.our_counter_price, ln.agreed_unit_price) == ("2000", "1450", "1450", "1450")
    assert (st.discount_pct, st.discount_days, st.net_days, st.agreed) == ("0.02", 15, 30, True)
    early, _ = neg.extract(_msgs(*TRANSCRIPT[:2]))
    assert early.lines[0].vendor_unit_price == "1520" and early.lines[0].our_counter_price == "1350"
    assert early.agreed is False and early.lines[0].agreed_unit_price is None
    assert neg.signature(early) != neg.signature(st)
    assert neg.contract_ready(early) is None and neg.contract_ready(NegotiationState()) is not None
    assert neg.extract([])[1] == "empty"


def _hbm_history():
    pos = json.loads((ROOT / "data/world/pos.json").read_text())
    terms = json.loads((ROOT / "data/world/contract_terms.json").read_text())
    vals = [Decimal(ln["unit_price"]) for p in pos for ln in p["lines"] if ln["sku"].startswith("HBM")]
    vals += [Decimal(t["unit_price"]) for t in terms if t["sku"].startswith("HBM")]
    return vals


def test_market_analysis_is_decimal_math():
    ref = json.loads((ROOT / "backend/slack/market_reference.json").read_text())["hbm_memory"]
    p25, med, p75 = (Decimal(ref[k]) for k in ("p25", "median", "p75"))
    st = NegotiationState(category=Category.hbm_memory, lines=[
        Line(description="HBM3E 12-high", quantity="2000", vendor_unit_price="1520")])
    a = market.analyze(st, load_policy())
    [la] = a.lines
    hist = _hbm_history()
    best = min(hist)
    assert la.internal_best_usd == str(best) and Decimal(la.internal_median_usd) == Decimal(statistics.median(hist))
    anchor, target = min(best, p25), min(med, best)
    assert (la.anchor_usd, la.target_usd, la.walk_away_usd) == (str(anchor), str(target), str(p75))
    qty, quoted = Decimal(2000), Decimal("1520.00")
    assert la.quoted_usd == "1520.00" and la.position == "above the market 75th percentile"
    assert la.savings_at_target_usd == str((quoted - target) * qty)
    assert la.savings_at_anchor_usd == str((quoted - anchor) * qty)
    assert a.contract_value_usd == "3040000.00" and a.terms_on_table == "not discussed yet"
    assert any("60800.00 USD" in t for t in a.term_asks)            # 2% of 3,040,000
    # a written part number narrows our history to that SKU
    st.lines[0].sku = "HBM3E-12H-24G"
    la = market.analyze(st, load_policy()).lines[0]
    assert (la.internal_best_usd, la.anchor_usd, la.target_usd) == ("1450.00", "1180.00", "1300.00")
    assert la.savings_at_target_usd == "440000.00" and la.gap_vs_target_pct == "16.9"
    assert market.terms_label(30, Decimal("0.02"), 15) == "2/15 net 30"
    assert market.terms_label(30, Decimal("0.10"), 10) == "10/10 net 30"   # no '1E+1'
    assert market.market_notes(Category.hbm_memory) == []                  # web off: no live call


def _session(channel="C1"):
    return Session(channel=channel, owner="U_HELIX", owner_email="j.park@helix.example", owner_name="J. Park",
                   vendor_name="Bayline Precision Machining Inc", started_at=NOW, transcript=_msgs(*TRANSCRIPT))


def test_contract_build_and_pdf(tmp_path):
    st, _ = neg.extract(_msgs(*TRANSCRIPT))
    st.lines.append(Line(description="Spare stacks", quantity="12", agreed_unit_price="1450.505"))
    c = ct.build(_session(), st, NOW)
    assert [i["unit_price"] for i in c.items] == ["1450.00", "1450.505"]   # the agreed price, never re-rounded
    assert [i["amount"] for i in c.items] == ["2900000.00", "17406.06"]
    assert all(Decimal(i["amount"]) == (Decimal(i["qty"]) * Decimal(i["unit_price"])).quantize(Decimal("0.01"))
               for i in c.items)
    assert c.total == sum(Decimal(i["amount"]) for i in c.items) == Decimal("2917406.06")
    assert (c.terms.net_days, c.terms.discount_pct, c.terms.discount_days) == (30, Decimal("0.02"), 15)
    assert c.vendor_name == "Bayline Precision Machining Inc" and c.requested_by == "j.park@helix.example"
    path = ct.render_pdf(c)
    assert path.parent == tmp_path / "contracts" and path.read_bytes()[:5] == b"%PDF-"
    assert "2% discount if paid within 15 days" in ct.terms_text(c.terms)


def _bayline(**kw) -> OnboardingRequestIn:
    req = next(s for s in onb.samples() if s["label"] == "Clean new US supplier")["request"]
    return OnboardingRequestIn.model_validate({**req, "contact_email": "dana@baylineprecision.com", **kw})


def _small_contract(store) -> VendorContract:
    st = NegotiationState(category=Category.other, lines=[Line(description="Fixtures", quantity="10",
                                                               agreed_unit_price="1200")], net_days=45)
    c = ct.build(_session(), st, NOW)
    store.put_record(ct.KIND, c.id, c)
    return c


def test_low_risk_onboarding_is_auto_approved_with_terms_and_email(offline):  # noqa: F811
    assert onboard.auto_approve_enabled()
    store, pay = fresh_store(), PaymentStore(":memory:")
    contract = _small_contract(store)
    case = onboard.start(_bayline(), contract, store, pay, NOW)
    assert case.risk_tier == "low" and case.status == "approved" and case.auto_approved
    assert case.decided_by == onboard.POLICY_APPROVER != case.request.requested_by
    v = store.get_vendor(case.vendor_id)
    assert v.on_probation and v.contact_email == "dana@baylineprecision.com" and v.terms.net_days == 45
    assert store.get_record(VendorContract, ct.KIND, contract.id).status == "onboarded"
    [em] = mail.outbox(store, vendor_id=v.id)
    assert em.kind == "onboarding_confirmation" and em.to == "dana@baylineprecision.com" and em.status == "outbox"
    assert em.id == case.confirmation_email_id and "Net 45 days" in em.body and "ending 4021" in em.body
    assert [c.id for c in pay.onboarding()] == [case.id]
    # same company again: a new vendor master record, never an overwrite of the existing one
    again = onb.decide(onb.submit(_bayline(bank_last4="9999"), store, onboard.make_crs(), NOW),
                       "m.chen@helix.example", "controller", "approved", "", store, NOW)
    assert again.vendor_id != v.id and store.get_vendor(v.id).bank_last4 == "4021"


def test_medium_risk_onboarding_waits_and_sends_nothing(offline):  # noqa: F811
    store, pay = fresh_store(), PaymentStore(":memory:")
    contract = _small_contract(store)
    case = onboard.start(_bayline(expected_annual_spend_usd="2500000.00"), contract, store, pay, NOW)
    assert case.risk_tier == "medium" and case.status == "needs_review" and not case.auto_approved
    assert case.vendor_id is None and mail.outbox(store) == []
    assert store.get_record(VendorContract, ct.KIND, contract.id).status == "held"


# --- Slack bot with a fake client ---------------------------------------------------------------------

class FakeSlack:
    def __init__(self):
        self.posts, self.ephemeral, self.uploads, self.views = [], [], [], []

    def auth_test(self):
        return {"user_id": "U_BOT"}

    def users_info(self, user):
        return {"user": {"real_name": {"U_HELIX": "J. Park"}.get(user, "Dana Reyes"),
                         "profile": {"email": "j.park@helix.example" if user == "U_HELIX" else "dana@baylineprecision.com"}}}

    def chat_postMessage(self, **kw):
        self.posts.append(kw)

    def chat_postEphemeral(self, **kw):
        self.ephemeral.append(kw)

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)

    def views_open(self, **kw):
        self.views.append(kw)


def _say(bot, user, text, ts="1"):
    bot.on_message({"channel": "C1", "user": user, "text": text, "ts": ts})


def _form(**over):
    vals = {"legal_name": "Bayline Precision Machining Inc", "country": "US", "tax_id": "US-77-4012339",
            "address": "1180 Harbor Way", "city": "Richmond", "state": "CA", "zip": "94804",
            "contact_name": "Dana Reyes", "contact_email": "dana@baylineprecision.com",
            "contact_phone": "+1 510 555 0142", "bank_last4": "4021", **over}
    out = {k: {"v": {"value": v}} for k, v in vals.items()}
    out["tax_form"] = {"v": {"selected_option": {"value": "W-9"}}}
    return out


def test_slack_bot_negotiation_contract_and_onboarding(offline, monkeypatch):  # noqa: F811
    store = fresh_store()
    c = client(monkeypatch, store)
    import backend.api.app as app_module
    fake = FakeSlack()
    bot = slack_bot.ReconBot(store, app_module.payments, client=fake)
    assert bot.app is None and bot.bot_user == "U_BOT"

    bot.handle("negotiate", "Bayline Precision", "U_HELIX", "C1")
    s = bot.session("C1")
    assert s.owner == "U_HELIX" and s.owner_email == "j.park@helix.example" and s.vendor_name == "Bayline Precision"
    assert "assisting *J. Park*" in fake.posts[-1]["text"] and len(fake.ephemeral) == 1

    _say(bot, "U_VENDOR", "Hello! Happy to be here.")                 # no numbers: recorded, no coaching
    assert len(bot.session("C1").transcript) == 1 and len(fake.ephemeral) == 1
    for i, (who, text) in enumerate(TRANSCRIPT[:2]):
        _say(bot, "U_HELIX" if who == "H" else "U_VENDOR", text, ts=str(i + 2))
    notes = [e for e in fake.ephemeral[1:]]
    assert len(notes) == 2 and all(e["user"] == "U_HELIX" for e in notes)   # owner only, once per move
    assert "only you see this" in notes[-1]["text"] and "HBM3E stacks" in notes[-1]["text"]
    s = bot.session("C1")
    assert [m.internal for m in s.transcript] == [False, False, True]
    _say(bot, "U_VENDOR", "Our fab has 3 lines running this quarter.", ts="9")   # digits, same deal: no new note
    assert len(fake.ephemeral) == 3 and len(bot.session("C1").transcript) == 4
    for i, (who, text) in enumerate(TRANSCRIPT[2:]):
        _say(bot, "U_HELIX" if who == "H" else "U_VENDOR", text, ts=str(i + 10))
    assert "/reconai contract" in fake.ephemeral[-1]["text"]           # agreed: prompt to draft

    n = len(fake.ephemeral)
    bot.handle("contract", "", "U_VENDOR", "C1")                       # the vendor can't draft
    assert "Only the Helix person" in fake.ephemeral[-1]["text"] and fake.uploads == []
    bot.handle("contract", "", "U_HELIX", "C1")
    [up] = fake.uploads
    s = bot.session("C1")
    contract = store.get_record(VendorContract, ct.KIND, s.contract_id)
    assert contract.total == Decimal("2900000.00") and up["file"].endswith(f"{contract.id}.pdf")
    assert open(up["file"], "rb").read(5) == b"%PDF-"
    button = fake.posts[-1]["blocks"][1]["elements"][0]
    assert (button["action_id"], button["value"]) == ("accept_contract", contract.id)

    bot.accept("U_HELIX", "C1", contract.id, "trig-owner")             # Helix can't accept its own contract
    assert fake.views == [] and "supplier accepts" in fake.ephemeral[-1]["text"] and len(fake.ephemeral) == n + 2
    bot.accept("U_VENDOR", "C1", contract.id, "trig-vendor")
    [view] = fake.views
    assert view["trigger_id"] == "trig-vendor" and view["view"]["callback_id"] == "onboard_vendor"
    meta = json.loads(view["view"]["private_metadata"])

    for bad in ("12345", "12a4", "", "0000 "):
        res = bot.submit_form("U_VENDOR", _form(bank_last4=bad), meta)
        if bad.strip() == "0000":
            assert "bank_last4" not in res["errors"]                   # values are stripped
        else:
            assert "bank_last4" in res["errors"]
    assert "contact_email" in bot.submit_form("U_VENDOR", _form(contact_email="nope"), meta)["errors"]
    res = bot.submit_form("U_VENDOR", _form(), meta)
    assert res["errors"] == {} and res["values"]["tax_form"] == "W-9"

    bot.process_form("U_VENDOR", res["values"], meta)                  # 2.9M of spend: medium risk, a controller decides
    [case] = app_module.payments.onboarding()
    assert case.source == "slack" and case.contract_id == contract.id and case.status == "needs_review"
    assert case.request.requested_by == "j.park@helix.example" and case.request.contact_email == "dana@baylineprecision.com"
    assert "with Helix finance for review" in fake.posts[-1]["text"] and mail.outbox(store) == []
    assert fake.ephemeral[-1]["user"] == "U_HELIX" and "risk *medium*" in fake.ephemeral[-1]["text"]
    assert store.get_record(VendorContract, ct.KIND, contract.id).accepted_by == "Dana Reyes (Slack U_VENDOR)"

    monkeypatch.setattr(slack_bot, "BOT", bot)
    decide = lambda who, role: c.post(f"/vendors/onboarding/{case.id}/decide",  # noqa: E731
                                      json={"approver": who, "role": role, "decision": "approved"})
    assert decide("j.park@helix.example", "controller").status_code == 403    # the requester
    assert decide("ap.lead@helix.example", "approver").status_code == 403     # medium risk needs a controller
    ok = decide("m.chen@helix.example", "controller").json()
    assert ok["status"] == "approved" and ok["confirmation_email_id"]
    v = store.get_vendor(ok["vendor_id"])
    assert (v.terms.net_days, v.terms.discount_pct) == (30, Decimal("0.02")) and v.contact_email == "dana@baylineprecision.com"
    [em] = mail.outbox(store)
    assert em.kind == "onboarding_confirmation" and em.id == ok["confirmation_email_id"]
    assert "2% discount if paid within 15 days" in em.body
    assert store.get_record(VendorContract, ct.KIND, contract.id).status == "onboarded"
    assert "is onboarded as" in fake.posts[-1]["text"] and "approved by m.chen@helix.example" in fake.posts[-1]["text"]
    assert c.get("/contracts").json()[0]["id"] == contract.id
    pdf = c.get(f"/contracts/{contract.id}/pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
