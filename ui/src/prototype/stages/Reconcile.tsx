// Stage 2 · Reconciled, automatically. Each check is something you can SEE:
//   quantities as pictograms (ordered vs received vs billed), prices as tags, the payee as bank cards that
//   snap together or bounce apart, the sender domain as a character diff, duplicates as a wipe slider,
//   and the result as a money bar: what can be paid now vs what is held.
import { motion } from "framer-motion";
import { useEffect, useState, type ReactNode } from "react";
import Avatar from "../../components/Avatar";
import type { Kind } from "../../story";
import { UnitIcon } from "../icons";
import type { Line, Scenario } from "../scenarios";

type St = "wait" | "check" | "done";
const st = (t: number, beat: number): St => (t < beat ? "wait" : t === beat ? "check" : "done");
const UNIT_NAME = { wafer: "wafers", chip: "memory stacks", package: "packages", box: "shipments" } as const;

export default function Reconcile({ s, t }: { s: Scenario; t: number }) {
  const qtyBad = s.lines.some((l) => l.received < l.billed || l.ordered < l.billed);
  const priceBad = !!s.price;
  const bankBad = s.bank.onFile !== s.bank.onInvoice;
  const domBad = s.domain.onFile !== s.domain.sender;
  return (
    <div className="recon">
      <div className="rc-left">
        <Panel title="Did we get what we're paying for?" agent="matcher" kind="code" name="Matcher" state={st(t, 2)} bad={qtyBad}>
          {s.lines.map((l) => <Quantities key={l.sku} l={l} on={t >= 2} />)}
        </Panel>
        <Panel title="What can be paid" agent="validators" kind="code" name="Validators" state={st(t, 6)} bad={s.outcome !== "pay"}
          extra={s.outcome !== "pay" && t >= 6 ? <span className="sbx"><Avatar id="investigator" kind="droid" size={18} />proposal from the sandbox</span> : null}>
          <MoneyBar s={s} on={t >= 6} />
        </Panel>
      </div>
      <div className="rc-right">
        <Panel title="Seen this invoice before?" agent="doc_dedup" kind="code" name="Dedup" state={st(t, 1)} bad={!!s.duplicate}>
          {s.duplicate ? <Wipe s={s} on={t >= 1} /> : <History on={t >= 1} />}
        </Panel>
        <Panel title="Right price?" agent="matcher" kind="code" name="Matcher" state={st(t, 3)} bad={priceBad}>
          <Prices s={s} on={t >= 3} />
        </Panel>
        <Panel title="Who gets the money?" agent="vendor_guard" kind="code" name="Vendor Guard" state={st(t, 4)} bad={bankBad || domBad}>
          <BankCards s={s} on={t >= 4} />
          <Domain a={s.domain.onFile} b={s.domain.sender} on={t >= 5} />
        </Panel>
      </div>
      <motion.div className={`rc-ready ${s.outcome}`} initial={false} animate={{ opacity: t >= 7 ? 1 : 0, y: t >= 7 ? 0 : 16 }}>
        <b>{s.outcome === "pay" ? "Clean." : s.outcome === "partial" ? "Partly payable." : s.outcome === "hold" ? "Do not pay yet." : "Duplicate."}</b>
        Sending to the reviewer with everything above ›
      </motion.div>
    </div>
  );
}

function Panel({ title, agent, kind, name, state, bad, children, extra }: {
  title: string; agent: string; kind: Kind; name: string; state: St; bad: boolean; children: ReactNode; extra?: ReactNode;
}) {
  return (
    <section className={`pn ${state} ${state === "done" ? (bad ? "bad" : "good") : ""}`}>
      <header>
        <span className="pn-t">{title}</span>
        <span className="pn-who"><Avatar id={agent} kind={kind} size={18} on={state === "check"} />{name}</span>
        <span className="pn-res">{state === "done" ? (bad ? "✕" : "✓") : state === "check" ? "" : "·"}</span>
      </header>
      <div className="pn-body">{children}</div>
      {extra}
      {state === "check" && <span className="pn-scan" />}
    </section>
  );
}

