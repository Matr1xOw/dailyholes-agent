// Parity test: does the game logic give exactly the same results in our Node
// sandbox as it does in the real game running in Chrome?
//
// `runParityCases` is written to be self-contained, so the exact same function
// can run in both places. It builds some courses, plays a fixed list of
// made-up shots on them, and records where every ball ends up. If the two
// result lists are identical, our simulator is playing the real game.
//
// Usage:
//   node sim/parity.js            runs the cases in Node and prints a fingerprint
//   node sim/parity.js --browser  prints the snippet to paste into the game page

const { loadGame } = require("./load_game.js");

function runParityCases(game) {
  // Our own little seeded generator, so the "random" shots are the same
  // list every time, in every environment.
  let state = 12345;
  function nextRandom() {
    state = (Math.imul(state, 1103515245) + 12345) >>> 0;
    return state / 4294967296;
  }

  const courseKeys = ["2026-11-10", "2026-11-12", "2026-11-15", "parity-a", "parity-b", "parity-c"];
  const results = [];

  for (const key of courseKeys) {
    const course = game.buildCourse(key);
    for (let holeIndex = 0; holeIndex < course.holes.length; holeIndex++) {
      const hole = course.holes[holeIndex];
      const tee = hole.path[0];
      const angleToGreen = Math.atan2(hole.green.x - tee.x, hole.green.y - tee.y);

      for (let attempt = 0; attempt < 6; attempt++) {
        const shotCount = 1 + Math.floor(nextRandom() * 4);
        const shots = [];
        for (let s = 0; s < shotCount; s++) {
          const clubIndex = Math.floor(nextRandom() * game.CLUBS.length);
          const aim = angleToGreen + (nextRandom() - 0.5) * 0.6;
          const meter = Math.round(nextRandom() * game.METER_MAX * 1000) / 1000;
          shots.push([clubIndex, aim, meter]);
        }
        const outcome = game.resumeHole(hole, holeIndex, key, shots);
        if (outcome == null) results.push("null");
        else if (outcome.score != null) results.push("score:" + outcome.score);
        else results.push(outcome.ball.x.toFixed(4) + "," + outcome.ball.y.toFixed(4) + "," + outcome.lie);
      }
    }
  }

  // A short fingerprint of all results, so the two sides can be compared at a glance.
  const joined = results.join("|");
  let hash = 2166136261;
  for (let i = 0; i < joined.length; i++) hash = Math.imul(hash ^ joined.charCodeAt(i), 16777619) >>> 0;
  return { count: results.length, fingerprint: hash.toString(16), results };
}

if (require.main === module) {
  if (process.argv.includes("--browser")) {
    // In the browser the game's functions and constants live in the page's global scope.
    console.log(
      `(${runParityCases.toString()})({ buildCourse, resumeHole, CLUBS, METER_MAX })`
    );
  } else {
    const game = loadGame();
    const { count, fingerprint, results } = runParityCases(game);
    const scored = results.filter((r) => r.startsWith("score")).length;
    console.log(`cases: ${count} (${scored} finished the hole), fingerprint: ${fingerprint}`);
    console.log("first few:", results.slice(0, 4).join("  "));
  }
}

module.exports = { runParityCases };
