// Display-only formatting. Money arrives as Decimal strings; no arithmetic on money here.
import type { Role } from "../types/contracts";
export { shortName } from "../story";

// Explicit symbols: Intl's narrowSymbol renders TWD as a bare "$", which reads as USD. Unknown codes keep "CODE ".
const SYMBOL: Record<string, string> = { USD: "$", TWD: "NT$", MYR: "RM", KRW: "₩", EUR: "€", GBP: "£", JPY: "¥", CNY: "CN¥" };
export const currencySymbol = (currency?: string | null) => (currency ? SYMBOL[currency] ?? `${currency} ` : "");
export const amount = (v: string | null | undefined, currency?: string | null) => {
  if (v == null) return "—";
  const n = Number(v);   // display only
  return `${n < 0 ? "-" : ""}${currencySymbol(currency)}${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};
export const usd = (v: string | null | undefined) =>
  v == null ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const usdShort = (v: string | number | null | undefined) =>
  v == null ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
export const day = (iso: string | null | undefined) =>
  iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—";
export const when = (iso: string) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
export const due = (days: number | null | undefined) =>
  days == null ? "" : days < 0 ? `${-days}d overdue` : days === 0 ? "due today" : `in ${days}d`;

export const STAGES: Record<string, { label: string; color: string }> = {
  processing: { label: "Processing", color: "gray" },
  needs_review: { label: "Needs review", color: "amber" },
  on_hold: { label: "On hold", color: "yellow" },
  ready_to_pay: { label: "Ready to pay", color: "brand" },
  blocked: { label: "Payment blocked", color: "red" },
  scheduled: { label: "Scheduled", color: "blue" },
  paid: { label: "Paid", color: "green" },
  failed: { label: "Payment failed", color: "red" },
  partially_paid: { label: "Partially paid", color: "orange" },
  rejected: { label: "Rejected", color: "red" },
};
export const REC: Record<string, { label: string; color: string }> = {
  approve: { label: "Clear", color: "brand" }, hold: { label: "Hold", color: "yellow" },
  reject: { label: "Reject", color: "red" }, escalate: { label: "Escalate", color: "violet" },
};
export const RISK: Record<string, string> = { high: "red", medium: "orange", low: "gray" };

export const stage = (s: string) => ({
  reader: "Reader", doc_dedup: "Dedup", registry: "Case registry", matcher: "Matcher", router: "Router",
  investigator: "Investigator", vendor_guard: "Vendor Guard", validators: "Validators", approver: "Approver", poster: "Poster",
} as Record<string, string>)[s] ?? s;
export const stepColor = (s: string) =>
  s === "ok" ? "brand" : s === "failed" || s === "blocked" ? "red" : s === "escalated" ? "amber" : s === "running" ? "blue" : "gray";
export const findingColor = (s: string) => (s === "ok" ? "brand" : s === "flag" ? "amber" : s === "blocked" ? "red" : "gray");

// Who's signed in. Mirrors the approval matrix in config/policy.yaml.
export type Seat = "approver" | "controller" | "cfo" | "cto";
export const PEOPLE: Record<Seat, { email: string; name: string; title: string; role: Role }> = {
  approver: { email: "ap.lead@helix.example", name: "Ana Lee", title: "AP lead", role: "approver" },
  controller: { email: "m.chen@helix.example", name: "M. Chen", title: "Controller", role: "controller" },
  cfo: { email: "r.okafor@helix.example", name: "R. Okafor", title: "CFO", role: "cfo" },
  cto: { email: "h.jogi@helix.example", name: "H. Jogi", title: "CTO", role: "cto" },
};

/** Tiered maker-checker: AP leads approve but never release; a controller, CFO or CTO releases. */
export const canRelease = (role: Role) => role === "controller" || role === "cfo" || role === "cto";
export const RELEASE_RULE = "AP leads approve; a controller, CFO or CTO releases the payment";

/** Exact sum of Decimal strings via integer cents (BigInt). Never floats for money. */
export function sumMoney(values: (string | null | undefined)[]): string {
  let cents = 0n;
  for (const v of values) {
    if (!v) continue;
    const neg = v.startsWith("-");
    const [i, f = ""] = v.replace("-", "").split(".");
    const c = BigInt(i || "0") * 100n + BigInt((f + "00").slice(0, 2));
    cents += neg ? -c : c;
  }
  const neg = cents < 0n, abs = neg ? -cents : cents;
  return `${neg ? "-" : ""}${abs / 100n}.${String(abs % 100n).padStart(2, "0")}`;
}
