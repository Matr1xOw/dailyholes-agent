import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { aimingMoment, holeOuts, withLeadIn } from "../clips";
import { Big, Footage, HoleOutClip, Muted, Reveal, Scene, Sfx } from "../parts";
import { colors, fonts, seconds, f30 } from "../theme";

// 1. The hook: straight into the par-4 ace, holding on the game's own
// "Hole in one" banner instead of carrying on into hole 2.
export const Hook: React.FC = () => {
  const ace = withLeadIn(holeOuts[0], 1.2);
  const dropAt = ace.drop - ace.from;
  return (
    <Scene>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 140px", gap: 110 }}>
        <div style={{ flex: 1 }}>
          <Reveal delay={f30(2)}><Big size={104}>I built an AI that plays golf</Big></Reveal>
          <Reveal delay={seconds(dropAt)} style={{ marginTop: 36 }}>
            <div style={{ fontSize: 52, fontWeight: 800, color: colors.accent }}>and it just aced a par 4</div>
          </Reveal>
        </div>
        <HoleOutClip moment={ace} height={920} freezeAfterDrop={1.0} />
      </AbsoluteFill>
    </Scene>
  );
};

// 2. The game in one line.
export const TheGame: React.FC = () => (
  <Scene>
    <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 140px", gap: 110 }}>
      <Footage from={aimingMoment} height={920} />
      <div style={{ flex: 1 }}>
        <Reveal delay={f30(2)}><Big size={92}>every shot is two taps</Big></Reveal>
        <Reveal delay={f30(14)} style={{ marginTop: 28 }}><Muted size={46}>one to stop the aim, one to stop the power</Muted></Reveal>
      </div>
    </AbsoluteFill>
    <Sfx name="click" at={0.5} />
    <Sfx name="click" at={0.75} />
  </Scene>
);

// 3. The simulator.
const TERMINAL_LINES = [
  { text: "324/324 shots match the real game", color: colors.accent },
  { text: "48,000 shots a second", color: colors.text },
];
const LINE_START = 14;
const LINE_GAP = 18;

export const Simulator: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Scene>
      <AbsoluteFill style={{ justifyContent: "center", padding: "0 160px" }}>
        <Reveal delay={f30(2)}><Big size={92}>first I cloned the game's physics</Big></Reveal>
        <div style={{
          marginTop: 60, background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 20,
          padding: "30px 44px", fontFamily: fonts.mono, fontSize: 48, lineHeight: 1.6,
        }}>
          {TERMINAL_LINES.map((line, index) => {
            const start = f30(LINE_START + index * LINE_GAP);
            const shown = Math.floor(interpolate(frame - start, [0, f30(10)], [0, line.text.length], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            }));
            return <div key={index} style={{ color: line.color, minHeight: 77 }}>{line.text.slice(0, shown)}</div>;
          })}
        </div>
      </AbsoluteFill>
      {TERMINAL_LINES.map((_, index) =>
        [0, 3, 6, 9].map((offset) => (
          <Sfx key={`${index}-${offset}`} name="tick" at={(LINE_START + index * LINE_GAP + offset) / 30} volume={0.35} />
        )),
      )}
    </Scene>
  );
};
