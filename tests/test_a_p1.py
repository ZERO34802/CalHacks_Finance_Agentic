"""A P1: manifests, S3/ERP, sub-cases, pay-undisputed, credit notes, corrections, replies, probation, queue,
missing files, onboarding checks. Offline (no LLM)."""
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from backend.core.runner import make_ctx
from backend.evals.fixtures import seed
from backend.intake import ingest as ingest_mod
from backend.intake.adapters import derive_links, parse_api
from backend.intake.ingest import ingest
from backend.onboarding.checks import flags, run_checks
from backend.pipeline import hooks as A
from backend.pipeline.doc_dedup import DocDedup
from backend.pipeline.lib import ledger as L
from backend.pipeline.lib.split import split
from backend.pipeline.matcher import Matcher
from backend.pipeline.poster import Poster
from backend.pipeline.registry import Registry
from backend.store.sqlite import SQLiteStore
from contracts import (Approval, ApprovalDecision, Case, CaseFixture, CaseLinkType, CaseStatus, Channel, Decision,
                       DiscrepancyType as T, Document, DocKind, FollowUp, FollowUpKind, FollowUpStatus,
                       InboundItem, Invoice, LineItem, OnboardingRequest, Role, StepStatus)

T0 = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)
CSV_H = "invoice_number,invoice_date,po_number,currency,line_no,sku,description,quantity,unit_price,line_amount,remit_last4"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("RECONAI_LEDGER", str(tmp_path / "ledger.beancount"))
    store = SQLiteStore(":memory:")
    seed(store)
    return make_ctx(store)


def step(ctx, cid, st, case):
    with ctx.trace.step(cid, st.name) as s:
        out = st.run(case, ctx)
    return out, s


def inv_(vendor, no, d, ccy, po, rows, total=None, **kw):
    lines = [LineItem(line_no=i, sku=s, description=s, qty=D(q), unit_price=D(p), amount=(D(q) * D(p)).quantize(D("0.01")))
             for i, (s, q, p) in enumerate(rows, 1)]
    return Invoice(doc_id="x", vendor_id=vendor, invoice_no=no, invoice_date=d, currency=ccy, po_number=po, lines=lines,
                   total=D(total) if total else sum((l.amount for l in lines), D(0)), **kw)


def mk_case(ctx, cid, invoice, vendor=None, as_of=date(2026, 10, 20), docs=None, save=True):
    doc = Document(id=f"{cid}-d1", kind=DocKind.credit_note if invoice and invoice.credit_for else DocKind.invoice,
                   channel="email", filename="f.pdf", sha256=f"sha-{cid}", mime="application/pdf", received_at=T0)
    if invoice:
        invoice.doc_id = doc.id
    c = Case(id=cid, vendor_id=vendor or invoice.vendor_id, invoice=invoice, documents=docs or [doc], created_at=T0,
             as_of=as_of, status=CaseStatus.in_progress)
    if save:
        ctx.store.save_case(c)
    return c


def triage(ctx, case):
    for st in (DocDedup(), Registry(), Matcher()):
        case, _ = step(ctx, case.id, st, case)
    ctx.store.save_case(case)
    return case


def approve(case, scope=None, approver="m.chen@helix.example", role=Role.controller, limit="1000000.00",
            decision=Decision.hold):
    case.decision = decision
    case.approvals = [Approval(id="a1", case_id=case.id, approver=approver, role=role, scope=scope,
                               decision=ApprovalDecision.approved, limit=D(limit) if limit else None, at=T0)]
    return case


def after(ctx, case):
    with ctx.trace.step(case.id, "after_case"):
        A.a_after_case(case, ctx)
    ctx.store.save_case(case)
    return case


WAFER = ("WFR-N3-300", "1000", "18600.00")


# --- intake --------------------------------------------------------------------------------

def _batch(tmp_path, files, manifest):
    items = []
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
        items.append(InboundItem(channel="sftp", path=name, sender="sftp-formosa", received_at=T0))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    items.append(InboundItem(channel="sftp", path="manifest.json", sender="sftp-formosa", received_at=T0))
    return CaseFixture(id="b1", title="batch", inbound=items, as_of=date(2026, 10, 24))


