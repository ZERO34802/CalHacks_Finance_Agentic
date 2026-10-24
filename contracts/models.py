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
    sku: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    delta: Optional[Money] = None
    citations: list[Citation] = []


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


class Approval(Model):
    id: str
    case_id: str
    approver: str
    role: Role
    decision: ApprovalDecision
    comment: str = ""
    limit: Optional[Money] = None
    at: datetime


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
    discrepancies: list[Discrepancy] = []
    skill: Optional[str] = None
    proposal: Optional[Proposal] = None
    approvals: list[Approval] = []
    journal_entry: Optional[JournalEntry] = None
    decision: Optional[Decision] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    notes: list[str] = []


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
    decision: Decision
    discrepancies: list[DiscrepancyType] = []
    skill: Optional[str] = None
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


class Scoreboard(Model):
    run_id: str
    at: datetime
    total: int
    passed: int
    catch_rate: float
    false_alarm_rate: float
    invariant_pass_rate: float
    results: list[EvalResult]


# --- API payloads -----------------------------------------------------------

class CaseDetail(Model):
    case: Case
    steps: list[Step]


class ApprovalRequest(Model):
    approver: str
    role: Role
    decision: ApprovalDecision
    comment: str = ""


ALL_MODELS: list[type[BaseModel]] = [
    Vendor, Document, LineItem, Invoice, POLine, PO, ReceiptLine, Receipt,
    Citation, Discrepancy, Posting, JournalEntry, Proposal, Approval, Case,
    Step, Event, MemoryEntry, SkillVersion, ExpectedOutcome, EvalResult,
    Scoreboard, CaseDetail, ApprovalRequest,
]
