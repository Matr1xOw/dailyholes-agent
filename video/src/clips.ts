// Turns the autopilot's event log (seconds from the start of the recording)
// into the moments the video cuts to.
import footage from "./footage.json";

type Event = { t: number; kind: string; hole?: number; shot?: number; score?: number; par?: number; holed?: boolean;
  scores?: number[]; to_par?: number; club?: string; source?: string; done?: boolean; swing_t?: number | null };
const events = footage.events as Event[];

export const nameFor = (score: number, par: number) => {
  if (score === 1) return "hole in one";
  return ({ [-1]: "birdie", [-2]: "eagle", [-3]: "albatross", [-4]: "condor" } as Record<number, string>)[score - par] ?? "par";
};

// How much of the swing to show before the club hits the ball.
const LEAD_IN = 2.2;

export type Moment = { from: number; swing: number; drop: number; hole: number; score: number; par: number };

// Every hole-out. `swing` comes from scripts/find_swings.py (the frame the
// game's button stops being green); `drop` is when the ball went in.
export const holeOuts: Moment[] = events
  .filter((e) => e.kind === "shot_end" && e.holed)
  .map((e) => {
    const swing = e.swing_t ?? e.t - 1.3;
    return { from: Math.max(0, swing - LEAD_IN), swing, drop: e.t, hole: (e.hole ?? 0) + 1, score: e.score ?? 0, par: e.par ?? 0 };
  });

// The same moment, starting `seconds` before the swing instead.
export const withLeadIn = (moment: Moment, seconds: number): Moment => ({ ...moment, from: Math.max(0, moment.swing - seconds) });

// The best few for the results montage: furthest under par first (aces count
// extra), skipping the opener the video starts with.
const rank = (m: Moment) => m.score - m.par - (m.score === 1 ? 0.5 : 0);
export const highlights = holeOuts.slice(1).sort((a, b) => rank(a) - rank(b)).slice(0, 4).sort((a, b) => a.hole - b.hole);

// A moment where the aim is swinging and nothing has been tapped yet.
const firstShotOfHole2 = events.find((e) => e.kind === "shot_start" && e.hole === 1);
export const aimingMoment = firstShotOfHole2 ? firstShotOfHole2.t : 5;

const roundOver = events.find((e) => e.kind === "round_over");
export const finalScores: number[] = roundOver?.scores ?? [];
export const finalToPar: number = roundOver?.to_par ?? 0;
export const pars: number[] = Array.from({ length: 9 }, (_, hole) =>
  events.find((e) => e.kind === "shot_end" && e.hole === hole)?.par ?? 4);
