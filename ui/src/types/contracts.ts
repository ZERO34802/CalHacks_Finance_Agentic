/* GENERATED from contracts/ by `make types`. Do not edit. */

/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Role".
 */
export type Role = "system" | "reader" | "investigator" | "approver" | "controller" | "cfo" | "cto" | "requester";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ApprovalDecision".
 */
export type ApprovalDecision = "approved" | "rejected" | "ask";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Decision".
 */
export type Decision = "approve" | "hold" | "reject" | "escalate";
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
  | "resolved"
  | "paused"
  | "awaiting_vendor"
  | "reopened";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "DocKind".
 */
export type DocKind = "invoice" | "po" | "receipt" | "contract" | "amendment" | "email" | "statement" | "credit_note";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Channel".
 */
export type Channel = "api" | "email" | "sftp" | "s3" | "erp" | "upload" | "slack";
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
 * via the `definition` "FollowUpKind".
 */
export type FollowUpKind = "credit_note" | "corrected_invoice" | "callback" | "supplier_reply" | "resend";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "FollowUpStatus".
 */
export type FollowUpStatus = "open" | "done" | "overdue";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "StepStatus".
 */
export type StepStatus = "running" | "ok" | "retried" | "failed" | "blocked" | "escalated" | "skipped";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "FixtureKind".
 */
export type FixtureKind = "inbound" | "tick";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "MemoryFolder".
 */
export type MemoryFolder =
  "company" | "controller-preferences" | "counterparties" | "people" | "open-matters" | "patterns";
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SkillProposalStatus".
 */
export type SkillProposalStatus = "proposed" | "approved" | "rejected" | "applied";
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
 * via the `definition` "ActivityItem".
 */
