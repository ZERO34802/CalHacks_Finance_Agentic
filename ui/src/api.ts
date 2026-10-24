// Switching mock -> real backend is just VITE_API_URL.
import type {
  ApprovalRequest, BusinessMetrics, Case, CaseDetail, Event, FailureItem, MemoryEntry, QueueItem, Scoreboard, StageStat, Vendor,
} from "./types/contracts";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:4010";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, init);
  if (!r.ok) throw new Error(`${init?.method ?? "GET"} ${path}: ${r.status}`);
  return r.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export const api = {
  cases: () => call<Case[]>("/cases"),
  case: (id: string) => call<CaseDetail>(`/cases/${id}`),
  runCase: (c: Case) => post<CaseDetail>("/cases", c),
  fixtures: () => call<Case[]>("/fixtures"),
  approve: (id: string, req: ApprovalRequest) => post<Case>(`/approvals/${id}`, req),
  vendors: () => call<Vendor[]>("/vendors"),
  vendor: (id: string) => call<Vendor>(`/vendors/${id}`),
  memory: () => call<MemoryEntry[]>("/memory"),
  scoreboard: () => call<Scoreboard>("/evals/scoreboard"),
  runEval: () => post<Scoreboard>("/evals/run"),
  queue: () => call<QueueItem[]>("/dashboard/queue"),
  metrics: () => call<BusinessMetrics>("/dashboard/metrics"),
  failures: () => call<FailureItem[]>("/dashboard/failures"),
  stages: () => call<StageStat[]>("/dashboard/stages"),
};

// Live step updates. Only the real backend serves WS (Prism can't); the mock just won't connect.
export function subscribe(onEvent: (e: Event) => void, onState?: (live: boolean) => void): () => void {
  const ws = new WebSocket(API_URL.replace(/^http/, "ws") + "/events");
  ws.onopen = () => onState?.(true);
  ws.onclose = () => onState?.(false);
  ws.onmessage = (m) => onEvent(JSON.parse(m.data) as Event);
  return () => ws.close();
}
