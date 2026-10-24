"""Shared data models. Single source of truth for backend and UI.

Changes here must be announced to the team first (see CLAUDE.md).
After editing, run `make types` to regenerate JSON Schema + TypeScript.

Money and quantities are Decimal, serialized as strings in JSON ("1250.00").
Never floats.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema

# --- Primitives -------------------------------------------------------------

Money = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$", "description": "Decimal amount as string"}),
]
Qty = Money  # same wire format


class Model(BaseModel):
    # defaults are always serialized, so the UI types mark them required
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# --- Enums ------------------------------------------------------------------

class DocKind(str, Enum):
    invoice = "invoice"
    po = "po"
    receipt = "receipt"
    contract = "contract"
    amendment = "amendment"
    email = "email"
    statement = "statement"
    credit_note = "credit_note"


class Channel(str, Enum):
    api = "api"
    email = "email"
    sftp = "sftp"
    s3 = "s3"
    erp = "erp"
    upload = "upload"


class CaseStatus(str, Enum):
    new = "new"
    in_progress = "in_progress"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    escalated = "escalated"
    posted = "posted"
    quarantined = "quarantined"
    resolved = "resolved"
    paused = "paused"                    # kill switch or human handoff; agent stages don't run
    awaiting_vendor = "awaiting_vendor"  # open follow-up (credit note, corrected invoice, callback)
    reopened = "reopened"                # follow-up overdue or new evidence; only the delta is re-triaged


class Decision(str, Enum):
    approve = "approve"   # clean, post it
    hold = "hold"         # exception, don't pay yet
    reject = "reject"     # e.g. duplicate, don't pay
    escalate = "escalate" # needs a human / no skill / low confidence


class DiscrepancyType(str, Enum):
    qty_short = "qty_short"
    price_over = "price_over"
    unapproved_freight = "unapproved_freight"
    fx_gap = "fx_gap"
    duplicate_invoice = "duplicate_invoice"
    bank_change = "bank_change"
    lookalike_domain = "lookalike_domain"
    embedded_instructions = "embedded_instructions"
    below_materiality = "below_materiality"
    currency_mismatch = "currency_mismatch"
    unknown_po = "unknown_po"
    missing_receipt = "missing_receipt"
    total_mismatch = "total_mismatch"      # printed total != sum of lines (code recomputes)
    over_limit = "over_limit"
    locked_period = "locked_period"


class CaseLinkType(str, Enum):
    duplicate_of = "duplicate_of"          # doc dedup: same invoice seen before (or paid)
    attached_to = "attached_to"            # case dedup: exact fingerprint, evidence attached
    corrected_by = "corrected_by"          # level 2: corrected invoice for same discrepancy
    related_pattern = "related_pattern"    # level 3: same vendor + type, other PO/period
    sub_case_of = "sub_case_of"            # one case per discrepancy under a parent invoice


class StepStatus(str, Enum):
    running = "running"
    ok = "ok"
    retried = "retried"
    failed = "failed"
    blocked = "blocked"
    escalated = "escalated"
    skipped = "skipped"


class Role(str, Enum):
    system = "system"         # deterministic code
    reader = "reader"         # Claude, no tools
    investigator = "investigator"  # Droid in sandbox
    approver = "approver"     # AP lead
    controller = "controller"
    cfo = "cfo"               # above the controller limit (human)
    requester = "requester"


class ApprovalDecision(str, Enum):
    approved = "approved"
    rejected = "rejected"
    ask = "ask"


class SkillStatus(str, Enum):
    shadow = "shadow"
    active = "active"
    retired = "retired"


class MemoryFolder(str, Enum):
    company = "company"
    controller_preferences = "controller-preferences"
    counterparties = "counterparties"
    people = "people"
    open_matters = "open-matters"
    patterns = "patterns"


# --- Master data ------------------------------------------------------------

class PaymentTerms(Model):
    """Commercial terms from the contract / vendor master (never from invoice text). e.g. 2/10 net 30."""
    net_days: int = 30
    discount_pct: Optional[Money] = Field(None, description="early-payment discount, e.g. 0.02")
    discount_days: Optional[int] = Field(None, description="pay within N days of the invoice date to earn it")
    prepay_discount_pct: Optional[Money] = Field(None, description="discount for paying in advance, e.g. 0.04")
    prepay_cap_usd: Optional[Money] = Field(None, description="max open prepaid balance for this vendor")
    source: str = Field("vendor master", description="where these terms come from")


class Vendor(Model):
    id: str
    name: str
    aliases: list[str] = []
    country: str
    currency: str
    email_domain: str
    bank_last4: str = Field(description="Last 4 digits only. Never store full numbers.")
    channels: list[Channel] = []
    tax_id: Optional[str] = None
    critical: bool = False
    on_probation: bool = False
    probation_until: Optional[date] = None
    contact_email: Optional[str] = Field(None, description="Verified contact on file; outbound goes here, never reply-to")
    expected_schedule: Optional[str] = Field(None, description="daily | weekly: expected-file schedule (missing-file alerts)")
    terms: Optional[PaymentTerms] = None


# --- Documents --------------------------------------------------------------

class Document(Model):
    id: str
    kind: DocKind
    vendor_id: Optional[str] = None
    channel: Channel
    filename: str
    sha256: str
    mime: str
    received_at: datetime
    text: Optional[str] = Field(None, description="Raw text. UNTRUSTED. Never sent to a prompt with tools.")
    sender: Optional[str] = None
    subject: Optional[str] = Field(None, description="Email Subject header (UNTRUSTED); carries [REC <case_id>] on replies")


class LineItem(Model):
    line_no: int
    sku: str
    description: str
    qty: Qty
    unit_price: Money
    amount: Money


class Invoice(Model):
    doc_id: str
    vendor_id: str
    invoice_no: str
    invoice_date: date
    due_date: Optional[date] = None
    currency: str
    po_number: Optional[str] = None
    lines: list[LineItem]
    total: Money
    bank_last4: Optional[str] = Field(None, description="Bank account on the invoice, last 4 only")
    flags: list[str] = Field(default_factory=list, description="Reader flags, e.g. embedded_instructions")
    credit_for: Optional[str] = Field(None, description="Credit note: invoice number it credits (amounts positive)")
    corrects: Optional[str] = Field(None, description="Corrected invoice: invoice number it replaces")


class POLine(Model):
    line_no: int
    sku: str
    description: str
    qty: Qty
    unit_price: Money


class PO(Model):
    doc_id: str
    po_number: str
    vendor_id: str
    po_date: date
    currency: str
    lines: list[POLine]
    requester: str


class ReceiptLine(Model):
    sku: str
    qty_received: Qty


class Receipt(Model):
    doc_id: str
    po_number: str
    received_date: date
    lines: list[ReceiptLine]
    received_by: str


# --- Case + decision --------------------------------------------------------

class Citation(Model):
    doc_id: str
    locator: str = Field(description="e.g. 'line 2', 'row 14', 'para 3'")
    quote: Optional[str] = None


class Discrepancy(Model):
    type: DiscrepancyType
    line_no: Optional[int] = None
    sku: Optional[str] = None
    material: bool = True
    expected: Optional[str] = None
    actual: Optional[str] = None
    delta: Optional[Money] = None
    citations: list[Citation] = []
    original_type: Optional[DiscrepancyType] = Field(
        None, description="For below_materiality: the type it would have been (e.g. price_over)")
    fingerprint: Optional[str] = Field(None, description="Per-discrepancy case fingerprint (vendor+PO+inv+type+SKU)")


class Posting(Model):
    account: str
    amount: Money
    currency: str


class JournalEntry(Model):
    id: str
    case_id: str
    date: date
    narration: str
    postings: list[Posting]
    requested_by: str
    approved_by: Optional[str] = None
    idempotency_key: str


class Proposal(Model):
    case_id: str
    recommendation: Decision
    explanation: str
    citations: list[Citation] = []
    proposed_entry: Optional[JournalEntry] = None
    confidence: float = Field(ge=0, le=1, description="Model confidence, not money")
    skill: Optional[str] = None
    skill_version: Optional[str] = None
    memory_version: Optional[str] = None
    policy_recommendation: Optional[Decision] = Field(
        None, description="Floor computed by code from the decision table; recommendation may never be below it")
    engine: Optional[str] = Field(None, description="droid | claude | deterministic fallback | code (clean / no skill)")
    source_of_truth: Optional[str] = Field(None, description="Which document wins and why (kept out of explanation)")
    next_action: Optional[str] = Field(None, description="e.g. request a credit note via the contact on file")


class Approval(Model):
    id: str
    case_id: str
    approver: str
    role: Role
    decision: ApprovalDecision
    scope: Optional[str] = Field(None, description="full | undisputed (pay only the undisputed part of a hold)")
    comment: str = ""
    limit: Optional[Money] = None
    at: datetime


class FollowUpKind(str, Enum):
    credit_note = "credit_note"
    corrected_invoice = "corrected_invoice"
    callback = "callback"            # out-of-band vendor verification via contact on file
    supplier_reply = "supplier_reply"
    resend = "resend"


class FollowUpStatus(str, Enum):
    open = "open"
    done = "done"
    overdue = "overdue"


class FollowUp(Model):
    id: str
    case_id: str
    kind: FollowUpKind
    due: date
    status: FollowUpStatus = FollowUpStatus.open
    note: str = ""
    created_at: datetime
    closed_by: Optional[str] = Field(None, description="Doc id / case id / person that closed it")


class SupplierEmail(Model):
    """Outbound email to the vendor's contact on file (never reply-to-sender). SIMULATED: not actually sent."""
    id: str
    case_id: str
    to: str
    subject: str = Field(description="Carries the case reference, e.g. '[REC case_02] ...', so replies link back")
    body: str
    idempotency_key: str
    sent_at: datetime