def test_sftp_manifest(ctx, tmp_path):
    csv1 = (CSV_H + "\nINV-1,2026-10-14,PO-5501,TWD,1,WFR-N3-300,w,1,18600.00,18600.00,2207\n").encode()
    sha = hashlib.sha256(csv1).hexdigest()
    ok = ingest(_batch(tmp_path, {"a.csv": csv1}, {"batch": "B", "count": 1, "files": [{"path": "a.csv", "sha256": sha}]}),
                tmp_path, ctx)
    assert ok.status == CaseStatus.new and [d.filename for d in ok.documents] == ["a.csv"]
    for man in ({"batch": "B", "count": 2, "files": [{"path": "a.csv", "sha256": sha}, {"path": "b.csv", "sha256": "0"}]},
                {"batch": "B", "count": 1, "files": [{"path": "a.csv", "sha256": "0" * 64}]}):
        bad = ingest(_batch(tmp_path, {"a.csv": csv1}, man), tmp_path, ctx)
        assert bad.status == CaseStatus.quarantined and "manifest" in bad.quarantine_reason


def test_s3_and_erp_connectors(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_mod, "s3_prefixes", lambda: {"s3://helix-ap-inbound/formosa/": "V-FORMOSA"})
    v = ctx.store.get_vendor("V-FORMOSA")
    ctx.store.save_vendor(v.model_copy(update={"channels": [*v.channels, Channel.s3]}))
    csv1 = (CSV_H + "\nINV-1,2026-10-14,PO-5501,TWD,1,WFR-N3-300,w,1,18600.00,18600.00,2207\n").encode()
    (tmp_path / "a.csv").write_bytes(csv1)
    fx = CaseFixture(id="s3", title="s3", inbound=[InboundItem(channel="s3", path="a.csv",
                                                                sender="s3://helix-ap-inbound/formosa/2026/", received_at=T0)],
                     as_of=date(2026, 10, 24))
    assert ingest(fx, tmp_path, ctx).vendor_id == "V-FORMOSA"
    fx.inbound[0].sender = "s3://other-bucket/"
    assert ingest(fx, tmp_path, ctx).status == CaseStatus.quarantined
    erp = {"schema": "helix.erp.ap_invoice.v1", "vendor_id": "V-PENANG", "invoice_no": "PPT-1", "invoice_date": "2026-10-20",
           "currency": "USD", "po_number": "PO-6100",
           "lines": [{"line_no": 1, "sku": "PKG-COWOS-L", "description": "pkg", "qty": "10", "unit_price": "1650.00",
                      "amount": "16500.00"}], "total": "16500.00", "bank_last4": "4418"}
    (tmp_path / "e.json").write_text(json.dumps(erp))
    fx = CaseFixture(id="erp", title="erp", inbound=[InboundItem(channel="erp", path="e.json", sender="erp-export",
                                                                  received_at=T0)], as_of=date(2026, 10, 24))
    case = ingest(fx, tmp_path, ctx)
    assert case.vendor_id == "V-PENANG" and case.status == CaseStatus.new
    inv, ver = parse_api(json.dumps(erp).encode(), "d", "V-PENANG")
    assert inv.total == D("16500.00") and "SIMULATED" in ver
    (tmp_path / "e.json").write_text(json.dumps({**erp, "vendor_id": "V-NOPE"}))
    assert ingest(fx, tmp_path, ctx).status == CaseStatus.quarantined


def test_corrected_number_derivation():
    i = derive_links(inv_("V", "INV-881-R", date(2026, 10, 23), "TWD", "PO-5501", [WAFER]))
    assert i.corrects == "INV-881"
    assert derive_links(inv_("V", "INV-2291-A", date(2026, 10, 23), "USD", "P", [WAFER])).corrects is None


# --- split / probation ------------------------------------------------------------------------

def test_split_case12_like(ctx):
    v = inv_("V-FORMOSA", "INV-9", date(2026, 10, 14), "TWD", "PO-5501", [WAFER, ("FRT-EXP-AIR", "1", "30000.00")])
    case = triage(ctx, mk_case(ctx, "c12", v))
    sp = split(case)
    assert sp["separable"] and sp["disputed"] == D("1146000.00") and sp["undisputed"] == D("17484000.00")
    assert case.disputed_amount == D("1146000.00") and sp["lines"] == {1: D("17484000.00"), 2: D("0.00")}


