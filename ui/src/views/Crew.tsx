// Crew: the ten hires, as staff ID badges on lanyards. Brush past to swing them; click to flip to the access
// card (what it can do, what it can NEVER do, how it's been doing). Stats come from /dashboard/stages.
import { motion, useSpring } from "framer-motion";
import { useEffect, useState } from "react";
import { api } from "../api";
import { go, type LiveProps } from "../App";
import Avatar from "../components/Avatar";
import { AGENTS, CODE, KIND_LABEL, seat, type Agent } from "../story";
import type { Case, StageStat } from "../types/contracts";

export default function Crew({ tick, active }: LiveProps) {
  const [stats, setStats] = useState<StageStat[]>([]);
  const [flipped, setFlipped] = useState<Set<string>>(new Set());
  const [cases, setCases] = useState<Case[]>([]);
  useEffect(() => { api.stages().then(setStats).catch(() => setStats([])); api.cases().then(setCases).catch(() => {}); }, [tick]);
  const flip = (id: string) => setFlipped((f) => { const n = new Set(f); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const human = cases.filter((c) => c.decision === "escalate" || c.status === "awaiting_approval").length;
  const runs = cases.filter((c) => c.decision).length;

  return (
    <div className="crew-room">
      <section className="crew-head">
        <h1 className="stencil">Ten hires.<br /><span>Two seats.</span></h1>
        <p className="lede">AP specialist and vendor-master clerk. Each badge is one agent: what it replaced, what it may touch, and what it can never do. <b>Click a badge.</b></p>
        <div className="crew-sum mono"><span><b>{runs}</b> cases worked</span><span><b>{human}</b> handed to a human</span>
          <button onClick={() => go("/work")}>watch them work ›</button></div>
      </section>
      <div className="rail-bar" />
      <section className="badges">
        {AGENTS.map((a, i) => (
          <Badge key={a.id} a={a} i={i} stat={stats.find((s) => s.stage === a.id)} flipped={flipped.has(a.id)} onFlip={() => flip(a.id)} working={active === a.id} />
        ))}
      </section>
    </div>
  );
}

function Badge({ a, i, stat, flipped, onFlip, working }: { a: Agent; i: number; stat?: StageStat; flipped: boolean; onFlip: () => void; working: boolean }) {
  const swing = useSpring(0, { stiffness: 60, damping: 6, mass: 0.8 });
  const push = (dx: number) => { swing.set(Math.max(-14, Math.min(14, dx * 1.6))); setTimeout(() => swing.set(0), 90); };
  return (
    <motion.div className="hang" style={{ rotate: swing }} onPointerMove={(e) => push(e.movementX)}
      initial={{ y: -120, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ type: "spring", stiffness: 90, damping: 12, delay: 0.05 * i }}>
      <svg className="lanyard" viewBox="0 0 40 70" aria-hidden><path d="M8 0 L20 62 M32 0 L20 62" /><rect x="14" y="58" width="12" height="10" rx="2" /></svg>
      <motion.button className={`badge ${working ? "working" : ""}`} onClick={onFlip} animate={{ rotateY: flipped ? 180 : 0 }}
        transition={{ type: "spring", stiffness: 140, damping: 16 }} aria-label={`${a.name} badge`}>
        <div className="face front">
          <div className="b-top"><span>RECON-AI</span><span>HELIX SILICON</span></div>
          <div className="b-photo"><Avatar id={a.id} kind={a.kind} size={64} /></div>
          <span className="b-name stencil">{a.name}</span>
          <span className="b-seat">{seat(a.id)}</span>
          <span className={`b-kind ${a.kind}`}>{KIND_LABEL[a.kind]} · {a.engine.split(" · ")[1] ?? a.engine}</span>
          <div className="b-rep"><span className="k">Replaced</span>{a.replaces}</div>
          <div className="b-foot"><span className="mono">RA-{String(i + 1).padStart(2, "0")} · {CODE[a.id]}</span><span className="barcode" /></div>
        </div>
        <div className="face back">
          <div className="b-top"><span>ACCESS</span><span>{CODE[a.id]}</span></div>
          <div className="acc">
            <span className="k">Granted</span>{a.can.map((x) => <p key={x} className="yes">{x}</p>)}
            <span className="k">Never</span>{a.cannot.map((x) => <p key={x} className="no">{x}</p>)}
          </div>
          <div className="b-stats">
            <div><b>{stat?.runs ?? 0}</b><span>runs</span></div><div><b>{stat?.ok ?? 0}</b><span>ok</span></div>
            <div><b>{stat?.skipped ?? 0}</b><span>skipped</span></div><div className={stat?.flagged ? "flag" : ""}><b>{stat?.flagged ?? 0}</b><span>to human</span></div>
          </div>
        </div>
      </motion.button>
    </motion.div>
  );
}