class PendingApproval(Model):
    role: Role
    approver: str
    requested_at: datetime
    due_at: datetime
    reminded_at: Optional[datetime] = None
    escalated_to: Optional[str] = Field(None, description="Backup approver after SLA breach")


class Handoff(Model):
    case_id: str
    from_actor: str
    to_actor: str
    at: datetime
    note: str = ""


class Alert(Model):
    """Stored as a record (kind='alert'). E.g. expected vendor file missing, SLA breach, payment due at risk."""
    id: str
    kind: str
    vendor_id: Optional[str] = None
    case_id: Optional[str] = None
    at: datetime
    message: str


class Controls(Model):
    """Kill switch. Stored as a record (kind='controls', key='global')."""
    paused_global: bool = False
    paused_vendors: list[str] = []
    updated_by: str = "system"
    updated_at: Optional[datetime] = None


class CaseLink(Model):
    type: CaseLinkType
    case_id: Optional[str] = None
    invoice_no: Optional[str] = None
    reason: str


class Case(Model):
    id: str
    parent_id: Optional[str] = None
    vendor_id: str
    status: CaseStatus = CaseStatus.new
    documents: list[Document] = []
    invoice: Optional[Invoice] = None
    po: Optional[PO] = None
    receipts: list[Receipt] = []
    fingerprint: Optional[str] = None
    evidence_hash: Optional[str] = None
    links: list[CaseLink] = []
    quarantine_reason: Optional[str] = None
    discrepancies: list[Discrepancy] = []
    skill: Optional[str] = None
    proposal: Optional[Proposal] = None
    approvals: list[Approval] = []
    journal_entry: Optional[JournalEntry] = None
    decision: Optional[Decision] = None
    replans: int = Field(0, description="Times the agent re-planned after a rejection")
    as_of: Optional[date] = Field(None, description="Business 'today' for this case (posting date, period locks)")
    sub_case_ids: list[str] = Field(default_factory=list, description="One sub-case per discrepancy (parent = invoice)")
    paid_amount: Optional[Money] = Field(None, description="Undisputed part posted for payment")
    disputed_amount: Optional[Money] = None
    follow_ups: list[FollowUp] = []
    outbound: list[SupplierEmail] = []
    pending_approval: Optional[PendingApproval] = None
    assigned_to: Optional[str] = Field(None, description="Human who took over; agent stages skip while set")
    handoffs: list[Handoff] = []
    priority: Optional[float] = Field(None, description="Queue priority score; higher = sooner")
    reopens: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    notes: list[str] = []


