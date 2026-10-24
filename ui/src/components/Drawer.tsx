// Source document drawer. Document text is UNTRUSTED: rendered as plain text only, never as HTML.
import { motion } from "framer-motion";
import type { Case } from "../types/contracts";

export default function Drawer({ c, id, onClose }: { c: Case; id: string; onClose: () => void }) {
  const d = c.documents.find((x) => x.id === id);
  return (
    <>
      <motion.div className="scrim" onClick={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
      <motion.aside className="drawer" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 260, damping: 30 }}>
        <button className="close" onClick={onClose}>Close ✕</button>
        {d ? (
          <>
            <span className="k">{d.kind} · via {d.channel}</span>
            <h3>{d.filename}</h3>
            <span className="mono dim">{d.sender ?? "internal"} · sha {d.sha256.slice(0, 12)}…</span>
            <pre className="doctext">{d.text ?? "(no text)"}</pre>
            <span className="k warn">Untrusted · shown, never obeyed</span>
          </>
        ) : <p className="dim">Document {id} isn't attached.</p>}
      </motion.aside>
    </>
  );
}
