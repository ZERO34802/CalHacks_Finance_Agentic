// Audit: the deterministic eval, performed in front of you. Press "Run the audit" and the Auditor cursor
// works down the report marking every case against the answer key; the tally counts up. Misses stay visible.
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api";
import { go, type LiveProps } from "../App";
import Cursor from "../components/Cursor";
import { compact, pct } from "../format";
import { shortName, stageName, verdict } from "../story";
import type { DashboardMetrics, FailureItem, Scoreboard } from "../types/contracts";

export default function Audit({ tick }: LiveProps) {
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [m, setM] = useState<DashboardMetrics | null>(null);
  const [fails, setFails] = useState<FailureItem[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [shown, setShown] = useState(0);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.scoreboard().then((b) => { setBoard(b); setShown((s) => (running ? s : b.results.length)); }).catch(() => setBoard(null));
    api.metrics().then(setM).catch(() => {});
    api.failures().then(setFails).catch(() => setFails([]));
    Promise.all([api.vendors(), api.cases()]).then(([vs, cs]) => {
      const vn = Object.fromEntries(vs.map((v) => [v.id, shortName(v.name)]));
      setNames(Object.fromEntries(cs.map((c) => [c.id, vn[c.vendor_id] ?? c.vendor_id])));
    }).catch(() => {});
  };
  useEffect(load, [tick]);

  const audit = async () => {
    setBusy(true); setError(null);
    try { const b = await api.runEval(); setBoard(b); setShown(0); setRunning(true); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  useEffect(() => {
    if (!running || !board) return;
    if (shown >= board.results.length) { setRunning(false); load(); return; }
    const t = setTimeout(() => setShown((s) => s + 1), 750);
    return () => clearTimeout(t);
  }, [running, shown, board]);

  const sheet = useRef<HTMLDivElement>(null);
  const [rows, setRows] = useState<{ x: number; y: number }[]>([]);
  useLayoutEffect(() => {
    if (!sheet.current) return;
    const b = sheet.current.getBoundingClientRect();
    setRows([...sheet.current.querySelectorAll<HTMLElement>("[data-mark]")].map((el) => {
      const r = el.getBoundingClientRect();
      return { x: r.left - b.left + 8, y: r.top - b.top + 10 };
    }));
  }, [board?.run_id, board?.results.length]);

  const results = board?.results ?? [];
  const passedSoFar = results.slice(0, shown).filter((r) => r.passed).length;
  const maxExc = Math.max(1, ...(m?.by_vendor.map((v) => v.exceptions) ?? [1]));
  const pen = rows[Math.min(shown, rows.length - 1)];

  return (
    <div className="audit">
      <section className="audit-head">
        <h1 className="stencil">The audit.</h1>
        <button className="go big" onClick={audit} disabled={running || busy}>{busy ? "Grading…" : running ? "Auditing…" : board ? "Run the audit again" : "Run the audit"}</button>
      </section>
      <div className="audit-grid">
        <div ref={sheet} className="report">
          <header><span className="k">Graded against the answer key{board && ` · ${board.run_id}`}</span><span className="k">deterministic</span></header>
          {results.map((r, i) => {
            const e = verdict(r.expected.decision), a = verdict(r.actual_decision);
            const failed = Object.entries(r.checks).filter(([, ok]) => !ok).map(([k]) => k.replace(/^inv_/, "").replace(/_/g, " "));
            const seen = i < shown;
            return (
              <button key={r.case_id} className={`rrow ${seen ? (r.passed ? "pass" : "miss") : "wait"}`} onClick={() => go(`/work/${r.case_id}`)}>
                <span data-mark className="pen">
                  <AnimatePresence>{seen && (
                    <motion.svg viewBox="0 0 28 28" initial="h" animate="v">
                      {r.passed ? <motion.path d="M5 15 L11 21 L23 7" variants={{ h: { pathLength: 0 }, v: { pathLength: 1 } }} transition={{ duration: 0.35 }} />
                        : <><motion.path d="M6 6 L22 22" variants={{ h: { pathLength: 0 }, v: { pathLength: 1 } }} transition={{ duration: 0.2 }} />
                          <motion.path d="M22 6 L6 22" variants={{ h: { pathLength: 0 }, v: { pathLength: 1 } }} transition={{ duration: 0.2, delay: 0.15 }} /></>}
                    </motion.svg>
                  )}</AnimatePresence>
                </span>
                <span className="rname"><b>{names[r.case_id] ?? r.case_id}</b><span className="mono">{r.case_id}</span></span>
                <span className="rcmp"><span className={`tiny-stamp ${e.tone}`}>{e.word}</span><i>expected</i></span>
                <span className="rcmp"><span className={`tiny-stamp ${a.tone}`}>{a.word}</span><i>got</i></span>
                <span className="rwhy mono">{seen && !r.passed ? failed.join(" · ") : ""}</span>
              </button>
            );
          })}
          {!board && <p className="dim">No audit yet. Run one.</p>}
          {running && pen && <Cursor x={pen.x} y={pen.y} color="#D2462F" name="Auditor" kind="answer key" />}
        </div>

        <div className="tally">
          <div className="score"><span className="stencil n">{board ? passedSoFar : "—"}</span><span className="stencil d">/{board?.total ?? "—"}</span></div>
          <span className="k">cases match the answer key</span>
          <div className="trio">
            <div><b>{board ? pct(board.catch_rate) : "—"}</b><span>exceptions caught</span></div>
            <div><b>{board ? pct(board.false_alarm_rate) : "—"}</b><span>false alarms</span></div>
            <div className={board && board.invariant_pass_rate < 1 ? "bad" : "good"}><b>{board ? pct(board.invariant_pass_rate) : "—"}</b><span>controls held</span></div>
          </div>
          <div className="money">
            <div><b className="stencil">${m ? compact(m.dollars_caught_usd) : "—"}</b><span>held back before payment¹</span></div>
            <div><b className="stencil">{m?.hours_saved_estimate ?? "—"}h</b><span>manual work saved²</span></div>
          </div>
          <span className="k">Exceptions per vendor</span>
          {m?.by_vendor.map((v) => (
            <div key={v.vendor_id} className="vb"><span>{shortName(v.vendor_name)}</span>
              <span className="track"><motion.i initial={{ width: 0 }} animate={{ width: `${(v.exceptions / maxExc) * 100}%` }} /></span>
              <span className="mono">{v.exceptions}/{v.cases}</span></div>
          ))}
          <span className="k gap">Incidents</span>
          {fails.length === 0 ? <p className="dim">No failed or blocked steps.</p> : fails.map((f) => (
            <button key={f.step_id} className="inc" onClick={() => go(`/work/${f.case_id}`)}>{stageName(f.stage)} {f.status} <span className="mono">{f.case_id}</span></button>
          ))}
          {m && <p className="fine">¹ {m.assumptions[1]} · ² {m.assumptions[2]} · {m.assumptions[0]}</p>}
          {error && <p className="err">{error}</p>}
        </div>
      </div>
    </div>
  );
}
