import type { CSSProperties, FC, ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, clamp, easeOut, mono, prog, stencil, ui, W } from "./theme";

// Caption at the bottom of a scene. Words blur in one after another (React Bits "Blur Text", rebuilt on frames), the
// whole line fades out before the cut.
export const Caption: FC<{ text: string; start?: number; duration: number; light?: boolean }> = ({ text, start = 6, duration, light }) => {
  const frame = useCurrentFrame();
  const out = interpolate(frame, [duration - 14, duration - 4], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 78, pointerEvents: "none" }}>
      <div style={{ fontFamily: ui, fontWeight: 700, fontSize: 60, letterSpacing: -1.2, color: light ? W.text : C.text,
        textShadow: light ? "0 2px 24px rgba(255,255,255,0.9)" : "0 0 40px rgba(167,139,250,0.35)",
        opacity: out, display: "flex", gap: "0.27em" }}>
        {text.split(" ").map((w, i) => {
          const p = prog(frame, start + i * 4, start + i * 4 + 20, BLUR_EASE);
          return <span key={i} style={{ display: "inline-block", opacity: p, filter: `blur(${(1 - p) * 10}px)`, transform: `translateY(${(1 - p) * -28}px)` }}>{w}</span>;
        })}
      </div>
    </AbsoluteFill>
  );
};
const BLUR_EASE = Easing.bezier(0.22, 1, 0.36, 1);

// Characters scramble, then lock in from the left (React Bits "Decrypted Text", rebuilt on frames). Starts at `at`.
const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*";
export const Decrypt: FC<{ text: string; at: number; scramble?: string }> = ({ text, at, scramble = C.cyan }) => {
  const frame = useCurrentFrame();
  const t = frame - at;
  return (
    <span>
      {Array.from(text).map((ch, i) => {
        if (t >= 6 + i * 1.2 || ch === " " || ch === "-") return <span key={i}>{ch}</span>;
        const g = GLYPHS[Math.floor(random(`${text}-${i}-${Math.floor(frame / 2)}`) * GLYPHS.length)];
        return <span key={i} style={{ color: scramble, opacity: t < 0 ? 0 : 0.85 }}>{g}</span>;
      })}
    </span>
  );
};

// One soft highlight sweeping across text (React Bits "Shiny Text", rebuilt on frames). Sweeps from `at`, every `every` frames.
export const Shiny: FC<{ children: ReactNode; at?: number; every?: number; color?: string }> = ({ children, at = 0, every = 90, color = C.text }) => {
  const frame = useCurrentFrame();
  const t = frame < at ? 0 : ((frame - at) % every) / 40;   // a 40-frame sweep, then rest
  const pos = 150 - Math.min(1, t) * 200;
  return (
    <span style={{ backgroundImage: `linear-gradient(110deg, ${color} 40%, #ffffff 50%, ${color} 60%)`, backgroundSize: "200% 100%",
      backgroundPosition: `${pos}% 0`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>{children}</span>
  );
};

// Short lines burst out from a click (React Bits "Click Spark": 8 sparks, 30px radius, 500ms, ease-out).
const ClickSpark: FC<{ clicks: number[]; color: string }> = ({ clicks, color }) => {
  const frame = useCurrentFrame();
  return (
    <svg width={120} height={120} viewBox="-60 -60 120 120" style={{ position: "absolute", left: -60, top: -60, overflow: "visible", pointerEvents: "none" }}>
      {clicks.map((c) => {
        const t = (frame - c) / 15;
        if (t < 0 || t > 1) return null;
        const e = 1 - Math.pow(1 - t, 3);
        return Array.from({ length: 8 }, (_, i) => {
          const a = (i / 8) * Math.PI * 2;
          const r = e * 34, len = 14 * (1 - e);
          return <line key={`${c}-${i}`} x1={Math.cos(a) * r} y1={Math.sin(a) * r} x2={Math.cos(a) * (r + len)} y2={Math.sin(a) * (r + len)}
            stroke={color} strokeWidth={2.5} strokeLinecap="round" />;
        });
      })}
    </svg>
  );
};

// Soft out-of-focus light behind everything: purple, cyan and green blobs that drift and breathe.
const BOKEH = Array.from({ length: 16 }, (_, i) => ({
  x: random(`bx${i}`) * 1920,
  y: random(`by${i}`) * 1080,
  r: 80 + random(`br${i}`) * 220,
  color: [C.violet, C.cyan, C.green, C.violet, C.cyan][i % 5],
  speed: 0.004 + random(`bs${i}`) * 0.008,
  phase: random(`bp${i}`) * Math.PI * 2,
}));

export const Bokeh: FC<{ intensity?: number }> = ({ intensity = 1 }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, overflow: "hidden" }}>
      {BOKEH.map((b, i) => {
        const t = frame * b.speed + b.phase;
        const pulse = 0.75 + 0.25 * Math.sin(frame * 0.03 + b.phase);
        return (
          <div key={i} style={{
            position: "absolute", left: b.x + Math.sin(t) * 120 - b.r, top: b.y + Math.cos(t * 0.8) * 90 - b.r,
            width: b.r * 2, height: b.r * 2, borderRadius: "50%", background: b.color,
            opacity: 0.13 * pulse * intensity, filter: "blur(70px)",
          }} />
        );
      })}
    </AbsoluteFill>
  );
};

