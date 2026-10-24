// Plain-language layer over the trace: agents, stations, narration, verdicts.
// Narration only restates what the backend recorded; it never decides anything.
import type { Case, Decision, DiscrepancyType, Step, Vendor } from "./types/contracts";

export type Act = "Read" | "Check" | "Decide" | "Post";
export type Kind = "claude" | "droid" | "code";

export type Agent = {
  id: string; name: string; act: Act; kind: Kind; engine: string;
  replaces: string; can: string[]; cannot: string[];
};

// One entry per pipeline stage, in pipeline order (mirrors backend/core/runner.py PIPELINE).
export const AGENTS: Agent[] = [
  { id: "reader", name: "Reader", act: "Read", kind: "claude", engine: "Claude · zero tools",
    replaces: "Keying invoices by hand", can: ["Extract fields into a strict schema", "Flag hidden instructions"],
    cannot: ["Call any tool", "Act on what it reads"] },
  { id: "doc_dedup", name: "Dedup", act: "Read", kind: "code", engine: "Deterministic code",
    replaces: "Hunting for double billing", can: ["Hash files and line items", "Check paid history"], cannot: ["Guess"] },
  { id: "registry", name: "Registry", act: "Read", kind: "code", engine: "Deterministic code",
    replaces: "Remembering what's already open", can: ["Fingerprint each discrepancy", "Reopen or attach"], cannot: ["Open duplicates"] },
  { id: "matcher", name: "Matcher", act: "Check", kind: "code", engine: "Deterministic code",
    replaces: "3-way match in spreadsheets", can: ["PO vs receipt vs invoice", "FX and tolerances"], cannot: ["Let an LLM do math"] },
  { id: "router", name: "Router", act: "Check", kind: "code", engine: "Deterministic code",
    replaces: "Deciding who handles it", can: ["Pick a skill by event type", "Escalate when none fits"], cannot: ["Let a document choose"] },
  { id: "investigator", name: "Investigator", act: "Check", kind: "droid", engine: "Factory Droid · sandbox",
    replaces: "Chasing down exceptions", can: ["Read the case, memory, skill", "Write one proposal"],
    cannot: ["Reach the network", "Touch secrets or the ledger"] },
  { id: "vendor_guard", name: "Vendor Guard", act: "Check", kind: "code", engine: "Code + CRS",
    replaces: "Bank-change fraud checks", can: ["Domain and bank vs master", "Sanctions screening"], cannot: ["Edit bank details"] },
  { id: "validators", name: "Validators", act: "Check", kind: "code", engine: "Deterministic code",
    replaces: "The second pair of eyes", can: ["Recompute every number", "Verify every citation"], cannot: ["Wave anything through"] },
  { id: "approver", name: "Approver", act: "Decide", kind: "claude", engine: "Separate identity",
    replaces: "Sign-off", can: ["Approve, reject, or ask", "Escalate over its limit"], cannot: ["Approve its own proposal"] },
  { id: "poster", name: "Poster", act: "Post", kind: "code", engine: "Beancount · double entry",
    replaces: "Booking the entry", can: ["Post balanced entries", "Tie subledger to GL"],
    cannot: ["Post if requester = approver", "Post over limit or into a closed month"] },
];
export const ACTS: Act[] = ["Read", "Check", "Decide", "Post"];
export const agent = (id: string) => AGENTS.find((a) => a.id === id);
export const stageName = (id: string) => agent(id)?.name ?? id.replace(/_/g, " ");
export const KIND_LABEL: Record<Kind, string> = { claude: "Claude", droid: "Factory Droid", code: "Code" };

export type Station = { id: string; name: string; act: Act; kind: Kind; step: Step | null };

/** Agents in pipeline order, each with the step it produced (if any) in this run. */
export function stations(steps: Step[]): Station[] {
  const top = steps.filter((s) => !s.parent_id);
  const known: Station[] = AGENTS.map((a) => ({ id: a.id, name: a.name, act: a.act, kind: a.kind, step: top.find((x) => x.stage === a.id) ?? null }));
  const extra = top.filter((x) => !agent(x.stage))
    .map((x): Station => ({ id: x.stage, name: stageName(x.stage), act: "Check", kind: "code", step: x }));
  return [...known, ...extra];
}
export const lastAvailable = (list: Station[]) => list.reduce((m, s, i) => (s.step ? i : m), -1);

export type Tone = "cleared" | "held" | "rejected" | "needs" | "open";
export type Verdict = { word: string; tone: Tone };

export function verdict(d: Decision | null | undefined): Verdict {
  switch (d) {
    case "approve": return { word: "Cleared", tone: "cleared" };
    case "hold": return { word: "Held", tone: "held" };
    case "reject": return { word: "Rejected", tone: "rejected" };
    case "escalate": return { word: "Needs you", tone: "needs" };
    default: return { word: "Unopened", tone: "open" };
  }
}

