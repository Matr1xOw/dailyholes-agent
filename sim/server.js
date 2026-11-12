// The simulator process that Python talks to.
//
// Python starts this once and keeps it running. They talk over stdin/stdout
// with one JSON message per line: Python writes a request, this writes back a
// response. Every request is answered in order.
//
// The server is "stateless" about episodes: Python keeps the list of shots
// taken so far and sends the whole list each time. Replaying a hole from the
// tee costs microseconds, and it means Python and Node can never disagree
// about where the ball is.
//
// Requests:
//   {"cmd": "observe", "key": "...", "hole": 0, "shots": [[club, aim, meter], ...]}
//     Replays the shots and describes the result: either the hole is over
//     (with its score), or where the ball is now plus the mini-map around it.
//   {"cmd": "course", "key": "..."}
//     Basic info about a course (name, pars).
//   {"cmd": "batch", "requests": [ ... ]}
//     Several requests in one message, to cut down on back-and-forth.

const readline = require("readline");
const { loadGame } = require("./load_game.js");

const game = loadGame();

// ---------------------------------------------------------------------------
// Mini-map settings
// ---------------------------------------------------------------------------

const MAP_SIZE = 64; // cells per side
const MIN_VIEW_YARDS = 40; // closest zoom, for short chips
const MAX_VIEW_YARDS = 360; // furthest zoom, a bit past a driver plus roll
const VIEW_PER_PIN_DISTANCE = 1.3; // the view reaches 30% past the pin
const BALL_FROM_BOTTOM = 0.1; // the ball sits 10% up from the bottom edge

// Each map cell is stored as one byte. The low 4 bits say what the ground is,
// and the high 4 bits are on/off flags for things laid over the ground.
const SURFACE_CODES = {
  fairway: 0, tee: 0, bridge: 0,
  rough: 1,
  deep: 2,
  bunker: 3, leaves: 3,
  water: 4,
  ob: 5,
  green: 6,
  cart: 7, ice: 7,
  portal: 8,
};
const FLAG_GUST = 1 << 4;
const FLAG_MILL = 1 << 5;
const FLAG_ONE_PUTT = 1 << 6;
const FLAG_TWO_PUTT = 1 << 7;

const LIE_NAMES = ["tee", "fairway", "rough", "deep", "bunker", "other"];

// ---------------------------------------------------------------------------
// Small geometry helpers. Angles follow the game: measured from +Y (tee
// toward green), positive is clockwise, so direction = (sin a, cos a).
// ---------------------------------------------------------------------------

const directionOf = (angle) => ({ x: Math.sin(angle), y: Math.cos(angle) });
const rightOf = (angle) => ({ x: Math.cos(angle), y: -Math.sin(angle) });
const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const bearing = (from, to) => Math.atan2(to.x - from.x, to.y - from.y);
const dot = (a, b) => a.x * b.x + a.y * b.y;

// How far along the hole's centre line a point is (used for the gust band).
function alongPath(path, point) {
  let best = Infinity, bestAlong = 0, walked = 0;
  for (let i = 0; i < path.length - 1; i++) {
    const a = path[i], b = path[i + 1];
    const dx = b.x - a.x, dy = b.y - a.y, lengthSq = dx * dx + dy * dy, length = Math.sqrt(lengthSq);
    let t = lengthSq > 0 ? ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSq : 0;
    t = Math.max(0, Math.min(1, t));
    const d = Math.hypot(point.x - (a.x + dx * t), point.y - (a.y + dy * t));
    if (d < best) { best = d; bestAlong = walked + length * t; }
    walked += length;
  }
  return bestAlong;
}

// ---------------------------------------------------------------------------
// Courses are built once and cached, since building takes ~10 ms.
// ---------------------------------------------------------------------------

const courseCache = new Map();
const COURSE_CACHE_LIMIT = 200;

function getCourse(key) {
  if (courseCache.has(key)) return courseCache.get(key);
  const course = game.buildCourse(key);
  if (courseCache.size >= COURSE_CACHE_LIMIT) courseCache.delete(courseCache.keys().next().value);
  courseCache.set(key, course);
  return course;
}

// ---------------------------------------------------------------------------
// Working out the ground type for every map cell. The game's surfaceAt() is
// the slow part (most of the time spent per step), so by default we call it
// for as few cells as we can get away with.
// ---------------------------------------------------------------------------

// Set DH_EXACT_MAPS=1 to look up every cell (slower, used to check the shortcut).
const exactMaps = process.env.DH_EXACT_MAPS === "1";

function exactGround(groundAt) {
  const ground = new Uint8Array(MAP_SIZE * MAP_SIZE);
  for (let row = 0; row < MAP_SIZE; row++)
    for (let col = 0; col < MAP_SIZE; col++) ground[row * MAP_SIZE + col] = groundAt(row, col);
  return ground;
}

