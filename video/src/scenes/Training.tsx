import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import data from "../../public/data.json";
import { Big, CountUp, Kicker, Muted, Reveal, Scene, Sfx } from "../parts";
import { colors, fonts, seconds, f30 } from "../theme";

const CHART = { width: 1600, height: 560, left: 90, right: 30, top: 30, bottom: 60 };
const Y_TOP = 6;
const Y_BOTTOM = -9;
const MAX_STEPS = 8_000_000;

const x = (steps: number) => CHART.left + (steps / MAX_STEPS) * (CHART.width - CHART.left - CHART.right);
const y = (toPar: number) => CHART.top + ((Y_TOP - toPar) / (Y_TOP - Y_BOTTOM)) * (CHART.height - CHART.top - CHART.bottom);

const Gridlines: React.FC = () => (
  <>
    {[6, 3, 0, -3, -6, -9].map((value) => (
      <g key={value}>
        <line x1={CHART.left} x2={CHART.width - CHART.right} y1={y(value)} y2={y(value)} stroke={colors.line} strokeWidth={2} />
        <text x={CHART.left - 18} y={y(value) + 10} fill={colors.muted} fontSize={26} textAnchor="end" fontFamily={fonts.mono}>
          {value > 0 ? `+${value}` : value}
        </text>
      </g>
    ))}
    {[0, 2, 4, 6, 8].map((millions) => (
      <text key={millions} x={x(millions * 1e6)} y={CHART.height - 14} fill={colors.muted} fontSize={26}
        textAnchor="middle" fontFamily={fonts.mono}>{millions}M</text>
    ))}
  </>
);

// A dashed line across the chart at a score, with its label. `besideBars`
// puts the label to the right of the line's end, clear of the ladder's bars.
const ReferenceLine: React.FC<{ value: number; label: string; color: string; show: number; besideBars?: boolean }> = ({
  value, label, color, show, besideBars = false,
}) => {
  const end = besideBars ? CHART.width - LADDER_LABEL_ROOM : CHART.width - CHART.right;
  return (
    <g opacity={show}>
      <line x1={CHART.left} x2={end} y1={y(value)} y2={y(value)} stroke={color} strokeWidth={3} strokeDasharray="12 10" />
      <text x={besideBars ? end + 16 : end - 8} y={besideBars ? y(value) + 10 : y(value) - 12} fill={color} fontSize={28}
        textAnchor={besideBars ? "start" : "end"} fontFamily={fonts.sans} fontWeight={700}>
        {label}
      </text>
    </g>
  );
};

const LADDER_LABEL_ROOM = 190; // space at the right of the ladder for the line labels

// 4. Reinforcement learning: the practice curve drawing itself.
const DRAW_START = 0.6;
const DRAW_END = 4.6;

export const Practice: React.FC = () => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [seconds(DRAW_START), seconds(DRAW_END)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const visible = data.curve.filter((point) => point.steps <= progress * MAX_STEPS);
  const path = visible.map((p, i) => `${i ? "L" : "M"}${x(p.steps).toFixed(1)},${y(p.to_par_round).toFixed(1)}`).join(" ");
  const last = visible[visible.length - 1];
  return (
    <Scene>
      <AbsoluteFill style={{ padding: "100px 160px" }}>
        <Reveal delay={f30(2)}>
          <div style={{ fontFamily: fonts.mono, fontSize: 96, color: colors.accent, fontWeight: 800, letterSpacing: -3 }}>
            <CountUp to={8_000_000} delay={seconds(DRAW_START)} duration={seconds(DRAW_END - DRAW_START)} /> practice shots
          </div>
        </Reveal>
        <Reveal delay={f30(10)} style={{ marginTop: 8 }}>
          <Muted size={38}>nobody told it how golf works, it figured it out</Muted>
        </Reveal>
        <svg width={CHART.width} height={CHART.height} style={{ marginTop: 40 }}>
          <Gridlines />
          <ReferenceLine value={data.baselines.smart_portals} label="my hand-written bot" color={colors.muted}
            show={interpolate(frame, [seconds(2.4), seconds(3)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
          <path d={path} fill="none" stroke={colors.accent} strokeWidth={6} strokeLinejoin="round" />
          {last && <circle cx={x(last.steps)} cy={y(last.to_par_round)} r={12} fill={colors.accent} />}
          {progress >= 1 && last && (
            <text x={x(last.steps) - 24} y={y(last.to_par_round) + 64} fill={colors.accent} fontSize={40} fontWeight={800}
              textAnchor="end" fontFamily={fonts.sans}>-6 a round</text>
          )}
        </svg>
      </AbsoluteFill>
      {Array.from({ length: 16 }, (_, i) => <Sfx key={i} name="tick" at={DRAW_START + i * 0.25} volume={0.18} />)}
      <Sfx name="click" at={2.45} />
      <Sfx name="pop" at={DRAW_END} volume={0.7} />
    </Scene>
  );
};
