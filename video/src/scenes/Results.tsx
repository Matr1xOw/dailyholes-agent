import React from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import { finalScores, finalToPar, highlights, nameFor, pars, withLeadIn } from "../clips";
import { Big, HoleOutClip, Muted, Reveal, Scene, Sfx } from "../parts";
import { colors, fonts, seconds, f30 } from "../theme";

export const MONTAGE_CLIP_SECONDS = 3.5;
const CELL_START = 0.5;
const CELL_GAP_FRAMES = 5;

// 9. The scorecard filling in, next to the real hole-outs.
const Scorecard: React.FC = () => {
  const frame = useCurrentFrame();
  const cellsShown = Math.floor(interpolate(frame, [seconds(CELL_START), seconds(CELL_START) + f30(9 * CELL_GAP_FRAMES)], [0, 9], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  }));
  const cell: React.CSSProperties = { width: 82, height: 74, display: "flex", alignItems: "center", justifyContent: "center" };
  return (
    <div style={{ fontFamily: fonts.mono, fontSize: 34, border: `1px solid ${colors.line}`, borderRadius: 18, overflow: "hidden" }}>
      {[
        { label: "hole", values: pars.map((_, i) => String(i + 1)), color: colors.muted },
        { label: "par", values: pars.map(String), color: colors.muted },
      ].map((row) => (
        <div key={row.label} style={{ display: "flex", background: colors.panel }}>
          <div style={{ ...cell, width: 110, color: colors.muted, fontSize: 24 }}>{row.label}</div>
          {row.values.map((value, i) => <div key={i} style={{ ...cell, color: row.color }}>{value}</div>)}
        </div>
      ))}
      <div style={{ display: "flex" }}>
        <div style={{ ...cell, width: 110, color: colors.muted, fontSize: 24 }}>AI</div>
        {finalScores.map((score, i) => (
          <div key={i} style={{ ...cell, opacity: i < cellsShown ? 1 : 0 }}>
            <div style={{
              width: 58, height: 58, borderRadius: 29, display: "flex", alignItems: "center", justifyContent: "center",
              background: score === 1 ? colors.warm : score < pars[i] ? colors.accent : "transparent",
              color: score < pars[i] ? colors.background : colors.text, fontWeight: 800,
            }}>{score}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

export const Results: React.FC = () => {
  const frame = useCurrentFrame();
  const clips = highlights;
  const clipFrames = seconds(MONTAGE_CLIP_SECONDS);
  const current = clips[Math.min(clips.length - 1, Math.floor(frame / clipFrames))];
  return (
    <Scene>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 120px", gap: 90 }}>
        <div style={{ flex: 1 }}>
          <Reveal delay={f30(2)}>
            <Big size={190}><span style={{ color: colors.accent }}>{finalToPar}</span></Big>
          </Reveal>
          <Reveal delay={f30(8)} style={{ marginTop: 10 }}>
            <Muted size={42}>in a real round (my best ever is -13)</Muted>
          </Reveal>
          <Reveal delay={f30(12)} style={{ marginTop: 48 }}><Scorecard /></Reveal>
        </div>
        <div style={{ position: "relative", marginTop: 60 }}>
          {clips.map((clip, index) => (
            <Sequence key={index} from={index * clipFrames} durationInFrames={index === clips.length - 1 ? Infinity : clipFrames} layout="none">
              <HoleOutClip moment={withLeadIn(clip, 1.0)} height={860} />
            </Sequence>
          ))}
          {current && (
            <div style={{
              position: "absolute", left: 0, top: -58, fontFamily: fonts.mono, fontSize: 30, color: colors.accent,
            }}>
              hole {current.hole} · {nameFor(current.score, current.par)}
            </div>
          )}
        </div>
      </AbsoluteFill>
      {finalScores.map((score, i) => (
        <Sfx key={i} name="pop" at={CELL_START + 0.4 + (i * CELL_GAP_FRAMES) / 30} volume={score === 1 ? 0.7 : 0.4} />
      ))}
    </Scene>
  );
};

// 10. Outro: the stack, and the honest small print.
const STACK = ["PyTorch PPO", "game sandbox in Node", "simulator search", "Playwright", "Remotion"];

export const Outro: React.FC = () => (
  <Scene>
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", textAlign: "center" }}>
      <Reveal delay={f30(2)}><Big size={110}>Daily Holes autopilot</Big></Reveal>
      <Reveal delay={f30(8)} style={{ marginTop: 50, display: "flex", gap: 22, flexWrap: "wrap", justifyContent: "center", maxWidth: 1500 }}>
        {STACK.map((item) => (
          <div key={item} style={{
            padding: "14px 26px", border: `1px solid ${colors.line}`, borderRadius: 999, fontFamily: fonts.mono,
            fontSize: 28, color: colors.muted, background: colors.panel,
          }}>{item}</div>
        ))}
      </Reveal>
      <Reveal delay={f30(14)} style={{ marginTop: 60 }}>
        <Muted size={26}>
          unofficial fan project, practice rounds only, nothing submitted
        </Muted>
      </Reveal>
    </AbsoluteFill>
  </Scene>
);
