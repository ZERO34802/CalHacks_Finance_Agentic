// Stage 3 · Reviewed by you. The agents' findings arrive as a decision packet; the reviewer approves with a
// deliberate gesture (slide to pay). The slider locks itself when the amount is over the reviewer's limit or
// the payee isn't verified; those rules are enforced in code by the Poster, the UI just shows them.
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import { useLayoutEffect, useRef, useState } from "react";
import type { Decision } from "../Proto";
import { Lock, Phone, UnitIcon } from "../icons";
import type { Scenario } from "../scenarios";
import { MoneyBar } from "./Reconcile";

const ROLES = { approver: { label: "AP lead", limit: "$100K" }, controller: { label: "Controller", limit: "$1M" } } as const;

export default function Review({ s, role, setRole, onDecide }: {
  s: Scenario; role: "approver" | "controller"; setRole: (r: "approver" | "controller") => void; onDecide: (d: Decision) => void;
}) {
  const overLimit = s.needs === "controller" && role === "approver";
  const l = s.lines[0];
  const qtyOk = !s.lines.some((x) => x.received < x.billed || x.ordered < x.billed);
  const bankOk = s.bank.onFile === s.bank.onInvoice && s.domain.onFile === s.domain.sender;
  const tiles = [
    { k: "Quantities", ok: qtyOk, viz: <span className="tv-q">{Array.from({ length: 10 }, (_, i) => <UnitIcon key={i} unit={l.unit} size={11} state={!qtyOk && i >= 8 ? "missing" : "ok"} />)}</span> },
    { k: "Price", ok: !s.price, viz: <span className="tv-p"><i style={{ height: "60%" }} /><i className={s.price ? "bad" : ""} style={{ height: s.price ? "80%" : "60%" }} /></span> },
    { k: "Payee", ok: bankOk, viz: <span className={`tv-b ${bankOk ? "" : "bad"}`}><i /><b>{bankOk ? "=" : "≠"}</b><i /></span> },
    { k: s.duplicate ? "Already paid" : "First time seen", ok: !s.duplicate, viz: <span className="tv-dd">{s.duplicate ? <><i /><i /></> : <i />}</span> },
  ];

  return (
    <div className="review">
      <div className="rv-left">
        <span className="rv-from"><i style={{ background: s.color }}>{s.short[0]}</i>{s.vendor} · {s.invoice.no} · due {s.invoice.due}</span>
        <h1 className="rv-head">{s.headline}</h1>
        <MoneyBar s={s} on big />
        <div className="tiles">
          {tiles.map((x, i) => (
            <motion.div key={x.k} className={`tile ${x.ok ? "ok" : "bad"}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 + i * 0.07 }}>
              {x.viz}<span>{x.k}</span><b>{x.ok ? "✓" : "✕"}</b>
            </motion.div>
          ))}
        </div>
        {s.followUp && <p className="rv-follow">Already drafted: {s.followUp}</p>}
      </div>

      <aside className="rv-right">
        <div className="who">
          <span className="you-dot">YOU</span>
          <div className="roles">
            {(Object.keys(ROLES) as (keyof typeof ROLES)[]).map((r) => (
              <button key={r} className={r === role ? "on" : ""} onClick={() => setRole(r)}>{ROLES[r].label}<em>up to {ROLES[r].limit}</em></button>
            ))}
          </div>
        </div>
        <p className="sod">Requested by j.park · the requester can never approve</p>

        {s.outcome === "pay" || s.outcome === "partial" ? (
          <>
            <Slide key={`${s.id}-${role}`} locked={overLimit} label={`Slide to pay ${s.currency} ${s.payNow}`}
              lockLabel={`Over your ${ROLES[role].limit} limit · needs Controller`} onDone={() => onDecide(s.outcome === "pay" ? "paid" : "partial")} />
            {s.held !== "0" && <p className="rv-note">{s.currency} {s.held} stays held</p>}
            <div className="alt"><button onClick={() => onDecide("held")}>Hold everything</button><button onClick={() => onDecide("rejected")}>Reject</button></div>
          </>
        ) : s.outcome === "hold" ? (
          <>
            <Slide locked label="" lockLabel="Payee not verified · payment blocked" onDone={() => {}} />
            <button className="primary-act" onClick={() => onDecide("held")}><Phone />Call the number on the vendor master</button>
            <p className="rv-note">Never the number in the email.</p>
          </>
        ) : (
          <>
            <button className="primary-act danger" onClick={() => onDecide("rejected")}>Reject duplicate</button>
            <p className="rv-note">Nothing is paid. Aerolane is told it was settled {s.duplicate?.paidOn}.</p>
          </>
        )}
      </aside>
    </div>
  );
}

function Slide({ label, lockLabel, locked, onDone }: { label: string; lockLabel: string; locked: boolean; onDone: () => void }) {
  const track = useRef<HTMLDivElement>(null);
  const [max, setMax] = useState(300);
  const [done, setDone] = useState(false);
  const x = useMotionValue(0);
  const fill = useTransform(x, (v) => v + 56);
  const fade = useTransform(x, [0, max * 0.6], [1, 0]);
  useLayoutEffect(() => { if (track.current) setMax(track.current.clientWidth - 60); }, []);
  if (locked) return <div className="slide locked"><Lock /><span>{lockLabel}</span></div>;
  return (
    <div ref={track} className={`slide ${done ? "done" : ""}`}>
      <motion.span className="sl-fill" style={{ width: fill }} />
      <motion.span className="sl-label" style={{ opacity: fade }}>{label}</motion.span>
      <motion.button className="sl-knob" drag="x" dragConstraints={{ left: 0, right: max }} dragElastic={0} dragMomentum={false} style={{ x }}
        onDragEnd={() => {
          if (x.get() > max * 0.85) { animate(x, max, { duration: 0.15 }); setDone(true); setTimeout(onDone, 450); }
          else animate(x, 0, { type: "spring", stiffness: 400, damping: 30 });
        }} aria-label={label}>›››</motion.button>
    </div>
  );
}
