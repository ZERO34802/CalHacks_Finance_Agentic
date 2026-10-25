import { fade } from "@remotion/transitions/fade";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { Fragment, type FC } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bokeh } from "./components";
import { LogoIntro } from "./LogoIntro";
import { OLD_WAY_FRAMES, OldWay } from "./scenes/OldWay";
import { Outro, OUTRO_FRAMES } from "./scenes/Outro";
import { Story, STORY_FRAMES } from "./scenes/Story";
import { clamp, easeInOut } from "./theme";

// The 47.5 s "starts at the first quote" cut (render out/demo-20261025-024107.mp4), kept so it can be rebuilt.
const LOGO_FRAMES = 105;
const XFADE = 15;

const SCENES: [FC, number][] = [
  [LogoIntro, LOGO_FRAMES],
  [OldWay, OLD_WAY_FRAMES],
  [Story, STORY_FRAMES],
  [() => <Outro variant="v4" />, OUTRO_FRAMES],
];

export const DEMO_V4_FRAMES = SCENES.reduce((n, [, d]) => n + d, 0) - XFADE * (SCENES.length - 1);

export const DemoV4: FC = () => {
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
