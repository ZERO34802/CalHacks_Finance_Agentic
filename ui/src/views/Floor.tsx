// Floor: what's on the floor, who's working, what needs you. Real miniature invoices sorted by outcome;
// the crew's cursors drift between them. During a live run, the working agent's cursor sits on that case.
import { motion } from "framer-motion";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api";
import { go, type LiveProps } from "../App";
import Cursor from "../components/Cursor";
import { compact, date, money, pct } from "../format";
import { agent, AGENTS, KIND_COLOR, shortName, verdict } from "../story";
import type { BusinessMetrics, Case, Scoreboard, Vendor } from "../types/contracts";

const ZONES = [
  { id: "needs", label: "Needs you", match: (c: Case) => c.decision === "escalate" },
  { id: "held", label: "Held · rejected", match: (c: Case) => c.decision === "hold" || c.decision === "reject" },
  { id: "cleared", label: "Cleared", match: (c: Case) => c.decision === "approve" },
];
const WANDERERS = ["reader", "matcher", "vendor_guard"];

export default function Floor({ tick, lastEvent }: LiveProps) {
  const [cases, setCases] = useState<Case[]>([]);
  const [fixtures, setFixtures] = useState<Case[]>([]);
  const [vendors, setVendors] = useState<Record<string, Vendor>>({});
  const [m, setM] = useState<BusinessMetrics | null>(null);
  const [board, setBoard] = useState<Scoreboard | null>(null);
  useEffect(() => {
    api.cases().then(setCases).catch(() => {});
    api.metrics().then(setM).catch(() => {});
    api.scoreboard().then(setBoard).catch(() => setBoard(null));
  }, [tick]);
  useEffect(() => {
    api.fixtures().then(setFixtures).catch(() => {});
    api.vendors().then((v) => setVendors(Object.fromEntries(v.map((x) => [x.id, x])))).catch(() => {});
  }, []);

  const name = (c: Case) => shortName(vendors[c.vendor_id]?.name ?? c.vendor_id);
  const decided = cases.filter((c) => c.decision);
  const needs = decided.filter((c) => c.decision === "escalate");
  const handled = decided.length - needs.length;
  const known = new Set(cases.map((c) => c.id));
  const incoming = fixtures.filter((f) => !known.has(f.id));

  // Cursor targets: positions of the mini docs on the floor.
  const floor = useRef<HTMLDivElement>(null);
  const [spots, setSpots] = useState<Record<string, { x: number; y: number }>>({});
  useLayoutEffect(() => {
    const measure = () => {
      if (!floor.current) return;
      const b = floor.current.getBoundingClientRect();
      const out: Record<string, { x: number; y: number }> = {};
      floor.current.querySelectorAll<HTMLElement>("[data-case]").forEach((el) => {
        const r = el.getBoundingClientRect();
        out[el.dataset.case!] = { x: r.left - b.left + r.width * 0.62, y: r.top - b.top + r.height * 0.4 };
      });
      setSpots(out);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [cases.length, incoming.length]);

  const ids = Object.keys(spots);
  const [beat, setBeat] = useState(0);
  useEffect(() => { const t = setInterval(() => setBeat((b) => b + 1), 2600); return () => clearInterval(t); }, []);
  const live = lastEvent?.step ? { stage: lastEvent.step.stage, caseId: lastEvent.step.case_id } : null;

  return (
    <div className="floor">
      <section className="statement">
        <motion.h1 className="stencil" initial="h" animate="v" variants={{ v: { transition: { staggerChildren: 0.09 } } }}>
          {[
            { n: cases.length + incoming.length, t: "invoices on the floor", to: null },
            { n: handled, t: "handled by the crew", to: "/crew" },
            { n: needs.length, t: "need you", to: "/turn", human: true },
          ].map((l) => (
            <motion.button key={l.t} className={`sline ${l.human ? "human" : ""}`} disabled={!l.to} onClick={() => l.to && go(l.to)}
              variants={{ h: { opacity: 0, y: 24 }, v: { opacity: 1, y: 0 } }}>
              <span className="blk">{l.n}</span>{l.t}{l.to && <em>›››</em>}
            </motion.button>
          ))}
        </motion.h1>
        <div className="feed-in">
          <span className="k">Drop an invoice in</span>
          {(incoming.length ? incoming : fixtures).map((f) => (
            <button key={f.id} onClick={() => go(`/work/${f.id}/play`)}>
              <span>{name(f)}</span><span className="mono">{compact(f.invoice?.total)} {f.invoice?.currency}</span><b>run ›</b>
            </button>
          ))}
        </div>
      </section>

      <section ref={floor} className="desk">
        {ZONES.map((z) => {
          const here = cases.filter(z.match);
          return (
            <div key={z.id} className={`zone ${z.id}`}>
              <div className="zone-h"><span className="stencil">{here.length}</span><span className="k">{z.label}</span></div>
              <div className="pile">
                {here.map((c, i) => (
                  <motion.button key={c.id} data-case={c.id} className="mini" onClick={() => go(`/work/${c.id}`)}
                    initial={{ opacity: 0, y: 30, rotate: (i % 2 ? 2 : -2) }} animate={{ opacity: 1, y: 0, rotate: (i % 3) - 1 }}
                    whileHover={{ y: -8, rotate: 0, scale: 1.03 }} transition={{ type: "spring", stiffness: 200, damping: 18, delay: i * 0.05 }}>
                    <span className="mini-h"><b>{name(c)}</b><span className="mono">{c.invoice?.invoice_no}</span></span>
                    {c.invoice?.lines.slice(0, 3).map((l) => <span key={l.line_no} className="mini-l"><i />{l.sku}<em className="mono">{money(l.amount)}</em></span>)}
                    <span className="mini-t mono">{money(c.invoice?.total, c.invoice?.currency)}</span>
                    <span className={`mini-stamp ${verdict(c.decision).tone}`}>{verdict(c.decision).word}</span>
                    <span className="mini-due mono">due {date(c.invoice?.due_date)}</span>
                  </motion.button>
                ))}
                {here.length === 0 && <span className="pile-empty">nothing here</span>}
              </div>
            </div>
          );
        })}
        {/* the crew, drifting between cases; a live step pins its agent to the real case */}
        {ids.length > 0 && WANDERERS.map((w, i) => {
          const isLive = live && live.stage === w && spots[live.caseId];
          const spot = isLive ? spots[live!.caseId] : spots[ids[(beat + i * 2) % ids.length]];
          const a = agent(w)!;
          return <Cursor key={w} x={spot.x + i * 14} y={spot.y + i * 18} color={KIND_COLOR[a.kind]} name={a.name} />;
        })}
        {live && !WANDERERS.includes(live.stage) && spots[live.caseId] && (() => {
          const a = agent(live.stage) ?? AGENTS[0];
          return <Cursor x={spots[live.caseId].x} y={spots[live.caseId].y - 30} color={KIND_COLOR[a.kind]} name={a.name} say="working" />;
        })()}
      </section>

      <p className="ledgerline">
        Held back <b>{m ? `$${compact(m.dollars_caught_usd)}` : "—"}</b> before payment<sup>1</sup>
        <span>·</span><b>{m?.hours_saved_estimate ?? "—"} h</b> of manual work saved<sup>2</sup>
        <span>·</span>controls held <b>{board ? pct(board.invariant_pass_rate) : "—"}</b>
        <span>·</span><button onClick={() => go("/audit")}>answer key <b>{board ? `${board.passed}/${board.total}` : "—"}</b> ›</button>
      </p>
      <p className="fine">1 discrepancy deltas when known, else the full invoice, USD at simulated FX · 2 estimate: 15 min per clean case, 90 per exception</p>
    </div>
  );
}