# --- System of record (ERP world) -------------------------------------------

class ContractTerm(Model):
    """Contract / amendment price. Amendment wins only from effective_from."""
    doc_id: str
    vendor_id: str
    sku: str
    unit_price: Money
    currency: str
    effective_from: date


class PaidInvoice(Model):
    vendor_id: str
    invoice_no: str
    po_number: Optional[str] = None
    total: Money
    currency: str
    paid_on: date
    line_hash: str = Field(description="sha256 of sorted (sku, qty, unit_price) lines; see doc dedup")


class Employee(Model):
    id: str
    name: str
    email: str
    bank_last4: str


# --- Fixtures (data/cases/<id>/case.json) -------------------------------------

class InboundItem(Model):
    """One file as it arrived. Paths are relative to the case folder."""
    channel: Channel
    path: str
    sender: Optional[str] = Field(None, description="Email From / SFTP account / API key owner")
    api_key: Optional[str] = Field(None, description="API channel only; simulated per-vendor key")
    received_at: datetime


class FixtureKind(str, Enum):
    inbound = "inbound"   # files arrive -> intake -> pipeline
    tick = "tick"         # no files: advance the clock to as_of and run sweeps (SLA, overdue follow-ups)


class CaseFixture(Model):
    id: str
    title: str
    kind: FixtureKind = FixtureKind.inbound
    inbound: list[InboundItem] = []
    as_of: date = Field(description="'Today' for this case (period locks, due dates)")


