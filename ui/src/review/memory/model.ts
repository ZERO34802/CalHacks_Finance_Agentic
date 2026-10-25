// Memory page model: source -> color family, time helpers, "as of" state, word diff. Display only.
import type { MemorySlot, MemoryVersion } from "../../types/contracts";

export type Shape = "circle" | "square" | "diamond" | "triangle";
export type Family = "fact" | "learned" | "human" | "seed";

// Three categorical hues (validated all-pairs on #ffffff: worst CVD dE 9.2, normal-vision dE 24.0) plus a
// deliberate neutral for seeded lines. Each family also has its own shape (secondary encoding).
export const FAMILY: Record<Family, { label: string; color: string; shape: Shape }> = {
  fact: { label: "Facts", color: "#2a78d6", shape: "circle" },
  learned: { label: "Learned from cases", color: "#1baf7a", shape: "square" },
  human: { label: "Human decisions", color: "#eb6834", shape: "diamond" },
  seed: { label: "Seeded", color: "#52514e", shape: "triangle" },
};

export const SOURCES: Record<string, { label: string; family: Family; hint: string }> = {
  system_of_record: { label: "System of record", family: "fact", hint: "ERP / vendor master, read fresh" },
  computed: { label: "Computed from cases", family: "learned", hint: "counted by code from case history" },
  outcome: { label: "Follow-up outcome", family: "learned", hint: "a verified result of a follow-up" },
  controller: { label: "Controller decision", family: "human", hint: "controller-approved rule" },
  approver: { label: "Approver decision", family: "human", hint: "AP approver decision" },
  seed: { label: "Seeded at setup", family: "seed", hint: "bootstrapped from last year's AP" },
};
export const sourceOf = (s: string) => SOURCES[s] ?? { label: s.replace(/_/g, " "), family: "seed" as Family, hint: "" };
export const familyOf = (s: string) => FAMILY[sourceOf(s).family];

export const ts = (s: string) => Date.parse(s.length <= 10 ? `${s}T00:00:00` : s);
export const dayStart = (t: number) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };
export const fmtDay = (t: number) => new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/** The version of a slot ReconAI believed at time t (null if not yet known or forgotten). */
export function versionAt(slot: MemorySlot, t: number): MemoryVersion | null {
  let v: MemoryVersion | null = null;
  for (const x of slot.versions) if (ts(x.valid_from) <= t) v = x;
  return v && v.change !== "forgotten" ? v : null;
}

/** Distinct days on which memory changed, oldest first. */
export const changeDays = (slots: MemorySlot[]) =>
  [...new Set(slots.flatMap((s) => s.versions.map((v) => dayStart(ts(v.valid_from)))))].sort((a, b) => a - b);

export type DiffPart = { t: string; op: "same" | "add" | "del" };

/** Word-level diff (LCS); memory lines are short so O(n*m) is fine. */
export function wordDiff(a: string, b: string): DiffPart[] {
  const x = a.split(/(\s+)/).filter(Boolean), y = b.split(/(\s+)/).filter(Boolean);
  const n = x.length, m = y.length;
  const L: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: DiffPart[] = [];
  const push = (t: string, op: DiffPart["op"]) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.t += t; else out.push({ t, op });
  };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { push(x[i], "same"); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) push(x[i++], "del");
    else push(y[j++], "add");
  }
  while (i < n) push(x[i++], "del");
  while (j < m) push(y[j++], "add");
  return out;
}
