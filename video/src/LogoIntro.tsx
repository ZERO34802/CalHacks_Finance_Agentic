import type { FC } from "react";
import { loadFont } from "@remotion/google-fonts/SairaStencil";
import { measureText } from "@remotion/layout-utils";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

// Opener in the style of a product launch: black frame, the ReconAI app icon appears alone, its glyph draws in
// (three ledger lines + a check: the books reconcile), then the icon slides left as the wordmark reveals beside it.
const { fontFamily } = loadFont("normal", { weights: ["400"] });

const TILE = 230;
const GAP = 46;
const FONT_SIZE = 196;
const WORD = "RECON-AI";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Glyph: FC<{ frame: number }> = ({ frame }) => {
  // stroke lengths for the draw-on effect (viewBox 100 x 100)
  const lines = [{ y: 30, x2: 70, start: 14 }, { y: 50, x2: 58, start: 19 }, { y: 70, x2: 40, start: 24 }];
  const check = interpolate(frame, [30, 44], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <svg viewBox="0 0 100 100" width={TILE * 0.62} height={TILE * 0.62}>
      {lines.map((l) => {
        const len = l.x2 - 22;
        const p = interpolate(frame, [l.start, l.start + 12], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
        return <line key={l.y} x1={22} y1={l.y} x2={l.x2} y2={l.y} stroke="#000" strokeWidth={9} strokeLinecap="round"
          strokeDasharray={len} strokeDashoffset={len * (1 - p)} />;
      })}
      {/* the check: lands at the end of the shortest line, where the books close */}
      <polyline points="52,70 62,80 82,56" fill="none" stroke="#000" strokeWidth={9} strokeLinecap="round"
        strokeLinejoin="round" strokeDasharray={48} strokeDashoffset={48 * (1 - check)} />
    </svg>
  );
};

export const LogoIntro: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const wordWidth = measureText({ text: WORD, fontFamily, fontSize: FONT_SIZE, fontWeight: "400", letterSpacing: "4px" }).width;

  // 1. the icon pops in, alone, centred
  const pop = spring({ frame: frame - 2, fps, config: { damping: 14, stiffness: 140, mass: 0.6 } });
  // 2. after the glyph draws, the icon slides left and the wordmark is revealed beside it
  const slide = interpolate(frame, [50, 74], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const reveal = interpolate(frame, [60, 86], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const total = TILE + GAP + wordWidth;
  const iconX = interpolate(slide, [0, 1], [0, -(total / 2 - TILE / 2)]);  // from centre to the group's left edge
  const textX = interpolate(reveal, [0, 1], [-(TILE + GAP) * 0.6, 0]);
  // the wordmark is only visible to the right of the tile, so it always emerges from behind it
  const tileRight = total / 2 + TILE / 2 + iconX;
  const clipLeft = Math.max(0, tileRight - (TILE + GAP + textX));
  const clipRight = Math.max(0, wordWidth - (clipLeft + reveal * (wordWidth + 40)));  // grows out with the reveal

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", justifyContent: "center", alignItems: "center" }}>
      <div style={{ position: "relative", width: total, height: TILE }}>
        {/* icon tile */}
        <div style={{
          position: "absolute", left: "50%", top: 0, width: TILE, height: TILE, marginLeft: -TILE / 2,
          transform: `translateX(${iconX}px) scale(${0.6 + 0.4 * pop})`, opacity: Math.min(1, pop),
          borderRadius: TILE * 0.2, background: "#fff", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2,
        }}>
          <Glyph frame={frame} />
        </div>
        {/* wordmark: wiped in from behind the icon */}
        <div style={{
          position: "absolute", left: TILE + GAP, top: 0, height: TILE, display: "flex", alignItems: "center",
          transform: `translateX(${textX}px)`, clipPath: `inset(-20% ${clipRight}px -20% ${clipLeft}px)`, zIndex: 1,
        }}>
          <span style={{ fontFamily, fontSize: FONT_SIZE, lineHeight: 1, letterSpacing: 4, color: "#fff", whiteSpace: "nowrap" }}>
            {WORD}
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
