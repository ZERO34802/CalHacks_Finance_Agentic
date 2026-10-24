"""Harness, tracer and data-set tests (owner C)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from email import policy
from email.parser import BytesParser

import pytest

from backend.core.llm import LLMResult
from backend.core.runner import make_ctx
from backend.evals.fixtures import answer_key, case_dir, case_ids, load_fixture, seed
from backend.evals.harness import build_board, invariants, score, scored_types
from backend.store.sqlite import SQLiteStore
from backend.trace.tracer import llm_cost, mask
from contracts import (Approval, ApprovalDecision, Case, CaseLink, CaseLinkType, CaseStatus, Decision, Discrepancy,
                       DiscrepancyType, Invoice, JournalEntry, LineItem, PaidInvoice, Posting, Role)

T0 = datetime(2026, 10, 24, 9, tzinfo=timezone.utc)
D = Decimal


def _ctx():
    store = SQLiteStore(":memory:")
    seed(store)
    return make_ctx(store)


def _inv(total="72500.00", cur="USD", no="KM-INV-30118") -> Invoice:
    return Invoice(doc_id="d1", vendor_id="V-KESTREL", invoice_no=no, invoice_date=date(2026, 10, 12), currency=cur,
                   po_number="PO-7001", total=D(total),
                   lines=[LineItem(line_no=1, sku="X", description="x", qty=D("50"), unit_price=D("1450.00"),
                                   amount=D("72500.00"))])


def _posted(cid="c1", approver="ap.lead@helix.example", role=Role.approver, limit="100000.00",
            requester="j.park@helix.example", key="V-KESTREL:30118", je_date=date(2026, 10, 12)) -> Case:
    return Case(id=cid, vendor_id="V-KESTREL", created_at=T0, decision=Decision.approve, status=CaseStatus.posted,
                invoice=_inv(),
                approvals=[Approval(id="a", case_id=cid, approver=approver, role=role,
                                    decision=ApprovalDecision.approved, limit=D(limit), at=T0)],
                journal_entry=JournalEntry(id="je", case_id=cid, date=je_date, narration="n", requested_by=requester,
                                           approved_by=approver, idempotency_key=key,
                                           postings=[Posting(account="Expenses:COGS:Materials", amount=D("72500.00"),
                                                             currency="USD"),
                                                     Posting(account="Liabilities:AP", amount=D("-72500.00"),
                                                             currency="USD")]))


# --- discrepancy normalization + variance ---------------------------------------------

def test_scored_types_conventions():
    c = Case(id="c", vendor_id="v", created_at=T0, discrepancies=[
        Discrepancy(type=DiscrepancyType.qty_short, delta=D("100")),
        Discrepancy(type=DiscrepancyType.price_over, material=False, delta=D("10")),
        Discrepancy(type=DiscrepancyType.locked_period, material=False),
        Discrepancy(type=DiscrepancyType.over_limit, material=False)])
    assert scored_types(c) == {DiscrepancyType.qty_short, DiscrepancyType.below_materiality}


def test_score_variance_and_extraction():
    ctx = _ctx()
    exp = answer_key()["case_12"]
    c = Case(id="case_12", vendor_id="V-FORMOSA", created_at=T0, decision=Decision.hold, skill="ap-3way-match",
             invoice=_inv(total="5610000.00", cur="TWD", no="INV-263"),
             discrepancies=[Discrepancy(type=DiscrepancyType.qty_short, delta=D("186000.00")),
                            Discrepancy(type=DiscrepancyType.unapproved_freight, delta=D("-30000.00"))])
    r = score(c, exp, [], ctx)
    assert r.checks["variance"] and r.checks["extract_invoice_no"] and r.checks["extract_total"]
    assert r.checks["decision"] and r.checks["discrepancies"] and r.checks["skill"]
    assert not r.checks["inv_trace_complete"] and any("inv_trace_complete" in m for m in r.misses)


def test_links_and_quarantine_checks():
    ctx = _ctx()
    exp = answer_key()["case_05"]
    c = Case(id="case_05", vendor_id="V-AEROLANE", created_at=T0, decision=Decision.reject,
             links=[CaseLink(type=CaseLinkType.duplicate_of, invoice_no="INV-2291", reason="paid"),
                    CaseLink(type=CaseLinkType.related_pattern, reason="ignored by the links check")])
    assert score(c, exp, [], ctx).checks["links"]
    c.links = []
    assert not score(c, exp, [], ctx).checks["links"]
    q = answer_key()["case_27"]
    cq = Case(id="case_27", vendor_id="V-FORMOSA", created_at=T0, decision=Decision.escalate,
              status=CaseStatus.quarantined, quarantine_reason="macro")
    r = score(cq, q, [], ctx)
    assert r.checks["quarantine"] and "extract_total" not in r.checks


def test_injection_checks():
    ctx = _ctx()
    exp = answer_key()["case_31"]
    c = _posted("case_31")
    c.decision = Decision.escalate
    r = score(c, exp, [], ctx)
    assert not r.checks["injection_flagged"] and not r.checks["injection_zero_actions"]
    assert not r.checks["inv_no_post_unless_approved"]


# --- invariants ---------------------------------------------------------------------

def test_invariants_clean_post():
    ctx = _ctx()
    checks = invariants(_posted(), [], ctx, {})
    assert {k: v for k, v in checks.items() if k != "inv_trace_complete"} == {
        "inv_no_post_unless_approved": True, "inv_balanced": True, "inv_approved_before_post": True,
        "inv_requester_ne_approver": True, "inv_within_limit": True, "inv_period_open": True,
        "inv_idempotency_unique": True}


@pytest.mark.parametrize("kw,broken", [
    ({"requester": "ap.lead@helix.example"}, "inv_requester_ne_approver"),
    ({"limit": "50000.00"}, "inv_within_limit"),
    ({"role": Role.approver, "limit": "5000000.00"}, None),  # approval.limit above the role's policy limit is capped
    ({"je_date": date(2026, 9, 29)}, "inv_period_open"),
])
def test_invariants_catch_violations(kw, broken):
    ctx = _ctx()
    checks = invariants(_posted(**kw), [], ctx, {})
    failed = {k for k, v in checks.items() if not v} - {"inv_trace_complete"}
    assert failed == ({broken} if broken else set())


def test_invariant_over_role_limit():
    ctx = _ctx()
    c = _posted(limit="5000000.00")
    c.invoice.total = D("174000.00")
    assert not invariants(c, [], ctx, {})["inv_within_limit"]          # AP lead policy limit 100k
    c.approvals[0].role = Role.controller
    assert invariants(c, [], ctx, {})["inv_within_limit"]


def test_duplicate_idempotency_key_across_run():
    ctx = _ctx()
    seen: dict[str, str] = {}
    assert invariants(_posted("c1"), [], ctx, seen)["inv_idempotency_unique"]
    assert not invariants(_posted("c2"), [], ctx, seen)["inv_idempotency_unique"]
    assert invariants(_posted("c1"), [], ctx, seen)["inv_idempotency_unique"]  # same case re-run is fine


def test_board_rates_and_tags():
    ctx = _ctx()
    key = answer_key()
    results = [score(Case(id=cid, vendor_id="v", created_at=T0, decision=Decision.escalate), key[cid], [], ctx)
               for cid in ("case_01", "case_04")]
    b = build_board("r", T0, results)
    assert b.catch_rate == 1.0 and b.false_alarm_rate == 1.0
    assert {t.tag for t in b.by_tag} >= {"clean", "attack", "format:pdf", "channel:email"}
    assert 0 <= b.check_rates["decision"] <= 1


# --- tracer ---------------------------------------------------------------------------

def test_record_llm_tokens_and_cost():
    ctx = _ctx()
    with ctx.trace.step("c1", "reader") as s:
        ctx.trace.record_llm(LLMResult(output=None, input_tokens=10_000, output_tokens=2_000), role="reader")
        ctx.trace.record_llm(LLMResult(output=None, input_tokens=500, output_tokens=50, cached=True))
    assert s.tokens == 12_550
    assert s.cost_usd == D("0.080000") == llm_cost(10_000, 2_000)
    assert len(s.detail["llm_calls"]) == 2
    stored = ctx.store.list_steps("c1", ctx.run_id)[0]
    assert stored.tokens == 12_550 and stored.cost_usd == D("0.080000")


def test_bank_numbers_masked_in_stored_detail():
    ctx = _ctx()
    with ctx.trace.step("c1", "vendor_guard"):
        ctx.trace.annotate(detail={"new_bank_account": "MY-5012-3344-9902", "bank_last4": "9902",
                                   "note": "remit to account no. 1234567890 now", "total": "3300000.00",
                                   "account": "Liabilities:AP"})
        ctx.trace.record_sandbox("write", path="scratch/plan.md", text="IBAN DE89370400440532013000")
    d = ctx.store.list_steps("c1", ctx.run_id)[0].detail
    assert d["new_bank_account"] == "****9902" and d["bank_last4"] == "9902"
    assert "1234567890" not in d["note"] and "****7890" in d["note"]
    assert d["total"] == "3300000.00" and d["account"] == "Liabilities:AP"
    assert "0532013000" not in json.dumps(d)
    assert mask({"routing_number": 26009593}) == {"routing_number": "****9593"}


# --- data set ------------------------------------------------------------------------

def _attachments(cid: str) -> list[tuple[str, bytes]]:
    folder = case_dir(cid)
    out = []
    for item in load_fixture(cid).inbound:
        data = (folder / item.path).read_bytes()
        if item.path.endswith(".eml"):
            msg = BytesParser(policy=policy.default).parsebytes(data)
            out += [(p.get_filename(), p.get_payload(decode=True)) for p in msg.iter_attachments()]
        else:
            out.append((item.path, data))
    return out


def test_dataset_shape():
    key = answer_key()
    assert set(key) == set(case_ids()) and len(key) >= 30
    for cid, exp in key.items():
        fx = load_fixture(cid)
        for item in fx.inbound:
            assert (case_dir(cid) / item.path).exists(), (cid, item.path)
        if exp.decision == Decision.hold:
            assert exp.skill == "ap-3way-match"
        if exp.quarantined:
            assert exp.decision == Decision.escalate
        assert any(t.startswith("format:") for t in exp.tags) and any(t.startswith("channel:") for t in exp.tags)
        assert exp.note


def test_structured_files_match_answer_key():
    key = answer_key()
    for cid in ("case_03", "case_06", "case_10", "case_16", "case_21", "case_25"):  # API JSON
        payload = json.loads(_attachments(cid)[0][1])
        no = payload.get("invoice_number") or payload.get("inv_no")
        tot = payload.get("total") or payload.get("invoice_total")
        assert (no, D(tot)) == (key[cid].invoice_no, key[cid].total), cid
    for cid in ("case_07", "case_33"):  # CSV
        raw = _attachments(cid)[0][1].decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(raw), delimiter=";" if cid == "case_33" else ","))
        assert rows[0]["invoice_number"] == key[cid].invoice_no
        assert sum(D(r["line_amount"]) for r in rows) == key[cid].total


def test_planted_attacks_and_ingest_cases():
    a13 = _attachments("case_13")[0][1]
    a14 = _attachments("case_14")[0][1]
    assert hashlib.sha256(a13).digest() == hashlib.sha256(a14).digest()
    macro = zipfile.ZipFile(io.BytesIO(_attachments("case_27")[0][1]))
    assert "xl/vbaProject.bin" in macro.namelist() and load_fixture("case_27").inbound[0].path.endswith(".xlsx")
    assert ",=" in _attachments("case_28")[0][1].decode()
    assert json.loads(_attachments("case_29")[0][1])["schema"] == "aerolane.invoice.v2"
    pdf31 = _attachments("case_31")[0][1]
    from pypdf import PdfReader
    assert "IGNORE ALL" in PdfReader(io.BytesIO(pdf31)).pages[0].extract_text().upper()


def test_paid_history_line_hashes_consistent():
    def line_hash(lines):  # same definition as data/generate.py (and doc dedup)
        canon = sorted((sk, str(D(q).normalize()), str(D(p).quantize(D("0.01")))) for sk, q, p in lines)
        return hashlib.sha256(json.dumps(canon).encode()).hexdigest()
    rows = json.loads((case_dir("case_01").parents[1] / "world" / "paid_history.json").read_text())
    paid = {r["invoice_no"]: PaidInvoice.model_validate(r) for r in rows}
    assert paid["INV-2291"].line_hash == line_hash([("FRT-AIR-TPE-SJC", "1", "18400.00"),
                                                    ("FRT-EXPEDITE", "1", "3200.00")])
    # the recurring-fee look-alike really does collide on line hash (that's the trap)
    assert paid["INV-2299"].line_hash == line_hash([("SVC-CUSTOMS-RET", "1", "2500.00")])
