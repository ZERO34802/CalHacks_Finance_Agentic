// The documents the agents work on, laid out on a fixed 1280x744 canvas. Every element an agent touches
// carries data-a="<anchor>". What's highlighted / linked / marked comes only from `fx` (see script.ts).
// Document text is UNTRUSTED and only ever rendered as plain text.
import { AnimatePresence, motion } from "framer-motion";
import type { ReactNode } from "react";
import { money } from "../format";
import type { applied, Glyph } from "../script";
import { shortName } from "../story";
import type { Case, Vendor } from "../types/contracts";

export const W = 1280, H = 744;
type Fx = ReturnType<typeof applied>;

const qty = (q: string) => Number(q).toLocaleString();

function Mark({ g }: { g?: Glyph }) {
  return (
    <AnimatePresence>
      {g && (
        <motion.span className={`mark ${g}`} initial={{ scale: 0, rotate: -30 }} animate={{ scale: 1, rotate: 0 }} exit={{ scale: 0 }}
          transition={{ type: "spring", stiffness: 500, damping: 18 }}>
          {g === "ok" ? "✓" : g === "diff" ? "≠" : "?"}
        </motion.span>
      )}
    </AnimatePresence>
  );
}

function A({ id, fx, children, className = "" }: { id: string; fx: Fx; children: ReactNode; className?: string }) {
  const tone = fx.hl.get(id);
  return (
    <span data-a={id} className={`anc ${tone ? `hl hl-${tone}` : ""} ${className}`}>
      {children}<Mark g={fx.marks.get(id)} />
    </span>
  );
}

function Chip({ id, fx, empty }: { id: string; fx: Fx; empty: string }) {
  const chip = fx.chips.get(id);
  return (
    <span data-a={id} className={`slot ${chip ? `filled ${chip.tone}` : ""}`}>
      <AnimatePresence mode="wait">
        <motion.span key={chip?.text ?? "empty"} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
          {chip?.text ?? empty}
        </motion.span>
      </AnimatePresence>
      <Mark g={fx.marks.get(id)} />
    </span>
  );
}

