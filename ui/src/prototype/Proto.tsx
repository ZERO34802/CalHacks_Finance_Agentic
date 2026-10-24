// PROTOTYPE. The product in one flow: an invoice arrives (trigger) -> agents reconcile it automatically ->
// the reviewer sees what they found and approves -> payment goes out. The spine on top never changes;
// one invoice token rides it. Stages 1-2 run by themselves, stage 3 waits for a human, stage 4 follows.
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import Avatar from "../components/Avatar";
import type { Kind } from "../story";
import { Bank, Envelope, Shield } from "./icons";
import { SCENARIOS } from "./scenarios";
import Paid from "./stages/Paid";
import Received from "./stages/Received";
import Reconcile from "./stages/Reconcile";
import Review from "./stages/Review";

export type Decision = "paid" | "partial" | "held" | "rejected";
const STAGES = [
  { label: "Received", who: "automatic", icon: <Envelope /> },
  { label: "Reconciled", who: "agents", icon: <ThreeWay /> },
  { label: "Reviewed", who: "you", icon: <span className="you-dot">YOU</span> },
  { label: "Paid", who: "automatic", icon: <Bank size={22} /> },
];
// Who works in each stage (pipeline order), and which beat each one owns.
const CREW: { id: string; name: string; kind: Kind; stage: number; beat: number }[] = [
  { id: "reader", name: "Reader", kind: "claude", stage: 0, beat: 2 },
  { id: "doc_dedup", name: "Dedup", kind: "code", stage: 1, beat: 1 },
  { id: "matcher", name: "Matcher", kind: "code", stage: 1, beat: 2 },
  { id: "vendor_guard", name: "Vendor Guard", kind: "code", stage: 1, beat: 4 },
  { id: "investigator", name: "Investigator", kind: "droid", stage: 1, beat: 6 },
  { id: "validators", name: "Validators", kind: "code", stage: 1, beat: 6 },
  { id: "approver", name: "Approver", kind: "claude", stage: 2, beat: 0 },
  { id: "poster", name: "Poster", kind: "code", stage: 3, beat: 1 },
];
const TICK = [950, 1150, 0, 850];
const END = [6, 8, 0, 6];

export default function Proto() {
  const [si, setSi] = useState(1);              // Formosa arrives first: the richest story
  const [stage, setStage] = useState(0);
  const [t, setT] = useState(0);
  const [reached, setReached] = useState(0);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [role, setRole] = useState<"approver" | "controller">("approver");
  const [speed, setSpeed] = useState(1);
  const s = SCENARIOS[si];

  // automatic stages advance on their own; review waits for the human
  useEffect(() => {
    if (stage === 2) return;
    if (t >= END[stage]) {
      if (stage < 2) { const n = stage + 1; setStage(n); setT(0); setReached((r) => Math.max(r, n)); }
      return;
    }
    const id = setTimeout(() => setT((x) => x + 1), TICK[stage] / speed);
    return () => clearTimeout(id);
  }, [stage, t, speed]);

  const start = (i: number) => { setSi(i); setStage(0); setT(0); setReached(0); setDecision(null); setRole("approver"); };
  const decide = (d: Decision) => { setDecision(d); setStage(3); setT(0); setReached(3); };
  const next = () => start((si + 1) % SCENARIOS.length);
  const visit = (i: number) => { if (i <= reached) { setStage(i); setT(i === 2 ? 0 : END[i]); } };

  return (
    <div className="proto">
      <header className="p-top">
        <a className="logo" href="/"><span>RECON</span><i>-</i><span>AI</span></a>
        <Spine stage={stage} reached={reached} onVisit={visit} decision={decision} vendor={s.short} color={s.color} />
        <div className="p-tools">
          <span className="proto-tag">Prototype · scripted from fixtures</span>
          <button onClick={() => setSpeed((v) => (v === 1 ? 2 : 1))}>{speed}×</button>
        </div>
      </header>

      <main className="p-stage">
        <AnimatePresence mode="wait">
          <motion.section key={`${s.id}-${stage}`} className="p-scene" initial={{ opacity: 0, x: 60 }} animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -60 }} transition={{ duration: 0.45, ease: [0.2, 0.7, 0.2, 1] }}>
            {stage === 0 && <Received s={s} t={t} current={si} onPick={start} />}
            {stage === 1 && <Reconcile s={s} t={t} />}
            {stage === 2 && <Review s={s} role={role} setRole={setRole} onDecide={decide} />}
            {stage === 3 && decision && <Paid s={s} t={t} decision={decision} onNext={next} />}
          </motion.section>
        </AnimatePresence>
      </main>

      <footer className="p-crew">
        <span className="p-crew-l"><Shield /> {stage === 2 ? "Your decision. Nothing moves without it." : stage === 3 ? "Code posts and pays. No agent can move money." : "Agents working. No human needed yet."}</span>
        <div className="p-crew-r">
          {CREW.map((c) => {
            const done = c.stage < stage || (c.stage === stage && t > c.beat);
            const state = done ? "done" : c.stage === stage && t >= c.beat - 1 ? "now" : "later";
            return (
              <span key={c.id} className={`pc ${state} ${c.stage === stage ? "this" : ""}`}>
                <Avatar id={c.id} kind={c.kind} size={22} on={state === "now"} />{c.name}
              </span>
            );
          })}
        </div>
      </footer>
    </div>
  );
}

function Spine({ stage, reached, onVisit, decision, vendor, color }: {
  stage: number; reached: number; onVisit: (i: number) => void; decision: Decision | null; vendor: string; color: string;
}) {
  const blocked = stage === 3 && (decision === "held" || decision === "rejected");
  return (
    <nav className="spine" aria-label="Invoice journey">
      <div className="sp-track"><motion.i animate={{ width: `${(stage / 3) * 100}%` }} transition={{ type: "spring", stiffness: 80, damping: 18 }}
        className={blocked ? "blocked" : ""} /></div>
      {STAGES.map((st, i) => (
        <button key={st.label} className={`sp-node ${i === stage ? "here" : ""} ${i <= reached ? "reached" : ""} ${st.who === "you" ? "human" : ""}
          ${blocked && i === 3 ? "blocked" : ""}`} style={{ left: `${(i / 3) * 100}%` }} onClick={() => onVisit(i)} disabled={i > reached}>
          <span className="sp-ic">{st.icon}</span>
          <span className="sp-l"><b>{blocked && i === 3 ? (decision === "held" ? "Held" : "Rejected") : st.label}</b><em>{st.who}</em></span>
        </button>
      ))}
      <motion.span className="sp-token" animate={{ left: `${(stage / 3) * 100}%` }} transition={{ type: "spring", stiffness: 90, damping: 16 }}
        style={{ ["--vc" as string]: color }}><i />{vendor}</motion.span>
    </nav>
  );
}

function ThreeWay() {
  return <svg width="24" height="22" viewBox="0 0 24 22" className="ic"><circle cx="8" cy="8" r="6" /><circle cx="16" cy="8" r="6" /><circle cx="12" cy="15" r="6" /></svg>;
}
