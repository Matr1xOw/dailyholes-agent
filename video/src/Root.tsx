import { Composition } from "remotion";
import { Showcase, SHOWCASE_FRAMES } from "./Showcase";
import { FPS } from "./theme";

export const Root = () => (
  <Composition id="Showcase" component={Showcase} durationInFrames={SHOWCASE_FRAMES} fps={FPS} width={1920} height={1080} />
);
