import type { FC } from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Icon, type IconName } from "../components";
import { C, easeInOut, glass, prog, ui } from "../theme";

// Scene 2, the old way: a bill drops into an empty inbox with a "?" over it. Everything AP would need to check it is
// scattered in six other tools; dashed lines reach from the bill toward each one and fall short.
// The tiles show the status quo, not ReconAI, so they are generic and carry no product claims.
export const OLD_WAY_FRAMES = 150;

export const BILL_AT = { x: 960, y: 430 };   // where the bill rests; the next scene picks it up from here
const TOOLS: { icon: IconName; label: string }[] = [
  { icon: "mail", label: "Re: Re: Re: pricing" }, { icon: "doc", label: "contract.pdf" }, { icon: "window", label: "ERP · PO" },
  { icon: "sheet", label: "receiving.xlsx" }, { icon: "shield", label: "Approval portal" }, { icon: "chat", label: "Chat" },
];
const toolPos = (i: number) => {
  const a = -Math.PI / 2 + Math.PI / 6 + (i * Math.PI * 2) / TOOLS.length;
  return { x: BILL_AT.x + Math.cos(a) * 690, y: BILL_AT.y + Math.sin(a) * 330 };
};

export const BillTile: FC<{ size?: number }> = ({ size = 1 }) => (
  <div style={{ width: 190 * size, height: 240 * size, borderRadius: 22 * size, background: C.tile, display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center", gap: 10 * size, boxShadow: "0 30px 70px rgba(0,0,0,0.55)", fontFamily: ui, color: C.ink }}>
    <Icon name="doc" size={110 * size} color={C.ink} width={2.4} />
    <div style={{ fontSize: 26 * size, fontWeight: 800 }}>Invoice</div>
  </div>
);

export const OldWay: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inbox = spring({ frame, fps, config: { damping: 16, stiffness: 110 } });
  const drop = spring({ frame: frame - 14, fps, config: { damping: 11, stiffness: 120 } });
  const q = spring({ frame: frame - 40, fps, config: { damping: 8, stiffness: 160 } });
  const pulse = 1 + 0.08 * Math.sin(Math.max(0, frame - 40) * 0.22);

  return (
    <AbsoluteFill style={{ fontFamily: ui, color: C.text }}>
      {/* six tools, far away and faded, drifting */}
      {TOOLS.map((t, i) => {
        const p = toolPos(i);
        const s = prog(frame, 6 + i * 4, 30 + i * 4);
        return (
          <div key={t.label} style={{ ...glass, position: "absolute", left: p.x + Math.sin(frame * 0.03 + i) * 14, top: p.y + Math.cos(frame * 0.025 + i * 2) * 10,
            transform: "translate(-50%, -50%)", opacity: 0.42 * s, borderRadius: 20, padding: "16px 22px", display: "flex", alignItems: "center", gap: 12,
            background: "rgba(20,22,30,0.6)", filter: "blur(0.6px)" }}>
            <Icon name={t.icon} size={38} color="#c8ccd6" />
            <span style={{ fontSize: 22, fontWeight: 600, whiteSpace: "nowrap", color: "#c8ccd6" }}>{t.label}</span>
          </div>
        );
      })}

      {/* the inbox, with one bill in it */}
      <div style={{ ...glass, position: "absolute", left: BILL_AT.x - 230, top: BILL_AT.y - 200, width: 460, height: 400, borderRadius: 30,
        background: "rgba(20,22,30,0.55)", opacity: inbox, transform: `scale(${0.9 + 0.1 * inbox})` }}>
        <div style={{ position: "absolute", left: 26, top: 22, display: "flex", alignItems: "center", gap: 12, color: C.muted, fontSize: 22, fontWeight: 600 }}>
          <Icon name="mail" size={30} color={C.muted} /> AP inbox
        </div>
      </div>
      {/* reaching lines: each stops ~40% short of its tool */}
      <svg width={1920} height={1080} style={{ position: "absolute" }}>
        {TOOLS.map((_, i) => {
          const p = toolPos(i);
          const reach = 0.6 * prog(frame, 52 + i * 5, 84 + i * 5, easeInOut);
          const x = BILL_AT.x + (p.x - BILL_AT.x) * reach;
          const y = BILL_AT.y + (p.y - BILL_AT.y) * reach;
          const flicker = reach > 0.55 ? 0.5 + 0.5 * Math.sin(frame * 0.6 + i) : 1;
          return (
            <g key={i} opacity={0.75 * flicker}>
              <line x1={BILL_AT.x} y1={BILL_AT.y} x2={x} y2={y} stroke={C.red} strokeWidth={3} strokeDasharray="10 12" strokeLinecap="round" />
              {reach > 0.05 && <circle cx={x} cy={y} r={6} fill={C.red} />}
            </g>
          );
        })}
      </svg>

      <div style={{ position: "absolute", left: BILL_AT.x, top: BILL_AT.y + 20, transform: `translate(-50%, -50%) translateY(${(1 - drop) * -520}px) rotate(${(1 - drop) * -14}deg)`,
        opacity: frame < 14 ? 0 : 1 }}>
        <BillTile size={0.95} />
        <div style={{ position: "absolute", top: -34, right: -34, width: 76, height: 76, borderRadius: 38, background: C.amber, color: "#1a1200",
          fontWeight: 800, fontSize: 50, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 ${30 * q}px ${C.amber}`,
          transform: `scale(${q * pulse})`, border: `5px solid ${C.bg}` }}>?</div>
      </div>

      <Caption text="The bill shouldn't be the first thing AP sees." duration={OLD_WAY_FRAMES} start={16} />
    </AbsoluteFill>
  );
};