// Adaptive sampling: look up every other cell in each direction first (a
// quarter of the map). Each cell in between sits among two or four of those.
// If they all agree, the gap is almost certainly the same ground, so copy it.
// Only where they disagree, along the edge of a bunker or the fairway, do the
// real lookup. Big uniform areas (out of bounds, wide fairway) become nearly free.
function adaptiveGround(groundAt) {
  const ground = new Uint8Array(MAP_SIZE * MAP_SIZE);
  for (let row = 0; row < MAP_SIZE; row += 2)
    for (let col = 0; col < MAP_SIZE; col += 2) ground[row * MAP_SIZE + col] = groundAt(row, col);

  const sampledNeighbours = (index) => {
    // The sampled rows/cols next to this one: itself if even, else one either side.
    const list = [];
    for (const step of index % 2 === 0 ? [0] : [-1, 1]) {
      const n = index + step;
      if (n >= 0 && n < MAP_SIZE && n % 2 === 0) list.push(n);
    }
    return list;
  };

  for (let row = 0; row < MAP_SIZE; row++) {
    for (let col = 0; col < MAP_SIZE; col++) {
      if (row % 2 === 0 && col % 2 === 0) continue;
      let first = -1, allSame = true;
      for (const r of sampledNeighbours(row)) {
        for (const c of sampledNeighbours(col)) {
          const value = ground[r * MAP_SIZE + c];
          if (first === -1) first = value;
          else if (value !== first) allSame = false;
        }
      }
      // Odd cells on the far edge only have neighbours on one side, so always look those up.
      const onFarEdge = (row === MAP_SIZE - 1 && row % 2 === 1) || (col === MAP_SIZE - 1 && col % 2 === 1);
      ground[row * MAP_SIZE + col] = allSame && !onFarEdge ? first : groundAt(row, col);
    }
  }
  return ground;
}

// ---------------------------------------------------------------------------
// The mini-map: a top-down picture of the hole around the ball, rotated so the
// pin is always straight up ("egocentric"), and zoomed to fit the pin.
// ---------------------------------------------------------------------------

function renderMiniMap(hole, ball) {
  const pinBearing = bearing(ball, hole.pin);
  const forward = directionOf(pinBearing);
  const right = rightOf(pinBearing);
  const pinDistance = distance(ball, hole.pin);
  const viewYards = Math.max(MIN_VIEW_YARDS, Math.min(MAX_VIEW_YARDS, pinDistance * VIEW_PER_PIN_DISTANCE));
  const cellYards = viewYards / MAP_SIZE;
  const rings = game.puttRings(hole);
  const gust = hole.gust;

  const cellPoint = (row, col) => {
    // Row 0 is the top of the picture (furthest ahead).
    const ahead = (MAP_SIZE - 1 - row + 0.5) * cellYards - BALL_FROM_BOTTOM * viewYards;
    const across = (col + 0.5) * cellYards - viewYards / 2;
    return {
      x: ball.x + forward.x * ahead + right.x * across,
      y: ball.y + forward.y * ahead + right.y * across,
    };
  };
  const groundAt = (row, col) => SURFACE_CODES[game.surfaceAt(hole, cellPoint(row, col))] ?? SURFACE_CODES.ob;
  const ground = exactMaps ? exactGround(groundAt) : adaptiveGround(groundAt);

  const cells = new Uint8Array(MAP_SIZE * MAP_SIZE);
  for (let row = 0; row < MAP_SIZE; row++) {
    for (let col = 0; col < MAP_SIZE; col++) {
      const point = cellPoint(row, col);
      let value = ground[row * MAP_SIZE + col];
      if (gust) {
        const along = alongPath(hole.path, point);
        if (along >= gust.along && along <= gust.along + gust.width) value |= FLAG_GUST;
      }
      if (hole.mill && distance(point, hole.mill) <= hole.mill.r) value |= FLAG_MILL;
      const toPin = distance(point, hole.pin);
      if (toPin <= rings.one) value |= FLAG_ONE_PUTT;
      if (toPin <= rings.two) value |= FLAG_TWO_PUTT;
      cells[row * MAP_SIZE + col] = value;
    }
  }
  return { cells, viewYards, pinBearing, forward, right, pinDistance, rings };
}

// ---------------------------------------------------------------------------
// The extra numbers that go alongside the picture.
// ---------------------------------------------------------------------------

