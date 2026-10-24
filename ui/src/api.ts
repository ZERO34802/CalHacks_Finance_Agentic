// Switching mock -> real backend is just VITE_API_URL.
import type { Case, CaseDetail, Event, MemoryEntry, Scoreboard, Vendor } from "./types/contracts";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:4010";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  cases: () => get<Case[]>("/cases"),
  case: (id: string) => get<CaseDetail>(`/cases/${id}`),
  vendor: (id: string) => get<Vendor>(`/vendors/${id}`),
  memory: () => get<MemoryEntry[]>("/memory"),
  scoreboard: () => get<Scoreboard>("/evals/scoreboard"),
};

// Live step updates. Only the real backend serves WS (Prism can't); the mock just won't connect.
export function subscribe(onEvent: (e: Event) => void): () => void {
  const ws = new WebSocket(API_URL.replace(/^http/, "ws") + "/events");
  ws.onmessage = (m) => onEvent(JSON.parse(m.data) as Event);
  return () => ws.close();
}