def test_probation_zero_tolerance_no_materiality(ctx):
    v = ctx.store.get_vendor("V-KESTREL")
    ctx.store.save_vendor(v.model_copy(update={"on_probation": True, "probation_until": date(2026, 12, 30)}))
    case = triage(ctx, mk_case(ctx, "p1", inv_("V-KESTREL", "KM-P1", date(2026, 10, 12), "USD", "PO-7001",
                                               [("HBM3E-12H-24G", "1", "1450.20")]), as_of=date(2026, 10, 12)))
    assert [(d.type, d.material, d.delta) for d in case.discrepancies] == [(T.price_over, True, D("0.20"))]
    ctx.store.save_vendor(v.model_copy(update={"on_probation": True, "probation_until": date(2026, 10, 1)}))
    case = triage(ctx, mk_case(ctx, "p2", inv_("V-KESTREL", "KM-77777", date(2026, 10, 12), "USD", "PO-7001",
                                               [("HBM3E-12H-24G", "1", "1450.20")]), as_of=date(2026, 10, 12)))
    assert [d.type for d in case.discrepancies] == [T.below_materiality]  # probation over


# --- poster: undisputed / credit note / correction ----------------------------------------------

def _case02(ctx, cid="case_02"):
    return triage(ctx, mk_case(ctx, cid, inv_("V-FORMOSA", "INV-881", date(2026, 10, 14), "TWD", "PO-5501", [WAFER]),
                               as_of=date(2026, 10, 14)))


def test_poster_pays_undisputed_part(ctx):
    case = approve(_case02(ctx), scope="undisputed")
    case, s = step(ctx, case.id, Poster(), case)
    assert s.status == StepStatus.ok and case.paid_amount == D("17484000.00") and case.disputed_amount == D("1116000.00")
    assert case.status != CaseStatus.posted and case.journal_entry.idempotency_key.endswith(":undisputed")
    assert s.detail["tied_out"]
    entries, errors = L.load(L.ledger_path(ctx.store))
    assert not errors and L.ap_balances(entries, "Liabilities:AP") == {"TWD": D("-17484000.00")}
    ctx.store.save_case(case)
    full = approve(case, scope=None, decision=Decision.approve)
    full, s2 = step(ctx, case.id, Poster(), full)
    assert s2.status == StepStatus.blocked and "already booked" in s2.error


def test_poster_undisputed_needs_separable_and_limit(ctx):
    case = approve(_case02(ctx), scope="undisputed", role=Role.approver, approver="ap.lead@helix.example",
                   limit="100000.00")
    case, s = step(ctx, case.id, Poster(), case)  # 17.48M TWD = 542k USD > 100k
    assert s.status == StepStatus.blocked and "limit" in s.error and case.journal_entry is None
    v = inv_("V-FORMOSA", "INV-7", date(2026, 10, 14), "KRW", "PO-5501", [WAFER])  # currency mismatch: not separable
    c2 = approve(triage(ctx, mk_case(ctx, "cx", v, as_of=date(2026, 10, 14))), scope="undisputed")
    c2, s = step(ctx, c2.id, Poster(), c2)
    assert s.status == StepStatus.blocked and "separable" in s.error


def _with_followup(ctx, case, kind=FollowUpKind.credit_note):
    case.follow_ups = [FollowUp(id="fu1", case_id=case.id, kind=kind, due=date(2026, 10, 20), created_at=T0)]
    ctx.store.save_case(case)
    return case