// Line icons on a 48 x 48 grid. They carry the story; captions stay short.
const ICON_PATHS = {
  doc: <><path d="M12 5 H29 L37 13 V43 H12 Z" /><path d="M29 5 V13 H37" /><path d="M17 22 H31 M17 28 H31 M17 34 H25" /></>,
  docs: <><path d="M16 9 H31 L38 16 V42 H16 Z" /><path d="M10 6 V37" opacity={0.5} /><path d="M10 6 H25" opacity={0.5} /><path d="M21 24 H33 M21 30 H33" /></>,
  mail: <><rect x={6} y={11} width={36} height={26} rx={4} /><polyline points="7,13 24,26 41,13" /></>,
  sheet: <><rect x={8} y={8} width={32} height={32} rx={3} /><path d="M8 18 H40 M8 29 H40 M19 8 V40" /></>,
  box: <><path d="M24 5 L41 14 V34 L24 43 L7 34 V14 Z" /><path d="M7 14 L24 23 L41 14 M24 23 V43" /></>,
  bank: <><path d="M6 18 L24 7 L42 18 Z" /><path d="M12 22 V36 M20 22 V36 M28 22 V36 M36 22 V36 M6 40 H42" /></>,
  lock: <><rect x={10} y={21} width={28} height={21} rx={4} /><path d="M16 21 V15 Q16 7 24 7 Q32 7 32 15 V21" /><path d="M24 29 V34" /></>,
  tag: <><path d="M6 24 L24 6 H42 V24 L24 42 Z" /><circle cx={34} cy={14} r={3} /></>,
  eyeOff: <><path d="M4 24 Q24 6 44 24 Q24 42 4 24 Z" /><circle cx={24} cy={24} r={6} /><path d="M8 42 L40 6" /></>,
  user: <><circle cx={24} cy={16} r={8} /><path d="M9 42 Q9 28 24 28 Q39 28 39 42" /></>,
  bot: <><rect x={9} y={15} width={30} height={23} rx={6} /><path d="M24 15 V9" /><circle cx={24} cy={7} r={2} /><path d="M18 26 V28 M30 26 V28" /></>,
  arrow: <path d="M8 24 H40 M30 14 L40 24 L30 34" />,
  home: <><path d="M6 22 L24 7 L42 22" /><path d="M11 19 V41 H37 V19" /><path d="M20 41 V30 H28 V41" /></>,
  chart: <><path d="M7 41 H41" /><path d="M9 33 L18 22 L26 28 L39 12" /></>,
  users: <><circle cx={18} cy={17} r={6} /><path d="M6 38 Q6 27 18 27 Q30 27 30 38" /><circle cx={33} cy={19} r={5} /><path d="M33 28 Q42 28 42 37" /></>,
  cart: <><path d="M5 8 H11 L15 31 H37 L41 15 H13" /><circle cx={18} cy={38} r={2.5} /><circle cx={34} cy={38} r={2.5} /></>,
  gear: <><circle cx={24} cy={24} r={6} /><circle cx={24} cy={24} r={13} /><path d="M24 5 V11 M24 37 V43 M5 24 H11 M37 24 H43 M10.6 10.6 L14.8 14.8 M33.2 33.2 L37.4 37.4 M10.6 37.4 L14.8 33.2 M33.2 14.8 L37.4 10.6" /></>,
  search: <><circle cx={21} cy={21} r={12} /><path d="M30 30 L41 41" /></>,
  chevron: <path d="M14 19 L24 29 L34 19" />,
  shield: <><path d="M24 5 L40 11 V23 Q40 36 24 43 Q8 36 8 23 V11 Z" /><polyline points="17,24 22,29 31,19" /></>,
  chat: <path d="M8 10 H40 Q42 10 42 12 V32 Q42 34 40 34 H20 L12 41 V34 H8 Q6 34 6 32 V12 Q6 10 8 10 Z" />,
  window: <><rect x={5} y={8} width={38} height={32} rx={3} /><path d="M5 16 H43 M11 24 H25 M11 30 H31" /></>,
  globe: <><circle cx={24} cy={24} r={18} /><path d="M6 24 H42 M24 6 Q13 24 24 42 Q35 24 24 6" /></>,
  truck: <><path d="M4 14 H30 V34 H4 Z" /><path d="M30 20 H38 L44 27 V34 H30" /><circle cx={12} cy={36} r={4} /><circle cx={36} cy={36} r={4} /></>,
} as const;
export type IconName = keyof typeof ICON_PATHS;

