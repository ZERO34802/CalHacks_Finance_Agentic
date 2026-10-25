import type { FC, ReactNode } from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, LogoTile } from "../components";
import { C, clamp, easeInOut, glass, ui } from "../theme";

// Scene 3: the five channels we support sit on a ring; documents fly from each one into ReconAI in the centre.
export const CHANNELS_FRAMES = 150;

const CX = 960;
const CY = 450;
const R = 360;

const stroke = { fill: "none", stroke: "#fff", strokeWidth: 2.4, strokeLinecap: "round", strokeLinejoin: "round" } as const;
const ICONS: { label: string; icon: ReactNode }[] = [
  { label: "Email", icon: <><rect x={6} y={11} width={36} height={26} rx={4} {...stroke} /><polyline points="7,13 24,26 41,13" {...stroke} /></> },
  { label: "API", icon: <><path d="M17 10 Q10 10 10 17 V21 Q10 24 6 24 Q10 24 10 27 V31 Q10 38 17 38" {...stroke} /><path d="M31 10 Q38 10 38 17 V21 Q38 24 42 24 Q38 24 38 27 V31 Q38 38 31 38" {...stroke} /></> },
  { label: "SFTP", icon: <><path d="M6 15 Q6 11 10 11 H19 L23 15 H38 Q42 15 42 19 V34 Q42 38 38 38 H10 Q6 38 6 34 Z" {...stroke} /><polyline points="19,27 24,22 29,27" {...stroke} /><line x1={24} y1={22} x2={24} y2={33} {...stroke} /></> },
  { label: "ERP", icon: <><ellipse cx={24} cy={12} rx={15} ry={5} {...stroke} /><path d="M9 12 V36 Q9 41 24 41 Q39 41 39 36 V12" {...stroke} /><path d="M9 24 Q9 29 24 29 Q39 29 39 24" {...stroke} /></> },
  { label: "Slack", icon: <><line x1={18} y1={8} x2={14} y2={40} {...stroke} /><line x1={34} y1={8} x2={30} y2={40} {...stroke} /><line x1={8} y1={18} x2={41} y2={18} {...stroke} /><line x1={7} y1={30} x2={40} y2={30} {...stroke} /></> },
];

// position on the ring, starting at the top and going clockwise
const at = (i: number) => {
  const a = -Math.PI / 2 + (i * 2 * Math.PI) / ICONS.length;
  return { x: CX + R * Math.cos(a), y: CY + R * Math.sin(a) * 0.78 };
};

// two documents per channel, staggered so arrivals are spread across the scene
const FLIGHTS = ICONS.flatMap((_, i) => [0, 1].map((k) => ({ ch: i, start: 34 + i * 8 + k * 38, len: 38 })));

export const Channels: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // centre node pulses once per arrival
  const pulse = FLIGHTS.reduce((acc, f) => {
    const t = frame - (f.start + f.len);
    return Math.max(acc, t >= 0 && t < 12 ? 1 - t / 12 : 0);
  }, 0);
  const node = spring({ frame, fps, config: { damping: 14, stiffness: 120 } });

  return (
    <AbsoluteFill>
      {/* faint ring */}
      <svg width={1920} height={1080} style={{ position: "absolute" }}>
        <ellipse cx={CX} cy={CY} rx={R} ry={R * 0.78} fill="none" stroke={C.line} strokeWidth={2} strokeDasharray="6 10"
          opacity={interpolate(frame, [0, 20], [0, 1], clamp)} />
      </svg>

      {/* centre: ReconAI */}
      <div style={{ position: "absolute", left: CX, top: CY, transform: `translate(-50%, -50%) scale(${(0.7 + 0.3 * node) * (1 + 0.08 * pulse)})` }}>
        <div style={{ position: "absolute", inset: -18 - 22 * pulse, borderRadius: 60, border: `3px solid ${C.cyan}`, opacity: 0.3 + 0.7 * pulse, boxShadow: `0 0 ${20 + 40 * pulse}px rgba(34,211,238,0.5)` }} />
        <LogoTile size={170} />
      </div>

      {/* documents in flight: quadratic curve bending away from the straight line, eased */}
      {FLIGHTS.map((f, j) => {
        const t = interpolate(frame, [f.start, f.start + f.len], [0, 1], { ...clamp, easing: easeInOut });
        if (frame < f.start || t >= 1) return null;
        const p0 = at(f.ch);
        const ctrl = { x: (p0.x + CX) / 2 + (p0.y - CY) * 0.35, y: (p0.y + CY) / 2 - (p0.x - CX) * 0.35 };
        const x = (1 - t) ** 2 * p0.x + 2 * (1 - t) * t * ctrl.x + t ** 2 * CX;
        const y = (1 - t) ** 2 * p0.y + 2 * (1 - t) * t * ctrl.y + t ** 2 * CY;
        return (
          <div key={j} style={{
            position: "absolute", left: x, top: y, width: 44, height: 56, borderRadius: 6, background: "#fff",
            transform: `translate(-50%, -50%) rotate(${(1 - t) * 18}deg) scale(${1 - 0.5 * t})`, opacity: 1 - t * 0.3,
            boxShadow: "0 8px 20px rgba(0,0,0,0.5)", padding: 8, boxSizing: "border-box",
          }}>
            {[1, 0.7, 0.85, 0.5].map((w, k) => <div key={k} style={{ height: 4, width: `${w * 100}%`, background: "#ccc", borderRadius: 2, marginBottom: 5 }} />)}
          </div>
        );
      })}

      {/* channel icons */}
      {ICONS.map((ch, i) => {
        const p = at(i);
        const s = spring({ frame: frame - 4 - i * 4, fps, config: { damping: 13, stiffness: 140 } });
        return (
          <div key={ch.label} style={{
            position: "absolute", left: p.x, top: p.y, transform: `translate(-50%, -50%) scale(${s})`,
            display: "flex", flexDirection: "column", alignItems: "center", gap: 12,
          }}>
            <div style={{ ...glass, width: 112, height: 112, borderRadius: 28,
              display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg viewBox="0 0 48 48" width={60} height={60}>{ch.icon}</svg>
            </div>
            <div style={{ fontFamily: ui, fontWeight: 500, fontSize: 22, color: C.muted }}>{ch.label}</div>
          </div>
        );
      })}

      <Caption text="Every channel. One place." duration={CHANNELS_FRAMES} start={10} />
    </AbsoluteFill>
  );
};
