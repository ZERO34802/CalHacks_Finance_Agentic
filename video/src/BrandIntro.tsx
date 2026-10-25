import { measureText } from "@remotion/layout-utils";
import type { FC } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { BrandLogo } from "./components";
import { clamp, easeInOut, easeOut, prog, stencil } from "./theme";

// Opener with the app's logo: the three forward chevrons arrive alone in the centre, then slide right as the teal
// "RECON-AI" wordmark wipes in beside them, and the chevrons keep their pulse.
export const BRAND_INTRO_FRAMES = 105;

const SIZE = 170;

export const BrandIntro: FC = () => {
  const frame = useCurrentFrame();
  const word = measureText({ text: "RECON-AI", fontFamily: stencil, fontSize: SIZE, fontWeight: "400" }).width + SIZE * 0.3;
  const chev = prog(frame, 4, 26, easeOut);
  const reveal = prog(frame, 30, 62, easeInOut);
  // while the wordmark is hidden, shift the group so the chevrons sit in the middle
  const shift = interpolate(reveal, [0, 1], [-word / 2, 0], clamp);
  const out = interpolate(frame, [BRAND_INTRO_FRAMES - 12, BRAND_INTRO_FRAMES], [1, 0.9], clamp);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ transform: `translateX(${shift}px) scale(${out})` }}>
        <BrandLogo size={SIZE} reveal={reveal} chev={chev} at={26} />
      </div>
    </AbsoluteFill>
  );
};
