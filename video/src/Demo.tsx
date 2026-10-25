import { clockWipe } from "@remotion/transitions/clock-wipe";
import { iris } from "@remotion/transitions/iris";
import { slide } from "@remotion/transitions/slide";
import { linearTiming, type TransitionPresentation, TransitionSeries } from "@remotion/transitions";
import { Fragment, type FC } from "react";
import { AbsoluteFill, Html5Audio, interpolate, staticFile } from "remotion";
import { BRAND_INTRO_FRAMES, BrandIntro } from "./BrandIntro";
import { LightBackdrop } from "./components";
import { Lifecycle, LIFECYCLE_FRAMES } from "./scenes/Lifecycle";
import { Outro, OUTRO_FRAMES } from "./scenes/Outro";
import { Tat, TAT_FRAMES } from "./scenes/Tat";
import { clamp, easeInOut } from "./theme";

// The product video (video/SCRIPT.md): the bill lifecycle in one vendor chat, in the app's light palette. Logo, today's
// turnaround time, the lifecycle (scenes 3-11 as one continuous component so the Slack window never crossfades onto
// itself), outro. Music: "Product Video" by SoundSurfer (Pixabay), cut to this timeline as public/audio/soundtrack.wav:
// the track's first 58.75 s (its quiet breakdown sits under the corrected invoice and the all-clear DM), then a crossfade
// into its last 8 s so the energy returns as the payout lands (58 s) and the song ends with the outro. Not in git (licence).
const XFADE = 15;
const size = { width: 1920, height: 1080 };

// [scene, frames, transition into it]
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SCENES: [FC, number, TransitionPresentation<any> | null][] = [
  [BrandIntro, BRAND_INTRO_FRAMES, null],
  [Tat, TAT_FRAMES, iris(size)],                          // opens out from the logo
  [Lifecycle, LIFECYCLE_FRAMES, slide({ direction: "from-right" })],   // fast-forward into the chat
  [Outro, OUTRO_FRAMES, clockWipe(size)],                 // time sweeps round to the end
];

export const DEMO_FRAMES = SCENES.reduce((n, [, d]) => n + d, 0) - XFADE * (SCENES.length - 1);

export const Demo: FC = () => (
  <AbsoluteFill>
    <LightBackdrop />
    <TransitionSeries>
      {SCENES.map(([Scene, d, into], i) => (
        <Fragment key={i}>
          {into && <TransitionSeries.Transition presentation={into} timing={linearTiming({ durationInFrames: XFADE, easing: easeInOut })} />}
          <TransitionSeries.Sequence durationInFrames={d}><Scene /></TransitionSeries.Sequence>
        </Fragment>
      ))}
    </TransitionSeries>
    <Html5Audio src={staticFile("audio/soundtrack.wav")} volume={(f) => 0.85 * interpolate(f, [0, 8, DEMO_FRAMES - 20, DEMO_FRAMES], [0, 1, 1, 0], clamp)} />
  </AbsoluteFill>
);
