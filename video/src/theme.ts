import { loadFont as loadGeist } from "@remotion/google-fonts/Geist";
import { loadFont as loadGeistMono } from "@remotion/google-fonts/GeistMono";
import { loadFont as loadStencil } from "@remotion/google-fonts/SairaStencil";
import type { CSSProperties } from "react";
import { Easing, interpolate } from "remotion";

// Dark-mode SaaS look: glass panels over drifting bokeh, white type, purple / cyan / neon-green accents.
// Geist, as in the app (ui/src/review/main.tsx)
export const ui = loadGeist("normal", { weights: ["400", "500", "600", "700", "800"] }).fontFamily;
export const mono = loadGeistMono("normal", { weights: ["500", "700"] }).fontFamily;
export const stencil = loadStencil("normal", { weights: ["400"] }).fontFamily;

export const C = {
  bg: "#06070b",
  tile: "#fff",
  ink: "#111",
  text: "#f4f5f8",
  muted: "#8a8f9c",
  line: "rgba(255,255,255,0.10)",
  teal: "#0e6e76",
  tealMid: "#7db6b6",
  cyan: "#22d3ee",
  violet: "#a78bfa",
  green: "#3ee08f",
  amber: "#fbbf24",
  red: "#ff5470",
};

export const glass: CSSProperties = {
  background: "rgba(255,255,255,0.055)",
  border: "1px solid rgba(255,255,255,0.11)",
  backdropFilter: "blur(24px)",
  boxShadow: "0 30px 80px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.08)",
};

// Light look for the current cut, in the app's palette (ui/src/styles.css, ui/src/review/main.tsx): brand teal
// #0E6E76, aqua, teal-tinted greys, violet = "you", amber held, red rejected; green marks what's completed.
// Same keys as C so a scene can swap.
export const W: typeof C = {
  bg: "#eef1ed",
  tile: "#fff",
  ink: "#0a1f21",
  text: "#0a1f21",
  muted: "#5b6a6e",
  line: "#dbe2de",
  teal: "#0e6e76",
  tealMid: "#7db6b6",
  cyan: "#1d8a83",
  violet: "#6a4cf5",
  green: "#16a34a",
  amber: "#d68f00",
  red: "#c24a40",
};

export const glassW: CSSProperties = {
  background: "rgba(255,255,255,0.8)",
  border: "1px solid #dbe2de",
  backdropFilter: "blur(20px)",
  boxShadow: "0 1px 2px rgba(10,31,33,0.06), 0 14px 34px -18px rgba(10,31,33,0.28)",
};

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
export const easeOut = Easing.out(Easing.cubic);
export const easeInOut = Easing.inOut(Easing.cubic);

// 0 -> 1 between two frames, eased
export const prog = (frame: number, from: number, to: number, easing = easeOut) =>
  interpolate(frame, [from, to], [0, 1], { ...clamp, easing });

// cursor path through keyframes [frame, x, y], eased on every leg
export const cursorPath = (frame: number, keys: [number, number, number][]) => ({
  x: interpolate(frame, keys.map((k) => k[0]), keys.map((k) => k[1]), { ...clamp, easing: easeInOut }),
  y: interpolate(frame, keys.map((k) => k[0]), keys.map((k) => k[2]), { ...clamp, easing: easeInOut }),
});

// 0 -> 1 -> 0 squash around each click frame
export const clickPress = (frame: number, clicks: number[]) =>
  Math.max(0, ...clicks.map((c) => interpolate(frame, [c, c + 4, c + 10], [0, 1, 0], clamp)));