class OnboardingRequest(Model):
    """data/onboarding/onb_*.json. Always started by an internal requester (vendors never self-sign-up)."""
    id: str
    title: str
    received_at: datetime
    requested_by: str
    legal_name: str
    trade_names: list[str] = []
    country: str
    tax_id: Optional[str] = None
    tax_form: Optional[str] = None
    email_domain: str
    bank_last4: str
    currency: str
    channels: list[Channel] = []
    payment_terms: Optional[str] = None
    expected_annual_spend_usd: Optional[Money] = None


class OnboardingCheck(Model):
    name: str = Field(description="e.g. duplicate_tax_id, sanctions, employee_bank, lookalike_domain, tax_form")
    passed: bool
    detail: str = ""
    simulated: bool = False


class OnboardingResult(Model):
    request_id: str
    checks: list[OnboardingCheck] = []
    flags: list[str] = Field(default_factory=list, description="Names of failed checks")
    risk_tier: Optional[str] = Field(None, description="low | medium | high")
    decision: Optional[Decision] = None
    approvals: list[Approval] = []
    vendor_id: Optional[str] = Field(None, description="Set only once activated")
    probation_until: Optional[date] = None
    notes: list[str] = []


class SkillProposalStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"


class SkillProposal(Model):
    id: str
    skill: str
    from_version: str
    to_version: str
    rationale: str
    diff: str = Field(description="Unified diff against SKILL.md / policy.yaml")
    evidence_case_ids: list[str] = []
    replay_before: dict[str, Any] = Field(default_factory=dict, description="Eval summary on current skill")
    replay_after: dict[str, Any] = Field(default_factory=dict, description="Eval summary with the proposal applied")
    loosens: bool = Field(False, description="Loosening needs controller + second sign-off (ratchet)")
    status: SkillProposalStatus = SkillProposalStatus.proposed
    approved_by: list[str] = []
    engine: Optional[str] = None
    created_at: datetime


# --- Trace ------------------------------------------------------------------

class Step(Model):
    id: str
    case_id: str
    run_id: str
    parent_id: Optional[str] = None
    seq: int
    stage: str
    role: Role = Role.system
    status: StepStatus = StepStatus.running
    skill: Optional[str] = None
    skill_version: Optional[str] = None
    memory_version: Optional[str] = None
    tool: Optional[str] = None
    inputs: list[str] = Field(default_factory=list, description="Doc/object references, not payloads")
    outputs: list[str] = []
    detail: dict[str, Any] = {}
    error: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    tokens: int = 0
    cost_usd: Optional[Money] = None


class Event(Model):
    """Pushed over WS /events."""
    type: str = Field(description="step.started | step.finished | case.updated")
    case_id: str
    step: Optional[Step] = None
    status: Optional[CaseStatus] = None
    at: datetime


# --- Memory / skills --------------------------------------------------------

class MemoryEntry(Model):
    id: str
    folder: MemoryFolder
    subject: str = Field(description="File name without .md, e.g. aerolane-freight")
    text: str
    provenance: str = Field(description="e.g. 'system-of-record', 'controller: M. Chen, 2026-09-14', 'case #63'")
    valid_from: date
    version: int = 1


class SkillVersion(Model):
    skill: str
    version: str
    status: SkillStatus
    created_at: datetime
    approved_by: Optional[str] = None
    git_sha: Optional[str] = None


# --- Evals ------------------------------------------------------------------

