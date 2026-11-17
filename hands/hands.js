// The hands: play one planned shot in the real game, in the browser.
//
// This runs inside the game's own page (the play.html iframe), so it sees the
// same clock and the same animation frames the game does. It only ever does
// what a player's taps do: pick a club, tap to set the aim line, tap to lock
// the aim, tap to swing. It never writes the aim or power values itself.
//
// How the timing works. The game updates the swinging aim and the meter once
// per screen frame, from that frame's timestamp, and a tap uses whatever value
// the last frame left behind. So the hands:
//   1. Tap the aim line so the target angle sits right at the edge of the sweep,
//      where the swing slows to a stop and every frame near it is close.
//   2. Time that tap to within a fraction of a frame, so a frame lands right
//      on the edge.
//   3. Lock the aim on a frame whose actual aim is within tolerance, timing the
//      lock so a later frame lands exactly on the wanted meter value.
//   4. Swing on a frame whose actual meter is within tolerance.
// Steps 3 and 4 check the game's real value before tapping, so if a prediction
// is off it just waits for the next pass instead of hitting a bad shot.
//
// Usage, from the iframe's window:
//   hands.shoot(clubIndex, aimRadians, meter)  -> Promise of a report
//   hands.nextHole()                           -> moves on after a hole ends
//   hands.state()                              -> where things stand