function Quantities({ l, on }: { l: Line; on: boolean }) {
  const max = Math.max(l.ordered, l.received, l.billed, 1);
  const per = Math.max(1, Math.ceil(max / 50));
  const n = (q: number) => Math.round(q / per);
  const rows = [
    { k: "Ordered", sub: "purchase order", q: l.ordered },
    { k: "Received", sub: "goods receipt", q: l.received },
    { k: "Billed", sub: "invoice", q: l.billed },
  ];
  const gap = l.billed - Math.min(l.received, l.ordered);
  return (
    <div className="qty">
      <div className="qty-h"><b>{l.desc}</b><span>{per > 1 ? `1 icon = ${per} ${UNIT_NAME[l.unit]}` : UNIT_NAME[l.unit]}</span></div>
      {rows.map((r, ri) => {
        const have = n(r.q), want = n(l.billed);
        const icons = Array.from({ length: Math.max(have, want) }, (_, i) => {
          const missing = i >= have;                                  // billed but not here
          const extra = ri === 2 && i >= n(Math.min(l.received, l.ordered)); // billed beyond what came / was ordered
          return missing ? "missing" : extra ? "extra" : "ok";
        });
        return (
          <div key={r.k} className="qrow">
            <span className="qk"><b>{r.k}</b><em>{r.sub}</em></span>
            <span className="qicons">
              {icons.map((state, i) => (
                <motion.span key={i} initial={{ scale: 0, opacity: 0 }} animate={on ? { scale: 1, opacity: 1 } : {}}
                  transition={{ delay: ri * 0.25 + i * 0.012, type: "spring", stiffness: 500, damping: 22 }}>
                  <UnitIcon unit={l.unit} state={state as never} size={15} />
                </motion.span>
              ))}
            </span>
            <span className={`qn ${r.q < l.billed ? "short" : ""}`}>{r.q.toLocaleString()}</span>
          </div>
        );
      })}
      <motion.div className={`qv ${gap > 0 ? "bad" : "good"}`} initial={{ opacity: 0 }} animate={{ opacity: on ? 1 : 0 }} transition={{ delay: 0.9 }}>
        {gap > 0 ? (l.ordered === 0 ? "Billed, but never ordered" : `${gap.toLocaleString()} ${UNIT_NAME[l.unit]} billed that never arrived`) : "All three agree"}
      </motion.div>
    </div>
  );
}

function Prices({ s, on }: { s: Scenario; on: boolean }) {
  const l = s.lines[0];
  const po = Number(l.poPrice.replace(/,/g, "")), inv = Number(l.invPrice.replace(/,/g, ""));
  const hi = Math.max(po, inv) || 1, lo = Math.min(po, inv) * 0.9;
  const h = (x: number) => (hi === lo / 0.9 ? 100 : 35 + (65 * (x - lo)) / (hi - lo)); // exaggerate the gap so it's visible
  return (
    <div className="prices">
      <div className="tags">
        {[{ k: "PO price", v: l.poPrice, h: po }, { k: "Billed", v: l.invPrice, h: inv }].map((x, i) => (
          <div key={x.k} className="tagcol">
            <motion.span className={`ptag ${i === 1 && s.price ? "bad" : ""}`} initial={{ height: 0 }} animate={{ height: on ? `${h(x.h)}%` : 0 }}
              transition={{ type: "spring", stiffness: 120, damping: 16, delay: i * 0.15 }}><b>{x.v}</b></motion.span>
            <em>{x.k}</em>
          </div>
        ))}
      </div>
      {s.price ? (
        <div className="timeline">
          <span className="tl-bar" />
          <motion.span className="tl-pin inv" initial={{ opacity: 0 }} animate={{ opacity: on ? 1 : 0 }} style={{ left: "28%" }}><i />invoice<br /><b>{s.price.invoiceDate}</b></motion.span>
          <motion.span className="tl-pin eff" initial={{ opacity: 0 }} animate={{ opacity: on ? 1 : 0 }} transition={{ delay: 0.3 }} style={{ left: "72%" }}><i />new price starts<br /><b>{s.price.effective}</b></motion.span>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: on ? 1 : 0 }} transition={{ delay: 0.6 }}>Billed before {s.price.amendment} takes effect → <b>PO price wins</b></motion.p>
        </div>
      ) : <p className="same">Same price on both</p>}
    </div>
  );
}

// A visual fingerprint for an account: same account -> same stripes, different -> obviously different.
const stripes = (seed: string) => [...seed.padEnd(6, seed)].slice(0, 6).map((ch, i) => `hsl(${(ch.charCodeAt(0) * 47 + i * 61) % 360} 55% 48%)`);

function BankCards({ s, on }: { s: Scenario; on: boolean }) {
  const same = s.bank.onFile === s.bank.onInvoice;
  const card = (k: string, last4: string, side: number) => (
    <motion.div className={`bcard ${!same && side === 1 ? "bad" : ""}`} initial={{ x: side ? 120 : -120, opacity: 0 }}
      animate={on ? (same ? { x: side ? -34 : 34, opacity: 1 } : { x: [side ? 120 : -120, side ? -20 : 20, side ? 14 : -14], opacity: 1 }) : {}}
      transition={same ? { type: "spring", stiffness: 140, damping: 16 } : { duration: 0.8, times: [0, 0.6, 1] }}>
      <span className="bk">{k}</span>
      <span className="bstripe">{stripes(last4).map((c, i) => <i key={i} style={{ background: c }} />)}</span>
      <b>•••• {last4}</b><em>{s.bank.bankName}</em>
    </motion.div>
  );
  return (
    <div className={`banks ${same ? "same" : "diff"}`}>
      {card("On file", s.bank.onFile, 0)}
      <motion.span className="bmid" initial={{ scale: 0 }} animate={{ scale: on ? 1 : 0 }} transition={{ delay: 0.7 }}>{same ? "=" : "≠"}</motion.span>
      {card("On this invoice", s.bank.onInvoice, 1)}
    </div>
  );
}

