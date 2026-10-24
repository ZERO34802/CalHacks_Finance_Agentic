"""Person B: router, policy table, cannot-downgrade, investigator + sandbox, vendor guard, approver + re-plan.

Cases are built by ingesting seed fixtures and setting invoice / discrepancies by hand, so these tests
don't depend on the real Reader / Matcher. Droid and Claude are forced off (deterministic paths).
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D

import pytest

from backend.agents import droid, policy_rules as rules
from backend.agents.approver import Approver, Review, deterministic_review
from backend.agents.investigator import AgentFinding, Investigator, investigate, to_proposal
from backend.agents.router import Router
from backend.agents.sandbox import build
from backend.agents.skills import load_skill
from backend.core.runner import make_ctx
from backend.evals.fixtures import case_dir, load_fixture, seed
from backend.intake.ingest import ingest
from backend.pipeline.vendor_guard import VendorGuard, lookalike_reason, screen
from backend.store.sqlite import SQLiteStore
from contracts import (ApprovalDecision, Case, CaseStatus, Citation, Decision, Discrepancy, DiscrepancyType as T,
                       Invoice, LineItem, Role, StepStatus)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("RECONAI_DROID", "off")
    monkeypatch.setenv("RECONAI_LLM", "off")


@pytest.fixture
def ctx():
    store = SQLiteStore(":memory:")
    seed(store)
    return make_ctx(store)


SEED = {  # case_id -> (vendor, invoice_no, date, po, currency, [(sku, qty, price)], bank_last4)
    "case_01": ("V-KESTREL", "KM-INV-30118", date(2026, 10, 12), "PO-7001", "USD", [("HBM3E-12H-24G", "50", "1450.00")], "5150"),
    "case_02": ("V-FORMOSA", "INV-881", date(2026, 10, 14), "PO-5501", "TWD", [("WFR-N3-300", "1000", "18600.00")], "2207"),
    "case_03": ("V-KESTREL", "KM-INV-30152", date(2026, 10, 16), "PO-7002", "USD", [("HBM3E-8H-24G", "40", "1240.00")], "5150"),
    "case_04": ("V-PENANG", "PPT-6620", date(2026, 10, 20), "PO-6100", "USD", [("PKG-COWOS-L", "2000", "1650.00")], "9902"),
    "case_05": ("V-AEROLANE", "INV-2291-A", date(2026, 10, 21), "PO-8840", "USD",
                [("FRT-AIR-TPE-SJC", "1", "18400.00"), ("FRT-EXPEDITE", "1", "3200.00")], "7731"),
}
QTY_SHORT = Discrepancy(type=T.qty_short, line_no=1, sku="WFR-N3-300", expected="940", actual="1000",
                        delta=D("1116000.00"), citations=[Citation(doc_id="erp-GRN-PO-5501", locator="row 1")])
PRICE_OVER = Discrepancy(type=T.price_over, line_no=1, sku="HBM3E-8H-24G", expected="1180.00", actual="1240.00",
                         delta=D("2400.00"), citations=[Citation(doc_id="erp-PO-7002", locator="line 1")])


def mk(ctx, cid: str, discs=(), **inv_over) -> Case:
    case = ingest(load_fixture(cid), case_dir(cid), ctx)
    vendor, no, d, po, cur, lines, bank = SEED[cid]
    doc = next((x.id for x in case.documents if x.kind.value == "invoice"), case.documents[0].id)
    items = [LineItem(line_no=i, sku=s, description=s, qty=D(q), unit_price=D(p), amount=D(q) * D(p))
             for i, (s, q, p) in enumerate(lines, 1)]
    fields = dict(doc_id=doc, vendor_id=vendor, invoice_no=no, invoice_date=d, currency=cur, po_number=po,
                  lines=items, total=sum((x.amount for x in items), D(0)), bank_last4=bank)
    fields.update(inv_over)
    case.invoice = Invoice(**fields)
    case.po, case.receipts = ctx.store.get_po(po), ctx.store.list_receipts(po)
    case.status = CaseStatus.in_progress
    case.discrepancies = [x.model_copy(deep=True) for x in discs]
    for x in case.discrepancies:
        x.citations.append(Citation(doc_id=doc, locator=f"line {x.line_no or 1}"))
    return case


def run_b(case: Case, ctx, approver: Approver | None = None) -> Case:
    for stage in [Router(), Investigator(), VendorGuard(), approver or Approver()]:
        with ctx.trace.step(case.id, stage.name):
            case = stage.run(case, ctx)
    return case


# --- router ---------------------------------------------------------------------

def test_router_mapping(ctx):
    pol = ctx.policy
    assert rules.route(mk(ctx, "case_02", [QTY_SHORT]), pol)[0] == "ap-3way-match"
    assert rules.route(mk(ctx, "case_03", [PRICE_OVER]), pol)[0] == "ap-3way-match"
    for t in (T.unapproved_freight, T.currency_mismatch, T.total_mismatch, T.fx_gap):
        assert rules.route(mk(ctx, "case_01", [Discrepancy(type=t)]), pol)[0] == "ap-3way-match"
    assert rules.route(mk(ctx, "case_04", [Discrepancy(type=T.bank_change)]), pol)[0] == "vendor-bank-change"
    assert rules.route(mk(ctx, "case_05", [Discrepancy(type=T.duplicate_invoice)]), pol)[0] is None
    assert rules.route(mk(ctx, "case_01", [Discrepancy(type=T.embedded_instructions), QTY_SHORT]), pol)[0] is None
    assert rules.route(mk(ctx, "case_01", [Discrepancy(type=T.unknown_po)]), pol)[0] is None
    assert rules.route(mk(ctx, "case_01", [Discrepancy(type=T.below_materiality, material=False)]), pol)[0] is None
    unknown = mk(ctx, "case_02", [QTY_SHORT])
    unknown.vendor_id = "V-UNKNOWN"
    assert rules.route(unknown, pol)[0] is None
    q = mk(ctx, "case_02", [QTY_SHORT])
    q.status = CaseStatus.quarantined
    assert rules.route(q, pol)[0] is None


def test_router_stage_picks_bank_change_skill_from_vendor_signals(ctx):
    case = mk(ctx, "case_04")  # no matcher discrepancies: Router pre-screens vendor risk
    with ctx.trace.step(case.id, "router"):
        case = Router().run(case, ctx)
    assert case.skill == "vendor-bank-change"
    assert {d.type for d in case.discrepancies} == {T.bank_change, T.lookalike_domain}


# --- policy table + cannot-downgrade ----------------------------------------------

@pytest.mark.parametrize("discs,expected", [
    ([], Decision.approve),
    ([Discrepancy(type=T.below_materiality, material=False)], Decision.approve),
    ([Discrepancy(type=T.over_limit)], Decision.approve),
    ([QTY_SHORT], Decision.hold),
    ([Discrepancy(type=T.currency_mismatch)], Decision.hold),
    ([Discrepancy(type=T.duplicate_invoice)], Decision.reject),
    ([Discrepancy(type=T.duplicate_invoice), QTY_SHORT], Decision.reject),
    ([Discrepancy(type=T.bank_change)], Decision.escalate),
    ([Discrepancy(type=T.lookalike_domain), Discrepancy(type=T.duplicate_invoice)], Decision.escalate),
    ([Discrepancy(type=T.embedded_instructions)], Decision.escalate),
    ([Discrepancy(type=T.missing_receipt)], Decision.escalate),
])
def test_policy_recommendation_table(ctx, discs, expected):
    assert rules.policy_recommendation(mk(ctx, "case_01", discs))[0] == expected


def test_policy_unknown_vendor_and_quarantine_escalate(ctx):
    c = mk(ctx, "case_01")
    c.vendor_id = "V-UNKNOWN"
    assert rules.policy_recommendation(c)[0] == Decision.escalate
    c = mk(ctx, "case_01")
    c.status = CaseStatus.quarantined
    assert rules.policy_recommendation(c)[0] == Decision.escalate


def test_cannot_downgrade():
    assert rules.cap(Decision.hold, Decision.approve) == Decision.hold
    assert rules.cap(Decision.escalate, Decision.hold) == Decision.escalate
    assert rules.cap(Decision.reject, Decision.approve) == Decision.reject
    assert rules.cap(Decision.hold, Decision.escalate) == Decision.escalate    # escalating further is fine
    assert rules.cap(Decision.hold, Decision.reject) == Decision.escalate      # agent can't invent a reject
    assert rules.cap(Decision.approve, None) == Decision.approve


def test_agent_downgrade_is_capped_in_proposal(ctx):
    case = mk(ctx, "case_02", [QTY_SHORT])
    f = AgentFinding(recommendation=Decision.approve, explanation="looks fine", source_of_truth="invoice",
                     citations=[Citation(doc_id="made-up-doc", locator="x")], next_action="pay", confidence=0.9)
    p, d = to_proposal(case, f, Decision.hold, "droid", load_skill("ap-3way-match"), None, {"erp-GRN-PO-5501"})
    assert p.recommendation == Decision.hold and d["capped"] and "cannot downgrade" in d["cap_note"]
    assert all(c.doc_id != "made-up-doc" for c in p.citations) and d["dropped_citations"]


# --- investigator + sandbox -------------------------------------------------------

def test_investigator_deterministic_fallback(ctx):
    case = mk(ctx, "case_03", [PRICE_OVER])
    case.skill = "ap-3way-match"
    p, meta = investigate(case, ctx)
    assert p.recommendation == Decision.hold and p.engine == "deterministic fallback"
    assert p.explanation.startswith("[deterministic fallback]")
    assert "erp-KESTREL-MSA-AMD3" in p.source_of_truth  # amendment effective after invoice date: PO/MSA wins
    assert len(p.explanation.splitlines()) <= 3 and "erp-PO-7002" in p.explanation  # names the winning doc
    assert p.next_action and p.skill == "ap-3way-match" and p.skill_version == "v2"
    assert p.policy_recommendation == Decision.hold
    assert meta["detail"]["engine"] == "deterministic fallback" and len(meta["detail"]["fallback_errors"]) == 2
    assert meta["detail"]["sandbox"]["wiped"]


def test_clean_case_skips_investigation_but_gets_proposal(ctx):
    case = mk(ctx, "case_01")
    with ctx.trace.step(case.id, "investigator"):
        case = Investigator().run(case, ctx)
    step = ctx.store.list_steps(case.id, ctx.run_id)[-1]
    assert case.proposal.recommendation == Decision.approve and step.status == StepStatus.skipped


def test_sandbox_ro_not_writable_and_no_raw_text(ctx):
    case = mk(ctx, "case_04", [Discrepancy(type=T.bank_change)])
    sb = build(case, ctx, load_skill("vendor-bank-change"), screen(case, ctx).vendor, Decision.escalate, ["bank_change"])
    try:
        for rel in sb.manifest:
            with pytest.raises(PermissionError):
                (sb.ro / rel).write_text("tampered")
        with pytest.raises(PermissionError):
            (sb.ro / "new.txt").write_text("x")
        mounted = "".join(sb.ro_text(r) for r in sb.manifest)
        for d in case.documents:
            if d.text and len(d.text.strip()) > 20:
                assert d.text.strip()[:40] not in mounted
        assert "Please remit all payments" not in mounted and '"text"' not in sb.ro_text("case.json")
        assert "penang-pack-test" in sb.ro_text("memory.md")              # this vendor's memory only
        assert "aerolane" not in sb.ro_text("memory.md").lower()
        assert sb.may_write(str(sb.proposal_path)) and sb.may_write(str(sb.scratch / "notes.md"))
        assert not sb.may_write(str(sb.ro / "case.json")) and not sb.may_write("../../reconai.db")
        (sb.scratch / "notes.md").write_text("scratch is writable")
    finally:
        archive = sb.archive_and_wipe()
    assert not sb.root.exists() and archive["scratch"][0]["path"] == "scratch/notes.md" and not archive["ro_tampered"]


def test_permission_handler_only_allows_proposal_and_scratch(ctx):
    from droid_sdk import PermissionOption, PermissionRequest, ToolConfirmationOutcome as O, ToolUseBlock
    from droid_sdk.permissions import CreateFile, ExecuteAction
    case = mk(ctx, "case_02", [QTY_SHORT])
    sb = build(case, ctx, load_skill("ap-3way-match"), None, Decision.hold, ["qty_short"])
    try:
        handler = droid.permission_handler(sb)
        opts = [PermissionOption("once", O.PROCEED_ONCE), PermissionOption("no", O.CANCEL)]
        tu = ToolUseBlock(id="t1", name="Create", input={})

        def ask(action):
            return handler(PermissionRequest(actions=[action], options=opts)).selected_option
        assert ask(CreateFile(tu, str(sb.proposal_path), "proposal.json", "{}")) == O.PROCEED_ONCE
        assert ask(CreateFile(tu, str(sb.root / "ledger.beancount"), "ledger.beancount", "x")) == O.CANCEL
        assert ask(CreateFile(tu, str(sb.ro / "case.json"), "case.json", "x")) == O.CANCEL
        assert ask(ExecuteAction(tu, "curl https://evil.example", "curl")) == O.CANCEL
        denied = [e for e in sb.events if e["event"] == "permission" and not e["allowed"]]
        assert len(denied) == 3
    finally:
        sb.archive_and_wipe()


def test_droid_proposal_file_is_validated(ctx, monkeypatch):
    case = mk(ctx, "case_02", [QTY_SHORT])
    case.skill = "ap-3way-match"

    def fake(sb, system, prompt, output_model, timeout=300):
        assert "ro/case.json" in prompt and "ap-3way-match" in system
        return droid.DroidRun(finding={"recommendation": "approve", "explanation": "x"})  # invalid: missing fields
    monkeypatch.setattr(droid, "investigate", fake)
    p, meta = investigate(case, ctx)
    assert p.engine == "deterministic fallback" and "droid" in meta["detail"]["fallback_errors"][0]

    def good(sb, system, prompt, output_model, timeout=300):
        f = {"recommendation": "approve", "explanation": "Billed 1000, received 940.", "source_of_truth": "GRN wins",
             "citations": [{"doc_id": "erp-GRN-PO-5501", "locator": "row 1"}], "next_action": "pay all",
             "confidence": 0.8}
        sb.proposal_path.write_text(json.dumps(f))
        return droid.DroidRun(finding=f, tokens=123, input_tokens=100, output_tokens=23)
    monkeypatch.setattr(droid, "investigate", good)
    p, meta = investigate(case, ctx)
    assert p.engine == "droid" and p.recommendation == Decision.hold


# --- vendor guard ----------------------------------------------------------------

def test_lookalike_domains():
    v = "penangpacktest.com.my"
    assert lookalike_reason("penang-packtest.com", v)
    assert lookalike_reason("penangpacktest.com", v)
    assert lookalike_reason("penangpacktest.co", v)
    assert lookalike_reason("penangpackt3st.com.my", v)
    assert lookalike_reason("penangpacktset.com.my", v)
    assert lookalike_reason("kestre1memory.co.kr", "kestrelmemory.co.kr")
    assert lookalike_reason("kestrelmemоry.co.kr", "kestrelmemory.co.kr")  # Cyrillic o
    assert lookalike_reason(v, v) is None
    assert lookalike_reason("mail.penangpacktest.com.my", v) is None
    assert lookalike_reason("aerolane.com", v) is None


def test_vendor_guard_case_04(ctx):
    case = run_b(mk(ctx, "case_04"), ctx)
    assert {d.type for d in case.discrepancies} == {T.bank_change, T.lookalike_domain}
    assert case.skill == "vendor-bank-change" and case.decision == Decision.escalate
    assert case.status == CaseStatus.escalated and not case.approvals
    assert any("callback" in n for n in case.notes)
    assert ctx.store.get_vendor("V-PENANG").bank_last4 == "4418"  # never edited
    bank = next(d for d in case.discrepancies if d.type == T.bank_change)
    assert "9902" in bank.actual and any("email body" in c.locator for c in bank.citations)
    step = [s for s in ctx.store.list_steps(case.id, ctx.run_id) if s.stage == "vendor_guard"][0]
    assert step.detail["callback_required"] and step.detail["vendor_master_changed"] is False


def test_vendor_guard_employee_bank_and_history(ctx):
    case = mk(ctx, "case_01", bank_last4="6610")  # matches employee E-104
    ctx.store.save_case(mk(ctx, "case_03", [PRICE_OVER]).model_copy(update={"id": "prior_1"}))
    with ctx.trace.step(case.id, "vendor_guard"):
        case = VendorGuard().run(case, ctx)
    bank = next(d for d in case.discrepancies if d.type == T.bank_change)
    assert any(c.doc_id == "employee:E-104" for c in bank.citations)
    step = ctx.store.list_steps(case.id, ctx.run_id)[-1]
    assert step.detail["history"]["prior_cases"] == ["prior_1"]


def test_clean_case_has_no_vendor_signal(ctx):
    assert screen(mk(ctx, "case_01"), ctx).discrepancies == []
    assert screen(mk(ctx, "case_02"), ctx).discrepancies == []


# --- approver ----------------------------------------------------------------------

def test_clean_under_limit_approved_by_ap_lead(ctx):
    case = run_b(mk(ctx, "case_01"), ctx)
    assert case.decision == Decision.approve and case.status == CaseStatus.approved
    a = case.approvals[-1]
    assert a.role == Role.approver and a.limit == D("100000.00") and a.approver != case.po.requester
    assert "simulated" in a.comment


def test_over_ap_lead_limit_goes_to_controller_and_is_approved(ctx):
    lines = [("HBM3E-12H-24G", "50", "2450.00")]  # USD 122,500 > AP lead limit
    case = mk(ctx, "case_01", lines=[LineItem(line_no=1, sku=s, description=s, qty=D(q), unit_price=D(p),
                                              amount=D(q) * D(p)) for s, q, p in lines], total=D("122500.00"))
    case = run_b(case, ctx)
    assert case.decision == Decision.approve and case.approvals[-1].role == Role.controller
    assert case.approvals[-1].limit == D("1000000.00")


def test_over_controller_limit_escalates(ctx):
    case = run_b(mk(ctx, "case_01", total=D("2000000.00")), ctx)
    assert case.decision == Decision.escalate and not case.approvals


def test_sod_requester_never_approves(ctx):
    case = mk(ctx, "case_01")
    case.po = case.po.model_copy(update={"requester": "d.ortiz@helix.example"})  # AP lead requested it
    case = run_b(case, ctx)
    assert case.approvals[-1].approver not in ("d.ortiz@helix.example", "agent:investigator")


def test_hold_reviewed_by_controller_no_payment_approval(ctx):
    case = run_b(mk(ctx, "case_02", [QTY_SHORT]), ctx)  # TWD 18.6M ~ USD 576,600
    assert case.decision == Decision.hold and case.status == CaseStatus.awaiting_approval
    assert not [a for a in case.approvals if a.decision == ApprovalDecision.approved]
    review = [s for s in ctx.store.list_steps(case.id, ctx.run_id) if s.stage == "approver.review"][0]
    assert review.role == Role.controller and review.parent_id is not None


def test_duplicate_rejected(ctx):
    case = run_b(mk(ctx, "case_05", [Discrepancy(type=T.duplicate_invoice)]), ctx)
    assert case.decision == Decision.reject and case.status == CaseStatus.rejected and case.skill is None


def test_replan_loop_with_rejecting_controller(ctx):
    calls = []

    def reviewer(case, proposal, role, who, ctx, history):
        calls.append(proposal.explanation)
        if len(calls) == 1:
            return Review(decision=ApprovalDecision.rejected, reason="ask for a corrected invoice, not just a hold"), {}
        return deterministic_review(case, proposal, role, who, ctx, history)

    case = run_b(mk(ctx, "case_02", [QTY_SHORT]), ctx, Approver(reviewer=reviewer))
    assert case.replans == 1 and len(calls) == 2 and case.decision == Decision.hold
    steps = ctx.store.list_steps(case.id, ctx.run_id)
    replan = [s for s in steps if s.stage == "investigator.replan"]
    approver = [s for s in steps if s.stage == "approver"][0]
    assert len(replan) == 1 and replan[0].parent_id == approver.id
    assert replan[0].detail["feedback"].startswith("ask for a corrected invoice")
    assert any(a.decision == ApprovalDecision.rejected for a in case.approvals)


def test_replan_limit_then_escalate(ctx):
    def always_no(case, proposal, role, who, ctx, history):
        return Review(decision=ApprovalDecision.rejected, reason="no"), {}
    case = run_b(mk(ctx, "case_02", [QTY_SHORT]), ctx, Approver(reviewer=always_no))
    assert case.replans == 2 and case.decision == Decision.escalate and case.status == CaseStatus.escalated


def test_reviewer_approval_cannot_turn_hold_into_payment(ctx):
    def yes(case, proposal, role, who, ctx, history):
        return Review(decision=ApprovalDecision.approved, reason="fine"), {}
    case = mk(ctx, "case_02", [QTY_SHORT])
    case = run_b(case, ctx, Approver(reviewer=yes))
    assert case.decision == Decision.hold and not case.approvals


def test_skill_files_and_versions():
    for name in ("ap-3way-match", "vendor-bank-change"):
        s = load_skill(name)
        assert s.version == "v2" and set(s.tools) == {"Read", "Grep", "Glob", "LS"}  # read-only
    with pytest.raises(KeyError):
        load_skill("../../config")


def test_claude_fallback_and_llm_reviewer(ctx, monkeypatch):
    from backend.core import llm
    seen = {}

    def fake_structured(model, system, content, **kw):
        seen.setdefault(kw["role"], []).append((system, content))
        if model is AgentFinding:
            out = AgentFinding(recommendation=Decision.hold, explanation="Billed 1000, received 940.",
                               source_of_truth="GRN wins for quantity.", next_action="request credit note",
                               citations=[Citation(doc_id="erp-GRN-PO-5501", locator="row 1")], confidence=0.8)
        else:
            out = Review(decision=ApprovalDecision.approved, reason="agree with hold")
        return llm.LLMResult(out, 10, 5)
    monkeypatch.setenv("RECONAI_LLM", "live")
    monkeypatch.setattr(llm, "structured", fake_structured)
    case = run_b(mk(ctx, "case_02", [QTY_SHORT]), ctx)
    assert case.proposal.engine == "claude" and case.decision == Decision.hold
    sys_prompt, content = seen["investigator"][0]
    assert "you do not write any file" in sys_prompt and "preferences.md" in content
    assert all(d.text is None or d.text[:30] not in content for d in case.documents if d.text and len(d.text) > 30)
    rsys, _ = seen["reviewer:controller"][0]
    assert "m.chen@helix.example" in rsys and "SIMULATED" in rsys


def test_explanation_three_lines_and_cost_recorded(ctx, monkeypatch):
    from backend.agents.investigator import clamp_lines
    assert len(clamp_lines("a\nb\nc\nd\ne").splitlines()) == 3
    case = mk(ctx, "case_02", [QTY_SHORT])
    case.skill = "ap-3way-match"

    def good(sb, system, prompt, output_model, timeout=300):
        assert "Explanations in 3 lines max" in sb.ro_text("preferences.md")
        f = {"recommendation": "hold", "explanation": "l1\nl2\nl3\nl4\nl5", "source_of_truth": "GRN wins",
             "citations": [], "next_action": "credit note", "confidence": 0.8}
        return droid.DroidRun(finding=f, tokens=1500, input_tokens=1000, output_tokens=500)
    monkeypatch.setattr(droid, "investigate", good)
    with ctx.trace.step(case.id, "investigator") as step:
        case = Investigator().run(case, ctx)
    assert len(case.proposal.explanation.splitlines()) == 3 and case.proposal.source_of_truth == "GRN wins"
    assert step.tokens == 1500 and step.cost_usd and step.cost_usd > 0


def test_clean_proposal_cites_three_way_match_and_contract(ctx):
    from backend.agents.investigator import preflight
    case = mk(ctx, "case_03")  # Kestrel HBM8 at 1240 with no discrepancies set: MSA in force on 2026-10-16
    case.invoice.lines[0].unit_price = D("1180.00")
    with ctx.trace.step(case.id, "investigator"):
        case = Investigator().run(case, ctx)
    p = case.proposal
    locs = {(c.doc_id, c.locator) for c in p.citations}
    assert (case.invoice.doc_id, "line 1") in locs and ("erp-PO-7002", "line 1") in locs
    assert ("erp-GRN-PO-7002", "sku HBM3E-8H-24G") in locs and ("erp-KESTREL-MSA", "sku HBM3E-8H-24G") in locs
    assert "erp-KESTREL-MSA-AMD3" in p.explanation and len(p.explanation.splitlines()) == 3
    assert p.source_of_truth.startswith("3-way match. Quantity: invoice line 1") and p.next_action
    assert preflight(case, p, ctx) == []


def test_clean_rejection_gets_one_code_replan(ctx):
    calls = []

    def reviewer(case, proposal, role, who, ctx, history):
        calls.append(len(proposal.citations))
        if len(calls) == 1:
            return Review(decision=ApprovalDecision.rejected, reason="cite the winning document"), {}
        return deterministic_review(case, proposal, role, who, ctx, history)
    case = run_b(mk(ctx, "case_01"), ctx, Approver(reviewer=reviewer))
    assert case.replans == 1 and case.decision == Decision.approve and calls[0] >= 3
    replan = [s for s in ctx.store.list_steps(case.id, ctx.run_id) if s.stage == "investigator.replan"][0]
    assert replan.detail["engine"] == "code"

    def always_no(case, proposal, role, who, ctx, history):
        return Review(decision=ApprovalDecision.rejected, reason="no"), {}
    case = run_b(mk(ctx, "case_01"), ctx, Approver(reviewer=always_no))
    assert case.replans == 1 and case.decision == Decision.escalate


def test_clean_proposal_shows_below_materiality_price_gap(ctx):
    case = mk(ctx, "case_01", [Discrepancy(type=T.below_materiality, material=False, line_no=1, sku="HBM3E-12H-24G",
                                           expected="1450.00", actual="1450.20", delta=D("10.00"))])
    case.invoice.lines[0].unit_price = D("1450.20")
    p = (lambda c: (Investigator().run(c, ctx), c.proposal)[1])
    with ctx.trace.step(case.id, "investigator"):
        prop = p(case)
    assert "invoice 1450.20 vs PO-7001 line 1 1450.00" in prop.explanation and "10.00" in prop.explanation
    assert "clean 3-way match" not in prop.explanation and len(prop.explanation.splitlines()) == 3
