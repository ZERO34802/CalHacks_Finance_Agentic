// Files: one dossier per vendor. Master record, what the crew remembers (each line with its source in the
// margin), the vendor's cases, and the onboarding checks. Memory is read-only here: the Memory Writer adds
// lines only from trusted signals, never from incoming documents.
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api } from "../api";
import { go, type LiveProps } from "../App";
import { compact, date, titleCase } from "../format";
import { shortName, verdict } from "../story";
import type { Case, MemoryEntry, Vendor } from "../types/contracts";

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const CHECKS = ["Registry & credit", "Sanctions (OFAC)", "Liens & bankruptcies", "Duplicate vendor",
  "Bank vs employees", "Independent callback", "Domain age", "Tax form on file"];

export default function Files({ route, tick }: LiveProps) {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [q, setQ] = useState("");
  useEffect(() => { api.vendors().then(setVendors).catch(() => {}); api.memory().then(setMemory).catch(() => {}); }, []);
  useEffect(() => { api.cases().then(setCases).catch(() => {}); }, [tick]);

  const v = vendors.find((x) => x.id === route[1]) ?? vendors[0];
  const mem = v ? memory.filter((m) => m.subject === slug(shortName(v.name))) : [];
  const theirs = cases.filter((c) => c.vendor_id === v?.id);
  const n = q.trim().toLowerCase();
  const hits = n ? memory.filter((m) => `${m.subject} ${m.text} ${m.provenance}`.toLowerCase().includes(n)) : [];

  return (
    <div className="files">
      <section className="files-head">
        <h1 className="stencil">The files.</h1>
        <input className="find" placeholder="Search what the crew remembers…" value={q} onChange={(e) => setQ(e.target.value)} />
      </section>
      <nav className="tabs">
        {vendors.map((x, i) => (
          <button key={x.id} className={x.id === v?.id ? "on" : ""} style={{ zIndex: x.id === v?.id ? 10 : vendors.length - i }} onClick={() => go(`/files/${x.id}`)}>
            {shortName(x.name)}{x.critical && <i>critical</i>}
          </button>
        ))}
      </nav>
      <AnimatePresence mode="wait">
        {n ? (
          <motion.section key="search" className="dossier" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <span className="k">{hits.length} line{hits.length === 1 ? "" : "s"} match “{q}”</span>
            <Notes rows={hits} subject />
          </motion.section>
        ) : v && (
          <motion.section key={v.id} className="dossier" initial={{ opacity: 0, y: 16, rotateX: -6 }} animate={{ opacity: 1, y: 0, rotateX: 0 }}
            exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.35 }}>
            <div className="d-grid">
              <div>
                <span className="k">Vendor master · system of record</span>
                <h2 className="stencil">{shortName(v.name)}</h2>
                <span className="dim">{v.aliases.join(" · ")}</span>
                <dl className="master">
                  <div><dt className="k">Bank on file</dt><dd className="mono">•••• {v.bank_last4}</dd></div>
                  <div><dt className="k">Domain</dt><dd className="mono">{v.email_domain}</dd></div>
                  <div><dt className="k">Tax ID</dt><dd className="mono">{v.tax_id ?? "missing"}</dd></div>
                  <div><dt className="k">From</dt><dd className="mono">{v.country} · {v.currency}</dd></div>
                  <div><dt className="k">Sends via</dt><dd>{v.channels.join(" · ")}</dd></div>
                  <div><dt className="k">Status</dt><dd>{v.on_probation ? "probation" : "active"}{v.critical ? " · critical" : ""}</dd></div>
                </dl>
                <span className="k gap">What the crew remembers · context, never evidence</span>
                {mem.length ? <Notes rows={mem} /> : <p className="dim">Nothing remembered yet.</p>}
              </div>
              <div>
                <span className="k">Cases</span>
                <div className="strip">
                  {theirs.map((c) => {
                    const t = verdict(c.decision);
                    return (
                      <button key={c.id} className="chipdoc" onClick={() => go(`/work/${c.id}`)}>
                        <span className="mono">{c.invoice?.invoice_no}</span><b>{compact(c.invoice?.total)} {c.invoice?.currency}</b>
                        <span className={`tiny-stamp ${t.tone}`}>{t.word}</span>
                      </button>
                    );
                  })}
                  {theirs.length === 0 && <p className="dim">No cases yet.</p>}
                </div>
                <span className="k gap">Before any first payment</span>
                <ol className="checks">
                  {CHECKS.map((c, i) => (
                    <motion.li key={c} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + i * 0.04 }}>
                      <span className="box" /><span>{c}</span>
                    </motion.li>
                  ))}
                </ol>
                <p className="fine">Vendor Guard runs these on every new vendor and every bank change. A second person approves.</p>
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  );
}

function Notes({ rows, subject = false }: { rows: MemoryEntry[]; subject?: boolean }) {
  return (
    <ul className="notes">
      {rows.map((m, i) => (
        <motion.li key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
          <p>{subject && <b>{titleCase(m.subject)} · </b>}{m.text}</p>
          <span className="src mono">{m.provenance}<em>since {date(m.valid_from)}</em></span>
        </motion.li>
      ))}
    </ul>
  );
}
