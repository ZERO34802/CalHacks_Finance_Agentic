// Stage 4 · Paid (or not). Approved money visibly travels from Helix's bank to the vendor's bank; the journal
// entry settles on a balance scale (debits = credits); held money sits in a locked vault with the follow-up
// flying back to the vendor. A blocked or rejected payment shows the transfer line cut. Payments are SIMULATED.
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import { useEffect } from "react";
import type { Decision } from "../Proto";
import { Bank, Envelope, Lock, Phone } from "../icons";
import type { Scenario } from "../scenarios";

const ARC = "M120 150 C 300 20, 500 20, 680 150";

export default function Paid({ s, t, decision, onNext }: { s: Scenario; t: number; decision: Decision; onNext: () => void }) {
  const moving = decision === "paid" || decision === "partial";
  const amount = moving ? s.payNow : "0.00";
  const steps = moving
    ? ["Payment instruction created", "Released by you", "Sent to the bank", "Settled · simulated"]
    : decision === "held" ? ["Payment blocked", "Callback requested", "Vendor master unchanged", "Waiting for verification"]
      : ["Payment refused", "Marked duplicate", "Vendor notified", "Nothing paid"];
  const title = moving ? (decision === "partial" ? "Paid what was right." : "Paid.") : decision === "held" ? "Not paid. Held safely." : "Not paid. Rejected.";

  return (
    <div className="paid">
      <h1 className={`pd-title ${moving ? "ok" : "stop"}`}>{title}</h1>

      <div className="transfer"><div className="tf">
        <svg viewBox="0 0 800 190" className="arc">
          <path d={ARC} className={`arc-path ${moving ? "" : "cut"}`} />
          {moving && t >= 1 && Array.from({ length: 9 }, (_, i) => (
            <circle key={i} r="9" className="coin-c">
              <animateMotion dur="1.5s" begin={`${i * 0.16}s`} repeatCount="2" path={ARC} fill="freeze" keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.4 0 0.2 1" />
            </circle>
          ))}
          {!moving && <g className="cutmark"><circle cx="400" cy="57" r="22" /><path d="M390 47l20 20M410 47l-20 20" /></g>}
        </svg>
        <div className="bk-node from"><Bank /><b>Helix Silicon</b><em>Operating account</em></div>
        <div className="bk-node to"><Bank /><b>{s.vendor}</b><em>{s.bank.bankName} •••• {moving ? s.bank.onInvoice : s.bank.onFile}</em></div>
        <div className={`counter ${moving ? "" : "zero"}`}><span>{s.currency}</span><Count to={amount} run={moving && t >= 1} /></div>
      </div></div>

      <div className="pd-grid">
        <ol className="steps">
          {steps.map((x, i) => (
            <motion.li key={x} className={t > i ? "on" : ""} initial={{ opacity: 0.3 }} animate={{ opacity: t > i ? 1 : 0.3 }}><i>{t > i ? "✓" : i + 1}</i>{x}</motion.li>
          ))}
        </ol>

        {moving ? <Scale s={s} on={t >= 4} /> : (
          <div className="stopcard">
            {decision === "held" ? <><span className="ring"><Phone size={26} /></span><b>Calling the number on the vendor master</b><em>not the one in the email</em></>
              : <><span className="stamp-rej">Rejected</span><b>Duplicate of {s.duplicate?.paidNo}</b><em>paid {s.duplicate?.paidOn}</em></>}
          </div>
        )}

        {s.held !== "0" && (
          <div className="vault">
            <span className="v-door"><Lock size={26} /></span>
            <b>{s.currency} {s.held}</b><em>{decision === "rejected" ? "not paid" : "held"}</em>
            {s.followUp && (
              <motion.span className="v-mail" initial={{ x: 0, y: 0, opacity: 0 }} animate={t >= 3 ? { x: 120, y: -70, opacity: [0, 1, 1, 0] } : {}}
                transition={{ duration: 1.6 }}><Envelope size={20} /></motion.span>
            )}
            {s.followUp && <p>{s.followUp}</p>}
          </div>
        )}
      </div>

      <motion.div className="pd-foot" initial={{ opacity: 0 }} animate={{ opacity: t >= 5 ? 1 : 0 }}>
        <button className="next" onClick={onNext}>Next invoice arriving ›</button>
      </motion.div>
    </div>
  );
}

function Count({ to, run }: { to: string; run: boolean }) {
  const target = Number(to.replace(/,/g, ""));
  const v = useMotionValue(0);
  const text = useTransform(v, (x) => x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  useEffect(() => { if (!run) return; const c = animate(v, target, { duration: 2.2, ease: [0.3, 0, 0.2, 1] }); return c.stop; }, [run, target]);
  return <motion.b>{text}</motion.b>;
}

/** The journal entry as a balance: the beam levels when the credit lands. Debits = credits, always. */
function Scale({ s, on }: { s: Scenario; on: boolean }) {
  return (
    <div className="scale">
      <span className="eyebrow-s">Ledger · double entry</span>
      <svg viewBox="0 0 320 170">
        <path d="M160 40 L160 150 M120 160 L200 160" className="post" />
        <motion.g initial={{ rotate: -14 }} animate={{ rotate: on ? 0 : -14 }} transition={{ type: "spring", stiffness: 60, damping: 7 }} style={{ originX: "160px", originY: "40px" }}>
          <path d="M50 40 L270 40" className="beam" />
          <path d="M50 40 L30 95 M50 40 L70 95 M270 40 L250 95 M270 40 L290 95" className="string" />
          <path d="M22 95 L78 95 L70 108 L30 108 Z" className="pan" />
          <motion.path d="M242 95 L298 95 L290 108 L250 108 Z" className={`pan ${on ? "full" : ""}`} />
        </motion.g>
      </svg>
      <div className="sides"><span><em>Debit</em>Accounts payable<b>{s.payNow}</b></span><span><em>Credit</em>Bank<b>{s.payNow}</b></span></div>
      <motion.p animate={{ opacity: on ? 1 : 0 }}>Balanced · posted</motion.p>
    </div>
  );
}
