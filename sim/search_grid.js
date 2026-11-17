// The inner loop of the hole-out search, shared by the server and its worker
// threads: try every (aim, meter) in a block of grid rows for one club and
// mark which ones are hits. Rows are aims, columns are meters.

function gridShape(request) {
  return {
    aimCount: 2 * Math.round(request.aim_half_width / request.aim_step) + 1,
    meterCount: 2 * Math.round(request.meter_half_width / request.meter_step) + 1,
  };
}

// Builds the "is this shot a hit?" test for a search request. Returns null if
// the goal can't be met on this hole at all (a portal search with no portal).
function makeHitTest(game, hole, request) {
  const shots = request.shots || [];
  let ball = { x: hole.path[0].x, y: hole.path[0].y }, lie = "tee", strokesBefore = 0;
  if (shots.length > 0) {
    const before = game.resumeHole(hole, request.hole, request.key, shots);
    if (!before || before.score != null) throw new Error("the hole is already over");
    ball = before.ball;
    lie = before.lie;
    strokesBefore = before.strokes;
  }
  // "holed" (the default): the shot drops. "portal": the shot comes to rest in
  // the hole's portal and gets sent to its exit. That is checked by replaying
  // the whole hole, so windmills and the like count too.
  if ((request.goal || "holed") === "portal") {
    if (!hole.portal) return null;
    return (club, aim, meter) => {
      const after = game.resumeHole(hole, request.hole, request.key, [...shots, [club, aim, meter]]);
      return after && after.score == null && after.strokes === strokesBefore + 1 &&
        Math.hypot(after.ball.x - hole.portal.exit.x, after.ball.y - hole.portal.exit.y) < 0.01;
    };
  }
  const rng = () => game.shotRng(request.key, request.hole, shots.length);
  return (club, aim, meter) => game.resolveShot(hole, ball, lie, game.CLUBS[club], aim, meter, rng()).holed;
}

// Fills rows [rowStart, rowEnd) of one club's grid. Returns one byte per cell.
// With a mask (one byte per cell of those rows), only cells it marks are tried.
function fillRows(game, hole, request, isHit, club, rowStart, rowEnd, mask = null) {
  const { aimCount, meterCount } = gridShape(request);
  const cells = new Uint8Array((rowEnd - rowStart) * meterCount);
  for (let i = rowStart; i < rowEnd; i++) {
    const aim = request.aim + (i - (aimCount - 1) / 2) * request.aim_step;
    for (let j = 0; j < meterCount; j++) {
      const k = (i - rowStart) * meterCount + j;
      if (mask && !mask[k]) continue;
      const meter = request.meter + (j - (meterCount - 1) / 2) * request.meter_step;
      if (meter < 0 || meter > game.METER_MAX) continue;
      if (isHit(club, aim, meter)) cells[k] = 1;
    }
  }
  return cells;
}

// ---------------------------------------------------------------------------
// Pruning, for big hole-out searches: most of a wide grid can't come anywhere
// near the cup (a 4 iron at full power on a 60 yard pitch). So first try every
// COARSE-th aim and meter and note how close each shot's path comes to the
// pin. Then only search the full grid around coarse shots that came close.
// ---------------------------------------------------------------------------

const COARSE = 4;

function segmentDistance(point, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, lengthSq = dx * dx + dy * dy;
  const t = lengthSq > 0 ? Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSq)) : 0;
  return Math.hypot(point.x - (a.x + dx * t), point.y - (a.y + dy * t));
}

// How close a shot's path along the ground comes to the pin (0 if it drops).
function makeApproachTest(game, hole, request) {
  const shots = request.shots || [];
  let ball = { x: hole.path[0].x, y: hole.path[0].y }, lie = "tee";
  if (shots.length > 0) {
    const before = game.resumeHole(hole, request.hole, request.key, shots);
    ball = before.ball;
    lie = before.lie;
  }
  return (club, aim, meter) => {
    const result = game.resolveShot(hole, ball, lie, game.CLUBS[club], aim, meter, game.shotRng(request.key, request.hole, shots.length));
    if (result.holed) return 0;
    const path = result.rollPath && result.rollPath.length ? result.rollPath : [result.land, result.rest];
    let closest = Math.hypot(path[0].x - hole.pin.x, path[0].y - hole.pin.y);
    for (let k = 1; k < path.length; k++) closest = Math.min(closest, segmentDistance(hole.pin, path[k - 1], path[k]));
    return closest;
  };
}

// The coarse cells in grid rows [rowStart, rowEnd) (only every COARSE-th row
// and column). Returns how close each came, Infinity where the meter is out of range.
function coarseRows(game, request, approach, club, rowStart, rowEnd) {
  const { aimCount, meterCount } = gridShape(request);
  const coarseCols = Math.ceil(meterCount / COARSE);
  const rows = [];
  for (let i = rowStart; i < rowEnd; i++) if (i % COARSE === 0) rows.push(i);
  const closest = new Float32Array(rows.length * coarseCols).fill(Infinity);
  rows.forEach((i, r) => {
    const aim = request.aim + (i - (aimCount - 1) / 2) * request.aim_step;
    for (let c = 0; c < coarseCols; c++) {
      const meter = request.meter + (c * COARSE - (meterCount - 1) / 2) * request.meter_step;
      if (meter < 0 || meter > game.METER_MAX) continue;
      closest[r * coarseCols + c] = approach(club, aim, meter);
    }
  });
  return closest;
}

module.exports = { gridShape, makeHitTest, fillRows, makeApproachTest, coarseRows, COARSE };
