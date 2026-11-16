import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import data from "../../public/data.json";
import { holeOuts, withLeadIn } from "../clips";
import footage from "../footage.json";
import { Big, CountUp, Footage, HoleOutClip, Muted, Reveal, Scene, Sfx } from "../parts";
import { colors, fonts, seconds, f30 } from "../theme";

// 5. The catch, short: sits on the music's breakdown, the riser runs under it.
export const TheWall: React.FC = () => (
  <Scene>
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", textAlign: "center" }}>
      <Reveal delay={f30(2)}><Big size={120}>-6 is basically my level</Big></Reveal>
      <Reveal delay={f30(22)} style={{ marginTop: 30 }}><Muted size={48}>so how does it beat me?</Muted></Reveal>
    </AbsoluteFill>
  </Scene>
);

// 6. The search as a real hit map: every square is one tee shot (aim across,
// power down), lit by how close it finishes. The bright ones go in.
const CELL = 6.6;
const SCAN_START = 0.3;
const SCAN_END = 2.2;

const HitMap: React.FC = () => {
  const frame = useCurrentFrame();
  const grid = data.hitmap.finish_yards;
  const rowsShown = interpolate(frame, [seconds(SCAN_START), seconds(SCAN_END)], [0, grid.length], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const pulse = 0.75 + 0.25 * Math.sin(frame / f30(3));
  return (
    <svg width={grid.length * CELL} height={grid.length * CELL} style={{ borderRadius: 16, background: "#06120b" }}>
      {grid.map((row, i) =>
        i < rowsShown
          ? row.map((yards, j) => {
              if (yards === 0) {
                return <rect key={j} x={j * CELL} y={i * CELL} width={CELL} height={CELL} fill={colors.accent} opacity={pulse} />;
              }
              const closeness = Math.max(0, 1 - yards / 30);
              return (
                <rect key={j} x={j * CELL} y={i * CELL} width={CELL} height={CELL}
                  fill={`rgba(74, 222, 128, ${0.04 + 0.45 * closeness * closeness})`} />
              );
            })
          : null,
      )}
    </svg>
  );
};

export const Search: React.FC = () => {
  const hitmap = data.hitmap;
  const total = hitmap.size * hitmap.size;
  return (
    <Scene>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 140px", gap: 100 }}>
        <div style={{ flex: 1 }}>
          <Reveal delay={f30(2)}><Big size={88}>it tests every shot before it swings</Big></Reveal>
          <Reveal delay={seconds(SCAN_END)} style={{ marginTop: 44, fontFamily: fonts.mono, fontSize: 56, lineHeight: 1.3 }}>
            <div><CountUp to={total} delay={seconds(SCAN_END)} duration={f30(14)} /> tested</div>
            <div style={{ color: colors.accent, fontWeight: 800 }}>
              <CountUp to={hitmap.hits} delay={seconds(SCAN_END + 0.6)} duration={f30(14)} /> go in
            </div>
          </Reveal>
        </div>
        <HitMap />
      </AbsoluteFill>
      <Sfx name="whoosh" at={SCAN_START} volume={0.6} />
      <Sfx name="whoosh" at={SCAN_START + 1} volume={0.4} />
      <Sfx name="pop" at={SCAN_END} />
      <Sfx name="cup" at={SCAN_END + 0.9} />
    </Scene>
  );
};

// 7. The hands: real taps in the real browser.
export const Hands: React.FC = () => {
  const shot = withLeadIn(holeOuts[2] ?? holeOuts[0], 1.5);
  return (
    <Scene>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 100px", gap: 70 }}>
        <div style={{ width: 600 }}>
          <Reveal delay={f30(2)}><Big size={80}>then it plays the real game</Big></Reveal>
          <Reveal delay={f30(18)} style={{ marginTop: 40, fontFamily: fonts.mono, fontSize: 42, lineHeight: 1.4 }}>
            <div>taps timed to the frame</div>
            <div>aim off by <span style={{ color: colors.accent }}>0.0003°</span></div>
          </Reveal>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 40 }}>
          <HoleOutClip moment={shot} height={880} />
          {/* The autopilot's panel from the same moment, cut out of the window. */}
          <Footage from={shot.from} height={300} crop={footage.panel_crop} />
        </div>
      </AbsoluteFill>
    </Scene>
  );
};
