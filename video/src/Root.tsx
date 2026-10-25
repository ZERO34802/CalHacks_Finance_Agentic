import type { FC } from "react";
import { Composition } from "remotion";
import { LogoIntro } from "./LogoIntro";

// Scene 1 of the ReconAI demo video: the logo. 1080p, 30 fps, 4 s.
export const Root: FC = () => (
  <Composition id="LogoIntro" component={LogoIntro} durationInFrames={120} fps={30} width={1920} height={1080} />
);