export const Icon: FC<{ name: IconName; size: number; color?: string; width?: number }> = ({ name, size, color = "#fff", width = 2.6 }) => (
  <svg viewBox="0 0 48 48" width={size} height={size} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round">
    {ICON_PATHS[name]}
  </svg>
);

// A check or cross whose stroke draws itself.
export const Mark: FC<{ ok: boolean; p: number; size?: number; color?: string }> = ({ ok, p, size = 44, color }) => {
  const stroke = color ?? (ok ? C.green : C.red);
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} style={{ filter: `drop-shadow(0 0 ${8 * p}px ${stroke})`, overflow: "visible" }}>
      <circle cx={20} cy={20} r={18} fill="none" stroke={stroke} strokeWidth={3} opacity={0.25 + 0.75 * Math.min(1, p * 2)} />
      {ok ? (
        <polyline points="11,21 17,27 29,14" fill="none" stroke={stroke} strokeWidth={4} strokeLinecap="round"
          strokeLinejoin="round" strokeDasharray={28} strokeDashoffset={28 * (1 - p)} />
      ) : (
        <g stroke={stroke} strokeWidth={4} strokeLinecap="round">
          <line x1={13} y1={13} x2={27} y2={27} strokeDasharray={20} strokeDashoffset={20 * (1 - Math.min(1, p * 2))} />
          <line x1={27} y1={13} x2={13} y2={27} strokeDasharray={20} strokeDashoffset={20 * (1 - Math.max(0, p * 2 - 1))} />
        </g>
      )}
    </svg>
  );
};

