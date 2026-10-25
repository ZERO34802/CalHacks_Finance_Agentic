// Calls for the AP workspace. Errors carry the server's `detail` (e.g. a 403 sign-off refusal).
import { API_URL } from "../api";
import type {
  ApReport, ApSettings, ApprovalRequest, Bill, BillDetail, Case, ChatMessage, ChatReply, IntakeAccepted, MemoryEntry,
  EarlyPayOffer, OnboardingCase, OnboardingRequestIn, OutboundEmail, PaymentBatch, Prepayment, PrepaymentQuote, ReviewPacket, Scoreboard,
  SignOff, TreasuryStatus, Vendor, VendorContract, VendorMemoryTimeline, PurchaseOrderView, Receipt, ErpStatus, SlackRoleHolder, Role,
} from "../types/contracts";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `${init?.method ?? "GET"} ${path}: ${r.status}`);
  }
  return r.json() as Promise<T>;
}
const post = <T>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const ap = {
  bills: () => call<Bill[]>("/ap/bills"),
  bill: (id: string) => call<BillDetail>(`/ap/bills/${id}`),
  report: () => call<ApReport>("/ap/report"),
  settings: () => call<ApSettings>("/ap/settings"),
  runs: () => call<PaymentBatch[]>("/ap/payments"),
  createRun: (case_ids: string[], pay_date: string, created_by: string, methods: Record<string, string> = {}) =>
    post<PaymentBatch>("/ap/payments", { case_ids, pay_date, created_by, methods }),
  release: (id: string, released_by: string, rail: "bank" | "coinbase" = "bank", role?: Role) =>
    post<PaymentBatch>(`/ap/payments/${id}/release`, { released_by, rail, role }),
  erpStatus: () => call<ErpStatus>("/erp/status"),
  purchaseOrders: () => call<PurchaseOrderView[]>("/erp/pos"),
  receive: (po: string, received_by: string, lines: Record<string, string>) =>
    post<Receipt>(`/erp/pos/${encodeURIComponent(po)}/receive`, { received_by, lines, source: "app" }),
  slackRoles: () => call<SlackRoleHolder[]>("/slack/roles"),
  treasury: () => call<TreasuryStatus>("/ap/coinbase"),
  fundTreasury: () => post<Record<string, string>>("/ap/coinbase/faucet", {}),
  provisionWallets: () => post<Vendor[]>("/ap/coinbase/vendor-wallets", {}),
  emails: (q: { case_id?: string; vendor_id?: string } = {}) =>
    call<OutboundEmail[]>(`/emails?${new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][])}`),
  sendCaseEmails: (case_id: string) => post<OutboundEmail[]>(`/emails/${case_id}/send`, {}),
  contracts: () => call<VendorContract[]>("/contracts"),
  contractPdfUrl: (id: string) => `${API_URL}/contracts/${id}/pdf`,
  memoryTimeline: (vendor_id: string) => call<VendorMemoryTimeline>(`/memory/vendors/${vendor_id}/timeline`),
  fixtures: () => call<Case[]>("/fixtures"),
  vendors: () => call<Vendor[]>("/vendors"),
  memory: () => call<MemoryEntry[]>("/memory"),
  intake: (c: Case) => post<IntakeAccepted>("/intake", c),
  review: (id: string) => call<ReviewPacket>(`/cases/${id}/review`),
  chat: (id: string, messages: ChatMessage[]) => post<ChatReply>(`/cases/${id}/chat`, { messages }),
  decide: (id: string, req: ApprovalRequest) => post<Case>(`/approvals/${id}`, req),
  scoreboard: () => call<Scoreboard>("/evals/scoreboard"),
  runEval: () => post<Scoreboard>("/evals/run", {}),
  discounts: () => call<EarlyPayOffer[]>("/ap/discounts"),
  prepayments: (vendor_id?: string) => call<Prepayment[]>(`/ap/prepayments${vendor_id ? `?vendor_id=${vendor_id}` : ""}`),
  prepayQuote: (vendor_id: string, credit_amount: string) =>
    call<PrepaymentQuote>(`/ap/prepayments/quote?vendor_id=${encodeURIComponent(vendor_id)}&credit_amount=${encodeURIComponent(credit_amount)}`),
  requestPrepayment: (vendor_id: string, credit_amount: string, requested_by: string, note: string) =>
    post<Prepayment>("/ap/prepayments", { vendor_id, credit_amount, requested_by, note }),
  decidePrepayment: (id: string, req: SignOff) => post<Prepayment>(`/ap/prepayments/${id}/decide`, req),
  crsPersonas: () => call<{ id: string; name: string; profile: string; decision: string }[]>("/vendors/onboarding/personas"),
  onboardingSamples: () => call<{ label: string; request: OnboardingRequestIn }[]>("/vendors/onboarding/samples"),
  onboarding: () => call<OnboardingCase[]>("/vendors/onboarding/list"),
  submitOnboarding: (req: OnboardingRequestIn) => post<OnboardingCase>("/vendors/onboarding", req),
  recheckOnboarding: (id: string) => post<OnboardingCase>(`/vendors/onboarding/${id}/recheck`, {}),
  decideOnboarding: (id: string, req: SignOff) => post<OnboardingCase>(`/vendors/onboarding/${id}/decide`, req),
};