function describeState(hole, holeIndex, ball, lie, strokes) {
  const map = renderMiniMap(hole, ball);
  const cap = game.strokeCap(hole);

  // The wind as a push along and across the line to the pin. Positive "along"
  // is a tailwind (it adds carry in the game's formula), positive "across" pushes right.
  const wind = directionOf(hole.wind);
  const windAlong = dot(wind, map.forward) * hole.wspd;
  const windAcross = dot(wind, map.right) * hole.wspd;

  let gustAlong = 0, gustAcross = 0;
  if (hole.gust) {
    const push = directionOf(hole.gust.dir);
    gustAlong = dot(push, map.forward) * hole.gust.spd;
    gustAcross = dot(push, map.right) * hole.gust.spd;
  }

  const lieName = LIE_NAMES.includes(lie) ? lie : "other";

  // Portals come in two kinds, and the map can't tell them apart, so we spell
  // it out. A green portal drops the ball on the green (the hole ends with one
  // or two putts). A forward portal sends it much further down the hole.
  // Since 13 Oct 2026 entering a portal costs no stroke.
  let portal = { has: false, on_green: false, ahead: 0, across: 0, radius: 0, exit_to_pin: 0 };
  if (hole.portal) {
    const offset = { x: hole.portal.x - ball.x, y: hole.portal.y - ball.y };
    portal = {
      has: true,
      on_green: !!hole.portal.onGreen,
      ahead: dot(offset, map.forward),
      across: dot(offset, map.right),
      radius: hole.portal.r,
      exit_to_pin: hole.portal.onGreen ? 0 : distance(hole.portal.exit, hole.pin),
    };
  }

  return {
    done: false,
    ball,
    lie,
    lie_index: LIE_NAMES.indexOf(lieName),
    strokes,
    strokes_left: cap - strokes,
    par: hole.par,
    hole_index: holeIndex,
    pin: hole.pin,
    pin_distance: map.pinDistance,
    pin_bearing: map.pinBearing,
    view_yards: map.viewYards,
    one_putt_radius: map.rings.one,
    two_putt_radius: map.rings.two,
    wind_along: windAlong,
    wind_across: windAcross,
    gust_along: gustAlong,
    gust_across: gustAcross,
    has_mill: !!hole.mill,
    is_dunk_hole: !!hole.dunk,
    portal,
    map_size: MAP_SIZE,
    map: Buffer.from(map.cells).toString("base64"),
  };
}

// ---------------------------------------------------------------------------
// Request handlers
// ---------------------------------------------------------------------------

function handleObserve(request) {
  const course = getCourse(request.key);
  const hole = course.holes[request.hole];
  if (!hole) throw new Error(`course ${request.key} has no hole ${request.hole}`);
  const shots = request.shots || [];

  if (shots.length === 0) {
    const tee = { x: hole.path[0].x, y: hole.path[0].y };
    return describeState(hole, request.hole, tee, "tee", 0);
  }

  const outcome = game.resumeHole(hole, request.hole, request.key, shots);
  if (outcome == null) throw new Error("the game rejected a shot (bad club index, aim or meter value)");
  if (outcome.score != null) {
    return { done: true, score: outcome.score, ace: !!outcome.ace, par: hole.par, shots_taken: shots.length,
             ...describeFinish(hole, request.hole, request.key, shots) };
  }
  return describeState(hole, request.hole, outcome.ball, outcome.lie, outcome.strokes);
}

// When a hole ends, resumeHole only reports the score. For the "finish close to
// the cup" bonus we also want to know where the last shot stopped and whether it
// dropped, so we replay up to the last shot and look at that one in detail.
function describeFinish(hole, holeIndex, key, shots) {
  const lastIndex = shots.length - 1;
  let ball = { x: hole.path[0].x, y: hole.path[0].y }, lie = "tee";
  if (lastIndex > 0) {
    const before = game.resumeHole(hole, holeIndex, key, shots.slice(0, lastIndex));
    if (!before || before.score != null) return { finish_pin_distance: null, holed: false };
    ball = before.ball;
    lie = before.lie;
  }
  const [clubIndex, aim, meter] = shots[lastIndex];
  const last = game.resolveShot(hole, ball, lie, game.CLUBS[clubIndex], aim, meter, game.shotRng(key, holeIndex, lastIndex));
  return {
    finish_pin_distance: last.holed ? 0 : distance(last.rest, hole.pin),
    holed: !!last.holed,
    one_putt_radius: game.puttRings(hole).one,
  };
}

function handleCourse(request) {
  const course = getCourse(request.key);
  return {
    key: course.key,
    name: course.name,
    pars: course.holes.map((h) => h.par),
    lengths: course.holes.map((h) => h.len),
    portal_kinds: course.holes.map((h) => (h.portal ? (h.portal.onGreen ? "green" : "forward") : null)),
    clubs: game.CLUBS.map((c) => ({ id: c.id, name: c.name, carry: c.carry, roll: c.roll })),
    meter_max: game.METER_MAX,
    lies: game.LIE,
  };
}

function handle(request) {
  switch (request.cmd) {
    case "observe": return handleObserve(request);
    case "course": return handleCourse(request);
    case "batch": return request.requests.map((r) => safeHandle(r));
    case "ping": return { pong: true };
    default: throw new Error(`unknown command: ${request.cmd}`);
  }
}

function safeHandle(request) {
  try {
    return { ok: true, result: handle(request) };
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) };
  }
}

const input = readline.createInterface({ input: process.stdin, terminal: false });
input.on("line", (line) => {
  if (!line.trim()) return;
  let request;
  try {
    request = JSON.parse(line);
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: "bad JSON" }) + "\n");
    return;
  }
  process.stdout.write(JSON.stringify(safeHandle(request)) + "\n");
});