def test_credit_note_closes_followup_resolves_subcase(ctx):
    case = approve(_case02(ctx), scope="undisputed")
    case, _ = step(ctx, case.id, Poster(), case)
    case = after(ctx, _with_followup(ctx, case))
    assert case.sub_case_ids == ["case_02-1"]
    kid = ctx.store.get_case("case_02-1")
    assert kid.parent_id == "case_02" and kid.links[0].type == CaseLinkType.sub_case_of and kid.fingerprint
    assert kid.decision == Decision.hold and kid.discrepancies[0].type == T.qty_short

    cn = inv_("V-FORMOSA", "CN-118", date(2026, 10, 22), "TWD", None, [("WFR-N3-300", "60", "18600.00")],
              credit_for="INV-881")
    cnc = triage(ctx, mk_case(ctx, "cn1", cn, as_of=date(2026, 10, 22)))
    assert any(l.type == CaseLinkType.attached_to and l.case_id == "case_02" for l in cnc.links)
    assert not cnc.discrepancies and cnc.journal_entry is None
    # support document: applied in the Matcher, ends resolved with no decision and no skill
    assert cnc.status == CaseStatus.resolved and cnc.decision is None and cnc.skill is None
    assert "credit note CN-118 applied to case_02" in cnc.notes
    after(ctx, cnc)  # idempotent
    tgt = ctx.store.get_case("case_02")
    assert tgt.follow_ups[0].status == FollowUpStatus.done and tgt.follow_ups[0].closed_by == "cn1-d1"
    assert ctx.store.get_case("case_02-1").status == CaseStatus.resolved and tgt.status == CaseStatus.resolved


def test_credit_note_from_lookalike_sender_closes_nothing(ctx):
    case = after(ctx, _with_followup(ctx, approve(_case02(ctx))))
    cn = inv_("V-FORMOSA", "CN-9", date(2026, 10, 22), "TWD", None, [("WFR-N3-300", "60", "18600.00")], credit_for="INV-881")
    c = mk_case(ctx, "cn2", cn, save=False)
    c.notes.append("intake: sender domain 'formosa-wafer.com' is a look-alike of Formosa (formosawafer.com.tw)")
    ctx.store.save_case(c)
    cnc = triage(ctx, c)
    assert cnc.status != CaseStatus.resolved
    assert ctx.store.get_case("case_02").follow_ups[0].status == FollowUpStatus.open


def test_correction_posts_only_delta_and_resolves_original(ctx):
    case = approve(_case02(ctx), scope="undisputed")
    case, _ = step(ctx, case.id, Poster(), case)
    case = after(ctx, _with_followup(ctx, case))
    corr = inv_("V-FORMOSA", "INV-881-R", date(2026, 10, 23), "TWD", "PO-5501", [("WFR-N3-300", "940", "18600.00")])
    derive_links(corr)
    cc = triage(ctx, mk_case(ctx, "case_37", corr, as_of=date(2026, 10, 23)))
    assert not cc.discrepancies and any(l.type == CaseLinkType.corrected_by and l.case_id == "case_02" for l in cc.links)
    cc = approve(cc, decision=Decision.approve)
    cc, s = step(ctx, cc.id, Poster(), cc)
    assert s.status == StepStatus.skipped and cc.paid_amount == D("0.00") and cc.journal_entry is None
    after(ctx, cc)
    orig = ctx.store.get_case("case_02")
    assert orig.status == CaseStatus.resolved and orig.reopens == 1 and orig.follow_ups[0].status == FollowUpStatus.done
    assert ctx.store.get_case("case_02-1").status == CaseStatus.resolved


def test_correction_of_unpaid_original_posts_in_full(ctx):
    _case02(ctx)
    corr = derive_links(inv_("V-FORMOSA", "INV-881-R", date(2026, 10, 23), "TWD", "PO-5501",
                             [("WFR-N3-300", "940", "18600.00")]))
    cc = approve(triage(ctx, mk_case(ctx, "c37", corr, as_of=date(2026, 10, 23))), decision=Decision.approve)
    cc, s = step(ctx, cc.id, Poster(), cc)
    assert s.status == StepStatus.ok and cc.paid_amount == D("17484000.00")


# --- sub-cases / replies -------------------------------------------------------------------------------

