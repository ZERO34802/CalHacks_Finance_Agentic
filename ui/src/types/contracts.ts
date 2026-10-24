/* GENERATED from contracts/ by `make types`. Do not edit. */

/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Role".
 */
export type Role = "system" | "reader" | "investigator" | "approver" | "controller" | "requester";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ApprovalDecision".
 */
export type ApprovalDecision = "approved" | "rejected" | "ask";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "CaseStatus".
 */
export type CaseStatus =
  | "new"
  | "in_progress"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "escalated"
  | "posted"
  | "quarantined"
  | "resolved";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "DocKind".
 */
export type DocKind = "invoice" | "po" | "receipt" | "contract" | "amendment" | "email" | "statement" | "credit_note";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Channel".
 */
export type Channel = "api" | "email" | "sftp" | "s3" | "erp" | "upload";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "CaseLinkType".
 */
export type CaseLinkType = "duplicate_of" | "attached_to" | "corrected_by" | "related_pattern" | "sub_case_of";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "DiscrepancyType".
 */
export type DiscrepancyType =
  | "qty_short"
  | "price_over"
  | "unapproved_freight"
  | "fx_gap"
  | "duplicate_invoice"
  | "bank_change"
  | "lookalike_domain"
  | "embedded_instructions"
  | "below_materiality"
  | "currency_mismatch"
  | "unknown_po"
  | "missing_receipt"
  | "total_mismatch"
  | "over_limit"
  | "locked_period";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Decision".
 */
export type Decision = "approve" | "hold" | "reject" | "escalate";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "StepStatus".
 */
export type StepStatus = "running" | "ok" | "retried" | "failed" | "blocked" | "escalated" | "skipped";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "MemoryFolder".
 */
export type MemoryFolder =
  "company" | "controller-preferences" | "counterparties" | "people" | "open-matters" | "patterns";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SkillStatus".
 */
export type SkillStatus = "shadow" | "active" | "retired";

