// Turns a case's real trace into choreography: one beat per agent, each a list of cursor actions on the
// documents. Marks are honest: "diff" only where the backend recorded a discrepancy, "unchecked" for stub
// stages (they pass everything through), "ok" only for a real stage that found nothing.
import { agent, narrate, stations, type Agent } from "./story";
import type { Case, DiscrepancyType, Step, Vendor } from "./types/contracts";

export type Tone = "teal" | "red" | "grey" | "violet";
export type Glyph = "ok" | "diff" | "unchecked";
export type Action =
  | { kind: "hl"; at: string; tone: Tone }
  | { kind: "link"; from: string; at: string; tone: Tone }
  | { kind: "mark"; at: string; glyph: Glyph }
  | { kind: "chip"; at: string; text: string; tone: Tone }
  | { kind: "note"; at: string; text: string }
  | { kind: "stamp"; at: string; text: string; tone: Tone; by: string }
  | { kind: "write"; at: string; row: number }
  | { kind: "point"; at: string };
export type Beat = { stage: string; agent: Agent; step: Step; say: string; actions: Action[]; handoff: boolean; stub: boolean };

const glyphTone = (g: Glyph): Tone => (g === "diff" ? "red" : g === "unchecked" ? "grey" : "teal");

export function script(c: Case, vendor: Vendor | null, steps: Step[]): Beat[] {
  const has = (...t: DiscrepancyType[]) => c.discrepancies.some((d) => t.includes(d.type));
  const inv = c.invoice;
  const skus = [...new Set([...(inv?.lines.map((l) => l.sku) ?? []), ...(c.po?.lines.map((l) => l.sku) ?? [])])];
  const beats: Beat[] = [];

  for (const st of stations(steps)) {
    const s = st.step;
    const a = agent(st.id);
    if (!s || !a) continue;
    const stub = s.detail?.stub === true;
    const check = (flagged: boolean): Glyph => (flagged ? "diff" : stub ? "unchecked" : "ok");
    const acts: Action[] = [];
    let handoff = false;

    switch (st.id) {
      case "reader":
        acts.push({ kind: "hl", at: "inv.vendor", tone: "teal" }, { kind: "hl", at: "inv.no", tone: "teal" });
        inv?.lines.forEach((l) => acts.push({ kind: "hl", at: `inv.line.${l.sku}`, tone: "teal" }));
        acts.push({ kind: "hl", at: "inv.total", tone: "teal" }, { kind: "hl", at: "inv.bank", tone: "teal" });
        if (inv?.flags.includes("embedded_instructions")) acts.push({ kind: "hl", at: "inv.bank", tone: "red" });
        break;
      case "doc_dedup": {
        const doc = c.documents.find((d) => d.id === inv?.doc_id);
        acts.push({ kind: "chip", at: "inv.print", text: `sha ${doc?.sha256.slice(0, 10) ?? "—"}`, tone: "teal" },
          { kind: "mark", at: "inv.print", glyph: check(has("duplicate_invoice")) });
        break;
      }
      case "registry":
        acts.push({ kind: "chip", at: "inv.case", text: s.detail?.action && s.detail.action !== "new_case" ? String(s.detail.action).replace(/_/g, " ") : "new case", tone: "teal" });
        break;
      case "matcher":
        for (const sku of skus) {
          const g = check(c.discrepancies.some((d) => d.sku === sku));
          acts.push({ kind: "link", from: `inv.line.${sku}`, at: `po.line.${sku}`, tone: glyphTone(g) },
            { kind: "link", from: `po.line.${sku}`, at: `rc.line.${sku}`, tone: glyphTone(g) },
            { kind: "mark", at: `rc.line.${sku}`, glyph: g });
        }
        break;
      case "router":
        acts.push({ kind: "chip", at: "sb.playbook", text: c.skill ? `playbook · ${c.skill}` : "no playbook needed", tone: c.skill ? "teal" : "grey" });
        break;
      case "investigator":
        if (s.status === "skipped") acts.push({ kind: "point", at: "sb.idle" });
        else acts.push({ kind: "point", at: "sb.note" }, { kind: "note", at: "sb.note", text: c.proposal?.explanation ?? "proposal" }, { kind: "point", at: "sb.slot" });
        break;
      case "vendor_guard": {
        const gb = check(has("bank_change")), gd = check(has("lookalike_domain"));
        acts.push({ kind: "link", from: "inv.bank", at: "vm.bank", tone: glyphTone(gb) }, { kind: "mark", at: "vm.bank", glyph: gb },
          { kind: "link", from: "inv.sender", at: "vm.domain", tone: glyphTone(gd) }, { kind: "mark", at: "vm.domain", glyph: gd });
        break;
      }
      case "validators":
        acts.push({ kind: "hl", at: "inv.total", tone: stub ? "grey" : "teal" }, { kind: "mark", at: "inv.total", glyph: check(false) });
        break;
      case "approver": {
        acts.push({ kind: "point", at: "sg.box" });
        const signed = c.approvals.find((x) => x.decision === "approved");
        if (c.status === "escalated" || c.status === "awaiting_approval" || c.decision === "escalate") handoff = true;
        else if (signed) acts.push({ kind: "stamp", at: "sg.box", text: "Approved", tone: "teal", by: signed.approver.split("@")[0] });
        break;
      }
      case "poster":
        if (c.journal_entry) c.journal_entry.postings.forEach((_, i) => acts.push({ kind: "write", at: `lg.row.${i}`, row: i }));
        else acts.push({ kind: "chip", at: "lg.box", text: "nothing booked · nothing paid", tone: "grey" });
        break;
      default:
        acts.push({ kind: "point", at: "inv.vendor" });
    }
    if (acts.length === 0) acts.push({ kind: "point", at: "inv.vendor" });
    beats.push({ stage: st.id, agent: a, step: s, say: narrate(s, c, vendor), actions: acts, handoff, stub });
  }
  return beats;
}

/** Everything visible on the documents at (beat, action): all earlier beats, plus this beat up to `sub`. */
export function applied(beats: Beat[], head: number, sub: number) {
  const out = { hl: new Map<string, Tone>(), links: [] as { from: string; at: string; tone: Tone; key: string }[],
    marks: new Map<string, Glyph>(), chips: new Map<string, { text: string; tone: Tone }>(), notes: new Map<string, string>(),
    stamps: [] as { at: string; text: string; tone: Tone; by: string }[], rows: new Set<number>() };
  beats.forEach((b, i) => {
    if (i > head) return;
    b.actions.forEach((a, j) => {
      if (i === head && j > sub) return;
      if (a.kind === "hl") out.hl.set(a.at, a.tone);
      if (a.kind === "link") out.links.push({ from: a.from, at: a.at, tone: a.tone, key: `${i}.${j}` });
      if (a.kind === "mark") out.marks.set(a.at, a.glyph);
      if (a.kind === "chip") out.chips.set(a.at, { text: a.text, tone: a.tone });
      if (a.kind === "note") out.notes.set(a.at, a.text);
      if (a.kind === "stamp") out.stamps.push(a);
      if (a.kind === "write") out.rows.add(a.row);
    });
  });
  return out;
}
