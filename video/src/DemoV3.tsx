import { fade } from "@remotion/transitions/fade";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { Fragment, type FC } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bokeh } from "./components";
import { LogoIntro } from "./LogoIntro";
import { APP_FRAMES, AppScene } from "./scenes/AppScene";
import { Channels, CHANNELS_FRAMES } from "./scenes/Channels";
import { Checks, CHECKS_FRAMES } from "./scenes/Checks";
import { Outro, OUTRO_V3_FRAMES } from "./scenes/Outro";
import { Problem, PROBLEM_FRAMES } from "./scenes/Problem";
import { SLACK_ACT_FRAMES, SlackAct } from "./scenes/SlackAct";
import { clamp, easeInOut } from "./theme";

// The previous 69 s cut (render out/demo-20261025-020857.mp4), kept so it can be rebuilt. Scenes 6-11 (the Slack act)
// are one continuous component, SlackAct.
const LOGO_FRAMES = 105;
const XFADE = 20;

const SCENES: [FC, number][] = [
  [LogoIntro, LOGO_FRAMES],
  [Problem, PROBLEM_FRAMES],
  [Channels, CHANNELS_FRAMES],
  [AppScene, APP_FRAMES],
  [Checks, CHECKS_FRAMES],
  [SlackAct, SLACK_ACT_FRAMES],
  [() => <Outro variant="v3" />, OUTRO_V3_FRAMES],
];

export const DEMO_V3_FRAMES = SCENES.reduce((n, [, d]) => n + d, 0) - XFADE * (SCENES.length - 1);

export const DemoV3: FC = () => {
  const frame = useCurrentFrame();
  // the logo opens on pure black; the bokeh comes up as it hands over to the first scene
  const bokeh = interpolate(frame, [LOGO_FRAMES - 30, LOGO_FRAMES + 10], [0, 1], { ...clamp, easing: easeInOut });
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <AbsoluteFill style={{ opacity: bokeh }}><Bokeh /></AbsoluteFill>
      <TransitionSeries>
        {SCENES.map(([Scene, d], i) => (
          <Fragment key={i}>
            {i > 0 && <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: XFADE, easing: easeInOut })} />}
            <TransitionSeries.Sequence durationInFrames={d}><Scene /></TransitionSeries.Sequence>
          </Fragment>
        ))}
      </TransitionSeries>
    </AbsoluteFill>
  );
};
