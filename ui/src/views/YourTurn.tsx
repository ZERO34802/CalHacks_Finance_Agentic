// Your turn: the human in the loop. Your pointer is the stamp. Pick Approve / Reject / Ask (A R Q), click the
// invoice, the stamp lands where you clicked and the paper leaves for the done tray; the next one rises.
// The UI only records the decision; segregation of duties and limits are enforced by the Poster, in code.
import { AnimatePresence, motion, useMotionValue, useSpring } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { go, type LiveProps } from "../App";
import { date, money } from "../format";
import { shortName } from "../story";
import type { ApprovalDecision, Case, QueueItem, Role } from "../types/contracts";

const SIGNERS: { approver: string; role: Role; label: string; limit: string }[] = [
  { approver: "ap.lead@helix.example", role: "approver", label: "AP lead", limit: "up to $100K" },
  { approver: "m.chen@helix.example", role: "controller", label: "Controller", limit: "up to $1M" },
];
const WORD = { approved: "Approved", rejected: "Rejected", ask: "Asked" } as const;

export default function YourTurn({ tick }: LiveProps) {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [cases, setCases] = useState<Record<string, Case>>({});
  const [done, setDone] = useState<{ id: string; d: ApprovalDecision; name: string }[]>([]);
  const [mode, setMode] = useState<ApprovalDecision>("approved");
  const [signer, setSigner] = useState(0);
  const [ink, setInk] = useState<{ x: number; y: number; d: ApprovalDecision } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.queue().then(setQueue).catch((e) => setError(String(e)));
    api.cases().then((cs) => setCases(Object.fromEntries(cs.map((c) => [c.id, c])))).catch(() => {});
  }, [tick]);

  const open = queue.filter((q) => !done.some((d) => d.id === q.case_id));
  const cur = open[0];
  const c = cur ? cases[cur.case_id] : undefined;

  // the stamp follows your pointer
  const desk = useRef<HTMLDivElement>(null);
  const px = useMotionValue(0), py = useMotionValue(0);
  const sx = useSpring(px, { stiffness: 600, damping: 40 }), sy = useSpring(py, { stiffness: 600, damping: 40 });
  const [over, setOver] = useState(false);

  const stamp = async (e: React.MouseEvent) => {
    if (!cur || ink) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const s = SIGNERS[signer];
    try {
      await api.approve(cur.case_id, { approver: s.approver, role: s.role, decision: mode, comment: "" });
      setInk({ x: e.clientX - r.left, y: e.clientY - r.top, d: mode });
      setTimeout(() => { setDone((d) => [{ id: cur.case_id, d: mode, name: shortName(cur.vendor_name) }, ...d]); setInk(null); }, 950);
    } catch (err) { setError(String(err)); }
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (k === "a") setMode("approved"); if (k === "r") setMode("rejected"); if (k === "q") setMode("ask");
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const why = c?.discrepancies.length ? c.discrepancies.map((d) => d.type.replace(/_/g, " ")).join(" · ")
    : c?.decision === "escalate" ? "Too risky for the crew to sign alone." : c?.proposal?.explanation ?? "Waiting for a signature.";

  return (
    <div className="turn-room">
      <section className="turn-head">
        <h1 className="stencil">{open.length ? <>Your turn.<span> {open.length} on the stack.</span></> : <>All clear.<span> Nothing needs you.</span></>}</h1>
        <div className="signas">
          <span className="k">Signing as</span>
          {SIGNERS.map((s, i) => <button key={s.label} className={i === signer ? "on" : ""} onClick={() => setSigner(i)}>{s.label}<em>{s.limit}</em></button>)}
        </div>
      </section>

      <section className="turn-grid">
        <aside className="tray">
          <span className="k">Done this session</span>
          <AnimatePresence>
            {done.map((d) => (
              <motion.div key={d.id} className={`tray-doc ${d.d}`} initial={{ x: 200, opacity: 0, rotate: 8 }} animate={{ x: 0, opacity: 1, rotate: -2 }}>
                <b>{d.name}</b><span className={`tiny-stamp ${d.d}`}>{WORD[d.d]}</span>
              </motion.div>
            ))}
          </AnimatePresence>
          {done.length === 0 && <p className="dim">Stamped papers land here.</p>}
        </aside>

        <div ref={desk} className="stamp-desk" onPointerMove={(e) => { const r = desk.current!.getBoundingClientRect(); px.set(e.clientX - r.left); py.set(e.clientY - r.top); }}
          onPointerEnter={() => setOver(true)} onPointerLeave={() => setOver(false)}>
          {open.slice(1, 4).map((q, i) => <div key={q.case_id} className="under" style={{ transform: `translate(${(i + 1) * 10}px, ${(i + 1) * 10}px) rotate(${(i + 1) * 1.4}deg)`, zIndex: 3 - i }} />)}
          <AnimatePresence mode="popLayout">
            {cur && c ? (
              <motion.article key={cur.case_id} className="paper" onClick={stamp}
                initial={{ y: 40, opacity: 0, scale: 0.97 }} animate={{ y: 0, opacity: 1, scale: 1, rotate: 0 }}
                exit={{ x: -520, y: 60, rotate: -14, opacity: 0, transition: { duration: 0.5, ease: [0.5, 0, 0.75, 0] } }}
                transition={{ type: "spring", stiffness: 160, damping: 20 }}>
                <header><span className="k">Invoice · {cur.invoice_no}</span><span className={`due ${cur.at_risk ? "risk" : ""}`}>due {date(cur.due_date)}{cur.days_to_due != null && ` · ${cur.days_to_due}d`}</span></header>
                <h2 className="stencil">{shortName(cur.vendor_name)}</h2>
                <div className="amt mono">{money(cur.total, cur.currency)}{cur.currency !== "USD" && <small>≈ {money(cur.total_usd, "USD")}</small>}</div>
                <div className="plines">
                  {c.invoice?.lines.map((l) => <div key={l.line_no}><span>{l.description}</span><span className="mono">{money(l.amount)}</span></div>)}
                </div>
                <p className="handed"><b>Handed to you by the Approver.</b> {why}</p>
                <AnimatePresence>
                  {ink && (
                    <motion.span className={`ink ${ink.d}`} style={{ left: ink.x - 110, top: ink.y - 36 }}
                      initial={{ scale: 2.4, opacity: 0, rotate: -22 }} animate={{ scale: 1, opacity: 1, rotate: -10 }} transition={{ type: "spring", stiffness: 520, damping: 17 }}>
                      {WORD[ink.d]}<small>{SIGNERS[signer].approver.split("@")[0]}</small>
                    </motion.span>
                  )}
                </AnimatePresence>
              </motion.article>
            ) : (
              <motion.div key="clear" className="clear-desk" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                <span className="stencil">Desk clear</span><button onClick={() => go("/")}>back to the floor ›</button>
              </motion.div>
            )}
          </AnimatePresence>
          {cur && over && !ink && (
            <motion.span className={`stamp-ghost ${mode}`} style={{ x: sx, y: sy }}>{WORD[mode]}</motion.span>
          )}
        </div>

        <aside className="margin-notes">
          {cur && (
            <>
              <span className="k">Why it's at the top</span>
              <div className="prio"><span className="stencil">{cur.priority}</span><span>priority</span></div>
              {cur.reasons.map((r) => <p key={r}>{r}</p>)}
              <button className="trace" onClick={() => go(`/work/${cur.case_id}`)}>See how the crew got here ›</button>
              <div className="modes-v">
                {(["approved", "rejected", "ask"] as const).map((m, i) => (
                  <button key={m} className={`${m} ${mode === m ? "on" : ""}`} onClick={() => setMode(m)}>{WORD[m]}<kbd>{"ARQ"[i]}</kbd></button>
                ))}
              </div>
              <p className="fine">Your stamp is recorded. The requester can never approve, and limits are enforced in code.</p>
            </>
          )}
          {error && <p className="err">{error}</p>}
        </aside>
      </section>
      {open.length > 0 && <p className="fine center">Pick a stamp (A · R · Q), then click the paper.</p>}
    </div>
  );
}