def test_sub_cases_per_material_discrepancy_and_strictest(ctx):
    v = inv_("V-FORMOSA", "INV-9", date(2026, 10, 14), "TWD", "PO-5501", [WAFER, ("FRT-EXP-AIR", "1", "30000.00")])
    case = triage(ctx, mk_case(ctx, "c12", v))
    case.decision = Decision.approve  # weaker than the children: raised
    case = after(ctx, case)
    assert case.sub_case_ids == ["c12-1", "c12-2"] and case.decision == Decision.hold
    kids = [ctx.store.get_case(i) for i in case.sub_case_ids]
    assert {k.discrepancies[0].type for k in kids} == {T.qty_short, T.unapproved_freight}
    assert all(k.parent_id == "c12" and not k.documents for k in kids)
    assert len({k.fingerprint for k in kids}) == 2
    again = triage(ctx, case)  # re-run: sub-cases are not compared as duplicates
    assert not any(d.type == T.duplicate_invoice for d in again.discrepancies)


def test_supplier_reply_links_same_vendor_only(ctx):
    _case02(ctx)
    body = Document(id="r-d1", kind=DocKind.email, channel="email", filename="reply.eml", sha256="r", mime="message/rfc822",
                    received_at=T0, text="We will send the credit note by Oct 20.", subject="Re: [REC case_02] short delivery")
    r = mk_case(ctx, "r", None, vendor="V-FORMOSA", docs=[body])
    for st in (DocDedup(), Registry(), Matcher()):
        r, s = step(ctx, r.id, st, r)
    assert any(l.type == CaseLinkType.attached_to and l.case_id == "case_02" for l in r.links)
    assert "supplier reply to case_02" in r.notes and "attached to case_02: supplier reply" in r.notes
    assert r.status == CaseStatus.resolved and r.decision is None
    other = mk_case(ctx, "r2", None, vendor="V-KESTREL", docs=[body.model_copy(update={"id": "r2-d1"})])
    with pytest.raises(ValueError, match="cannot be attached"):  # nothing linked -> runner escalates with reason
        step(ctx, other.id, Registry(), other)
    assert not other.links and any("another vendor" in n for n in other.notes)


# --- queue / sweep / onboarding ------------------------------------------------------------------------

def test_priority_and_queue_route(ctx, monkeypatch):
    big = mk_case(ctx, "q1", inv_("V-FORMOSA", "INV-Q1", date(2026, 9, 10), "TWD", "PO-5501", [WAFER]),
                  as_of=date(2026, 10, 20))
    small = mk_case(ctx, "q2", inv_("V-AEROLANE", "INV-Q2", date(2026, 10, 19), "USD", "PO-8840",
                                    [("FRT-AIR-TPE-SJC", "1", "100.00")]), as_of=date(2026, 10, 20))
    pb, db = A.priority(big, ctx)
    ps, _ = A.priority(small, ctx)
    assert pb > ps and db["f_due"] == 1.0 and db["f_critical"] == 1.0
    from fastapi.testclient import TestClient
    import backend.api.app as app_module
    monkeypatch.setattr(app_module, "store", ctx.store)
    rows = TestClient(app_module.app).get("/queue").json()
    ids = [r["case_id"] for r in rows]
    assert ids.index("q1") < ids.index("q2")


def test_missing_files_sweep(ctx):
    v = ctx.store.get_vendor("V-KESTREL")
    ctx.store.save_vendor(v.model_copy(update={"expected_schedule": "daily"}))
    mk_case(ctx, "k1", inv_("V-KESTREL", "KM-1", date(2026, 10, 20), "USD", "PO-7001", [("HBM3E-12H-24G", "1", "1.00")]))
    with ctx.trace.step("tick", "sweep"):
        assert A.missing_files(ctx, date(2026, 10, 21)) == []
        alerts = A.missing_files(ctx, date(2026, 10, 25))
        A.missing_files(ctx, date(2026, 10, 25))  # idempotent
    assert [a.vendor_id for a in alerts] == ["V-KESTREL"]
    from contracts import Alert
    assert len([a for a in ctx.store.list_records(Alert, "alert") if a.kind == "missing_file"]) == 1


def test_onboarding_checks_match_answer_key(ctx):
    from backend.evals.fixtures import DATA
    key = {r["id"]: sorted(r["flags"]) for r in json.loads((DATA / "onboarding" / "answer_key.json").read_text())}
    for rid, want in key.items():
        req = OnboardingRequest.model_validate_json((DATA / "onboarding" / f"{rid}.json").read_text())
        checks = run_checks(req, ctx)
        assert sorted(flags(checks)) == want, rid
        assert any(c.simulated for c in checks if c.name == "sanctions_hit")


