// Workspace: watch the agents work one case like teammates in a shared doc. Their cursors move over the real
// documents, highlight what they extract, draw the 3-way match, and say what they found. When a human is
// needed the room dims and your own cursor becomes the stamp. Live runs stream over WS.
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { go, type LiveProps } from "../App";
import Avatar from "../components/Avatar";
import Cursor from "../components/Cursor";
import Docs, { H, W } from "../components/Docs";
import Drawer from "../components/Drawer";
import { compact, date } from "../format";
import { applied, script, type Tone } from "../script";
import { HUMAN_COLOR, KIND_COLOR, KIND_LABEL, shortName, stepTone, summary, verdict } from "../story";
import type { ApprovalDecision, Case, Role, Step, Vendor } from "../types/contracts";

const ACTION_MS = 620, BEAT_MS = 900;
const TONE: Record<Tone, string> = { teal: "#0E6E76", red: "#D2462F", grey: "#9AA6A4", violet: HUMAN_COLOR };
const SIGNERS: { approver: string; role: Role; label: string }[] = [
  { approver: "ap.lead@helix.example", role: "approver", label: "AP lead" },
  { approver: "m.chen@helix.example", role: "controller", label: "Controller" },
];
type Rect = { x: number; y: number; w: number; h: number };

export default function Workspace({ lastEvent, route }: LiveProps) {
  const id = route[1];
  const autoplay = route[2] === "play";
  const [cases, setCases] = useState<Case[]>([]);
  const [fixtures, setFixtures] = useState<Case[]>([]);
  const [vendors, setVendors] = useState<Record<string, Vendor>>({});
  const [c, setC] = useState<Case | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [head, setHead] = useState(-1);
  const [sub, setSub] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [running, setRunning] = useState(false);
  const [turn, setTurn] = useState(false);
  const [human, setHuman] = useState<{ d: ApprovalDecision; x: number; y: number; by: string } | null>(null);
  const [mode, setMode] = useState<ApprovalDecision>("approved");
  const [signer, setSigner] = useState(0);
  const [source, setSource] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const vendor = c ? vendors[c.vendor_id] ?? null : null;
  const beats = useMemo(() => (c ? script(c, vendor, steps) : []), [c, vendor, steps]);
  const beat = beats[head];
  const lastSub = beat ? beat.actions.length - 1 : 0;
  const done = !playing && !running && !turn && beats.length > 0 && head === beats.length - 1 && sub >= lastSub;
  const fx = useMemo(() => applied(beats, head, sub), [beats, head, sub]);
  const fixture = fixtures.find((f) => f.id === id) ?? null;

  useEffect(() => {
    api.cases().then(setCases).catch(() => {});
    api.fixtures().then(setFixtures).catch(() => {});
    api.vendors().then((v) => setVendors(Object.fromEntries(v.map((x) => [x.id, x])))).catch(() => {});
  }, []);
  useEffect(() => {
    if (!id && cases.length) go(`/work/${cases.find((x) => x.decision === "escalate")?.id ?? cases[0].id}`);
  }, [id, cases]);

  const reset = () => { setHead(-1); setSub(0); setTurn(false); setHuman(null); };
  const run = async (f: Case) => {
    setError(null); setC(f); setSteps([]); reset(); setRunning(true); setPlaying(true);
    try { const d = await api.runCase(f); setC(d.case); setSteps(d.steps); } catch (e) { setError(String(e)); } finally { setRunning(false); }
  };
  useEffect(() => {
    if (!id || autoplay) return;
    api.case(id).then((d) => { setC(d.case); setSteps(d.steps); reset(); setPlaying(true); }).catch(() => setC(null));
  }, [id, autoplay]);
  useEffect(() => { if (autoplay && fixture && !started.current) { started.current = true; run(fixture); } }, [autoplay, fixture]);
  useEffect(() => {
    const s = lastEvent?.step;
    if (!s || s.case_id !== id || !running) return;
    setSteps((p) => (p.length && p[0].run_id !== s.run_id ? p : [...p.filter((x) => x.id !== s.id), s].sort((a, b) => a.seq - b.seq)));
  }, [lastEvent, id, running]);

  // Playback: action by action, beat by beat; stop and hand over when a human is needed.
  useEffect(() => {
    if (!playing) return;
    let t: ReturnType<typeof setTimeout>;
    if (head < 0) t = setTimeout(() => { if (beats.length) { setHead(0); setSub(0); } }, 700);
    else if (beat && sub < lastSub) t = setTimeout(() => setSub((s) => s + 1), ACTION_MS);
    else if (beat?.handoff && !human) { setPlaying(false); setTurn(true); }
    else if (head < beats.length - 1) t = setTimeout(() => { setHead((h) => h + 1); setSub(0); }, BEAT_MS);
    else if (!running) setPlaying(false);
    return () => clearTimeout(t);
  }, [playing, head, sub, beats.length, lastSub, running, human, beat]);

  const jump = (i: number) => { setPlaying(false); setTurn(false); setHead(i); setSub(beats[i].actions.length - 1); };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "ArrowRight" && head < beats.length - 1) jump(head + 1);
      if (e.key === "ArrowLeft" && head > 0) jump(head - 1);
      if (e.key === " ") { e.preventDefault(); if (done) { reset(); setPlaying(true); } else if (!turn) setPlaying((p) => !p); }
      if (turn) { const k = e.key.toLowerCase(); if (k === "a") stamp("approved"); if (k === "r") stamp("rejected"); if (k === "q") stamp("ask"); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  // Fit the fixed canvas to the available width; measure every anchor in canvas units.
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [rects, setRects] = useState<Record<string, Rect>>({});
  useLayoutEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setScale(Math.min(1.1, e.contentRect.width / W)));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, [c?.id]);
  const measure = useCallback(() => {
    const root = canvas.current;
    if (!root) return;
    const base = root.getBoundingClientRect();
    const out: Record<string, Rect> = {};
    root.querySelectorAll<HTMLElement>("[data-a]").forEach((el) => {
      const r = el.getBoundingClientRect();
      out[el.dataset.a!] = { x: (r.left - base.left) / scale, y: (r.top - base.top) / scale, w: r.width / scale, h: r.height / scale };
    });
    setRects(out);
  }, [scale]);
  useLayoutEffect(() => { measure(); const t = setTimeout(measure, 300); return () => clearTimeout(t); }, [measure, c?.id, steps.length]);
  useEffect(() => { document.fonts?.ready.then(measure); }, [measure]);

  const action = beat?.actions[Math.min(sub, lastSub)];
  const target = action ? rects[action.at] : undefined;
  const cur = target ? { x: target.x + Math.min(target.w * 0.65, 48), y: target.y + target.h * 0.55 } : { x: -60, y: 380 };

  // Your turn: your pointer becomes the stamp.
  const [me, setMe] = useState({ x: W - 200, y: H - 120 });
  const onMove = (e: React.PointerEvent) => {
    const base = canvas.current!.getBoundingClientRect();
    setMe({ x: (e.clientX - base.left) / scale, y: (e.clientY - base.top) / scale });
  };
  const stamp = async (d: ApprovalDecision = mode) => {
    if (!turn || !c) return;
    const s = SIGNERS[signer], sg = rects["sg.box"];
    try {
      await api.approve(c.id, { approver: s.approver, role: s.role, decision: d, comment: "" });
      setMode(d);
      setHuman({ d, x: me.x - (sg?.x ?? 0), y: me.y - (sg?.y ?? 0), by: s.approver.split("@")[0] });
      setTurn(false);
      setTimeout(() => setPlaying(true), 900);
    } catch (e) { setError(String(e)); }
  };

  const link = (from: Rect, to: Rect) => {
    const rightward = to.x > from.x + from.w / 2;
    const x1 = rightward ? from.x + from.w : from.x + from.w / 2, y1 = from.y + from.h / 2;
    const x2 = rightward ? to.x : to.x + to.w / 2, y2 = rightward ? to.y + to.h / 2 : to.y;
    const dx = Math.max(40, Math.abs(x2 - x1) * 0.45);
    return rightward ? `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` : `M${x1},${y1} C${x1},${y1 + 60} ${x2},${y2 - 60} ${x2},${y2}`;
  };
  const v = verdict(c?.decision);
  const known = new Set(cases.map((x) => x.id));
  const picks = [...cases, ...fixtures.filter((f) => !known.has(f.id))];
  const mark = { approved: "Approved", rejected: "Rejected", ask: "Asked" } as const;

  return (
    <div className="work">
      <div className="work-head">
        <div>
          <div className="picks">
            {picks.map((p) => (
              <button key={p.id} className={`pick ${p.id === id ? "on" : ""}`} onClick={() => go(known.has(p.id) ? `/work/${p.id}` : `/work/${p.id}/play`)}>
                <i className={`dot ${verdict(p.decision).tone}`} />{shortName(vendors[p.vendor_id]?.name ?? p.vendor_id)}
              </button>
            ))}
          </div>
          {c && <h1 className="stencil big">{shortName(vendor?.name ?? c.vendor_id)}</h1>}
          {c && <span className="mono sub">{c.invoice?.invoice_no} · {compact(c.invoice?.total)} {c.invoice?.currency} · due {date(c.invoice?.due_date)}</span>}
        </div>
        <AnimatePresence>
          {done && c && (
            <motion.div className={`verdict ${v.tone}`} initial={{ scale: 2, opacity: 0, rotate: -14 }} animate={{ scale: 1, opacity: 1, rotate: -4 }}
              transition={{ type: "spring", stiffness: 420, damping: 20 }}>
              {human ? mark[human.d] : v.word}<small>{human ? `by you · ${human.by}` : summary(c)}</small>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {!c ? <div className="boot"><i /></div> : (
        <div className="work-grid">
          <div ref={wrap} className="stage" style={{ height: H * scale }}>
            <div ref={canvas} className={`canvas ${turn ? "turn" : ""}`} style={{ width: W, height: H, transform: `scale(${scale})` }}
              onPointerMove={onMove}>
              <Docs c={c} vendor={vendor} fx={fx} onSource={setSource} signature={
                <div className={`sg ${turn ? "live" : ""}`} onClick={() => stamp()}>
                  {turn ? (
                    <>
                      <span className="sg-title stencil">Your turn</span>
                      <div className="modes" onClick={(e) => e.stopPropagation()}>
                        {(["approved", "rejected", "ask"] as const).map((m, i) => (
                          <button key={m} className={`${m} ${mode === m ? "on" : ""}`} onMouseEnter={() => setMode(m)} onClick={() => stamp(m)}>{mark[m]}<kbd>{"ARQ"[i]}</kbd></button>
                        ))}
                      </div>
                      <div className="as" onClick={(e) => e.stopPropagation()}>
                        {SIGNERS.map((s, i) => <button key={s.label} className={i === signer ? "on" : ""} onClick={() => setSigner(i)}>{s.label}</button>)}
                      </div>
                      <span className="sg-hint">pick a stamp · or click the card · A R Q</span>
                    </>
                  ) : !fx.stamps.length && !human && <span className="sg-wait mono">{head >= 0 && beat?.stage === "approver" ? "reviewing…" : "—"}</span>}
                  {human && (
                    <motion.span className={`ink ${human.d}`} style={{ left: human.x - 90, top: human.y - 28 }}
                      initial={{ scale: 2.2, opacity: 0, rotate: -20 }} animate={{ scale: 1, opacity: 1, rotate: -9 }} transition={{ type: "spring", stiffness: 520, damping: 18 }}>
                      {mark[human.d]}<small>{human.by}</small>
                    </motion.span>
                  )}
                </div>
              } />
              <svg className="links" width={W} height={H}>
                {fx.links.map((l) => rects[l.from] && rects[l.at] && (
                  l.tone === "grey"
                    ? <motion.path key={l.key} d={link(rects[l.from], rects[l.at])} stroke={TONE.grey} strokeWidth={1.5} strokeDasharray="5 5" fill="none"
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }} />
                    : <motion.path key={l.key} d={link(rects[l.from], rects[l.at])} stroke={TONE[l.tone]} strokeWidth={l.tone === "red" ? 2.4 : 1.8} fill="none"
                        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.55, ease: [0.4, 0, 0.2, 1] }} />
                ))}
              </svg>
              {turn && <div className="veil" />}
              {beat && !turn && (
                <Cursor x={cur.x} y={cur.y} color={KIND_COLOR[beat.agent.kind]} name={beat.agent.name} kind={KIND_LABEL[beat.agent.kind]}
                  say={sub >= lastSub || beat.actions.length === 1 ? beat.say : undefined} pulse={head * 100 + sub + 1} stub={beat.stub} />
              )}
              {turn && <Cursor x={me.x} y={me.y} color={HUMAN_COLOR} name={`You · ${SIGNERS[signer].label}`} say={`${mark[mode]} stamp ready`} />}
            </div>
          </div>

          <aside className="rail">
            <div className="rail-top">
              <span className="k">Crew on this case</span>
              <div className="ctl">
                {done ? <button className="go" onClick={() => { reset(); setPlaying(true); }}>Replay</button>
                  : <button className="go" disabled={turn} onClick={() => setPlaying((p) => !p)}>{playing ? "Pause" : "Play"}</button>}
                {fixture && done && <button onClick={() => run(fixture)}>Rerun</button>}
              </div>
            </div>
            <ol className="crew">
              {beats.map((b, i) => {
                const st = i < head || (i === head && sub >= b.actions.length - 1) ? stepTone(b.step) : i === head ? "running" : "pending";
                return (
                  <li key={b.stage} className={`${st} ${i === head ? "here" : ""}`} onClick={() => jump(i)}>
                    <Avatar id={b.stage} kind={b.agent.kind} size={26} on={i === head} />
                    <div>
                      <b>{b.agent.name}{b.stub && <em>stub</em>}</b>
                      <AnimatePresence initial={false}>
                        {i <= head && <motion.p initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}>{b.say}</motion.p>}
                      </AnimatePresence>
                    </div>
                    <i className={`st ${st}`} />
                  </li>
                );
              })}
              {turn && <li className="you here"><span className="av human" style={{ width: 26, height: 26 }}><b>YOU</b></span><div><b>You</b><p>Stamp the sign-off card.</p></div></li>}
            </ol>
            <span className="keys mono">← → step · space play</span>
            {error && <p className="err">{error}</p>}
          </aside>
        </div>
      )}
      <AnimatePresence>{source && c && <Drawer c={c} id={source} onClose={() => setSource(null)} />}</AnimatePresence>
    </div>
  );
}