class ExpectedOutcome(Model):
    case_id: str
    decision: Optional[Decision] = Field(description="None for tick fixtures (use asserts)")
    discrepancies: list[DiscrepancyType] = []
    skill: Optional[str] = None
    quarantined: bool = False
    links: list[CaseLinkType] = []
    invoice_no: Optional[str] = Field(None, description="Extraction check")
    total: Optional[Money] = Field(None, description="Extraction check")
    currency: Optional[str] = None
    variance: Optional[Money] = Field(None, description="Expected disputed amount, to the cent")
    paid_amount: Optional[Money] = Field(None, description="Expected undisputed amount posted (pay what's clean)")
    asserts: dict[str, str] = Field(default_factory=dict,
                                    description="'<case_id>.<dotted.path>' -> expected str value, checked after this fixture")
    tags: list[str] = Field(default_factory=list, description="e.g. attack, onboarding, format:xlsx, channel:sftp")
    note: str = ""


class EvalResult(Model):
    case_id: str
    run_id: str
    expected: ExpectedOutcome
    actual_decision: Optional[Decision] = None
    actual_discrepancies: list[DiscrepancyType] = []
    actual_skill: Optional[str] = None
    checks: dict[str, bool] = Field(description="decision, discrepancies, skill, inv_* invariants")
    passed: bool
    misses: list[str] = Field(default_factory=list, description="Human-readable reason per failed check")


class TagScore(Model):
    """Per-tag breakdown (format:*, channel:*, attack, dedup, ...)."""
    tag: str
    total: int
    passed: int
    pass_rate: float


class Scoreboard(Model):
    run_id: str
    at: datetime
    total: int
    passed: int
    catch_rate: float
    false_alarm_rate: float
    invariant_pass_rate: float
    results: list[EvalResult]
    check_rates: dict[str, float] = Field(default_factory=dict, description="Pass rate per check name")
    by_tag: list[TagScore] = Field(default_factory=list)
    llm_scores: list["LLMJudgeScore"] = Field(default_factory=list)
    stability: Optional[float] = Field(None, description="Decision stability across repeated runs (0-1)")
    metrics: Optional["BusinessMetrics"] = None
    onboarding: list[EvalResult] = Field(default_factory=list,
                                         description="Vendor-onboarding results; reported separately from the headline")
    notes: list[str] = Field(default_factory=list, description="Run notes, e.g. a skipped section and why")


class LLMJudgeScore(Model):
    case_id: str
    rubric: str = Field(description="explanation | supplier_email | escalation | defend_decision | skill_proposal")
    score: float = Field(description="Mean 1-5 over runs")
    runs: int
    rationale: str = ""
    model: str


class BusinessMetrics(Model):
    dollars_caught_usd: Money
    hours_saved_est: Money = Field(description="ESTIMATE, labeled as such in the UI")
    on_time_payment_rate: float
    exceptions_per_vendor: dict[str, int] = {}
    avg_time_to_resolve_hours: Optional[float] = None
    notes: list[str] = []


# --- Dashboard (owner: D) ---------------------------------------------------

class QueueItem(Model):
    """One open case in the approval queue, sorted by priority (highest first)."""
    case_id: str
    vendor_id: str
    vendor_name: str
    status: CaseStatus
    decision: Optional[Decision] = None
    invoice_no: Optional[str] = None
    total: Optional[Money] = None
    currency: Optional[str] = None
    total_usd: Optional[Money] = Field(None, description="At the simulated policy FX rate")
    due_date: Optional[date] = None
    days_to_due: Optional[int] = None
    at_risk: bool = Field(False, description="Due within the at-risk window or overdue")
    critical_vendor: bool = False
    priority: int = Field(description="Higher = work first")
    reasons: list[str] = Field(default_factory=list, description="Why it ranks where it does")


class VendorExceptions(Model):
    vendor_id: str
    vendor_name: str
    cases: int
    exceptions: int


class DashboardMetrics(Model):
    """Dashboard read model (D). C's BusinessMetrics is the eval/scoreboard model."""
    cases: int
    exceptions: int
    dollars_caught_usd: Money = Field(description="Held/rejected/escalated exposure, USD at simulated FX")
    hours_saved_estimate: Money = Field(description="ESTIMATE: per-case manual minutes x cases handled")
    on_time_payment_rate: Optional[float] = Field(None, description="Posted on or before due date; None if nothing posted")
    avg_hours_to_resolve: Optional[float] = None
    by_vendor: list[VendorExceptions]
    assumptions: list[str] = Field(default_factory=list, description="Shown next to the numbers")


class StageStat(Model):
    """How one pipeline stage behaved across every case's latest run."""
    stage: str
    runs: int
    ok: int
    skipped: int
    flagged: int = Field(description="failed + blocked + escalated + retried")
    avg_ms: Optional[float] = None


