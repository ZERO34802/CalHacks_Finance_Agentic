// App-wide state: who's signed in, the bills (refreshed from the live feed), vendors, routing.
import { notifications } from "@mantine/notifications";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { subscribe } from "../api";
import type { Bill, Event, Vendor } from "../types/contracts";
import { ap } from "./api";
import { PEOPLE, type Seat } from "./format";

type Ctx = {
  bills: Bill[]; vendors: Record<string, Vendor>; refresh: () => void; live: boolean; lastEvent: Event | null;
  seat: Seat; setSeat: (s: Seat) => void; route: string[]; go: (path: string) => void;
};
const AppCtx = createContext<Ctx>(null as never);
export const useApp = () => useContext(AppCtx);

const readRoute = () => (location.hash.replace(/^#\/?/, "") || "home").split("/");

export function AppProvider({ children }: { children: ReactNode }) {
  const [bills, setBills] = useState<Bill[]>([]);
  const [vendors, setVendors] = useState<Record<string, Vendor>>({});
  const [live, setLive] = useState(false);
  const [lastEvent, setLastEvent] = useState<Event | null>(null);
  const [seat, setSeatState] = useState<Seat>(() => (localStorage.getItem("seat") as Seat) || "approver");
  const [route, setRoute] = useState(readRoute);

  const refresh = useCallback(() => { ap.bills().then(setBills).catch(() => {}); }, []);
  const go = (path: string) => { location.hash = `/${path}`; };
  const setSeat = (s: Seat) => { setSeatState(s); try { localStorage.setItem("seat", s); } catch { /* private mode */ } };

  useEffect(() => {
    refresh();
    ap.vendors().then((v) => setVendors(Object.fromEntries(v.map((x) => [x.id, x])))).catch(() => {});
    const on = () => { setRoute(readRoute()); window.scrollTo({ top: 0 }); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, [refresh]);

  useEffect(() => subscribe((e) => {
    setLastEvent(e);
    if (e.type === "case.updated" || e.type.startsWith("run.")) refresh();
    if (e.type === "run.finished") {
      ap.bills().then((bs) => {
        setBills(bs);
        const b = bs.find((x) => x.case_id === e.case_id);
        if (!b) return;
        const human = b.stage === "needs_review";
        notifications.show({
          title: human ? "Ready for review" : b.stage === "blocked" ? "Cleared by agents, but payment is blocked" : "Cleared by the agents",
          message: `${b.vendor_name} · ${b.invoice_no ?? b.case_id}. Click to open.`, autoClose: 7000,
          color: human ? "violet" : b.stage === "blocked" ? "red" : "brand",
          onClick: () => go(`bill/${b.case_id}`), style: { cursor: "pointer" },
        });
      });
    }
  }, setLive), [refresh]);

  return <AppCtx.Provider value={{ bills, vendors, refresh, live, lastEvent, seat, setSeat, route, go }}>{children}</AppCtx.Provider>;
}

export const me = (seat: Seat) => PEOPLE[seat];
