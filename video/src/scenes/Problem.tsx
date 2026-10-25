import type { FC } from "react";
import { AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Icon, type IconName } from "../components";
import { C, clamp, easeOut, ui } from "../theme";

// Scene 2: bills, emails and spreadsheets rain into a messy pile; red "!" badges pop on the bad ones while a counter
// ticks to $857k (README: caught before payment).
export const PROBLEM_FRAMES = 150;

const KINDS: IconName[] = ["doc", "mail", "sheet", "doc", "mail", "doc", "sheet", "doc", "mail", "doc", "doc", "sheet", "mail", "doc"];
const BAD = [1, 4, 7, 10, 12];
const TILE = 140;

export const Problem: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const count = interpolate(frame, [15, 125], [0, 857], { ...clamp, easing: easeOut });

  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", top: 60, width: "100%", textAlign: "center", fontFamily: ui, color: "#fff" }}>
        <div style={{ fontSize: 130, fontWeight: 800, letterSpacing: -4, fontVariantNumeric: "tabular-nums", textShadow: "0 0 50px rgba(255,84,112,0.45)" }}>${Math.round(count)}k</div>
        <div style={{ fontSize: 32, color: C.muted, marginTop: -8 }}>in bad bills</div>
      </div>

      {KINDS.map((kind, i) => {
        const start = 10 + i * 7;
        const s = spring({ frame: frame - start, fps, config: { damping: 14, stiffness: 110, mass: 0.9 } });
        const x = 960 + (random(`x${i}`) - 0.5) * 980;
        const y = 590 + (random(`y${i}`) - 0.5) * 240;
        const rot = (random(`r${i}`) - 0.5) * 50 + Math.sin(frame * 0.12 + i) * 2;
        const b = BAD.indexOf(i);
        const badge = b < 0 ? 0 : spring({ frame: frame - (92 + b * 9), fps, config: { damping: 9, stiffness: 180 } });
        return (
          <div key={i} style={{
            position: "absolute", left: x - TILE / 2, top: y - TILE / 2, width: TILE, height: TILE, borderRadius: 30,
            background: C.tile, display: "flex", alignItems: "center", justifyContent: "center",
            transform: `translateY(${(1 - s) * -800}px) rotate(${rot}deg)`, opacity: frame < start ? 0 : 1,
            boxShadow: "0 20px 50px rgba(0,0,0,0.6)", zIndex: i,
          }}>
            <Icon name={kind} size={84} color={C.ink} width={2.8} />
            {b >= 0 && (
              <div style={{
                position: "absolute", top: -16, right: -16, width: 52, height: 52, borderRadius: 26, background: C.red,
                color: "#fff", fontFamily: ui, fontWeight: 800, fontSize: 34, display: "flex", alignItems: "center",
                justifyContent: "center", transform: `scale(${badge})`, border: `4px solid ${C.bg}`, boxShadow: `0 0 ${20 * badge}px ${C.red}`,
              }}>!</div>
            )}
          </div>
        );
      })}

      <Caption text="Supplier bills are a mess." duration={PROBLEM_FRAMES} start={10} />
    </AbsoluteFill>
  );
};