export interface ActivityItem {
  at: string;
  actor: string;
  text: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "AgingBucket".
 */
export interface AgingBucket {
  label: string;
  /**
   * Decimal amount as string
   */
  amount_usd: string;
  count: number;
}
/**
 * Stored as a record (kind='alert'). E.g. expected vendor file missing, SLA breach, payment due at risk.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Alert".
 */
export interface Alert {
  id: string;
  kind: string;
  vendor_id: string | null;
  case_id: string | null;
  at: string;
  message: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ApReport".
 */
export interface ApReport {
  /**
   * Decimal amount as string
   */
  open_usd: string;
  /**
   * Decimal amount as string
   */
  due_7d_usd: string;
  /**
   * Decimal amount as string
   */
  overdue_usd: string;
  needs_review: number;
  blocked: number;
  touchless_rate: number | null;
  /**
   * USD of bills held, rejected or payment-blocked by checks
   */
  caught_usd: string;
  /**
   * Decimal amount as string
   */
  discounts_available_usd: string;
  /**
   * Decimal amount as string
   */
  discounts_captured_usd: string;
  /**
   * Decimal amount as string
   */
  discounts_missed_usd: string;
  aging: AgingBucket[];
  forecast: ForecastWeek[];
  by_vendor: SpendRow[];
  by_gl: SpendRow[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ForecastWeek".
 */
export interface ForecastWeek {
  week_start: string;
  /**
   * Decimal amount as string
   */
  approved_usd: string;
  /**
   * Decimal amount as string
   */
  pending_usd: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SpendRow".
 */
export interface SpendRow {
  label: string;
  /**
   * Decimal amount as string
   */
  amount_usd: string;
  count: number;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ApSettings".
 */
export interface ApSettings {
  approval_limits: {
    /**
     * Decimal amount as string
     */
    [k: string]: string;
  };
  sla_hours: number;
  /**
   * Decimal amount as string
   */
  materiality_abs: string;
  /**
   * Decimal amount as string
   */
  materiality_pct: string;
  /**
   * Decimal amount as string
   */
  qty_tolerance_pct: string;
  /**
   * Decimal amount as string
   */
  price_tolerance_pct: string;
  locked_periods: string[];
  fx_rates: {
    /**
     * Decimal amount as string
     */
    [k: string]: string;
  };
  accounts: {
    [k: string]: string;
  };
  integrations: Integration[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Integration".
 */
export interface Integration {
  name: string;
  /**
   * connected | simulated | not_connected
   */
  status: string;
  note: string;
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
  /**
   * full | undisputed (pay only the undisputed part of a hold)
   */
  scope: string | null;
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
  /**
   * full | undisputed; default: undisputed on a hold, else full
   */
  scope: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ApprovalStep".
 */
export interface ApprovalStep {
  step: number;
  label: string;
  who: string;
  /**
   * done | waiting | pending | rejected | on_hold
   */
  status: string;
  note: string;
}
/**
 * One invoice as the AP team sees it.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Bill".
 */
export interface Bill {
  case_id: string;
  vendor_id: string;
  vendor_name: string;
  invoice_no: string | null;
  invoice_date: string | null;
  due_date: string | null;
  days_to_due: number | null;
  amount: string | null;
  currency: string | null;
  amount_usd: string | null;
  /**
   * processing | needs_review | on_hold | ready_to_pay | blocked | scheduled | paid | rejected
   */
  stage: string;
  recommendation: Decision | null;
  approved_by: string | null;
  /**
   * role that must sign, or nobody
   */
  needs: string;
  /**
   * high | medium | low
   */
  risk: string;
  signals: Signal[];
  /**
   * time since it was handed to a human
   */
  waiting_hours: number | null;
  sla_breached: boolean;
  payment_block: string | null;
  payment: Payment | null;
  /**
   * amount at risk from the 3-way match, invoice currency
   */
  overbilled: string | null;
  discount: EarlyPayOffer | null;
  /**
   * advance-payment credit open for this vendor
   */
  credit_available: string | null;
  /**
   * one line shown under the bill in lists
   */
  warning: string | null;
  /**
   * AP booked by the Poster and not yet credited: what a payment run may pay (the undisputed part of a partial hold)
   */
  payable: string | null;
  payable_usd: string | null;
  /**
   * held part of a hold (invoice currency)
   */
  disputed: string | null;
  /**
   * the pipeline's case status
   */
  case_status: CaseStatus | null;
  /**
   * where the second-line checks and the agents' decision disagree
   */
  disagreements: string[];
  /**
   * one sub-case per discrepancy, grouped here
   */
  sub_case_ids: string[];
  po_number: string | null;
}
/**
 * A pre-payment check run by code at review time.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Signal".
 */
export interface Signal {
  /**
   * bank_mismatch | lookalike_domain | duplicate | qty_short | price_over | not_on_po | over_limit | embedded_instructions | probation
   */
  code: string;
  /**
   * high | medium | low
   */
  severity: string;
  title: string;
  detail: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Payment".
 */
export interface Payment {
  id: string;
  batch_id: string;
  case_id: string;
  vendor_id: string;
  /**
   * Decimal amount as string
   */
  amount: string;
  currency: string;
  /**
   * Decimal amount as string
   */
  amount_usd: string;
  /**
   * ach | wire | intl_wire | check
   */
  method: string;
  pay_date: string;
  /**
   * Always the vendor master's account, never the invoice's
   */
  pay_to_last4: string;
  /**
   * scheduled | paid
   */
  status: string;
  /**
   * invoice total before discount and credits
   */
  gross_amount: string | null;
  /**
   * early-payment discount taken
   */
  discount_amount: string;
  /**
   * advance-payment credit used
   */
  credit_applied: string;
  /**
   * bank (simulated ACH/wire) | coinbase (USDC on-chain)
   */
  rail: string;
  /**
   * e.g. base-sepolia (coinbase rail)
   */
  network: string | null;
  onchain_token: string | null;
  /**
   * Token amount sent (testnet: scaled from amount_usd)
   */
  onchain_amount: string | null;
  /**
   * Vendor master wallet_address, never the invoice's
   */
  payee_address: string | null;
  tx_hash: string | null;
  explorer_url: string | null;
  error: string | null;
}
/**
 * An early-payment discount on one bill, computed in code from the vendor's terms.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "EarlyPayOffer".
 */
export interface EarlyPayOffer {
  case_id: string;
  vendor_id: string;
  vendor_name: string;
  invoice_no: string | null;
  /**
   * e.g. 2/15 net 30
   */
  terms: string;
  /**
   * Decimal amount as string
   */
  discount_pct: string;
  /**
   * Decimal amount as string
   */
  discount_amount: string;
  currency: string;
  /**
   * Decimal amount as string
   */
  discount_usd: string;
  pay_by: string;
  days_left: number;
  /**
   * what paying early 'earns', annualised
   */
  annualized_return_pct: number;
  /**
   * available | needs_approval | blocked | missed | captured
   */
  status: string;
  note: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "BillDetail".
 */
export interface BillDetail {
  bill: Bill;
  /**
   * ready | review | risk
   */
  verdict: string;
  verdict_text: string;
  checks: CheckResult[];
  match: MatchRow[];
  gl: GLLine[];
  approval_steps: ApprovalStep[];
  activity: ActivityItem[];
  last_paid: LastPaid | null;
  est_pay_date: string | null;
  /**
   * methods allowed for this vendor
   */
  pay_methods: string[];
  default_method: string | null;
  statement_descriptor: string;
  /**
   * the account printed on the invoice (last 4)
   */
  invoice_bank_last4: string | null;
}
/**
 * One pre-payment check and whether it passed, with references to the evidence.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "CheckResult".
 */
export interface CheckResult {
  name: string;
  passed: boolean;
  /**
   * high | medium | low (only meaningful when not passed)
   */
  severity: string;
  detail: string;
  /**
   * e.g. 'Line 1', 'PO-5501', 'INV-2291'
   */
  refs: string[];
}
/**
 * One SKU across purchase order, goods receipt and invoice. Variances computed in code.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "MatchRow".
 */
export interface MatchRow {
  sku: string;
  description: string;
  ordered: string | null;
  /**
   * Decimal amount as string
   */
  received: string;
  /**
   * Decimal amount as string
   */
  billed: string;
  po_price: string | null;
  /**
   * Decimal amount as string
   */
  invoice_price: string;
  /**
   * billed - min(ordered, received)
   */
  qty_variance: string;
  /**
   * invoice_price - po_price
   */
  price_variance: string | null;
  /**
   * what would be overpaid, in invoice currency
   */
  amount_at_risk: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "GLLine".
 */
export interface GLLine {
  line_no: number;
  sku: string;
  description: string;
  /**
   * Decimal amount as string
   */
  amount: string;
  account: string;
  /**
   * why this account was suggested
   */
  basis: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "LastPaid".
 */
export interface LastPaid {
  invoice_no: string;
  /**
   * Decimal amount as string
   */
  amount: string;
  currency: string;
  paid_on: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "BusinessMetrics".
 */
export interface BusinessMetrics {
  /**
   * Decimal amount as string
   */
  dollars_caught_usd: string;
  /**
   * ESTIMATE, labeled as such in the UI
   */
  hours_saved_est: string;
  on_time_payment_rate: number;
  exceptions_per_vendor: {
    [k: string]: number;
  };
  avg_time_to_resolve_hours: number | null;
  notes: string[];
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
  /**
   * One sub-case per discrepancy (parent = invoice)
   */
  sub_case_ids: string[];
  /**
   * Undisputed part posted for payment
   */
  paid_amount: string | null;
  disputed_amount: string | null;
  follow_ups: FollowUp[];
  outbound: SupplierEmail[];
  pending_approval: PendingApproval | null;
  /**
   * Human who took over; agent stages skip while set
   */
  assigned_to: string | null;
  handoffs: Handoff[];
  /**
   * Queue priority score; higher = sooner
   */
  priority: number | null;
  reopens: number;
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
  /**
   * Email Subject header (UNTRUSTED); carries [REC <case_id>] on replies
   */
  subject: string | null;
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
  /**
   * Credit note: invoice number it credits (amounts positive)
   */
  credit_for: string | null;
  /**
   * Corrected invoice: invoice number it replaces
   */
  corrects: string | null;
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
  /**
   * Supply agreement this PO was created from (Slack contract)
   */
  contract_id: string | null;
  /**
   * Record in the external ERP, e.g. odoo:purchase.order:42
   */
  erp_ref: string | null;
  /**
   * ordered | partially_received | received | invoiced | paid
   */
  status: string;
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
  /**
   * Record in the external ERP, e.g. odoo:stock.picking:17
   */
  erp_ref: string | null;
  /**
   * erp | app | slack (always a Helix person, never the vendor)
   */
  source: string;
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
 * via the `definition` "FollowUp".
 */
export interface FollowUp {
  id: string;
  case_id: string;
  kind: FollowUpKind;
  due: string;
  status: FollowUpStatus;
  note: string;
  created_at: string;
  /**
   * Doc id / case id / person that closed it
   */
  closed_by: string | null;
}
/**
 * Outbound email to the vendor's contact on file (never reply-to-sender). SIMULATED: not actually sent.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SupplierEmail".
 */
export interface SupplierEmail {
  id: string;
  case_id: string;
  to: string;
  /**
   * Carries the case reference, e.g. '[REC case_02] ...', so replies link back
   */
  subject: string;
  body: string;
  idempotency_key: string;
  sent_at: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PendingApproval".
 */
export interface PendingApproval {
  role: Role;
  approver: string;
  requested_at: string;
  due_at: string;
  reminded_at: string | null;
  /**
   * Backup approver after SLA breach
   */
  escalated_to: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Handoff".
 */
export interface Handoff {
  case_id: string;
  from_actor: string;
  to_actor: string;
  at: string;
  note: string;
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
  kind: FixtureKind;
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
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ChatMessage".
 */
export interface ChatMessage {
  /**
   * user | assistant
   */
  role: string;
  content: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ChatReply".
 */
export interface ChatReply {
  content: string;
  /**
   * claude | offline
   */
  source: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ChatRequest".
 */
export interface ChatRequest {
  messages: ChatMessage[];
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
 * Kill switch. Stored as a record (kind='controls', key='global').
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Controls".
 */
export interface Controls {
  paused_global: boolean;
  paused_vendors: string[];
  updated_by: string;
  updated_at: string | null;
}
/**
 * Dashboard read model (D). C's BusinessMetrics is the eval/scoreboard model.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "DashboardMetrics".
 */
export interface DashboardMetrics {
  cases: number;
  exceptions: number;
  /**
   * Held/rejected/escalated exposure, USD at simulated FX
   */
  dollars_caught_usd: string;
  /**
   * ESTIMATE: per-case manual minutes x cases handled
   */
  hours_saved_estimate: string;
  /**
   * Posted on or before due date; None if nothing posted
   */
  on_time_payment_rate: number | null;
  avg_hours_to_resolve: number | null;
  by_vendor: VendorExceptions[];
  /**
   * Shown next to the numbers
   */
  assumptions: string[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "VendorExceptions".
 */
export interface VendorExceptions {
  vendor_id: string;
  vendor_name: string;
  cases: number;
  exceptions: number;
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
 * via the `definition` "ErpStatus".
 */
export interface ErpStatus {
  /**
   * odoo | simulated
   */
  mode: string;
  connected: boolean;
  url: string | null;
  database: string | null;
  note: string;
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
  /**
   * None for tick fixtures (use asserts)
   */
  decision: Decision | null;
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
   * Expected undisputed amount posted (pay what's clean)
   */
  paid_amount: string | null;
  /**
   * '<case_id>.<dotted.path>' -> expected str value, checked after this fixture
   */
  asserts: {
    [k: string]: string;
  };
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
 * A non-ok step and what the pipeline did next.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "FailureItem".
 */
export interface FailureItem {
  case_id: string;
  run_id: string;
  step_id: string;
  stage: string;
  status: StepStatus;
  error: string | null;
  next_stage: string | null;
  next_status: StepStatus | null;
  at: string;
}
/**
 * One check the agents ran, in plain language, for the reviewer.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Finding".
 */
export interface Finding {
  /**
   * e.g. '3-way match', 'Vendor & bank'
   */
  check: string;
  /**
   * pipeline stage that ran it
   */
  agent: string;
  /**
   * ok | flag | unchecked | blocked
   */
  status: string;
  detail: string;
}
/**
 * Returned by POST /intake: the run continues in the background.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "IntakeAccepted".
 */
export interface IntakeAccepted {
  case_id: string;
  run_id: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "LLMJudgeScore".
 */
export interface LLMJudgeScore {
  case_id: string;
  /**
   * explanation | supplier_email | escalation | defend_decision | skill_proposal
   */
  rubric: string;
  /**
   * Mean 1-5 over runs
   */
  score: number;
  runs: number;
  rationale: string;
  model: string;
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
 * via the `definition` "MemoryEvent".
 */
export interface MemoryEvent {
  /**
   * skill_change | memory_use
   */
  kind: string;
  at: string;
  label: string;
  case_ids: string[];
}
/**
 * A memory line and its history (oldest version first).
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "MemorySlot".
 */
export interface MemorySlot {
  entry_id: string;
  label: string;
  current: MemoryVersion | null;
  versions: MemoryVersion[];
}
/**
 * One version of one memory line.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "MemoryVersion".
 */
export interface MemoryVersion {
  entry_id: string;
  version: number;
  text: string;
  provenance: string;
  /**
   * system_of_record | computed | controller | approver | outcome | seed
   */
  source: string;
  valid_from: string;
  /**
   * added | updated | forgotten
   */
  change: string;
  cases: string[];
  people: string[];
}
/**
 * A case decision that read this vendor's memory (from the trace).
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "MemoryUse".
 */
export interface MemoryUse {
  case_id: string;
  memory_version: string;
  decision: string | null;
  at: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "OnboardingCase".
 */
export interface OnboardingCase {
  id: string;
  request: OnboardingRequestIn;
  /**
   * needs_review | approved | rejected
   */
  status: string;
  checks: VendorCheck[];
  /**
   * low | medium | high
   */
  risk_tier: string;
  /**
   * role that must approve: approver | controller
   */
  needs: string;
  /**
   * live | simulated
   */
  crs_mode: string;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_comment: string;
  vendor_id: string | null;
  /**
   * app | slack (negotiated in Slack, contract attached)
   */
  source: string;
  contract_id: string | null;
  /**
   * Approved by policy (low risk, every check passed), no human click
   */
  auto_approved: boolean;
  confirmation_email_id: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "OnboardingRequestIn".
 */
export interface OnboardingRequestIn {
  legal_name: string;
  country: string;
  currency: string;
  tax_id: string | null;
  address: string;
  city: string;
  state: string;
  zip: string;
  email_domain: string;
  website: string;
  bank_last4: string;
  contact_name: string;
  contact_phone: string;
  /**
   * Decimal amount as string
   */
  expected_annual_spend_usd: string;
  requested_by: string;
  /**
   * W-9 (US) | W-8BEN-E (non-US); null = not received
   */
  tax_form: string | null;
  trade_names: string[];
  /**
   * Becomes the verified contact on file once approved
   */
  contact_email: string | null;
  /**
   * Owner / authorized signer, as a CRS sandbox test persona id (P01-P20): CRS identity, fraud and court-record checks run on them
   */
  principal_persona: string | null;
  /**
   * The owner consented to a soft credit check (FCRA permissible purpose)
   */
  credit_consent: boolean;
}
/**
 * One onboarding check as shown in the UI (D): CRS or code, pass/warn/fail.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "VendorCheck".
 */
export interface VendorCheck {
  name: string;
  /**
   * CRS | code
   */
  provider: string;
  /**
   * pass | warn | fail | not_covered | incomplete
   */
  status: string;
  detail: string;
  simulated: boolean;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "OnboardingCheck".
 */
export interface OnboardingCheck {
  /**
   * e.g. duplicate_tax_id, sanctions, employee_bank, lookalike_domain, tax_form
   */
  name: string;
  passed: boolean;
  detail: string;
  simulated: boolean;
}
/**
 * data/onboarding/onb_*.json. Always started by an internal requester (vendors never self-sign-up).
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "OnboardingRequest".
 */
export interface OnboardingRequest {
  id: string;
  title: string;
  received_at: string;
  requested_by: string;
  legal_name: string;
  trade_names: string[];
  country: string;
  tax_id: string | null;
  tax_form: string | null;
  email_domain: string;
  bank_last4: string;
  currency: string;
  channels: Channel[];
  payment_terms: string | null;
  expected_annual_spend_usd: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "OnboardingResult".
 */
export interface OnboardingResult {
  request_id: string;
  checks: OnboardingCheck[];
  /**
   * Names of failed checks
   */
  flags: string[];
  /**
   * low | medium | high
   */
  risk_tier: string | null;
  decision: Decision | null;
  approvals: Approval[];
  /**
   * Set only once activated
   */
  vendor_id: string | null;
  probation_until: string | null;
  notes: string[];
}
/**
 * An email ReconAI sent or queued. Delivered via Resend when configured; always kept here (the outbox).
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "OutboundEmail".
 */
export interface OutboundEmail {
  id: string;
  /**
   * supplier_discrepancy | onboarding_confirmation | onboarding_received
   */
  kind: string;
  case_id: string | null;
  vendor_id: string | null;
  /**
   * Intended recipient (contact on file)
   */
  to: string;
  /**
   * Where it actually went (demo redirect inbox)
   */
  delivered_to: string | null;
  subject: string;
  body: string;
  /**
   * sent | outbox | failed
   */
  status: string;
  /**
   * resend | outbox
   */
  provider: string;
  provider_id: string | null;
  error: string | null;
  idempotency_key: string;
  created_at: string;
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
 * via the `definition` "PaymentBatch".
 */
export interface PaymentBatch {
  id: string;
  pay_date: string;
  /**
   * scheduled | paid | partially_paid
   */
  status: string;
  /**
   * Set at release: bank | coinbase
   */
  rail: string | null;
  created_by: string;
  created_at: string;
  released_by: string | null;
  released_at: string | null;
  payments: Payment[];
  /**
   * Decimal amount as string
   */
  total_usd: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PaymentBatchRequest".
 */
export interface PaymentBatchRequest {
  case_ids: string[];
  pay_date: string;
  created_by: string;
  /**
   * case_id -> method; default by vendor country
   */
  methods: {
    [k: string]: string;
  };
}
/**
 * Commercial terms from the contract / vendor master (never from invoice text). e.g. 2/10 net 30.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PaymentTerms".
 */
export interface PaymentTerms {
  net_days: number;
  /**
   * early-payment discount, e.g. 0.02
   */
  discount_pct: string | null;
  /**
   * pay within N days of the invoice date to earn it
   */
  discount_days: number | null;
  /**
   * discount for paying in advance, e.g. 0.04
   */
  prepay_discount_pct: string | null;
  /**
   * max open prepaid balance for this vendor
   */
  prepay_cap_usd: string | null;
  /**
   * where these terms come from
   */
  source: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PrepayApplication".
 */
export interface PrepayApplication {
  case_id: string;
  /**
   * Decimal amount as string
   */
  amount: string;
  at: string;
}
/**
 * An advance payment that buys vendor credit at a discount. SIMULATED settlement.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "Prepayment".
 */
export interface Prepayment {
  id: string;
  vendor_id: string;
  vendor_name: string;
  currency: string;
  /**
   * credit granted against future invoices
   */
  credit_amount: string;
  /**
   * what Helix pays now
   */
  cash_amount: string;
  /**
   * Decimal amount as string
   */
  discount_amount: string;
  /**
   * Decimal amount as string
   */
  discount_pct: string;
  /**
   * Decimal amount as string
   */
  cash_usd: string;
  /**
   * requested | paid | rejected
   */
  status: string;
  requested_by: string;
  requested_at: string;
  approved_by: string | null;
  approved_at: string | null;
  note: string;
  applied: PrepayApplication[];
  /**
   * Decimal amount as string
   */
  remaining: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PrepaymentQuote".
 */
export interface PrepaymentQuote {
  vendor_id: string;
  currency: string;
  /**
   * Decimal amount as string
   */
  credit_amount: string;
  /**
   * Decimal amount as string
   */
  cash_amount: string;
  /**
   * Decimal amount as string
   */
  discount_amount: string;
  /**
   * Decimal amount as string
   */
  discount_pct: string;
  /**
   * Decimal amount as string
   */
  cash_usd: string;
  cap_remaining_usd: string | null;
  allowed: boolean;
  reason: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PrepaymentRequest".
 */
export interface PrepaymentRequest {
  vendor_id: string;
  /**
   * Decimal amount as string
   */
  credit_amount: string;
  requested_by: string;
  note: string;
}
/**
 * A PO as the Purchasing page shows it: ordered vs received vs invoiced, with its ERP record.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "PurchaseOrderView".
 */
export interface PurchaseOrderView {
  po: PO;
  vendor_name: string;
  receipts: Receipt[];
  /**
   * sku -> qty received so far
   */
  received: {
    /**
     * Decimal amount as string
     */
    [k: string]: string;
  };
  /**
   * case ids of bills billed against this PO
   */
  invoices: string[];
  /**
   * Decimal amount as string
   */
  total: string;
  /**
   * ordered | partially_received | received | invoiced | paid
   */
  status: string;
  /**
   * Deep link to the record in the ERP (Odoo)
   */
  erp_url: string | null;
}
/**
 * One open case in the approval queue, sorted by priority (highest first).
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "QueueItem".
 */
export interface QueueItem {
  case_id: string;
  vendor_id: string;
  vendor_name: string;
  status: CaseStatus;
  decision: Decision | null;
  invoice_no: string | null;
  total: string | null;
  currency: string | null;
  /**
   * At the simulated policy FX rate
   */
  total_usd: string | null;
  due_date: string | null;
  days_to_due: number | null;
  /**
   * Due within the at-risk window or overdue
   */
  at_risk: boolean;
  critical_vendor: boolean;
  /**
   * Higher = work first
   */
  priority: number;
  /**
   * Why it ranks where it does
   */
  reasons: string[];
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ReceiveRequest".
 */
export interface ReceiveRequest {
  received_by: string;
  /**
   * sku -> qty received now
   */
  lines: {
    /**
     * Decimal amount as string
     */
    [k: string]: string;
  };
  /**
   * app | slack
   */
  source: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ReleaseRequest".
 */
export interface ReleaseRequest {
  released_by: string;
  /**
   * Releaser's role: AP leads can't release; controller/CFO/CTO can
   */
  role: Role | null;
  /**
   * bank (simulated) | coinbase (USDC, Base Sepolia testnet)
   */
  rail: string;
}
/**
 * Everything the reviewer gets once the background run is done.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "ReviewPacket".
 */
export interface ReviewPacket {
  case_id: string;
  /**
   * False while the pipeline is still running
   */
  ready: boolean;
  summary: string;
  recommendation: Decision | null;
  /**
   * who must sign: approver | controller | nobody
   */
  needs: string;
  findings: Finding[];
  trace: Step[];
  files: Document[];
  /**
   * pre-payment checks run by code
   */
  signals: Signal[];
  /**
   * questions the reviewer can tap
   */
  suggested: string[];
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
  llm_scores: LLMJudgeScore[];
  /**
   * Decision stability across repeated runs (0-1)
   */
  stability: number | null;
  metrics: BusinessMetrics | null;
  /**
   * Vendor-onboarding results; reported separately from the headline
   */
  onboarding: EvalResult[];
  /**
   * Run notes, e.g. a skipped section and why
   */
  notes: string[];
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
 * A human decision on a prepayment or onboarding request.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SignOff".
 */
export interface SignOff {
  approver: string;
  role: Role;
  /**
   * approved | rejected
   */
  decision: string;
  comment: string;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SkillProposal".
 */
export interface SkillProposal {
  id: string;
  skill: string;
  from_version: string;
  to_version: string;
  rationale: string;
  /**
   * Unified diff against SKILL.md / policy.yaml
   */
  diff: string;
  evidence_case_ids: string[];
  /**
   * Eval summary on current skill
   */
  replay_before: {
    [k: string]: unknown;
  };
  /**
   * Eval summary with the proposal applied
   */
  replay_after: {
    [k: string]: unknown;
  };
  /**
   * Loosening needs controller + second sign-off (ratchet)
   */
  loosens: boolean;
  status: SkillProposalStatus;
  approved_by: string[];
  engine: string | null;
  created_at: string;
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
 * A Slack user registered to an AP role with /reconai role (who gets which notifications and buttons).
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "SlackRoleHolder".
 */
export interface SlackRoleHolder {
  slack_user: string;
  name: string;
  email: string;
  role: Role;
}
/**
 * How one pipeline stage behaved across every case's latest run.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "StageStat".
 */
export interface StageStat {
  stage: string;
  runs: number;
  ok: number;
  skipped: number;
  /**
   * failed + blocked + escalated + retried
   */
  flagged: number;
  avg_ms: number | null;
}
/**
 * The Coinbase (CDP) treasury wallet that pays vendors on the coinbase rail.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "TreasuryStatus".
 */
export interface TreasuryStatus {
  /**
   * live | not_configured
   */
  mode: string;
  network: string;
  address: string | null;
  /**
   * token symbol -> decimal amount
   */
  balances: {
    [k: string]: string;
  };
  /**
   * testnet: USDC sent = amount_usd x usd_scale
   */
  usd_scale: string;
  explorer_url: string | null;
  note: string;
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
  probation_until: string | null;
  /**
   * Verified contact on file; outbound goes here, never reply-to
   */
  contact_email: string | null;
  /**
   * daily | weekly: expected-file schedule (missing-file alerts)
   */
  expected_schedule: string | null;
  terms: PaymentTerms | null;
  /**
   * On-chain payout address on file (Coinbase rail, testnet). Changed only like bank details: never from an invoice or email
   */
  wallet_address: string | null;
}
/**
 * A supply contract ReconAI drafted from a Slack negotiation. Terms are what both sides agreed in the thread.
 *
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "VendorContract".
 */
export interface VendorContract {
  id: string;
  vendor_name: string;
  category: string;
  /**
   * sku/description, qty, unit, unit_price
   */
  items: {
    [k: string]: unknown;
  }[];
  currency: string;
  /**
   * Decimal amount as string
   */
  total: string;
  terms: PaymentTerms;
  delivery: string;
  warranty: string;
  other_terms: string[];
  requested_by: string;
  channel: string;
  created_at: string;
  /**
   * draft | accepted | onboarding | onboarded | held
   */
  status: string;
  accepted_by: string | null;
  onboarding_id: string | null;
}
/**
 * This interface was referenced by `ReconAIContracts`'s JSON-Schema
 * via the `definition` "VendorMemoryTimeline".
 */
export interface VendorMemoryTimeline {
  vendor_id: string;
  vendor_name: string;
  subject: string | null;
  memory_version: string | null;
  slots: MemorySlot[];
  uses: MemoryUse[];
  events: MemoryEvent[];
  sources: {
    [k: string]: number;
  };
}
