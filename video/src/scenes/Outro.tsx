import type { FC, ReactNode } from "react";
import { measureText } from "@remotion/layout-utils";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { BrandLogo, Caption, Icon, LogoTile, Mark } from "../components";
import { C, clamp, easeInOut, glass, glassW, prog, stencil, ui, W } from "../theme";

// The hero view. Three panels from the video float in a fan, then scale down into the centre and the ReconAI logo
// comes out of them; the wordmark wipes in and the frame fades to black. `variant` picks each cut's panels.
export const OUTRO_FRAMES = 150;
export const OUTRO_V3_FRAMES = 180;
type Variant = "v3" | "v4" | "v5";

const Panel: FC<{ i: number; x: number; y: number; rot: number; gather: number; light: boolean; children: ReactNode }> = ({ i, x, y, rot, gather, light, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - 4 - i * 8, fps, config: { damping: 14, stiffness: 100 } });
  const g = prog(frame, gather + i * 3, gather + 30 + i * 3, easeInOut);
  const float = Math.sin(frame * 0.05 + i * 2) * 10;
  return (
    <div style={{
      ...(light ? glassW : glass), position: "absolute", left: 960, top: 470, borderRadius: 26, padding: "26px 32px", fontFamily: ui,
      color: light ? W.text : C.text, background: light ? "rgba(255,255,255,0.88)" : "rgba(20,22,30,0.7)",
      transform: `translate(-50%, -50%) translate(${x * (1 - g)}px, ${(y + float) * (1 - g)}px) rotate(${rot * (1 - g)}deg) scale(${(0.8 + 0.2 * s) * (1 - 0.8 * g)})`,
      opacity: Math.min(1, s * 1.5) * (1 - g),
    }}>
      {children}
    </div>
  );
};

const Stat: FC<{ label: string; value: string; glow: string }> = ({ label, value, glow }) => (
  <>
    <div style={{ fontSize: 20, color: C.muted }}>{label}</div>
    <div style={{ fontSize: 60, fontWeight: 800, letterSpacing: -2, textShadow: `0 0 30px ${glow}` }}>{value}</div>
  </>
);
const Held = () => (
  <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
    <div style={{ width: 70, height: 70, borderRadius: 35, background: C.red, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 30px ${C.red}` }}>
      <Icon name="lock" size={42} />
    </div>
    <div>
      <div style={{ fontSize: 40, fontWeight: 800 }}>$3.3M</div>
      <div style={{ fontSize: 22, color: C.red, fontWeight: 700, letterSpacing: 2 }}>HELD</div>
    </div>
  </div>
);
const Paid: FC<{ color?: string; label?: string }> = ({ color, label = "Paid · USDC" }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
    <Mark ok p={1} size={56} color={color} />
    <div style={{ fontSize: 34, fontWeight: 800 }}>{label}</div>
  </div>
);
const HEROES: Record<Variant, ReactNode[]> = {
  v3: [<Stat label="Caught before payment" value="$857k" glow={C.cyan} />, <Held />, <Paid />],
  v4: [<Stat label="At the aim" value="+$11,000" glow={C.green} />, <Paid />, <Held />],
  v5: [<Stat label="Documents matched" value="3 / 3" glow="rgba(14,110,118,0.25)" />, <Paid color={W.green} label="Paid" />,
    <Stat label="Invoice to paid" value="31 min" glow="rgba(22,163,74,0.25)" />],
};

export const Outro: FC<{ variant?: Variant }> = ({ variant = "v5" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const frames = variant === "v3" ? OUTRO_V3_FRAMES : OUTRO_FRAMES;
  const GATHER = variant === "v3" ? 70 : 56;   // panels start shrinking into the centre
  const tile = spring({ frame: frame - (GATHER + 24), fps, config: { damping: 12, stiffness: 120 } });
  const word = prog(frame, GATHER + 40, GATHER + 66, easeInOut);
  const flash = interpolate(frame, [GATHER + 22, GATHER + 30, GATHER + 60], [0, 1, 0], clamp);
  const fadeOut = interpolate(frame, [frames - 20, frames], [1, 0], clamp);
  const [a, b, c] = HEROES[variant];
  const light = variant === "v5";

  return (
    <AbsoluteFill style={{ opacity: fadeOut }}>
      <Panel i={0} x={-520} y={-40} rot={-8} gather={GATHER} light={light}>{a}</Panel>
      <Panel i={1} x={0} y={-90} rot={2} gather={GATHER} light={light}>{b}</Panel>
      <Panel i={2} x={520} y={-20} rot={7} gather={GATHER} light={light}>{c}</Panel>

      {/* light burst where the panels meet */}
      <div style={{ position: "absolute", left: 960 - 300, top: 470 - 300, width: 600, height: 600, borderRadius: 300,
        background: light ? `radial-gradient(circle, rgba(14,110,118,0.35), rgba(58,175,167,0.15) 45%, transparent 70%)`
          : `radial-gradient(circle, rgba(167,139,250,0.55), rgba(34,211,238,0.2) 45%, transparent 70%)`, opacity: flash, transform: `scale(${0.5 + flash})` }} />

      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 44, paddingBottom: 140 }}>
        {light ? (
          // the app's logo: teal stencil wordmark + forward chevrons
          // chevrons start centred and slide right as the wordmark wipes in (as in BrandIntro)
          <div style={{ transform: `translateX(${-(1 - word) * (measureText({ text: "RECON-AI", fontFamily: stencil, fontSize: 160, fontWeight: "400" }).width + 48) / 2}px) scale(${0.85 + 0.15 * tile})`,
            opacity: Math.min(1, tile * 2) }}>
            <BrandLogo size={160} reveal={word} chev={tile} at={GATHER + 24} />
          </div>
        ) : (
          <>
            <div style={{ transform: `scale(${0.3 + 0.7 * tile})`, opacity: Math.min(1, tile * 2), filter: `drop-shadow(0 0 ${40 * tile}px rgba(167,139,250,0.5))` }}>
              <LogoTile size={200} />
            </div>
            <span style={{
              fontFamily: stencil, fontSize: 168, color: "#fff", letterSpacing: 4, lineHeight: 1,
              clipPath: `inset(-20% ${(1 - word) * 100}% -20% 0)`, transform: `translateX(${(1 - word) * -40}px)`,
            }}>RECON-AI</span>
          </>
        )}
      </AbsoluteFill>
      <Caption light={light} text="Built at Cal Hacks 13.0" duration={frames + 30} start={GATHER + 60} />
    </AbsoluteFill>
  );
};
