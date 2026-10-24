// Stage 1 · Received. The trigger: a supplier email lands in the AP inbox and ReconAI takes the PDF by itself.
// The Reader (Claude, zero tools) scans it; boxes lock onto the fields and the structured record fills.
// Any other email's PDF can be dragged onto the scanner to start that invoice.
import { motion } from "framer-motion";
import { useRef } from "react";
import { Envelope, Shield } from "../icons";
import { SCENARIOS, type Scenario } from "../scenarios";

const FIELDS = ["Vendor", "Invoice no.", "PO", "Lines", "Total", "Pay to"];

export default function Received({ s, t, current, onPick }: { s: Scenario; t: number; current: number; onPick: (i: number) => void }) {
  const drop = useRef<HTMLDivElement>(null);
  const inDrop = (x: number, y: number) => {
    const r = drop.current?.getBoundingClientRect();
    return !!r && x > r.left && x < r.right && y > r.top && y < r.bottom;
  };
  const box = (n: number) => (t >= 3 ? `fbox on f${n}` : "fbox");

  return (
    <div className="received">
      <aside className="inbox">
        <div className="ib-head"><Envelope /><b>ap@helixsilicon.com</b><span className="live">watching</span></div>
        {SCENARIOS.map((x, i) => {
          const isCur = i === current;
          return (
            <motion.div key={x.id} className={`mail ${isCur ? "cur" : ""}`} layout
              initial={isCur ? { opacity: 0, y: -40, scale: 0.96 } : false} animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ type: "spring", stiffness: 220, damping: 20 }}>
              <span className="m-av" style={{ background: x.color }}>{x.short[0]}</span>
              <div className="m-main">
                <span className="m-from">{x.email.from}</span>
                <span className="m-sub">{x.email.subject}</span>
                <motion.span className={`pdf ${isCur && t >= 1 ? "taken" : ""}`} drag={!isCur} dragSnapToOrigin whileDrag={{ scale: 1.15, rotate: -4, zIndex: 50 }}
                  onDragEnd={(_, info) => { if (inDrop(info.point.x - window.scrollX, info.point.y - window.scrollY)) onPick(i); }}
                  title={isCur ? "" : "Drag onto ReconAI to start"}>
                  <i>PDF</i>{x.email.file}
                </motion.span>
              </div>
              <span className="m-at">{x.email.at}</span>
              {isCur && <span className="m-new" />}
            </motion.div>
          );
        })}
        <p className="hint">Drag any PDF onto the scanner →</p>
      </aside>

      <div ref={drop} className={`scanner ${t >= 1 ? "busy" : ""}`}>
        <span className="sc-label"><Shield /> ReconAI picks up every invoice the moment it lands</span>
        {t < 1 && <div className="sc-empty"><span>Waiting for an invoice…</span></div>}
        {t >= 1 && (
          <motion.article className="pdfdoc" initial={{ x: -420, y: -60, scale: 0.3, rotate: -8, opacity: 0 }} animate={{ x: 0, y: 0, scale: 1, rotate: 0, opacity: 1 }}
            transition={{ type: "spring", stiffness: 120, damping: 18 }}>
            <header>
              <span className={box(1)}><span className="logo-blk" style={{ background: s.color }}>{s.short.slice(0, 2).toUpperCase()}</span><b>{s.vendor}</b></span>
              <span className="doc-title">INVOICE</span>
            </header>
            <div className="doc-meta">
              <span className={box(2)}>No. <b>{s.invoice.no}</b></span>
              <span>Date {s.invoice.date}</span>
              <span className={box(3)}>PO <b>{s.invoice.po}</b></span>
            </div>
            <div className="doc-bill">Bill to · Helix Silicon, Inc. · Accounts Payable</div>
            <div className={box(4)}>
              <table><tbody>
                {s.lines.map((l) => <tr key={l.sku}><td>{l.desc}<small>{l.sku}</small></td><td>{l.billed.toLocaleString()}</td><td>{l.invPrice}</td><td>{l.amount}</td></tr>)}
              </tbody></table>
            </div>
            <div className="doc-total"><span className={box(5)}>Total {s.currency} <b>{s.invoice.total}</b></span></div>
            <div className="doc-pay"><span className={box(6)}>Remit to {s.bank.bankName} •••• {s.bank.onInvoice}</span><span>Due {s.invoice.due}</span></div>
            {t >= 2 && t < 4 && <span className="beam" />}
          </motion.article>
        )}
      </div>

      <aside className="record">
        <div className="rc-head"><span className="rc-av">RD</span><div><b>Reader</b><em>Claude · zero tools · can read, can't act</em></div></div>
        {FIELDS.map((f, i) => {
          const v = [s.vendor, s.invoice.no, s.invoice.po, `${s.lines.length} line${s.lines.length > 1 ? "s" : ""}`, `${s.currency} ${s.invoice.total}`, `•••• ${s.bank.onInvoice}`][i];
          const on = t >= 4;
          return (
            <motion.div key={f} className={`slot f${i + 1} ${on ? "on" : ""}`} initial={false} animate={on ? { opacity: 1, x: 0 } : { opacity: 0.45, x: 0 }}
              transition={{ delay: on ? i * 0.08 : 0 }}>
              <span className="n">{i + 1}</span><span className="sl">{f}</span><b>{on ? v : ""}</b>
            </motion.div>
          );
        })}
        <motion.div className="rc-foot" animate={{ opacity: t >= 4 ? 1 : 0 }}>Handing to the reconciliation crew ›</motion.div>
      </aside>
    </div>
  );
}