export interface ReconAIContracts {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Approval".
 */
export interface Approval {
  id: string;
  case_id: string;
  approver: string;
  role: Role;
  decision: ApprovalDecision;
  comment: string;
  limit: string | null;
  at: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ApprovalRequest".
 */
export interface ApprovalRequest {
  approver: string;
  role: Role;
  decision: ApprovalDecision;
  comment: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Case".
 */
export interface Case {
  id: string;
  parent_id: string | null;
  vendor_id: string;
  status: CaseStatus;
  documents: Document[];
  invoice: Invoice | null;
  po: PO | null;
  receipts: Receipt[];
  fingerprint: string | null;
  evidence_hash: string | null;
  links: CaseLink[];
  quarantine_reason: string | null;
  discrepancies: Discrepancy[];
  skill: string | null;
  proposal: Proposal | null;
  approvals: Approval[];
  journal_entry: JournalEntry | null;
  decision: Decision | null;
  /**
   * Times the agent re-planned after a rejection
   */
  replans: number;
  /**
   * Business 'today' for this case (posting date, period locks)
   */
  as_of: string | null;
  created_at: string;
  updated_at: string | null;
  notes: string[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Document".
 */
export interface Document {
  id: string;
  kind: DocKind;
  vendor_id: string | null;
  channel: Channel;
  filename: string;
  sha256: string;
  mime: string;
  received_at: string;
  /**
   * Raw text. UNTRUSTED. Never sent to a prompt with tools.
   */
  text: string | null;
  sender: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Invoice".
 */
export interface Invoice {
  doc_id: string;
  vendor_id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  currency: string;
  po_number: string | null;
  lines: LineItem[];
  /**
   * Decimal amount as string
   */
  total: string;
  /**
   * Bank account on the invoice, last 4 only
   */
  bank_last4: string | null;
  /**
   * Reader flags, e.g. embedded_instructions
   */
  flags: string[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "LineItem".
 */
export interface LineItem {
  line_no: number;
  sku: string;
  description: string;
  /**
   * Decimal amount as string
   */
  qty: string;
  /**
   * Decimal amount as string
   */
  unit_price: string;
  /**
   * Decimal amount as string
   */
  amount: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PO".
 */
export interface PO {
  doc_id: string;
  po_number: string;
  vendor_id: string;
  po_date: string;
  currency: string;
  lines: POLine[];
  requester: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "POLine".
 */
export interface POLine {
  line_no: number;
  sku: string;
  description: string;
  /**
   * Decimal amount as string
   */
  qty: string;
  /**
   * Decimal amount as string
   */
  unit_price: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Receipt".
 */
export interface Receipt {
  doc_id: string;
  po_number: string;
  received_date: string;
  lines: ReceiptLine[];
  received_by: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ReceiptLine".
 */
export interface ReceiptLine {
  sku: string;
  /**
   * Decimal amount as string
   */
  qty_received: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "CaseLink".
 */
export interface CaseLink {
  type: CaseLinkType;
  case_id: string | null;
  invoice_no: string | null;
  reason: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Discrepancy".
 */
export interface Discrepancy {
  type: DiscrepancyType;
  line_no: number | null;
  sku: string | null;
  material: boolean;
  expected: string | null;
  actual: string | null;
  delta: string | null;
  citations: Citation[];
  /**
   * For below_materiality: the type it would have been (e.g. price_over)
   */
  original_type: DiscrepancyType | null;
  /**
   * Per-discrepancy case fingerprint (vendor+PO+inv+type+SKU)
   */
  fingerprint: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Citation".
 */
export interface Citation {
  doc_id: string;
  /**
   * e.g. 'line 2', 'row 14', 'para 3'
   */
  locator: string;
  quote: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Proposal".
 */
export interface Proposal {
  case_id: string;
  recommendation: Decision;
  explanation: string;
  citations: Citation[];
  proposed_entry: JournalEntry | null;
  /**
   * Model confidence, not money
   */
  confidence: number;
  skill: string | null;
  skill_version: string | null;
  memory_version: string | null;
  /**
   * Floor computed by code from the decision table; recommendation may never be below it
   */
  policy_recommendation: Decision | null;
  /**
   * droid | claude | deterministic fallback | code (clean / no skill)
   */
  engine: string | null;
  /**
   * Which document wins and why (kept out of explanation)
   */
  source_of_truth: string | null;
  /**
   * e.g. request a credit note via the contact on file
   */
  next_action: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "JournalEntry".
 */
export interface JournalEntry {
  id: string;
  case_id: string;
  date: string;
  narration: string;
  postings: Posting[];
  requested_by: string;
  approved_by: string | null;
  idempotency_key: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Posting".
 */
export interface Posting {
  account: string;
  /**
   * Decimal amount as string
   */
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "CaseDetail".
 */
export interface CaseDetail {
  case: Case;
  steps: Step[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Step".
 */
export interface Step {
  id: string;
  case_id: string;
  run_id: string;
  parent_id: string | null;
  seq: number;
  stage: string;
  role: Role;
  status: StepStatus;
  skill: string | null;
  skill_version: string | null;
  memory_version: string | null;
  tool: string | null;
  /**
   * Doc/object references, not payloads
   */
  inputs: string[];
  outputs: string[];
  detail: {
    [k: string]: unknown;
  };
  error: string | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  tokens: number;
  cost_usd: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "CaseFixture".
 */
export interface CaseFixture {
  id: string;
  title: string;
  inbound: InboundItem[];
  /**
   * 'Today' for this case (period locks, due dates)
   */
  as_of: string;
}
/**
 * One file as it arrived. Paths are relative to the case folder.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "InboundItem".
 */
export interface InboundItem {
  channel: Channel;
  path: string;
  /**
   * Email From / SFTP account / API key owner
   */
  sender: string | null;
  /**
   * API channel only; simulated per-vendor key
   */
  api_key: string | null;
  received_at: string;
}
/**
 * Contract / amendment price. Amendment wins only from effective_from.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ContractTerm".
 */
export interface ContractTerm {
  doc_id: string;
  vendor_id: string;
  sku: string;
  /**
   * Decimal amount as string
   */
  unit_price: string;
  currency: string;
  effective_from: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Employee".
 */
export interface Employee {
  id: string;
  name: string;
  email: string;
  bank_last4: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "EvalResult".
 */
export interface EvalResult {
  case_id: string;
  run_id: string;
  expected: ExpectedOutcome;
  actual_decision: Decision | null;
  actual_discrepancies: DiscrepancyType[];
  actual_skill: string | null;
  /**
   * decision, discrepancies, skill, inv_* invariants
   */
  checks: {
    [k: string]: boolean;
  };
  passed: boolean;
  /**
   * Human-readable reason per failed check
   */
  misses: string[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ExpectedOutcome".
 */
export interface ExpectedOutcome {
  case_id: string;
  decision: Decision;
  discrepancies: DiscrepancyType[];
  skill: string | null;
  quarantined: boolean;
  links: CaseLinkType[];
  /**
   * Extraction check
   */
  invoice_no: string | null;
  /**
   * Extraction check
   */
  total: string | null;
  currency: string | null;
  /**
   * Expected disputed amount, to the cent
   */
  variance: string | null;
  /**
   * e.g. attack, onboarding, format:xlsx, channel:sftp
   */
  tags: string[];
  note: string;
}
/**
 * Pushed over WS /events.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Event".
 */
export interface Event {
  /**
   * step.started | step.finished | case.updated
   */
  type: string;
  case_id: string;
  step: Step | null;
  status: CaseStatus | null;
  at: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "MemoryEntry".
 */
export interface MemoryEntry {
  id: string;
  folder: MemoryFolder;
  /**
   * File name without .md, e.g. aerolane-freight
   */
  subject: string;
  text: string;
  /**
   * e.g. 'system-of-record', 'controller: M. Chen, 2026-09-14', 'case #63'
   */
  provenance: string;
  valid_from: string;
  version: number;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PaidInvoice".
 */
export interface PaidInvoice {
  vendor_id: string;
  invoice_no: string;
  po_number: string | null;
  /**
   * Decimal amount as string
   */
  total: string;
  currency: string;
  paid_on: string;
  /**
   * sha256 of sorted (sku, qty, unit_price) lines; see doc dedup
   */
  line_hash: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Scoreboard".
 */
export interface Scoreboard {
  run_id: string;
  at: string;
  total: number;
  passed: number;
  catch_rate: number;
  false_alarm_rate: number;
  invariant_pass_rate: number;
  results: EvalResult[];
  /**
   * Pass rate per check name
   */
  check_rates: {
    [k: string]: number;
  };
  by_tag: TagScore[];
}
/**
 * Per-tag breakdown (format:*, channel:*, attack, dedup, ...).
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "TagScore".
 */
export interface TagScore {
  tag: string;
  total: number;
  passed: number;
  pass_rate: number;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SkillVersion".
 */
export interface SkillVersion {
  skill: string;
  version: string;
  status: SkillStatus;
  created_at: string;
  approved_by: string | null;
  git_sha: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Vendor".
 */
export interface Vendor {
  id: string;
  name: string;
  aliases: string[];
  country: string;
  currency: string;
  email_domain: string;
  /**
   * Last 4 digits only. Never store full numbers.
   */
  bank_last4: string;
  channels: Channel[];
  tax_id: string | null;
  critical: boolean;
  on_probation: boolean;
}