// Mouse pointer, drawn at (x, y) = its tip. `press` 0 -> 1 squashes it and flashes a click ring. `label` adds a
// multiplayer-style name tag, so it's clear whose click it is. `sparks` are click frames that get a Click Spark.
export const Cursor: FC<{ x: number; y: number; press?: number; opacity?: number; label?: string; color?: string; sparks?: number[] }> = (
  { x, y, press = 0, opacity = 1, label, color = C.violet, sparks = [] },
) => (
  <div style={{ position: "absolute", left: x, top: y, opacity, zIndex: 50 }}>
    <ClickSpark clicks={sparks} color={C.cyan} />
    {label && (
      <div style={{ position: "absolute", left: 30, top: 38, padding: "5px 12px", borderRadius: 10, background: color, color: "#fff",
        fontFamily: ui, fontSize: 19, fontWeight: 700, whiteSpace: "nowrap", boxShadow: "0 6px 16px rgba(0,0,0,0.4)" }}>{label}</div>
    )}
    <div style={{
      position: "absolute", left: -30, top: -30, width: 60, height: 60, borderRadius: 30, border: `3px solid ${C.cyan}`,
      opacity: press * 0.9, transform: `scale(${0.4 + press * 0.8})`,
    }} />
    <svg viewBox="0 0 24 24" width={44} height={44} style={{
      transform: `scale(${1 - 0.15 * press})`, transformOrigin: "0 0", filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.6))",
    }}>
      <path d="M3 2 L3 19 L8 14.5 L11.5 22 L14.5 20.7 L11 13.4 L17.5 13.4 Z" fill="#fff" stroke="#000" strokeWidth={1.4} strokeLinejoin="round" />
    </svg>
  </div>
);

// The ReconAI app icon (white tile, ledger lines + check), drawn complete.
export const LogoTile: FC<{ size: number; dark?: boolean }> = ({ size, dark }) => (
  <div style={{
    width: size, height: size, borderRadius: size * 0.2, background: dark ? W.ink : C.tile,
    display: "flex", alignItems: "center", justifyContent: "center",
  }}>
    <svg viewBox="0 0 100 100" width={size * 0.62} height={size * 0.62}>
      {[{ y: 30, x2: 70 }, { y: 50, x2: 58 }, { y: 70, x2: 40 }].map((l) => (
        <line key={l.y} x1={22} y1={l.y} x2={l.x2} y2={l.y} stroke={dark ? "#fff" : "#000"} strokeWidth={9} strokeLinecap="round" />
      ))}
      <polyline points="52,70 62,80 82,56" fill="none" stroke={dark ? "#fff" : "#000"} strokeWidth={9} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </div>
);

// White with a slow gradient: three soft colour fields drift under a white wash (the current cut's backdrop).
export const LightBackdrop: FC = () => {
  const frame = useCurrentFrame();
  const fields = [
    { x: 260, y: 180, r: 620, c: "rgba(14,110,118,0.14)", s: 0.006 },
    { x: 1640, y: 260, r: 560, c: "rgba(58,175,167,0.16)", s: 0.008 },
    { x: 1100, y: 980, r: 700, c: "rgba(125,182,182,0.18)", s: 0.005 },
  ];
  return (
    <AbsoluteFill style={{ background: "linear-gradient(160deg, #ffffff 0%, #f4f7f6 50%, #e6f1f0 100%)", overflow: "hidden" }}>
      {fields.map((f, i) => (
        <div key={i} style={{ position: "absolute", left: f.x - f.r + Math.sin(frame * f.s + i) * 90, top: f.y - f.r + Math.cos(frame * f.s * 0.8 + i) * 70,
          width: f.r * 2, height: f.r * 2, borderRadius: "50%", background: `radial-gradient(circle, ${f.c}, transparent 65%)` }} />
      ))}
    </AbsoluteFill>
  );
};

