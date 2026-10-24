// Pictograms: what Helix actually buys, drawn so quantities can be SEEN, not read.
import type { Unit } from "./scenarios";

export function UnitIcon({ unit, size = 16, state = "ok" }: { unit: Unit; size?: number; state?: "ok" | "missing" | "extra" | "ghost" }) {
  const cls = `u u-${state}`;
  switch (unit) {
    case "wafer": return (
      <svg className={cls} width={size} height={size} viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" />
        <path d="M3 6h10M3 10h10M6 3v10M10 3v10" className="u-grid" /><path d="M6.5 15h3" className="u-notch" /></svg>);
    case "chip": return (
      <svg className={cls} width={size} height={size} viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="1.5" />
        <path d="M4 6h8M4 8h8M4 10h8" className="u-grid" /></svg>);
    case "package": return (
      <svg className={cls} width={size} height={size} viewBox="0 0 16 16"><rect x="3.5" y="3.5" width="9" height="9" rx="1" />
        <path d="M1 6h2.5M1 10h2.5M12.5 6H15M12.5 10H15M6 1v2.5M10 1v2.5M6 12.5V15M10 12.5V15" className="u-pin" /></svg>);
    default: return (
      <svg className={cls} width={size} height={size} viewBox="0 0 16 16"><path d="M8 1.5 14.5 5v6L8 14.5 1.5 11V5z" />
        <path d="M1.5 5 8 8.5 14.5 5M8 8.5v6" className="u-grid" /></svg>);
  }
}

export const Bank = ({ size = 44 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 44 44" className="ics"><path d="M4 16 22 5l18 11z" /><path d="M9 19v13M17 19v13M27 19v13M35 19v13" /><path d="M4 35h36M6 39h32" /></svg>);
export const Envelope = ({ size = 22 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 22 22" className="ics"><rect x="2" y="5" width="18" height="13" rx="2" /><path d="m3 7 8 6 8-6" /></svg>);
export const Lock = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 18 18" className="ic"><rect x="3" y="8" width="12" height="8" rx="2" /><path d="M6 8V5.5a3 3 0 0 1 6 0V8" className="ic-l" /></svg>);
export const Phone = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 18 18" className="ic"><path d="M5 2h3l1.5 4-2 1.3a9 9 0 0 0 3.2 3.2L12 8.5l4 1.5v3a2 2 0 0 1-2 2A12 12 0 0 1 3 4a2 2 0 0 1 2-2z" /></svg>);
export const Shield = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" className="ic"><path d="M8 1.5 14 4v4c0 3.4-2.6 5.8-6 6.5C4.6 13.8 2 11.4 2 8V4z" /></svg>);
export const Coin = () => <span className="coin" />;
