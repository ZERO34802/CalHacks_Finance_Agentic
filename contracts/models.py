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
    requester = "requester"
    cfo = "cfo"               # above the controller limit (human)


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


# --- API payloads -----------------------------------------------------------

class CaseDetail(Model):
    case: Case
    steps: list[Step]


class ApprovalRequest(Model):
    approver: str
    role: Role
    decision: ApprovalDecision
    comment: str = ""


Scoreboard.model_rebuild()

ALL_MODELS: list[type[BaseModel]] = [
    Vendor, Document, LineItem, Invoice, POLine, PO, ReceiptLine, Receipt,
    Citation, Discrepancy, CaseLink, Posting, JournalEntry, Proposal, Approval, Case,
    ContractTerm, PaidInvoice, Employee, InboundItem, CaseFixture,
    FollowUp, SupplierEmail, PendingApproval, Handoff, Controls, Alert, OnboardingRequest, OnboardingCheck,
    OnboardingResult, SkillProposal, LLMJudgeScore, BusinessMetrics,
    Step, Event, MemoryEntry, SkillVersion, ExpectedOutcome, EvalResult, TagScore,
    Scoreboard, CaseDetail, ApprovalRequest,
]