/** Which outcome lane a decision takes after the Approver. */
export const lane = (d: Decision | null | undefined): "cleared" | "needs" | "held" | null =>
  d === "approve" ? "cleared" : d === "escalate" ? "needs" : d === "hold" || d === "reject" ? "held" : null;

/** Visual state of a step for the 3D scenes and timeline. */
export const stepTone = (s: Step | null | undefined): "pending" | "ok" | "skipped" | "needs" | "rejected" | "held" | "running" => {
  if (!s) return "pending";
  if (s.status === "failed" || s.status === "blocked") return "rejected";
  if (s.status === "escalated") return "needs";
  if (s.status === "retried") return "held";
  if (s.status === "skipped") return "skipped";
  if (s.status === "running") return "running";
  return "ok";
};

const PLACEHOLDER_CLAIMS = new Set(["doc_dedup", "registry", "matcher", "vendor_guard", "validators"]);
const has = (c: Case, ...t: DiscrepancyType[]) => c.discrepancies.some((d) => t.includes(d.type));

/** One sentence for the station under the playhead. */
export function narrate(s: Step, c: Case, v: Vendor | null): string {
  if (s.status === "failed") return `Stopped. ${s.error ?? "Something broke."}`;
  if (s.status === "blocked") return `Blocked. ${s.error ?? "A control said no."}`;
  // Stub stages pass everything through; never let them sound like a real check happened.
  if (s.detail?.stub === true && PLACEHOLDER_CLAIMS.has(s.stage)) return "Placeholder for now. Passed through.";
  const inv = c.invoice;
  switch (s.stage) {
    case "reader":
      if (inv?.flags.includes("embedded_instructions")) return "Hidden instructions found. Ignored.";
      return inv ? `Read ${inv.invoice_no}. ${inv.lines.length} line${inv.lines.length === 1 ? "" : "s"}. No tools.` : "Reading the invoice.";
    case "doc_dedup":
      return has(c, "duplicate_invoice") ? "Seen this before. Possible duplicate." : "Never seen before.";
    case "registry":
      return s.detail.action && s.detail.action !== "new_case" ? `Known case: ${String(s.detail.action).replace(/_/g, " ")}.` : "A new case.";
    case "matcher":
      return c.discrepancies.length ? `${c.discrepancies.length} mismatch${c.discrepancies.length === 1 ? "" : "es"} found.` : "Invoice, PO and receipt agree.";
    case "router":
      return s.status === "skipped" ? "Clean. No playbook needed." : `Playbook: ${c.skill ?? s.skill ?? "none"}.`;
    case "investigator":
      return s.status === "skipped" ? "Nothing to investigate." : "Investigating inside the sandbox.";
    case "vendor_guard":
      if (has(c, "bank_change", "lookalike_domain")) return "Bank details don't match the vendor on file.";
      return v ? "Vendor and bank match the master." : "Vendor checked.";
    case "validators":
      return "Every number recomputed in code.";
    case "approver":
      if (c.decision === "escalate") return "Too risky to sign alone. Sent to a human.";
      if (c.approvals.length) return `Signed by ${c.approvals[c.approvals.length - 1].approver.split("@")[0]}.`;
      return "Waiting for a signature.";
    case "poster":
      return c.journal_entry ? "Booked to the ledger." : "Not booked. Nothing paid.";
    default:
      return `${stageName(s.stage)}: ${s.status}.`;
  }
}

/** The closing line once the run is over. */
export function summary(c: Case): string {
  switch (c.decision) {
    case "approve": return c.journal_entry ? "Cleared and booked." : "Cleared. Waiting to be booked.";
    case "hold": return "Held. Nothing paid until it's fixed.";
    case "reject": return "Rejected. Nothing paid.";
    case "escalate": return "Too risky to decide alone. Your call.";
    default: return "Stopped before a decision.";
  }
}

export const shortName = (name: string) => name.replace(/\s+(Co\.,? Ltd\.?|Ltd\.?|Inc\.?|Sdn Bhd|LLC)$/i, "").trim();

// Callsigns (cursor tags, badges) and which seat each agent fills.
export const CODE: Record<string, string> = {
  reader: "RD", doc_dedup: "DD", registry: "RG", matcher: "MT", router: "RT",
  investigator: "IV", vendor_guard: "VG", validators: "VL", approver: "AP", poster: "PS",
};
export const seat = (id: string) => (id === "vendor_guard" ? "Vendor-master clerk" : "AP specialist");

// Cursor colors by kind. Teal (the brand) = Claude, ink = deterministic code, orange = Factory Droid, violet = you.
export const KIND_COLOR: Record<Kind, string> = { claude: "#0E6E76", code: "#0A1F21", droid: "#E0702A" };
export const HUMAN_COLOR = "#6A4CF5";