(() => {
  // How close the game's aim and meter must be before the hands tap. Each shot
  // can pass its own: a hole-out needs to be tight, a drive doesn't, and a
  // looser tolerance means less waiting for the meter to come round.
  const DEFAULT_AIM_TOLERANCE_DEG = 0.004;
  const DEFAULT_METER_TOLERANCE = 0.0004;
  const WAIT_LIMIT_MS = 90000;

  const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));
  const frameTimes = [];
  (function watchFrames(t) {
    frameTimes.push(t);
    if (frameTimes.length > 240) frameTimes.shift();
    requestAnimationFrame(watchFrames);
  })(performance.now());

  // The time between frames. Measured over the whole recent stretch, not frame
  // to frame: the browser rounds timestamps to 0.1 ms, which reads a 60 Hz
  // screen as 16.7 ms instead of 16.667, and that small error adds up to a
  // couple of ms over a one-second swing, enough to miss the meter target.
  function frameInterval() {
    if (frameTimes.length < 10) return 1000 / 60;
    const gaps = [];
    for (let i = 1; i < frameTimes.length; i++) gaps.push(frameTimes[i] - frameTimes[i - 1]);
    gaps.sort((a, b) => a - b);
    const rough = gaps[Math.floor(gaps.length / 2)];
    const span = frameTimes[frameTimes.length - 1] - frameTimes[0];
    return span / Math.round(span / rough); // still right if a frame was dropped
  }

  // Inside a frame that started at frameTime, pick a moment to tap so that, for
  // one of the delays in "delays" (ms from tap to the wanted moment), a future
  // frame lands exactly on it. Returns the moment, or null if none fit in what
  // is left of this frame.
  function tapMomentFor(frameTime, delays) {
    const interval = frameInterval();
    const earliest = performance.now() - frameTime + 0.4;
    const latest = interval - 2.0;
    for (const delay of delays.slice().sort((a, b) => a - b)) {
      const offset = (((-delay) % interval) + interval) % interval;
      if (offset >= earliest && offset <= latest) return frameTime + offset;
    }
    return null;
  }
  function waitUntil(moment) { while (performance.now() < moment) { /* a few ms, on purpose */ } }

  async function waitFor(condition, what) {
    const started = performance.now();
    while (!condition()) {
      if (performance.now() - started > WAIT_LIMIT_MS) throw new Error("timed out waiting for " + (what));
      await nextFrame();
    }
  }
  const readyToAim = () => st.phase === "aim" && !st.locked && !st.anim && performance.now() >= aimGuard;
  const settled = () => !st.anim && (st.phase === "aim" || st.phase === "holeend") && !st.thief;

  async function shoot(clubIndex, aim, meter, tolerances = {}) {
    const AIM_TOLERANCE = ((tolerances.aim_deg || DEFAULT_AIM_TOLERANCE_DEG) * Math.PI) / 180;
    const METER_TOLERANCE = tolerances.meter || DEFAULT_METER_TOLERANCE;
    await waitFor(readyToAim, "the aim phase");
    // The game greys out clubs that carry further than this lie allows.
    if (CLUBS[clubIndex].carry > (pvLie().maxCarry || 1e9)) throw new Error("club " + clubIndex + " is not allowed from this lie");
    if (st.clubIdx !== clubIndex) pickClub(clubIndex);
    if (st.clubIdx !== clubIndex) throw new Error("could not pick club " + (clubIndex) + " from this lie");
    const club = CLUBS[clubIndex];
    const fan = (club.fan * Math.PI) / 180;
    const sweepMs = club.sweep * 1000;
    const center = aim - fan; // the sweep's right edge (+fan) is the target

    // 1-2: tap the aim line, timed so a frame lands on the sweep's edge.
    const peakDelays = [];
    for (let n = 0; n < 6; n++) peakDelays.push(sweepMs / 4 + n * sweepMs);
    for (;;) {
      const t = await nextFrame();
      const moment = tapMomentFor(t, peakDelays);
      if (moment == null) continue;
      waitUntil(moment);
      aimAt({ x: st.ball.x + 100 * Math.sin(center), y: st.ball.y + 100 * Math.cos(center) });
      break;
    }

    // 3: lock on a frame that's on target, timing the lock for the meter.
    const periodMs = club.climb * 2 * 1000;
    const rise = (meter / st.meterMax) * club.climb * 1000;
    const fall = (2 - meter / st.meterMax) * club.climb * 1000;
    const meterDelays = [];
    for (let n = 0; n < 25; n++) meterDelays.push(rise + n * periodMs, fall + n * periodMs);
    let lockedAt = null, aimPasses = 0, lastAim = null;
    const started = performance.now();
    while (lockedAt == null) {
      if (performance.now() - started > WAIT_LIMIT_MS) throw new Error("never got the aim on target");
      const t = await nextFrame();
      if (!(st.phase === "aim" && !st.locked)) throw new Error("aim phase ended unexpectedly (" + (st.phase) + ")");
      if (lastAim != null && Math.abs(lastAim - aim) < fan * 0.02) aimPasses++;
      lastAim = st.aimAngle;
      if (Math.abs(st.aimAngle - aim) > AIM_TOLERANCE) continue;
      const moment = tapMomentFor(t, meterDelays);
      if (moment == null) continue;
      waitUntil(moment);
      act();
      if (st.locked && st.phase === "power") lockedAt = performance.now();
    }
    const lockedAim = st.aimAngle;

    // 4: swing on a frame whose meter is on target.
    let meterPasses = 0;
    for (;;) {
      if (performance.now() - lockedAt > WAIT_LIMIT_MS) throw new Error("never got the meter on target");
      await nextFrame();
      if (st.phase !== "power") throw new Error("power phase ended unexpectedly (" + (st.phase) + ")");
      if (Math.abs(st.power - meter) <= METER_TOLERANCE) { act(); break; }
      meterPasses++;
    }
    const swungAt = performance.now();
    const logged = st.log[st.log.length - 1];

    await waitFor(settled, "the ball to stop");
    return {
      wanted: [clubIndex, aim, meter],
      played: [logged[2], logged[3], logged[4]],
      aim_error_deg: ((logged[3] - aim) * 180) / Math.PI,
      meter_error: logged[4] - meter,
      seconds_to_lock: (lockedAt - started) / 1000,
      seconds_to_swing: (swungAt - lockedAt) / 1000,
      frame_ms: frameInterval(),
      ...state(),
    };
  }

  function state() {
    return {
      course_key: course.key,
      course_name: course.name,
      practice,
      // The game's own test (see its end card): a ranked Wild Three runs with
      // practice=true under the hood but still counts.
      ranked: (!practice && !tutorial) || (wildOn && wildRanked),
      hole_index: st.holeIdx,
      phase: st.phase,
      strokes: st.strokes,
      scores: st.scores.slice(),
      round_over: st.scores.length >= course.holes.length,
      hole_shots: st.log.filter((r) => r[0] === st.holeIdx).sort((a, b) => a[1] - b[1]).map((r) => [r[2], r[3], r[4]]),
      ball: { x: st.ball.x, y: st.ball.y },
    };
  }

  function nextHole() {
    if (st.phase !== "holeend" || st.anim) throw new Error("not at the end of a hole (" + (st.phase) + ")");
    act();
    return state();
  }

  // The browser tool gives up on calls that take too long, and a swing can
  // take a while, so a shot can also run in the background: start() kicks it
  // off and wait() checks on it.
  let job = null;
  function start(clubIndex, aim, meter, tolerances) {
    job = { done: false };
    const current = job;
    shoot(clubIndex, aim, meter, tolerances).then(
      (report) => Object.assign(current, { done: true, report }),
      (error) => Object.assign(current, { done: true, error: String(error && error.message || error) }),
    );
    return "started";
  }
  async function wait(limitMs = 40000) {
    const until = performance.now() + limitMs;
    while (job && !job.done && performance.now() < until) await new Promise((r) => setTimeout(r, 200));
    return job;
  }

  window.hands = { shoot, start, wait, nextHole, state, frameInterval };
})();