// React Bits "Split Flap Text", rebuilt on frames: each tile flips on a hinge when its character changes. The top half
// of the old character falls (ease-in), then the bottom half of the new one lands (ease-out). `value(frame)` gives the
// string to show; tiles with a space are left blank.
const FLIP = 6;
const Half: FC<{ ch: string; top: boolean; style?: CSSProperties }> = ({ ch, top, style }) => (
  <span style={{ position: "absolute", left: 0, right: 0, height: "50%", top: top ? 0 : "50%", overflow: "hidden", ...style }}>
    <span style={{ position: "absolute", left: 0, right: 0, top: top ? 0 : "-100%", height: "200%", display: "flex", alignItems: "center", justifyContent: "center" }}>{ch}</span>
  </span>
);
export const SplitFlap: FC<{ value: (f: number) => string; size: number; tile?: string; color?: string }> = ({ value, size, tile = "#111827", color = "#f8fafc" }) => {
  const frame = useCurrentFrame();
  const now = value(frame);
  return (
    <span style={{ display: "inline-flex", gap: size * 0.08, fontSize: size, fontWeight: 760, lineHeight: 1, color, fontVariantNumeric: "tabular-nums",
      fontFamily: mono }}>
      {Array.from(now).map((ch, i) => {
        // find a change on this tile within the last FLIP frames
        let from = ch, p = 1;
        for (let k = 0; k < FLIP; k++) {
          const a = value(frame - k)[i] ?? " ", b = value(frame - k - 1)[i] ?? " ";
          if (a !== b) { from = b; p = (k + 0.5) / FLIP; break; }
        }
        const flipping = p < 1;
        const front = Math.min(1, p * 2), back = Math.max(0, p * 2 - 1);
        const bg = `radial-gradient(circle at 50% 0%, rgba(255,255,255,0.16), transparent 44%), linear-gradient(180deg, #2a3142, ${tile})`;
        return (
          <span key={i} style={{ position: "relative", width: "0.78em", height: "1.08em", borderRadius: size * 0.12, background: bg, perspective: "10em",
            boxShadow: `inset 0 0.035em 0.08em rgba(255,255,255,0.08), inset 0 -0.05em 0.1em rgba(0,0,0,0.38), 0 0.16em 0.38em rgba(15,18,34,0.28)`, overflow: "hidden" }}>
            <Half ch={ch} top />
            <Half ch={flipping ? from : ch} top={false} />
            {flipping && front < 1 && (
              <Half ch={from} top style={{ background: bg, transformOrigin: "50% 100%", transform: `rotateX(${-90 * Easing.in(Easing.cubic)(front)}deg)`,
                filter: `brightness(${1.08 - 0.4 * front})` }} />
            )}
            {flipping && back > 0 && (
              <Half ch={ch} top={false} style={{ background: bg, transformOrigin: "50% 0%", transform: `rotateX(${90 * (1 - easeOut(back))}deg)`,
                filter: `brightness(${0.58 + 0.42 * back})` }} />
            )}
            {/* hinge */}
            <span style={{ position: "absolute", left: 0, right: 0, top: "calc(50% - 1px)", height: 2,
              background: "linear-gradient(90deg, transparent, rgba(0,0,0,0.64) 50%, transparent)" }} />
          </span>
        );
      })}
    </span>
  );
};

