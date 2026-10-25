import type { FC } from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Icon, type IconName, SplitFlap } from "../components";
import { clamp, easeInOut, glassW as glass, prog, ui, W as C } from "../theme";

// Scene 2, the turnaround time today, told visually: a split-flap board counts up to 17.4 days while one invoice limps
// between the tools AP checks it against (icons only), an hourglass at each stop, never reaching "Paid".
// Source: Ardent Partners, The State of ePayables 2024: "3.1 days vs. 17.4 days to process a single invoice"
// (best-in-class vs. everyone else).
export const TAT_FRAMES = 180;

const DAYS = 17.4;
const COUNT = [12, 132];   // the counter runs over these frames
const daysAt = (f: number) => interpolate(f, COUNT, [0, DAYS], { ...clamp, easing: easeInOut });
// the board updates every 3 frames so each flip has time to land
const board = (f: number) => daysAt(Math.floor(f / 3) * 3).toFixed(1).padStart(4, " ");

const STOPS: { icon: IconName; label: string }[] = [
  { icon: "mail", label: "Inbox" }, { icon: "sheet", label: "Receiving" }, { icon: "window", label: "ERP · PO" },
  { icon: "chat", label: "Vendor" }, { icon: "shield", label: "Approval" }, { icon: "bank", label: "Paid" },
];
const ROW_Y = 660;
const stopX = (i: number) => 330 + i * 252;

export const Tat: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const head = spring({ frame, fps, config: { damping: 16, stiffness: 110 } });
  // the invoice limps through the first five stops and stalls before "Paid"
  const hop = interpolate(frame, [20, 140], [0, 4], { ...clamp, easing: easeInOut });
  const at = Math.floor(hop);
  const t = hop - at;
  const x = stopX(at) + (stopX(Math.min(at + 1, 5)) - stopX(at)) * t;
  const y = ROW_Y - 72 - Math.sin(t * Math.PI) * 60;

  return (
    <AbsoluteFill style={{ fontFamily: ui, color: C.text }}>
      {/* the number, on a split-flap board */}
      <div style={{ position: "absolute", top: 70, width: "100%", display: "flex", flexDirection: "column", alignItems: "center", opacity: head,
        transform: `translateY(${(1 - head) * 40}px)` }}>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 26 }}>
          <SplitFlap value={board} size={170} />
          <span style={{ fontSize: 104, fontWeight: 800, letterSpacing: -3, lineHeight: 1, marginBottom: 8 }}>days</span>
        </div>
      </div>

      {/* the bill's route through the tools */}
      <svg width={1920} height={1080} style={{ position: "absolute" }}>
        <line x1={stopX(0)} y1={ROW_Y} x2={stopX(5)} y2={ROW_Y} stroke="rgba(15,18,34,0.15)" strokeWidth={4} strokeDasharray="8 12" />
        <line x1={stopX(0)} y1={ROW_Y} x2={x} y2={ROW_Y} stroke={C.amber} strokeWidth={4} />
      </svg>
      {STOPS.map((s, i) => {
        const p = prog(frame, 8 + i * 5, 26 + i * 5);
        const last = i === STOPS.length - 1;
        const waiting = !last && at === i && t < 0.5 && frame > 20;
        return (
          <div key={s.label} style={{ position: "absolute", left: stopX(i), top: ROW_Y, transform: `translate(-50%, -50%) scale(${0.8 + 0.2 * p})`, opacity: p * (last ? 0.45 : 1) }}>
            <div style={{ ...glass, width: 96, height: 96, borderRadius: 26, display: "flex", alignItems: "center", justifyContent: "center",
              borderColor: waiting ? C.amber : undefined, boxShadow: waiting ? `0 0 30px rgba(217,119,6,0.35)` : glass.boxShadow }}>
              <Icon name={s.icon} size={48} color={last ? C.muted : C.text} />
            </div>
            {waiting && <div style={{ position: "absolute", top: -26, right: -26, width: 46, height: 46, borderRadius: 23, background: C.amber, fontSize: 26,
              display: "flex", alignItems: "center", justifyContent: "center", transform: `rotate(${Math.sin(frame * 0.3) * 20}deg)` }}>⏳</div>}
          </div>
        );
      })}
      <div style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)", opacity: prog(frame, 16, 26) }}>
        <div style={{ width: 70, height: 88, borderRadius: 12, background: "#fff", border: `1px solid ${C.line}`, display: "flex", alignItems: "center",
          justifyContent: "center", boxShadow: "0 16px 40px rgba(15,18,34,0.18)" }}>
          <Icon name="doc" size={50} color={C.text} width={2.6} />
        </div>
      </div>

      <div style={{ position: "absolute", right: 40, bottom: 30, fontSize: 15, color: C.muted, opacity: 0.8 * prog(frame, 40, 60) }}>
        Source: Ardent Partners, State of ePayables 2024
      </div>
      <Caption light text="One invoice. 17.4 days." duration={TAT_FRAMES} start={30} />
    </AbsoluteFill>
  );
};
