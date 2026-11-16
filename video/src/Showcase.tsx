// The whole video: scenes back to back, with the music underneath. Scene
// lengths live in timing.json, which the music generator reads too
// (scripts/make_audio.py), so the beat stays in step with the cuts.
import React from "react";
import { Html5Audio, Series, staticFile } from "remotion";
import { Hook, Simulator, TheGame } from "./scenes/Intro";
import { Outro, Results } from "./scenes/Results";
import { Hands, Search, TheWall } from "./scenes/Search";
import { Practice } from "./scenes/Training";
import { Sfx } from "./parts";
import { seconds } from "./theme";
import timing from "./timing.json";

const COMPONENTS: Record<string, React.FC> = { Hook, TheGame, Simulator, Practice, TheWall, Search, Hands, Results, Outro };
const SCENES = (timing.scenes as [string, number][]).map(([name, length]) => ({ name, component: COMPONENTS[name], length }));

export const SHOWCASE_FRAMES = SCENES.reduce((total, scene) => total + seconds(scene.length), 0);

export const Showcase: React.FC = () => (
  <>
    <Html5Audio src={staticFile("audio/music.wav")} volume={0.55} />
    <Series>
      {SCENES.map(({ name, component: Component, length }, index) => (
        <Series.Sequence key={name} durationInFrames={seconds(length)}>
          <Component />
          {index > 0 && <Sfx name="whoosh" at={0} volume={0.45} />}
        </Series.Sequence>
      ))}
    </Series>
  </>
);
