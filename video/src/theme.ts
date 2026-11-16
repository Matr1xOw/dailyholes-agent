// One place for the look: dark background, one bright green accent, big type.
// 50 fps: the recorded footage is 25 fps, so each recorded frame shows for
// exactly two video frames and the motion stays even (30 fps made it judder).
export const FPS = 50;
export const seconds = (s: number) => Math.round(s * FPS);
// Frame counts that were tuned at 30 fps, converted to the current rate.
export const f30 = (frames: number) => Math.round((frames * FPS) / 30);

export const colors = {
  background: "#0b100d",
  panel: "#131b16",
  line: "#22312a",
  text: "#eef5f0",
  muted: "#8fa79a",
  accent: "#4ade80",
  accentDim: "#1f5c3a",
  warm: "#fbbf24",
  bad: "#f87171",
};

export const fonts = {
  sans: "Inter, -apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif",
  mono: "'SF Mono', Menlo, ui-monospace, monospace",
};
