import type { CSSProperties, FC, ReactNode } from "react";
import { LogoTile } from "../components";

// Slack, as the product looks in the workspace screenshots: light theme, aubergine sidebar, APP tags, green buttons.
export const SL = { side: "#3f0e40", top: "#350d36", sideText: "#d9c7da", active: "#f4e6f5", text: "#1d1c1d", muted: "#616061", line: "#e4e4e4",
  eph: "#f6f6f6", green: "#007a5a", code: "#e01e5a" };

export const Av: FC<{ bg: string; children: ReactNode; size?: number; dim?: number }> = ({ bg, children, size = 52, dim = 0 }) => (
  <div style={{ width: size, height: size, borderRadius: size * 0.2, background: bg, display: "flex", alignItems: "center", justifyContent: "center",
    color: "#fff", fontWeight: 800, fontSize: size * 0.44, flexShrink: 0, opacity: 1 - 0.7 * dim, overflow: "hidden" }}>{children}</div>
);
export const BotAv = () => <Av bg="#fff"><LogoTile size={50} /></Av>;

export const Chip: FC<{ w?: number; color?: string; bg?: string; children: ReactNode; style?: CSSProperties }> = ({ w, color = SL.text, bg = "#f1f1f1", children, style }) => (
  <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, width: w, height: 40, borderRadius: 8, padding: w ? 0 : "0 14px",
    background: bg, color, fontSize: 20, fontWeight: 700, border: "1px solid rgba(0,0,0,0.08)", boxSizing: "border-box", whiteSpace: "nowrap", ...style }}>{children}</span>
);
export const AppTag = () => <span style={{ fontSize: 13, fontWeight: 700, background: "#e8e8e8", color: SL.muted, padding: "2px 6px", borderRadius: 4, marginLeft: 8, verticalAlign: 3 }}>APP</span>;