class FailureItem(Model):
    """A non-ok step and what the pipeline did next."""
    case_id: str
    run_id: str
    step_id: str
    stage: str
    status: StepStatus
    error: Optional[str] = None
    next_stage: Optional[str] = None
    next_status: Optional[StepStatus] = None
    at: datetime


# --- Review (owner: D) -----------------------------------------------------

class IntakeAccepted(Model):
    """Returned by POST /intake: the run continues in the background."""
    case_id: str
    run_id: str


class Finding(Model):
    """One check the agents ran, in plain language, for the reviewer."""
    check: str = Field(description="e.g. '3-way match', 'Vendor & bank'")
    agent: str = Field(description="pipeline stage that ran it")
    status: str = Field(description="ok | flag | unchecked | blocked")
    detail: str


class ReviewPacket(Model):
    """Everything the reviewer gets once the background run is done."""
    case_id: str
    ready: bool = Field(description="False while the pipeline is still running")
    summary: str
    recommendation: Optional[Decision] = None
    needs: str = Field(description="who must sign: approver | controller | nobody")
    findings: list[Finding] = []
    trace: list[Step] = []
    files: list[Document] = []
    signals: list[Signal] = Field(default_factory=list, description="pre-payment checks run by code")
    suggested: list[str] = Field(default_factory=list, description="questions the reviewer can tap")


class ChatMessage(Model):
    role: str = Field(description="user | assistant")
    content: str


class ChatRequest(Model):
    messages: list[ChatMessage]


class ChatReply(Model):
    content: str
    source: str = Field(description="claude | offline")


# --- Accounts payable workspace (owner: D) ---------------------------------

class Signal(Model):
    """A pre-payment check run by code at review time."""
    code: str = Field(description="bank_mismatch | lookalike_domain | duplicate | qty_short | price_over | not_on_po | over_limit | embedded_instructions | probation")
    severity: str = Field(description="high | medium | low")
    title: str
    detail: str


class MatchRow(Model):
    """One SKU across purchase order, goods receipt and invoice. Variances computed in code."""
    sku: str
    description: str
    ordered: Optional[Qty] = None
    received: Qty
    billed: Qty
    po_price: Optional[Money] = None
    invoice_price: Money
    qty_variance: Qty = Field(description="billed - min(ordered, received)")
    price_variance: Optional[Money] = Field(None, description="invoice_price - po_price")
    amount_at_risk: Money = Field(description="what would be overpaid, in invoice currency")


class GLLine(Model):
    line_no: int
    sku: str
    description: str
    amount: Money
    account: str
    basis: str = Field(description="why this account was suggested")


class CheckResult(Model):
    """One pre-payment check and whether it passed, with references to the evidence."""
    name: str
    passed: bool
    severity: str = Field(description="high | medium | low (only meaningful when not passed)")
    detail: str
    refs: list[str] = Field(default_factory=list, description="e.g. 'Line 1', 'PO-5501', 'INV-2291'")


class ApprovalStep(Model):
    step: int
    label: str
    who: str
    status: str = Field(description="done | waiting | pending | rejected | on_hold")
    note: str = ""


class LastPaid(Model):
    invoice_no: str
    amount: Money
    currency: str
    paid_on: date


class Payment(Model):
    id: str
    batch_id: str
    case_id: str
    vendor_id: str
    amount: Money
    currency: str
    amount_usd: Money
    method: str = Field(description="ach | wire | intl_wire | check")
    pay_date: date
    pay_to_last4: str = Field(description="Always the vendor master's account, never the invoice's")
    status: str = Field(description="scheduled | paid")
    gross_amount: Optional[Money] = Field(None, description="invoice total before discount and credits")
    discount_amount: Money = Field(Decimal("0"), description="early-payment discount taken")
    credit_applied: Money = Field(Decimal("0"), description="advance-payment credit used")


class PaymentBatch(Model):
    id: str
    pay_date: date
    status: str = Field(description="scheduled | paid")
    created_by: str
    created_at: datetime
    released_by: Optional[str] = None
    released_at: Optional[datetime] = None
    payments: list[Payment] = []
    total_usd: Money


class PaymentBatchRequest(Model):
    case_ids: list[str]
    pay_date: date
    created_by: str
    methods: dict[str, str] = Field(default_factory=dict, description="case_id -> method; default by vendor country")


