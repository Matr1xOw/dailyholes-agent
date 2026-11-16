// For the video: tries a fine grid of aims and meters around one shot and
// records where each one finishes, so the video can show the tiny islands of
// shots that hole out. Prints JSON.
//
// Usage: node scripts/hitmap.js <course key> <hole index> '<[club, aim, meter]>'

const { loadGame } = require("../sim/load_game.js");

const game = loadGame();
const [key, holeArg, shotArg] = process.argv.slice(2);
const holeIndex = Number(holeArg);
const [club, centerAim, centerMeter] = JSON.parse(shotArg);
const hole = game.buildCourse(key).holes[holeIndex];
const tee = { x: hole.path[0].x, y: hole.path[0].y };

const SIZE = 120;
const AIM_HALF = (0.6 * Math.PI) / 180;
const METER_HALF = 0.03;
const rows = [];
let hits = 0;
for (let i = 0; i < SIZE; i++) {
  const meter = centerMeter + METER_HALF - (2 * METER_HALF * i) / (SIZE - 1);
  const row = [];
  for (let j = 0; j < SIZE; j++) {
    const aim = centerAim - AIM_HALF + (2 * AIM_HALF * j) / (SIZE - 1);
    const result = game.resolveShot(hole, tee, "tee", game.CLUBS[club], aim, meter, game.shotRng(key, holeIndex, 0));
    if (result.holed) hits++;
    // 0 = holed; otherwise yards from the cup, capped for the colour scale.
    row.push(result.holed ? 0 : Math.min(30, Math.round(Math.hypot(result.rest.x - hole.pin.x, result.rest.y - hole.pin.y) * 10) / 10));
  }
  rows.push(row);
}
console.log(JSON.stringify({
  course: key, hole: holeIndex + 1, par: hole.par, club: game.CLUBS[club].id,
  aim_half_width_deg: 0.6, meter_half_width: METER_HALF, meter_center: centerMeter,
  size: SIZE, hits, finish_yards: rows,
}));