export default function Docs({ c, vendor, fx, onSource, signature }: {
  c: Case; vendor: Vendor | null; fx: Fx; onSource: (docId: string) => void; signature: ReactNode;
}) {
  const inv = c.invoice;
  const invDoc = c.documents.find((d) => d.id === inv?.doc_id);
  const sender = c.documents.find((d) => d.sender)?.sender ?? "—";
  const je = c.journal_entry;

  return (
    <>
      {/* invoice */}
      <section className="doc invoice" style={{ left: 24, top: 24, width: 456, height: 476 }}>
        <header><span className="dk">Invoice</span><button className="src" onClick={() => inv && onSource(inv.doc_id)}>source ↗</button></header>
        <h3><A id="inv.vendor" fx={fx}>{shortName(vendor?.name ?? c.vendor_id)}</A></h3>
        <div className="meta mono">
          <A id="inv.no" fx={fx}>{inv?.invoice_no ?? "—"}</A><span>{inv?.invoice_date}</span><span>{inv?.po_number ?? "no PO"}</span>
        </div>
        <div className="lines">
          {inv?.lines.map((l) => (
            <div key={l.line_no} className="line">
              <A id={`inv.line.${l.sku}`} fx={fx} className="ln"><b>{l.description}</b><span className="mono">{l.sku}</span></A>
              <span className="mono r">{qty(l.qty)} × {money(l.unit_price)}</span>
              <span className="mono r">{money(l.amount)}</span>
            </div>
          ))}
        </div>
        <div className="total"><span className="dk">Total</span><A id="inv.total" fx={fx} className="mono">{money(inv?.total, inv?.currency)}</A></div>
        <div className="foot mono">
          <span>remit to <A id="inv.bank" fx={fx}>•••• {inv?.bank_last4 ?? "—"}</A></span>
          <span>from <A id="inv.sender" fx={fx}>{sender.split("@")[1] ?? sender}</A></span>
        </div>
        <div className="chips"><Chip id="inv.print" fx={fx} empty="fingerprint" /><Chip id="inv.case" fx={fx} empty="case" /></div>
        <span className="sha mono">sha {invDoc?.sha256.slice(0, 8)}</span>
      </section>

      {/* purchase order */}
      <section className="doc po" style={{ left: 504, top: 24, width: 360, height: 220 }}>
        <header><span className="dk">Purchase order</span><button className="src" onClick={() => c.po && onSource(c.po.doc_id)}>source ↗</button></header>
        <h4 className="mono">{c.po?.po_number ?? "no PO on file"}</h4>
        {c.po?.lines.map((l) => (
          <div key={l.sku} className="row"><A id={`po.line.${l.sku}`} fx={fx}><span className="mono">{l.sku}</span></A>
            <span className="mono r">{qty(l.qty)} × {money(l.unit_price)}</span></div>
        ))}
        <div className="by mono">raised by {c.po?.requester.split("@")[0] ?? "—"}</div>
      </section>

      {/* receipt */}
      <section className="doc rc" style={{ left: 888, top: 24, width: 368, height: 220 }}>
        <header><span className="dk">Goods receipt</span><button className="src" onClick={() => c.receipts[0] && onSource(c.receipts[0].doc_id)}>source ↗</button></header>
        <h4 className="mono">{c.receipts[0]?.received_date ?? "nothing received"}</h4>
        {c.receipts.flatMap((r) => r.lines).map((l, i) => (
          <div key={`${l.sku}${i}`} className="row"><A id={`rc.line.${l.sku}`} fx={fx}><span className="mono">{l.sku}</span></A>
            <span className="mono r">{qty(l.qty_received)} received</span></div>
        ))}
        <div className="by mono">signed {c.receipts[0]?.received_by.split("@")[0] ?? "—"}</div>
      </section>

      {/* vendor master */}
      <section className="doc vm" style={{ left: 504, top: 268, width: 360, height: 232 }}>
        <header><span className="dk">Vendor master · system of record</span></header>
        <h4>{vendor ? shortName(vendor.name) : c.vendor_id}</h4>
        <div className="row"><span className="dk">bank on file</span><A id="vm.bank" fx={fx} className="mono">•••• {vendor?.bank_last4 ?? "—"}</A></div>
        <div className="row"><span className="dk">domain</span><A id="vm.domain" fx={fx} className="mono">{vendor?.email_domain ?? "—"}</A></div>
        <div className="row"><span className="dk">tax id</span><span className="mono">{vendor?.tax_id ?? "missing"}</span></div>
      </section>

      {/* the Droid's sandbox */}
      <section className="doc sandbox" style={{ left: 888, top: 268, width: 368, height: 232 }}>
        <header><span className="dk">Droid sandbox · no network</span><Chip id="sb.playbook" fx={fx} empty="playbook" /></header>
        <div data-a="sb.idle" className="sb-idle" />
        <div data-a="sb.note" className="sb-note">
          <AnimatePresence>{fx.notes.get("sb.note") && (
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }}>“{fx.notes.get("sb.note")}”</motion.p>
          )}</AnimatePresence>
        </div>
        <div data-a="sb.slot" className="sb-slot"><span>only exit · proposal</span></div>
      </section>

      {/* ledger */}
      <section className="doc ledger" style={{ left: 24, top: 524, width: 840, height: 196 }}>
        <header><span className="dk">Ledger · Beancount · double entry</span><Chip id="lg.box" fx={fx} empty={je ? "journal entry" : "awaiting decision"} /></header>
        {je ? je.postings.map((p, i) => (
          <div key={i} data-a={`lg.row.${i}`} className="lrow">
            <AnimatePresence>{fx.rows.has(i) && (
              <motion.div className="lrow-in" initial={{ clipPath: "inset(0 100% 0 0)" }} animate={{ clipPath: "inset(0 0% 0 0)" }} transition={{ duration: 0.6 }}>
                <span className="mono dim">{je.date}</span><span>{p.account}</span><span className="mono r">{money(p.amount, p.currency)}</span>
              </motion.div>
            )}</AnimatePresence>
          </div>
        )) : <div className="lempty" />}
      </section>

      {/* signature */}
      <section data-a="sg.box" className="doc sign" style={{ left: 888, top: 524, width: 368, height: 196 }}>
        <header><span className="dk">Sign-off</span></header>
        {signature}
        {fx.stamps.map((s, i) => (
          <motion.span key={i} className={`ink ${s.tone}`} initial={{ scale: 1.8, opacity: 0, rotate: -18 }} animate={{ scale: 1, opacity: 1, rotate: -8 }}
            transition={{ type: "spring", stiffness: 520, damping: 20 }}>{s.text}<small>{s.by}</small></motion.span>
        ))}
      </section>
    </>
  );
}
