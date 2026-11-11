// Loads the real Daily Holes game script (vendor/game.js) inside a Node sandbox
// and hands back the pure game-logic functions: course building, terrain
// lookup, shot physics and hole replay.
//
// The script was written for a browser, so it expects things like `document`,
// a drawing canvas and `localStorage`. Node has none of those. Instead of
// editing their code, we run it unmodified and give it "stubs": fake objects
// that accept any property access or function call and quietly do nothing.
// The drawing and UI code runs into the void, and the physics loads exactly
// as the site wrote it.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const GAME_SCRIPT_PATH = path.join(__dirname, "..", "vendor", "game.js");

// A stub that never breaks: every property is another stub, calling it returns
// another stub, and it turns into 0 / "" when used as a number or string.
function makeStub(name = "stub") {
  const target = function () {};
  return new Proxy(target, {
    get(_, property) {
      if (property === Symbol.toPrimitive) return (hint) => (hint === "number" ? 0 : "");
      if (property === Symbol.iterator) return function* () {};
      if (property === "then") return undefined; // so nothing treats it as a Promise
      if (property === "length") return 0;
      // document.fonts.ready is a Promise the UI waits on; one that never resolves is harmless.
      if (property === "fonts") return { ready: new Promise(() => {}) };
      return makeStub(`${name}.${String(property)}`);
    },
    set() {
      return true;
    },
    apply() {
      return makeStub(`${name}()`);
    },
    construct() {
      return makeStub(`new ${name}`);
    },
    has() {
      return true;
    },
  });
}

// localStorage gets a real (in-memory) implementation, since the game reads
// values back out of it and a stub would confuse that logic.
function makeMemoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
    key: (index) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    },
  };
}

// Names the logic needs to read back out of the sandbox once the script runs.
const EXPORTED_NAMES = [
  "buildCourse",
  "surfaceAt",
  "resolveShot",
  "replayHole",
  "resumeHole",
  "shotRng",
  "puttRings",
  "puttsFrom",
  "strokeCap",
  "todayKey",
  "CLUBS",
  "LIE",
  "METER_MAX",
  "PURE_LO",
  "PURE_HI",
];

function loadGame() {
  if (!fs.existsSync(GAME_SCRIPT_PATH)) {
    throw new Error("vendor/game.js is missing. Run: python3 scripts/fetch_game.py");
  }
  const gameScript = fs.readFileSync(GAME_SCRIPT_PATH, "utf8");

  const sandbox = {
    console,
    Math,
    Date,
    Intl,
    JSON,
    // Timers and animation frames do nothing: no game loop should run here.
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    requestAnimationFrame: () => 0,
    cancelAnimationFrame: () => {},
    // No network access from the sandbox, ever.
    fetch: () => new Promise(() => {}),
    localStorage: makeMemoryStorage(),
    sessionStorage: makeMemoryStorage(),
    document: makeStub("document"),
    navigator: makeStub("navigator"),
    location: makeStub("location"),
    history: makeStub("history"),
    performance: { now: () => 0 },
    matchMedia: () => makeStub("matchMedia()"),
    addEventListener: () => {},
    removeEventListener: () => {},
    AudioContext: makeStub("AudioContext"),
    Image: makeStub("Image"),
    MutationObserver: makeStub("MutationObserver"),
    ResizeObserver: makeStub("ResizeObserver"),
    IntersectionObserver: makeStub("IntersectionObserver"),
    BroadcastChannel: makeStub("BroadcastChannel"),
    WebSocket: makeStub("WebSocket"),
    EventSource: makeStub("EventSource"),
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.parent = sandbox;
  sandbox.top = sandbox;

  const context = vm.createContext(sandbox);

  // The UI part of the script may still throw somewhere deep in the stubs.
  // That's fine as long as all the logic got defined first, which we check below.
  try {
    vm.runInContext(gameScript, context, { filename: "game.js" });
  } catch (error) {
    context.__loadError = String(error && error.stack ? error.stack.split("\n")[0] : error);
  }

  // `const` values at the top level of a script aren't properties of the
  // sandbox object, but a second script in the same context can still see
  // them. So we ask for everything by name from inside.
  const api = vm.runInContext(
    `({ ${EXPORTED_NAMES.map((name) => `${name}: typeof ${name} === "undefined" ? undefined : ${name}`).join(", ")} })`,
    context
  );

  const missing = EXPORTED_NAMES.filter((name) => api[name] === undefined);
  if (missing.length) {
    throw new Error(
      `couldn't load from game.js: ${missing.join(", ")}` +
        (context.__loadError ? ` (script stopped early: ${context.__loadError})` : "")
    );
  }
  api.loadWarning = context.__loadError || null;
  return api;
}

module.exports = { loadGame };
