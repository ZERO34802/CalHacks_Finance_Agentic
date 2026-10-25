import type { FC } from "react";
import { AbsoluteFill, Composition, Folder } from "remotion";
import { BRAND_INTRO_FRAMES, BrandIntro } from "./BrandIntro";
import { Bokeh, LightBackdrop } from "./components";
import { Demo, DEMO_FRAMES } from "./Demo";
import { DEMO_V3_FRAMES, DemoV3 } from "./DemoV3";
import { DEMO_V4_FRAMES, DemoV4 } from "./DemoV4";
import { LogoIntro } from "./LogoIntro";
import { THUMB, Thumbnail } from "./Thumbnail";
import { APP_FRAMES, AppScene } from "./scenes/AppScene";
import { Channels, CHANNELS_FRAMES } from "./scenes/Channels";
import { Checks, CHECKS_FRAMES } from "./scenes/Checks";
import { Lifecycle, LIFECYCLE_FRAMES } from "./scenes/Lifecycle";
import { OLD_WAY_FRAMES, OldWay } from "./scenes/OldWay";
import { Outro, OUTRO_FRAMES } from "./scenes/Outro";
import { Problem, PROBLEM_FRAMES } from "./scenes/Problem";
import { SLACK_ACT_FRAMES, SlackAct } from "./scenes/SlackAct";
import { Story, STORY_FRAMES } from "./scenes/Story";
import { Tat, TAT_FRAMES } from "./scenes/Tat";

// ReconAI product video. 1080p, 30 fps. "Demo" is the current cut; earlier cuts live under "Previous-cut". Scenes are
// also registered alone for the studio, each over the same bokeh background the full cut uses.
const video = { fps: 30, width: 1920, height: 1080 };
const onBokeh = (Scene: FC): FC => () => <AbsoluteFill><Bokeh /><Scene /></AbsoluteFill>;
const onLight = (Scene: FC): FC => () => <AbsoluteFill><LightBackdrop /><Scene /></AbsoluteFill>;

export const Root: FC = () => (
  <>
    <Composition id="Demo" component={Demo} durationInFrames={DEMO_FRAMES} {...video} />
    <Composition id="Thumbnail" component={Thumbnail} durationInFrames={1} fps={30} {...THUMB} />
    <Folder name="Scenes">
      <Composition id="BrandIntro" component={onLight(BrandIntro)} durationInFrames={BRAND_INTRO_FRAMES} {...video} />
      <Composition id="LogoIntro" component={LogoIntro} durationInFrames={120} {...video} />
      <Composition id="Tat" component={onLight(Tat)} durationInFrames={TAT_FRAMES} {...video} />
      <Composition id="Lifecycle" component={onLight(Lifecycle)} durationInFrames={LIFECYCLE_FRAMES} {...video} />
      <Composition id="Outro" component={onLight(Outro)} durationInFrames={OUTRO_FRAMES} {...video} />
    </Folder>
    <Folder name="Previous-cut">
      <Composition id="DemoV4" component={DemoV4} durationInFrames={DEMO_V4_FRAMES} {...video} />
      <Composition id="OldWay" component={onBokeh(OldWay)} durationInFrames={OLD_WAY_FRAMES} {...video} />
      <Composition id="Story" component={onBokeh(Story)} durationInFrames={STORY_FRAMES} {...video} />
      <Composition id="DemoV3" component={DemoV3} durationInFrames={DEMO_V3_FRAMES} {...video} />
      <Composition id="Problem" component={onBokeh(Problem)} durationInFrames={PROBLEM_FRAMES} {...video} />
      <Composition id="Channels" component={onBokeh(Channels)} durationInFrames={CHANNELS_FRAMES} {...video} />
      <Composition id="App" component={onBokeh(AppScene)} durationInFrames={APP_FRAMES} {...video} />
      <Composition id="Checks" component={onBokeh(Checks)} durationInFrames={CHECKS_FRAMES} {...video} />
      <Composition id="SlackAct" component={onBokeh(SlackAct)} durationInFrames={SLACK_ACT_FRAMES} {...video} />
    </Folder>
  </>
);
