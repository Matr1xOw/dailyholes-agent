// Experiment: for each hole of a saved round, keep every shot except the last
// one and search a grid of alternatives for that last shot (nearby clubs,
// aims and meters) to see whether a hole-out was there to be found, and how
// big the target is: how much aim and meter error a hole-out can absorb.
//
// Usage: node scripts/holeout_probe.js outputs/round_<...>.json

const fs = require("fs");
const { loadGame } = require("../sim/load_game.js");

const game = loadGame();
const round = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const key = round.course;
const course = game.buildCourse(key);

const AIM_HALF_WIDTH = (3 * Math.PI) / 180; // search +-3 degrees around the agent's aim
const AIM_STEP = (0.02 * Math.PI) / 180;
const METER_HALF_WIDTH = 0.15;
const METER_STEP = 0.001;

let totalSaved = 0;
course.holes.forEach((hole, holeIndex) => {
  const shots = round.shots[holeIndex];
  const lastIndex = shots.length - 1;
  let ball = { x: hole.path[0].x, y: hole.path[0].y }, lie = "tee";
  if (lastIndex > 0) {
    const before = game.resumeHole(hole, holeIndex, key, shots.slice(0, lastIndex));
    ball = before.ball;
    lie = before.lie;
  }
  const [agentClub, agentAim, agentMeter] = shots[lastIndex];
  const rnd = () => game.shotRng(key, holeIndex, lastIndex);

  const hits = [];
  let tried = 0;
  for (let club = Math.max(0, agentClub - 1); club <= Math.min(8, agentClub + 1); club++) {
    for (let aim = agentAim - AIM_HALF_WIDTH; aim <= agentAim + AIM_HALF_WIDTH; aim += AIM_STEP) {
      for (let meter = Math.max(0, agentMeter - METER_HALF_WIDTH); meter <= Math.min(game.METER_MAX, agentMeter + METER_HALF_WIDTH); meter += METER_STEP) {
        tried++;
        const result = game.resolveShot(hole, ball, lie, game.CLUBS[club], aim, meter, rnd());
        if (result.holed) hits.push([club, aim, meter]);
      }
    }
  }

  const agentScore = game.resumeHole(hole, holeIndex, key, shots).score;
  let summary = `hole ${holeIndex + 1} (par ${hole.par}): agent scored ${agentScore}, `;
  if (hits.length === 0) {
    summary += `no hole-out found in ${tried} tries`;
  } else {
    // A hole-out scores the strokes taken up to and including it.
    const holedScore = game.resumeHole(hole, holeIndex, key, [...shots.slice(0, lastIndex), hits[0]]).score;
    totalSaved += agentScore - holedScore;
    // Size of the target around the best hit: how far can aim / meter drift and still drop?
    const byClub = {};
    for (const [club, aim, meter] of hits) (byClub[club] = byClub[club] || []).push([aim, meter]);
    const parts = Object.entries(byClub).map(([club, list]) => {
      const aims = list.map((h) => h[0]), meters = list.map((h) => h[1]);
      const aimSpan = ((Math.max(...aims) - Math.min(...aims)) * 180) / Math.PI;
      const meterSpan = Math.max(...meters) - Math.min(...meters);
      return `${game.CLUBS[club].id}: ${list.length} hits, aim span ${aimSpan.toFixed(2)} deg, meter span ${meterSpan.toFixed(3)}`;
    });
    summary += `HOLE-OUT available (would score ${holedScore}). ${parts.join("; ")}`;
  }
  console.log(summary);
});
console.log(`strokes a perfect last shot would have saved: ${totalSaved}`);
