// Minimal shell so the skeleton is visible end to end. Owner: D (replace freely).
import { useEffect, useState } from "react";
import { api, API_URL, subscribe } from "./api";
import type { Case, CaseDetail, Scoreboard } from "./types/contracts";

export default function App() {
  const [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    api.cases().then(setCases).catch((e) => setError(String(e)));
    api.scoreboard().then(setBoard).catch(() => setBoard(null));
  };
  useEffect(refresh, []);
  useEffect(() => {
    if (selected) api.case(selected).then(setDetail).catch((e) => setError(String(e)));
  }, [selected]);
  useEffect(() => subscribe((e) => {
    refresh();
    if (e.case_id === selected) api.case(e.case_id).then(setDetail);
  }), [selected]);

  return (
    <div className="app">
      <header>
        <h1>ReconAI</h1>
        <span className="muted">API: {API_URL}</span>
      </header>
      {error && <p className="error">{error}</p>}
      {board && (
        <section className="board">
          <strong>{board.passed}/{board.total} passed</strong>
          <span>catch {pct(board.catch_rate)}</span>
          <span>false alarm {pct(board.false_alarm_rate)}</span>
          <span>invariants {pct(board.invariant_pass_rate)}</span>
        </section>
      )}
      <main>
        <ul className="cases">
          {cases.map((c) => (
            <li key={c.id} className={c.id === selected ? "active" : ""} onClick={() => setSelected(c.id)}>
              <b>{c.id}</b> {c.vendor_id}
              <span className={`pill ${c.status}`}>{c.status}</span>
              <div className="muted">{c.invoice?.invoice_no} · {c.invoice?.total} {c.invoice?.currency}</div>
            </li>
          ))}
        </ul>
        <section className="detail">
          {detail ? (
            <>
              <h2>{detail.case.id} · decision: {detail.case.decision ?? "-"}</h2>
              <ol className="pipeline">
                {detail.steps.map((s) => (
                  <li key={s.id} className={`step ${s.status}`} title={s.error ?? ""}>
                    <span>{s.stage}</span>
                    <small>{s.role} · {s.status} · {s.duration_ms ?? "…"}ms</small>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <p className="muted">Select a case</p>
          )}
        </section>
      </main>
    </div>
  );
}

const pct = (x: number) => `${Math.round(x * 100)}%`;