/** Character diff (LCS) so a look-alike domain shows exactly where it differs. */
function diff(a: string, b: string) {
  const m = a.length, n = b.length, dp = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const ka = new Set<number>(), kb = new Set<number>();
  for (let i = 0, j = 0; i < m && j < n;) { if (a[i] === b[j]) { ka.add(i++); kb.add(j++); } else if (dp[i + 1][j] >= dp[i][j + 1]) i++; else j++; }
  return { ka, kb };
}
function Domain({ a, b, on }: { a: string; b: string; on: boolean }) {
  const { ka, kb } = diff(a, b);
  const same = a === b;
  return (
    <motion.div className={`domain ${same ? "same" : "diff"}`} initial={{ opacity: 0 }} animate={{ opacity: on ? 1 : 0 }}>
      <div><span className="dk">known domain</span><code>{[...a].map((c, i) => <span key={i} className={ka.has(i) ? "" : "miss"}>{c}</span>)}</code></div>
      <div><span className="dk">email came from</span><code>{[...b].map((c, i) => <span key={i} className={kb.has(i) ? "" : "add"}>{c}</span>)}</code></div>
      {!same && <p>Look-alike domain</p>}
    </motion.div>
  );
}

function Wipe({ s, on }: { s: Scenario; on: boolean }) {
  const [pos, setPos] = useState(100);
  useEffect(() => { if (!on) return; const t = setTimeout(() => setPos(52), 400); return () => clearTimeout(t); }, [on]);
  const mini = (no: string, paid: boolean) => (
    <div className="minidoc">
      <b>{s.vendor}</b><span>{no}</span>
      {s.lines.map((l) => <span key={l.sku} className="ml"><i />{l.amount}</span>)}
      <span className="mt">{s.currency} {s.invoice.total}</span>
      {paid && <span className="paidst">PAID {s.duplicate!.paidOn}</span>}
    </div>
  );
  return (
    <div className="wipe">
      <div className="wipe-box">
        {mini(s.duplicate!.paidNo, true)}
        <motion.div className="wipe-top" animate={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} transition={{ type: "spring", stiffness: 120, damping: 20 }}>{mini(s.invoice.no, false)}</motion.div>
        <motion.span className="wipe-h" animate={{ left: `${pos}%` }} transition={{ type: "spring", stiffness: 120, damping: 20 }}><i>⟷</i></motion.span>
        <input type="range" min={0} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))} aria-label="Compare with the invoice already paid" />
      </div>
      <p><b>Same lines, same amounts</b> as {s.duplicate!.paidNo}, paid {s.duplicate!.paidOn}. Drag to compare.</p>
    </div>
  );
}

function History({ on }: { on: boolean }) {
  return (
    <div className="hist">
      <div className="dots">{Array.from({ length: 96 }, (_, i) => (
        <motion.i key={i} initial={{ opacity: 0.25 }} animate={on ? { opacity: [0.25, 1, 0.35], scale: [1, 1.5, 1] } : {}} transition={{ delay: i * 0.008, duration: 0.5 }} />
      ))}</div>
      <p>Checked against every invoice already paid · <b>no match</b></p>
    </div>
  );
}

export function MoneyBar({ s, on, big = false }: { s: Scenario; on: boolean; big?: boolean }) {
  const total = Number(s.invoice.total.replace(/,/g, "")), pay = Number(s.payNow.replace(/,/g, ""));
  const p = total ? pay / total : 0;
  return (
    <div className={`money ${big ? "big" : ""}`}>
      <div className="mbar">
        <motion.span className="m-pay" initial={{ width: 0 }} animate={{ width: on ? `${p * 100}%` : 0 }} transition={{ type: "spring", stiffness: 70, damping: 16 }} />
        <motion.span className="m-hold" initial={{ width: 0 }} animate={{ width: on ? `${(1 - p) * 100}%` : 0 }} transition={{ type: "spring", stiffness: 70, damping: 16, delay: 0.15 }} />
      </div>
      <div className="mlegend">
        <span className="lp"><i />Pay now <b>{s.currency} {s.payNow}</b></span>
        {s.held !== "0" && <span className="lh"><i />Hold <b>{s.currency} {s.held}</b><em>{s.heldReason}</em></span>}
      </div>
    </div>
  );
}
