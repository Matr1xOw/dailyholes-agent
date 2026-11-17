// A worker thread for the hole-out search. It loads its own copy of the game
// and fills blocks of grid rows the server hands it (see search_grid.js).

const { parentPort } = require("worker_threads");
const { loadGame } = require("./load_game.js");
const { makeHitTest, fillRows, makeApproachTest, coarseRows } = require("./search_grid.js");

const game = loadGame();
const courses = new Map();
let setup = { id: null };

parentPort.on("message", ({ searchId, kind, request, club, rowStart, rowEnd, mask }) => {
  if (!courses.has(request.key)) {
    if (courses.size > 20) courses.clear();
    courses.set(request.key, game.buildCourse(request.key));
  }
  const hole = courses.get(request.key).holes[request.hole];
  // Replaying the hole to find the ball is cheap but not free, so do it once per search.
  if (setup.id !== searchId) setup = { id: searchId, isHit: makeHitTest(game, hole, request), approach: null };
  let cells;
  if (kind === "coarse") {
    if (!setup.approach) setup.approach = makeApproachTest(game, hole, request);
    cells = coarseRows(game, request, setup.approach, club, rowStart, rowEnd);
  } else {
    cells = fillRows(game, hole, request, setup.isHit, club, rowStart, rowEnd, mask);
  }
  parentPort.postMessage({ searchId, kind, club, rowStart, cells }, [cells.buffer]);
});