// React Bits "Rotating Text", rebuilt on frames: the word changes every `every` frames from `at`, its characters
// sliding up into place one after another (spring, damping 30 / stiffness 400) while the old word slides out the top.
export const RotatingText: FC<{ words: string[]; at: number; every: number; style?: CSSProperties }> = ({ words, at, every, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = Math.max(0, frame - at);
  const idx = Math.min(words.length - 1, Math.floor(t / every));
  const changed = at + idx * every;
  const word = (w: string, enter: boolean) => Array.from(w).map((ch, i) => {
    const s = spring({ frame: frame - changed - i, fps, config: { damping: 30, stiffness: 400 } });
    return <span key={i} style={{ display: "inline-block", transform: `translateY(${enter ? (1 - s) * 100 : -120 * s}%)` }}>{ch}</span>;
  });
  return (
    <span style={{ position: "relative", display: "inline-flex", overflow: "hidden", padding: "2px 10px", borderRadius: 8, ...style }}>
      <span style={{ display: "inline-flex" }}>{word(words[idx], frame >= at)}</span>
      {idx > 0 && <span style={{ position: "absolute", left: 10, top: 2, display: "inline-flex" }}>{word(words[idx - 1], false)}</span>}
    </span>
  );
};

// React Bits "Border Glow" in its animated mode, rebuilt on frames: a cone of colour sweeps around the card's border
// (110deg -> 465deg, ease-in then ease-out) and fades. Place inside a positioned card.
export const GlowSweep: FC<{ at: number; dur?: number; radius: number; colors?: string[] }> = ({ at, dur = 70, radius, colors = ["#c084fc", "#f472b6", "#38bdf8"] }) => {
  const frame = useCurrentFrame();
  const t = (frame - at) / dur;
  if (t < 0 || t > 1) return null;
  const angle = 110 + 355 * (t < 0.4 ? 0.5 * Easing.in(Easing.cubic)(t / 0.4) : 0.5 + 0.5 * easeOut((t - 0.4) / 0.6));
  const edge = interpolate(t, [0, 0.12, 0.7, 1], [0, 1, 1, 0], clamp);
  const cone = `conic-gradient(from ${angle - 60}deg, transparent 0deg, ${colors[0]} 30deg, ${colors[1]} 60deg, ${colors[2]} 90deg, transparent 120deg)`;
  const ring: CSSProperties = { position: "absolute", inset: -2, borderRadius: radius + 2, padding: 3, background: cone,
    WebkitMask: "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)", WebkitMaskComposite: "xor", maskComposite: "exclude", pointerEvents: "none" };
  return (
    <>
      <div style={{ ...ring, opacity: edge * 0.8, filter: "blur(10px)" }} />
      <div style={{ ...ring, opacity: edge }} />
    </>
  );
};

// The ReconAI logo as the app draws it (ui/src/App.tsx .logo): "RECON-AI" in Saira Stencil, brand teal, the hyphen at
// 55%, and three forward chevrons that pulse in a wave (opacity 1 -> 0.35 -> 1 over 2.4 s, 0.12 s apart).
// `reveal` 0 -> 1 wipes the wordmark out from the chevrons (right to left); `chev` 0 -> 1 slides the chevrons in.
export const Chevrons: FC<{ width: number; color?: string; at?: number; chev?: number }> = ({ width, color = W.teal, at = 0, chev = 1 }) => {
  const frame = useCurrentFrame();
  return (
    <svg viewBox="0 0 30 16" width={width} height={(width * 16) / 30} style={{ overflow: "visible", flexShrink: 0 }}>
      {[0, 8, 16].map((x, i) => {
        const wave = (((frame - at - i * 3.6) % 72) + 72) % 72 / 72;   // 2.4 s loop
        const o = wave < 0.3 ? 1 - 0.65 * (wave / 0.3) : wave < 0.6 ? 0.35 + 0.65 * ((wave - 0.3) / 0.3) : 1;
        const s = Math.max(0, Math.min(1, chev * 3 - i));
        return <path key={x} d={`M${x} 0h5l7 8-7 8h-5l7-8z`} fill={color} opacity={o * s} transform={`translate(${(1 - s) * -10} 0)`} />;
      })}
    </svg>
  );
};
export const BrandLogo: FC<{ size: number; color?: string; reveal?: number; chev?: number; at?: number }> = ({ size, color = W.teal, reveal = 1, chev = 1, at = 0 }) => (
  <div style={{ display: "flex", alignItems: "center", gap: size * 0.02, fontFamily: stencil, fontSize: size, lineHeight: 1, color }}>
    <span style={{ display: "inline-flex", clipPath: `inset(-20% 0 -20% ${(1 - reveal) * 100}%)` }}>
      <span>RECON</span><span style={{ opacity: 0.55, margin: `0 ${size * 0.04}px` }}>-</span><span>AI</span>
    </span>
    <span style={{ marginLeft: size * 0.3 }}><Chevrons width={size * 1.15} color={color} at={at} chev={chev} /></span>
  </div>
);
