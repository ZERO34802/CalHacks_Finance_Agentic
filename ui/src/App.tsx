// Shell. Owner: D. The nav is the logo's chevron run: the six rooms read as one forward flow.
// Presence (top right) shows the crew like collaborators in a shared doc; whoever is working lights up.
import { AnimatePresence, motion } from "framer-motion";
import { lazy, Suspense, useEffect, useState } from "react";
import { api, subscribe } from "./api";
import Avatar from "./components/Avatar";
import { AGENTS } from "./story";
import type { Event } from "./types/contracts";

const Floor = lazy(() => import("./views/Floor"));
const Crew = lazy(() => import("./views/Crew"));
const Workspace = lazy(() => import("./views/Workspace"));
const YourTurn = lazy(() => import("./views/YourTurn"));
const Files = lazy(() => import("./views/Files"));
const Audit = lazy(() => import("./views/Audit"));

export type LiveProps = { tick: number; lastEvent: Event | null; route: string[]; active: string | null };
export const go = (path: string) => { location.hash = path; };

const ROOMS = [
  { path: "", label: "Floor" }, { path: "crew", label: "Crew" }, { path: "work", label: "Workspace" },
  { path: "turn", label: "Your turn" }, { path: "files", label: "Files" }, { path: "audit", label: "Audit" },
];

function useRoute() {
  const read = () => location.hash.replace(/^#\/?/, "").split("/");
  const [r, setR] = useState(read);
  useEffect(() => {
    const on = () => { setR(read()); window.scrollTo({ top: 0 }); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r;
}

export default function App() {
  const route = useRoute();
  const [tick, setTick] = useState(0);
  const [lastEvent, setLastEvent] = useState<Event | null>(null);
  const [live, setLive] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [needs, setNeeds] = useState(0);

  useEffect(() => subscribe((e) => {
    setLastEvent(e);
    if (e.type === "case.updated") setTick((t) => t + 1);
    if (e.step) setActive(e.step.stage);
  }, setLive), []);
  useEffect(() => { if (!active) return; const t = setTimeout(() => setActive(null), 1800); return () => clearTimeout(t); }, [active, lastEvent]);
  useEffect(() => { api.queue().then((q) => setNeeds(q.length)).catch(() => setNeeds(0)); }, [tick, route[0]]);

  const room = route[0] ?? "";
  const props: LiveProps = { tick, lastEvent, route, active };
  const page = room === "crew" ? <Crew {...props} /> : room === "work" ? <Workspace {...props} /> : room === "turn" ? <YourTurn {...props} />
    : room === "files" ? <Files {...props} /> : room === "audit" ? <Audit {...props} /> : <Floor {...props} />;

  return (
    <div className="app">
      <header className="bar">
        <a href="#/" className="logo" aria-label="ReconAI"><span>RECON</span><i>-</i><span>AI</span><Chevrons /></a>
        <nav className="run">
          {ROOMS.map((r, i) => (
            <a key={r.label} href={`#/${r.path}`} className={room === r.path ? "on" : ""}>
              {i > 0 && <Chevrons small />}<span>{r.label}</span>{r.path === "turn" && needs > 0 && <b>{needs}</b>}
            </a>
          ))}
        </nav>
        <div className="presence" title={live ? "Live: the crew's actions stream in" : "Not connected to the live trace"}>
          {AGENTS.map((a) => <Avatar key={a.id} id={a.id} kind={a.kind} size={22} on={active === a.id} title={`${a.name} · ${a.engine}`} />)}
          <span className="av human" style={{ width: 26, height: 26 }}><b>YOU</b></span>
          <i className={`livedot ${live ? "on" : ""}`} />
        </div>
      </header>
      <AnimatePresence mode="wait">
        <motion.main key={room + (room === "work" ? route[1] ?? "" : "")} className="room"
          initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.32, ease: [0.2, 0.7, 0.2, 1] }}>
          <Suspense fallback={<div className="boot"><i /></div>}>{page}</Suspense>
        </motion.main>
      </AnimatePresence>
    </div>
  );
}

export function Chevrons({ small = false }: { small?: boolean }) {
  return (
    <svg className={`chev ${small ? "s" : ""}`} viewBox="0 0 30 16" aria-hidden>
      {[0, 8, 16].map((x, i) => <path key={x} d={`M${x} 0h5l7 8-7 8h-5l7-8z`} style={{ animationDelay: `${i * 0.12}s` }} />)}
    </svg>
  );
}