class ReleaseRequest(Model):
    released_by: str


class EarlyPayOffer(Model):
    """An early-payment discount on one bill, computed in code from the vendor's terms."""
    case_id: str
    vendor_id: str
    vendor_name: str
    invoice_no: Optional[str] = None
    terms: str = Field(description="e.g. 2/15 net 30")
    discount_pct: Money
    discount_amount: Money
    currency: str
    discount_usd: Money
    pay_by: date
    days_left: int
    annualized_return_pct: float = Field(description="what paying early 'earns', annualised")
    status: str = Field(description="available | needs_approval | blocked | missed | captured")
    note: str = ""


class PrepayApplication(Model):
    case_id: str
    amount: Money
    at: datetime


class Prepayment(Model):
    """An advance payment that buys vendor credit at a discount. SIMULATED settlement."""
    id: str
    vendor_id: str
    vendor_name: str
    currency: str
    credit_amount: Money = Field(description="credit granted against future invoices")
    cash_amount: Money = Field(description="what Helix pays now")
    discount_amount: Money
    discount_pct: Money
    cash_usd: Money
    status: str = Field(description="requested | paid | rejected")
    requested_by: str
    requested_at: datetime
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    note: str = ""
    applied: list[PrepayApplication] = []
    remaining: Money


class PrepaymentRequest(Model):
    vendor_id: str
    credit_amount: Money
    requested_by: str
    note: str = ""


class PrepaymentQuote(Model):
    vendor_id: str
    currency: str
    credit_amount: Money
    cash_amount: Money
    discount_amount: Money
    discount_pct: Money
    cash_usd: Money
    cap_remaining_usd: Optional[Money] = None
    allowed: bool
    reason: str = ""


class SignOff(Model):
    """A human decision on a prepayment or onboarding request."""
    approver: str
    role: Role
    decision: str = Field(description="approved | rejected")
    comment: str = ""


class OnboardingRequestIn(Model):
    legal_name: str
    country: str
    currency: str = "USD"
    tax_id: Optional[str] = None
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    email_domain: str
    website: str = ""
    bank_last4: str
    contact_name: str = ""
    contact_phone: str = ""
    expected_annual_spend_usd: Money = Decimal("0")
    requested_by: str
    tax_form: Optional[str] = Field(None, description="W-9 (US) | W-8BEN-E (non-US); null = not received")
    trade_names: list[str] = []


class VendorCheck(Model):
    """One onboarding check as shown in the UI (D): CRS or code, pass/warn/fail."""
    name: str
    provider: str = Field(description="CRS | code")
    status: str = Field(description="pass | warn | fail | not_covered | incomplete")
    detail: str
    simulated: bool = False


class OnboardingCase(Model):
    id: str
    request: OnboardingRequestIn
    status: str = Field(description="needs_review | approved | rejected")
    checks: list[VendorCheck] = []
    risk_tier: str = Field(description="low | medium | high")
    needs: str = Field(description="role that must approve: approver | controller")
    crs_mode: str = Field(description="live | simulated")
    created_at: datetime
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_comment: str = ""
    vendor_id: Optional[str] = None


class Bill(Model):
    """One invoice as the AP team sees it."""
    case_id: str
    vendor_id: str
    vendor_name: str
    invoice_no: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    days_to_due: Optional[int] = None
    amount: Optional[Money] = None
    currency: Optional[str] = None
    amount_usd: Optional[Money] = None
    stage: str = Field(description="processing | needs_review | on_hold | ready_to_pay | blocked | scheduled | paid | rejected")
    recommendation: Optional[Decision] = None
    approved_by: Optional[str] = None
    needs: str = Field(description="role that must sign, or nobody")
    risk: str = Field(description="high | medium | low")
    signals: list[Signal] = []
    waiting_hours: Optional[float] = Field(None, description="time since it was handed to a human")
    sla_breached: bool = False
    payment_block: Optional[str] = None
    payment: Optional[Payment] = None
    overbilled: Optional[Money] = Field(None, description="amount at risk from the 3-way match, invoice currency")
    discount: Optional[EarlyPayOffer] = None
    credit_available: Optional[Money] = Field(None, description="advance-payment credit open for this vendor")
    warning: Optional[str] = Field(None, description="one line shown under the bill in lists")
    payable: Optional[Money] = Field(None, description="AP booked by the Poster and not yet credited: what a payment "
                                                       "run may pay (the undisputed part of a partial hold)")
    payable_usd: Optional[Money] = None
    disputed: Optional[Money] = Field(None, description="held part of a hold (invoice currency)")
    case_status: Optional[CaseStatus] = Field(None, description="the pipeline's case status")
    disagreements: list[str] = Field(default_factory=list,
                                     description="where the second-line checks and the agents' decision disagree")
    sub_case_ids: list[str] = Field(default_factory=list, description="one sub-case per discrepancy, grouped here")
    po_number: Optional[str] = None


