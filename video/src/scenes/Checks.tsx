import type { FC, ReactNode } from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Icon, Mark } from "../components";
import { C, glass, prog, ui } from "../theme";

// Scene 4: one bill on the left, three checks as symbols on the right. 3-way match passes, duplicate check passes,
// the bank account flips to a new one and fails; a lock drops on the bill and it is HELD.
// Real Penang case from data/answer_key.json (PPT-6620, USD 3.3M, bank 9902 vs 4418 on file).
export const CHECKS_FRAMES = 210;

const ROW_T = [28, 76, 124];   // frame each check row starts
const HOLD = 168;              // frame the bill turns red and locks

const Pop: FC<{ at: number; children: ReactNode }> = ({ at, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 150 } });
  return <div style={{ transform: `scale(${s})`, opacity: Math.min(1, s * 2), display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>{children}</div>;
};

const Label: FC<{ children: ReactNode }> = ({ children }) => (
  <div style={{ fontFamily: ui, fontSize: 20, color: C.muted }}>{children}</div>
);

const Sign: FC<{ at: number; text: string; color?: string }> = ({ at, text, color = "#fff" }) => {
  const frame = useCurrentFrame();
  return <div style={{ fontFamily: ui, fontSize: 56, fontWeight: 700, color, opacity: prog(frame, at, at + 8), width: 60, textAlign: "center", marginBottom: 28 }}>{text}</div>;
};

const Row: FC<{ t: number; top: number; ok: boolean; children: ReactNode }> = ({ t, top, ok, children }) => {
  const frame = useCurrentFrame();
  const p = prog(frame, t - 8, t + 4);
  return (
    <div style={{
      ...glass, position: "absolute", left: 800, top, width: 820, height: 170, borderRadius: 28, display: "flex", alignItems: "center", padding: "0 44px", boxSizing: "border-box",
      opacity: p, transform: `translateX(${(1 - p) * 40}px)`,
    }}>
      <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 18 }}>{children}</div>
      <Mark ok={ok} p={prog(frame, t + 28, t + 40)} size={84} />
    </div>
  );
};

export const Checks: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const bill = spring({ frame, fps, config: { damping: 16, stiffness: 110 } });
  const red = prog(frame, HOLD, HOLD + 10);
  const shake = frame >= HOLD && frame < HOLD + 12 ? Math.sin((frame - HOLD) * 2.2) * (HOLD + 12 - frame) * 1.1 : 0;
  const lock = spring({ frame: frame - (HOLD + 6), fps, config: { damping: 10, stiffness: 170, mass: 0.8 } });
  const stamp = spring({ frame: frame - (HOLD + 14), fps, config: { damping: 9, stiffness: 160, mass: 0.7 } });
  const flip = prog(frame, ROW_T[2] + 14, ROW_T[2] + 22);  // bank account: old -> new

  return (
    <AbsoluteFill>
      {/* the bill */}
      <div style={{
        position: "absolute", left: 300, top: 150, width: 400, height: 560, borderRadius: 34, background: C.tile,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20,
        transform: `translateX(${shake}px) translateY(${(1 - bill) * 60}px)`, opacity: bill,
        boxShadow: `0 0 0 ${8 * red}px ${C.red}, 0 0 ${90 * red}px rgba(255,84,112,0.55), 0 30px 80px rgba(0,0,0,0.6)`,
      }}>
        <Icon name="doc" size={230} color={C.ink} width={2.2} />
        <div style={{ fontFamily: ui, fontSize: 76, fontWeight: 800, letterSpacing: -2, color: C.ink }}>$3.3M</div>

        {/* lock drops onto the bill */}
        <div style={{
          position: "absolute", top: 130, width: 160, height: 160, borderRadius: 80, background: C.red,
          display: "flex", alignItems: "center", justifyContent: "center", opacity: frame < HOLD + 6 ? 0 : 1,
          transform: `translateY(${(1 - lock) * -300}px) scale(${0.6 + 0.4 * lock})`, boxShadow: "0 10px 40px rgba(229,72,77,0.5)",
        }}>
          <Icon name="lock" size={96} width={3.2} />
        </div>
        <div style={{
          position: "absolute", bottom: -34, padding: "14px 40px", borderRadius: 16, background: C.red, color: "#fff",
          fontFamily: ui, fontSize: 48, fontWeight: 800, letterSpacing: 4, opacity: frame < HOLD + 14 ? 0 : 1,
          transform: `rotate(${-6 * stamp}deg) scale(${1.6 - 0.6 * stamp})`,
        }}>HELD</div>
      </div>

      {/* 1. three-way match: PO = receipt = invoice */}
      <Row t={ROW_T[0]} top={140} ok>
        <Pop at={ROW_T[0]}><Icon name="doc" size={72} /><Label>PO</Label></Pop>
        <Sign at={ROW_T[0] + 10} text="=" />
        <Pop at={ROW_T[0] + 6}><Icon name="box" size={72} /><Label>Received</Label></Pop>
        <Sign at={ROW_T[0] + 16} text="=" />
        <Pop at={ROW_T[0] + 12}><Icon name="doc" size={72} /><Label>Bill</Label></Pop>
      </Row>

      {/* 2. not a duplicate: this bill vs everything already paid */}
      <Row t={ROW_T[1]} top={345} ok>
        <Pop at={ROW_T[1]}><Icon name="doc" size={72} /><Label>Bill</Label></Pop>
        <Sign at={ROW_T[1] + 12} text="≠" />
        <Pop at={ROW_T[1] + 6}><Icon name="docs" size={72} /><Label>Paid</Label></Pop>
      </Row>

      {/* 3. bank account on the bill vs the one on file: flips to a new account and fails */}
      <Row t={ROW_T[2]} top={550} ok={false}>
        <Pop at={ROW_T[2]}><Icon name="bank" size={72} color={flip > 0.5 ? C.red : "#fff"} /><Label>Bank</Label></Pop>
        <div style={{ position: "relative", width: 260, height: 70, marginLeft: 20, marginBottom: 28, opacity: prog(frame, ROW_T[2] + 4, ROW_T[2] + 10) }}>
          {[["••4418", "#fff", 1 - flip, -flip * 40], ["••9902", C.red, flip, (1 - flip) * 40]].map(([t, c, o, dy]) => (
            <div key={t as string} style={{ position: "absolute", fontFamily: ui, fontSize: 52, fontWeight: 800, color: c as string,
              opacity: o as number, transform: `translateY(${dy}px)`, fontVariantNumeric: "tabular-nums" }}>{t}</div>
          ))}
        </div>
      </Row>

      <Caption text="Checks every bill before you pay." duration={CHECKS_FRAMES} start={10} />
    </AbsoluteFill>
  );
};
