// Small building blocks shared by the scenes.
import React from "react";
import { AbsoluteFill, Freeze, Html5Audio, interpolate, OffthreadVideo, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { Moment } from "./clips";
import { colors, fonts, FPS, f30 } from "./theme";
import footage from "./footage.json";

// Fades and slides a block in, starting at `delay` frames into the scene.
export const Reveal: React.FC<{ delay?: number; children: React.ReactNode; style?: React.CSSProperties }> = ({
  delay = 0, children, style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // Snappy: a quick spring with a little overshoot, so text pops in.
  const t = spring({ frame: frame - delay, fps, config: { damping: 14, stiffness: 220, mass: 0.6 } });
  return (
    <div style={{ opacity: Math.min(1, t * 1.5), transform: `translateY(${(1 - t) * 40}px) scale(${0.96 + 0.04 * t})`, ...style }}>
      {children}
    </div>
  );
};

export const Scene: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  // A quick fade at both ends, so cuts between scenes feel deliberate.
  const opacity = interpolate(frame, [0, f30(3), durationInFrames - f30(3), durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ background: colors.background, color: colors.text, fontFamily: fonts.sans, opacity, ...style }}>
      {children}
    </AbsoluteFill>
  );
};

export const Kicker: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ fontFamily: fonts.mono, fontSize: 26, letterSpacing: 4, color: colors.accent, textTransform: "uppercase" }}>
    {children}
  </div>
);

export const Big: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 84 }) => (
  <div style={{ fontSize: size, fontWeight: 800, lineHeight: 1.05, letterSpacing: -2 }}>{children}</div>
);

export const Muted: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 34 }) => (
  <div style={{ fontSize: size, color: colors.muted, lineHeight: 1.35 }}>{children}</div>
);

// Counts a number up from 0 over `duration` frames.
export const CountUp: React.FC<{ to: number; duration?: number; delay?: number; format?: (n: number) => string }> = ({
  to, duration = 40, delay = 0, format = (n) => Math.round(n).toLocaleString("en-US"),
}) => {
  const frame = useCurrentFrame();
  const t = interpolate(frame - delay, [0, duration], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const eased = 1 - Math.pow(1 - t, 3);
  return <>{format(to * eased)}</>;
};

// A window onto the recorded round: crops the game card out of the browser
// recording and starts playing at `from` seconds into it.
type Crop = { x: number; y: number; w: number; h: number };

export const Footage: React.FC<{ from: number; height: number; playbackRate?: number; crop?: Crop; style?: React.CSSProperties }> = ({
  from, height, playbackRate = 1, crop = footage.crop, style,
}) => {
  const { size } = footage;
  const scale = height / crop.h;
  return (
    <div style={{
      width: crop.w * scale, height, overflow: "hidden", borderRadius: 28, position: "relative",
      boxShadow: "0 30px 80px rgba(0,0,0,.55)", border: `1px solid ${colors.line}`, ...style,
    }}>
      <OffthreadVideo
        src={staticFile("footage/round.webm")}
        trimBefore={Math.round(from * FPS)}
        playbackRate={playbackRate}
        muted
        style={{
          position: "absolute", width: size.width * scale, height: size.height * scale,
          left: -crop.x * scale, top: -crop.y * scale, maxWidth: "none",
        }}
      />
    </div>
  );
};

// ------------------------------------------------------------------ sound

export type SoundName = "hit" | "cup" | "ace" | "whoosh" | "click" | "tick" | "pop";

// Plays one sound effect `at` seconds into the current scene.
export const Sfx: React.FC<{ name: SoundName; at: number; volume?: number }> = ({ name, at, volume = 0.8 }) => (
  <Sequence from={Math.round(at * FPS)} durationInFrames={Math.round(3 * FPS)} layout="none">
    <Html5Audio src={staticFile(`audio/${name}.wav`)} volume={volume} />
  </Sequence>
);

// A recorded hole-out: the footage plus its sounds (club on ball at the swing,
// the cup rattle at the drop), and for an ace, a sting, a flash and a punch-in.
export const HoleOutClip: React.FC<{ moment: Moment; height: number; freezeAfterDrop?: number }> = ({
  moment, height, freezeAfterDrop,
}) => {
  const frame = useCurrentFrame();
  const swingAt = moment.swing - moment.from;
  const dropAt = moment.drop - moment.from;
  const dropFrame = dropAt * FPS;
  const ace = moment.score === 1;
  const sinceDrop = frame - dropFrame;
  const punch = ace ? 1 + 0.06 * Math.exp(-Math.max(0, sinceDrop) / f30(10)) * (sinceDrop >= 0 ? 1 : 0) : 1;
  const flash = ace && sinceDrop >= 0 ? Math.exp(-sinceDrop / f30(5)) * 0.8 : 0;
  const freezeFrame = freezeAfterDrop == null ? null : Math.round((dropAt + freezeAfterDrop) * FPS);
  const video = <Footage from={moment.from} height={height} />;
  return (
    <div style={{ position: "relative", transform: `scale(${punch})` }}>
      {freezeFrame == null ? video : <Freeze frame={freezeFrame} active={(f) => f >= freezeFrame}>{video}</Freeze>}
      <div style={{ position: "absolute", inset: 0, borderRadius: 28, background: "#fff", opacity: flash, pointerEvents: "none" }} />
      <Sfx name="hit" at={swingAt} volume={0.9} />
      <Sfx name="cup" at={dropAt} volume={0.9} />
      {ace && <Sfx name="ace" at={dropAt + 0.05} volume={0.85} />}
    </div>
  );
};