class ActivityItem(Model):
    at: datetime
    actor: str
    text: str


class BillDetail(Model):
    bill: Bill
    verdict: str = Field(description="ready | review | risk")
    verdict_text: str
    checks: list[CheckResult]
    match: list[MatchRow]
    gl: list[GLLine]
    approval_steps: list[ApprovalStep]
    activity: list[ActivityItem]
    last_paid: Optional[LastPaid] = None
    est_pay_date: Optional[date] = None
    pay_methods: list[str] = Field(default_factory=list, description="methods allowed for this vendor")
    default_method: Optional[str] = None
    statement_descriptor: str
    invoice_bank_last4: Optional[str] = Field(None, description="the account printed on the invoice (last 4)")


class AgingBucket(Model):
    label: str
    amount_usd: Money
    count: int


class ForecastWeek(Model):
    week_start: date
    approved_usd: Money
    pending_usd: Money


class SpendRow(Model):
    label: str
    amount_usd: Money
    count: int


class ApReport(Model):
    open_usd: Money
    due_7d_usd: Money
    overdue_usd: Money
    needs_review: int
    blocked: int
    touchless_rate: Optional[float] = None
    caught_usd: Money = Field(description="USD of bills held, rejected or payment-blocked by checks")
    discounts_available_usd: Money = Decimal("0")
    discounts_captured_usd: Money = Decimal("0")
    discounts_missed_usd: Money = Decimal("0")
    aging: list[AgingBucket]
    forecast: list[ForecastWeek]
    by_vendor: list[SpendRow]
    by_gl: list[SpendRow]


class Integration(Model):
    name: str
    status: str = Field(description="connected | simulated | not_connected")
    note: str


class ApSettings(Model):
    approval_limits: dict[str, Money]
    sla_hours: int
    materiality_abs: Money
    materiality_pct: Money
    qty_tolerance_pct: Money
    price_tolerance_pct: Money
    locked_periods: list[str]
    fx_rates: dict[str, Money]
    accounts: dict[str, str]
    integrations: list[Integration]


# --- API payloads -----------------------------------------------------------

class CaseDetail(Model):
    case: Case
    steps: list[Step]


class ApprovalRequest(Model):
    approver: str
    role: Role
    decision: ApprovalDecision
    comment: str = ""
    scope: Optional[str] = Field(None, description="full | undisputed; default: undisputed on a hold, else full")


Scoreboard.model_rebuild()

ALL_MODELS: list[type[BaseModel]] = [
    Vendor, Document, LineItem, Invoice, POLine, PO, ReceiptLine, Receipt,
    Citation, Discrepancy, CaseLink, Posting, JournalEntry, Proposal, Approval, Case,
    ContractTerm, PaidInvoice, Employee, InboundItem, CaseFixture,
    FollowUp, SupplierEmail, PendingApproval, Handoff, Controls, Alert, OnboardingRequest, OnboardingCheck,
    OnboardingResult, SkillProposal, LLMJudgeScore, BusinessMetrics,
    Step, Event, MemoryEntry, SkillVersion, ExpectedOutcome, EvalResult, TagScore,
    Scoreboard, QueueItem, VendorExceptions, DashboardMetrics, StageStat, FailureItem,
    IntakeAccepted, Finding, ReviewPacket, ChatMessage, ChatRequest, ChatReply,
    Signal, MatchRow, GLLine, CheckResult, ApprovalStep, LastPaid, Payment, PaymentBatch, PaymentBatchRequest, ReleaseRequest, Bill, ActivityItem,
    BillDetail, AgingBucket, ForecastWeek, SpendRow, ApReport, Integration, ApSettings,
    PaymentTerms, EarlyPayOffer, PrepayApplication, Prepayment, PrepaymentRequest, PrepaymentQuote, SignOff,
    OnboardingRequestIn, VendorCheck, OnboardingCase,
    CaseDetail, ApprovalRequest,
]