def test_validators_accept_memory_and_skill_citations(ctx):
    from backend.pipeline.validators import Validators
    from contracts import Citation, Proposal
    case = _case02(ctx)
    case.proposal = Proposal(case_id=case.id, recommendation=Decision.hold, explanation="held", confidence=0.9,
                             citations=[Citation(doc_id="memory:formosa-wafer", locator="line 3"),
                                        Citation(doc_id="skill:ap-3way-match", locator="v8")])
    case, s = step(ctx, case.id, Validators(), case)
    assert s.status == StepStatus.ok and case.proposal is not None


def test_validators_know_linked_case_figures(ctx):
    from backend.pipeline.validators import Validators
    from contracts import Citation, Proposal
    case = approve(_case02(ctx), scope="undisputed")
    case, _ = step(ctx, case.id, Poster(), case)
    ctx.store.save_case(case)
    corr = derive_links(inv_("V-FORMOSA", "INV-881-R", date(2026, 10, 23), "TWD", "PO-5501",
                             [("WFR-N3-300", "940", "18600.00")]))
    cc = triage(ctx, mk_case(ctx, "c37", corr, as_of=date(2026, 10, 23)))
    assert any("only the delta 0.00" in n for n in cc.notes)
    cc.proposal = Proposal(case_id=cc.id, recommendation=Decision.approve, confidence=0.9,
                           explanation="Corrects INV-881: removes the disputed TWD 1,116,000.00; 17,484,000.00 already booked.",
                           citations=[Citation(doc_id=cc.invoice.doc_id, locator="line 1")])
    cc, s = step(ctx, cc.id, Validators(), cc)
    assert s.status == StepStatus.ok, s.error


def test_poster_cfo_can_book_above_controller_limit(ctx):
    # USD 1.5M invoice: above the controller's 1M, within the CFO's policy limit
    ctx.store.save_po(ctx.store.get_po("PO-7001").model_copy(update={"po_number": "PO-BIG", "doc_id": "erp-PO-BIG"}))
    from contracts import Receipt, ReceiptLine
    ctx.store.save_receipt(Receipt(doc_id="erp-GRN-BIG", po_number="PO-BIG", received_date=date(2026, 10, 10),
                                   lines=[ReceiptLine(sku="HBM3E-12H-24G", qty_received=D("1100"))], received_by="w"))
    big = inv_("V-KESTREL", "KM-BIG", date(2026, 10, 12), "USD", "PO-BIG", [("HBM3E-12H-24G", "1000", "1450.00")])
    case = triage(ctx, mk_case(ctx, "cfo1", big, as_of=date(2026, 10, 12)))
    assert not [d for d in case.discrepancies if d.material]
    ctl = approve(case, decision=Decision.approve, role=Role.controller, limit="1000000.00")
    ctl, s = step(ctx, ctl.id, Poster(), ctl)
    assert s.status == StepStatus.blocked and "limit" in s.error  # controller can't
    cfo = approve(case, decision=Decision.approve, approver="hum_cfo@helix.example", role=Role.cfo, limit=None)
    cfo.approvals[0].limit = None  # no limit on the approval: the policy cfo limit applies
    cfo, s = step(ctx, cfo.id, Poster(), cfo)
    assert s.status == StepStatus.ok and cfo.paid_amount == D("1450000.00") and s.detail["effective_limit"] == "100000000.00"
    # SoD still applies to the CFO
    sod = approve(triage(ctx, mk_case(ctx, "cfo2", inv_("V-KESTREL", "KM-BIG2", date(2026, 10, 12), "USD", "PO-BIG",
                                                       [("HBM3E-12H-24G", "10", "1450.00")]), as_of=date(2026, 10, 12))),
                  decision=Decision.approve, approver="j.park@helix.example", role=Role.cfo, limit="100000000.00")
    sod, s = step(ctx, sod.id, Poster(), sod)
    assert s.status == StepStatus.blocked and "requester" in s.error
