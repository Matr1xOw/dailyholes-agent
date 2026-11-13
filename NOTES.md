# Project notes

A running log of how this project is going: what I decided, why, what the numbers said, and what I learned along the way. Newest entries at the bottom.

## 2026-11-16: Recon and planning

**The idea.** Daily Holes gives everyone the same nine holes each day. I wanted an agent that gets good at the game in general, not one that brute-forces a single day. So it has to train on lots of different courses and be tested on ones it has never seen.

**What the game's code showed.**
- The game runs in an iframe at `dailyholes.com/play.html`. All the logic sits in one big inline script, readable and with comments.
- Courses come from a seeded random number generator. The seed is the date, which is why everyone gets the same course. Any text works as a seed, so we can make unlimited practice courses.
- Shots are "random" too, but seeded by course, hole and stroke number, so the same shot on the same stroke always does the same thing. That's how the server can replay a submitted card to check it. It also explains why an overswing seemed to slice the same way every time.
- A shot is three numbers: club (0-8), aim angle, and meter (0 to 1.15). The pure band is 94.5-100%. Past 100% you get only about a third as much extra carry, plus a curve.
- In the UI, the aim swings in a sine wave across the club's cone, and the meter rises and falls at a steady speed. That's what the browser "hands" will have to time.
- Reaching the green ends the hole, and the putt rings decide 1, 2 or 3 putts. The cup is 0.36 yards across. A ball drops if it rolls over the cup with less than 1.6 yards of run left.
- Practice mode is unranked. Today's course is unlimited in practice once you've played your ranked round, and other courses get 3 practice rounds a day without a membership. The private-window trick works because the practice count lives in localStorage.
- Some rules switch on by date: free portals from Oct 13, chip rules from Oct 14, landing in the cup counts from Nov 4. Frozen ponds and winter courses kick in for December.

**Ground rules.** Never submit anything to the site. Train offline only. Keep the game's code out of the repo (it gets downloaded into a gitignored `vendor/` folder). Don't publish daily solutions.

**Plan.** The brain is the RL agent, which picks club, aim and meter. The hands are a separate browser module that turns those choices into click timing, with a learned correction for lag. The hands are supervised learning, not RL, because the timing follows an exact formula.

## 2026-11-16: Simulator

- Ran the whole unmodified `game.js` inside a Node sandbox (`vm`), with stubs standing in for the browser (document, canvas, observers and so on). Splitting the file by hand would have been fragile, because some physics functions live inside the rendering section.
- **Parity test:** 324 random shot sequences across 6 courses, fingerprinted. Node and the real game in Chrome both gave `cc0b655a`, so the results are identical.
- Speed is about 48,000 shots per second for the raw physics on one core, and about 11 ms to build a course.

## 2026-11-16: Environment

- Python talks to a long-running Node process, one JSON line each way. The Node side is stateless: Python sends the full shot list every time and Node replays the hole. That's cheap and means the two sides can never disagree.
- **State:** a 64x64 mini-map rotated so the pin is straight up (egocentric), zoomed to fit (40-360 yards across), with 14 layers: the terrain types, gust band, windmill, putt rings and the cup. Plus 24 numbers: distance, zoom level, wind, gust, lie, strokes, par, putt ring sizes, dunk hole, and portal type and position.
- Trees turned out to be scenery only, with no effect on play.
- **Reward:** -1 per stroke, minus putts at the end, so the total is exactly -score. On top of that there's a bonus of up to 0.5 for finishing close to the cup inside the one-putt ring. Without it every spot in the ring scores the same and hole-outs only happen by luck (sparse reward). It's capped under one stroke so the agent never trades a real stroke for it. Grading always uses the true score only.
- Started the bonus at 0.3 and raised it to 0.5, since hole-outs are what separate great rounds. Plan to watch the scores and adjust.

## 2026-11-16: Baselines

Scoreboard: 40 fixed test courses (`eval-0` to `eval-39`, 360 holes) that training never touches.

| player | vs par (9 holes) | hole-outs | one-putt ring |
|---|---|---|---|
| simple (aim at the pin) | +7.4 | 1.9% | 38.6% |
| smart (game formulas plus the map) | -2.4 | 2.8% | 49.2% |
| smart plus portals | -3.6 | 1.9% | 39.7% |

- Portals were a big miss at first. A **green portal** (16% of holes) drops you on the green: 1 putt one time in five, otherwise 2. A **forward portal** (3%, long holes only) skips hundreds of yards. Both are free. Teaching the smart player to use them was worth 1.2 strokes a round, even though its hole-outs went down.
- The smart player's roll estimate runs long in a tailwind (about +5 yards) and long with a full driver (about +15). That matches stopping below the green line in the real game. Small, skewed sample though, since only shots that missed the green could be measured.
- For scale: my typical round is -6 to -7 and my winning round was -13.

## 2026-11-16: First PPO run

Setup: CNN for the map plus a small network for the numbers. It picks the club first, then picks aim and meter with that club in mind. 8 environments at once, 1,024 shots per update, GAE (lambda 0.95, gamma 1.0), clip 0.2, entropy weight 0.005. 300k shots in about 40 minutes.

| shots | vs par per hole (exploring) | aim spread | meter spread |
|---|---|---|---|
| 1k | +5.36 | 7.8 deg | 0.136 |
| 150k | +1.01 | 4.8 deg | 0.090 |
| 300k | +0.49 | 3.2 deg | 0.057 |

Test set, greedy play: **-0.1 per round**, 1.1% hole-outs. That's way better than simple, but 3.5 strokes behind smart.

Where the gap is: green portals cost 48 strokes over the test set, forward portals 22, par 4s 54. Par 5s are about even with smart. It barely uses portals yet, since they're rare and small.

It was still improving when the run stopped, and the spreads shrank steadily without collapsing, so this looks like an undertrained agent, not a broken one.

**Decided:** stick with pure RL (no copying the smart player). For run two: make training faster, train much longer, and show it portal holes more often.

## 2026-11-16: Speeding things up for run two

- Profiled it. Almost all the simulator time is inside the game's own `surfaceAt()` (about 8 ms per mini-map). The learning side was 3.5 s per update on the CPU.
- **GPU:** moved the learning to the M4's GPU (`mps`). That's 217 ms down to 31 ms per minibatch, about 7x.
- **Adaptive map sampling:** look up every other cell first, and only do the real lookup for in-between cells where the neighbours disagree. 8.4 down to 4.5 ms per map. Checked against exact maps on 1,216 real positions: 0.013% of cells differ (about half a cell per map, on feature edges). `DH_EXACT_MAPS=1` switches back to exact.
- Overall about 260 steps/s with 10 environments, up from 128. Not the 3-5x I hoped for, since the game's terrain lookup is still the floor.
- **Portal oversampling:** 35% of training holes are now deliberately picked to have a portal (normally about 19%). The test set is unchanged so the comparison stays fair.
- Also added learning-rate decay (shrinks to zero over the run), brain snapshots every 500k shots, and a by-hole-type breakdown in the scoreboard.
- Started run two as an overnight run instead: 8M shots, 10 environments, about 8.5 hours, wrapped in `caffeinate` so the Mac stays awake. (A 3M version got 2 minutes in before I restarted it longer, so the learning-rate decay fits the full run.)

## Plan: showcase video (for my site)

To build after run two. No live recording needed: the run saves the brain every 500k shots, so everything can be replayed and filmed later.

- **Story:** the same hole played by brains from different points in training (untrained, 500k, 1M, ... 8M), alongside an animated learning curve, then a highlight reel of the trained agent's best shots, and maybe the agent playing the real game in Chrome as a finale.
- **Look:** a separate renderer just for the video, not the agent's 64x64 mini-map. Draw holes as smooth shapes from the course geometry at high resolution, with mowing stripes, soft rough edges, bunker shadows, water shading, glowing portals, turning windmills, flag and cup. Original style, not the game's own art.
- **Motion:** real ball flight from the physics (landing spot, roll path, curve, gust push), with a shadow that separates from the ball to show height, and a fading tracer.
- **Camera:** smooth eased pans and zooms that follow the ball, tight on approaches, slow motion and a hold on hole-outs and portal entries.
- **Overlays:** hole, par and yards; club and meter for each shot; stroke count; which brain is playing; a small learning curve with a moving marker.
- **Output:** Python renders each frame, ffmpeg stitches them into a 60 fps MP4.
- **Still to decide:** flat "yardage book" look or more realistic; 16:9, 9:16 or both; 30-60 second reel or longer.
- **Etiquette:** credit Daily Holes, say it's unofficial, and think about giving the developer a heads-up before showing real game footage.

## 2026-11-16: Run two results

8M shots, 10 environments, about 10.5 hours (the speed drifted from 250 down to about 211 steps/s over the night). It finished cleanly and saved a snapshot every 500k shots.

**Training curve** (average while exploring, on portal-oversampled holes, so it reads better than real play):

| shots | vs par per round | hole-outs | aim spread | meter spread |
|---|---|---|---|---|
| 0-1M | +3.3 | 1.5% | 2.7 deg | 0.048 |
| 1-2M | -2.7 | 2.2% | 0.8 deg | 0.013 |
| 3-4M | -3.8 | 2.2% | 0.5 deg | 0.009 |
| 5-6M | -4.8 | 2.2% | 0.4 deg | 0.006 |
| 7-8M | -5.8 | 2.4% | 0.3 deg | 0.005 |

**Test set** (360 unseen holes, greedy play), each snapshot:

| snapshot | vs par per round | hole-outs | birdie or better | bogey or worse |
|---|---|---|---|---|
| 500k | -1.5 | 1.4% | 44.7% | 16.1% |
| 1M | -2.1 | 1.4% | 41.9% | 11.1% |
| 1.5M | -3.1 | 3.1% | 49.2% | 11.1% |
| 2M | -2.6 | 1.9% | 44.7% | 13.9% |
| 2.5M | -2.5 | 2.8% | 44.4% | 13.1% |
| 3M | -3.8 | 2.8% | 50.3% | 9.2% |
| 3.5M | -3.1 | 2.5% | 48.1% | 10.0% |
| 4M | -3.9 | 2.2% | 50.0% | 9.2% |
| 4.5M | -3.2 | 2.5% | 49.4% | 8.6% |
| 5M | -4.7 | 1.7% | 53.1% | 5.6% |
| 5.5M | -4.5 | 3.6% | 51.4% | 8.3% |
| 6M | -4.8 | 2.5% | 53.6% | 6.1% |
| 6.5M | -5.3 | 2.8% | 57.2% | 7.2% |
| 7M | -5.4 | 2.8% | 57.5% | 5.6% |
| 7.5M | -6.2 | 4.7% | 61.4% | 4.4% |
| 8M | **-6.0** | 2.2% | 59.7% | 3.6% |

For comparison, smart plus portals is -3.6. The agent passed it somewhere between 3M and 5M shots. The test curve is bumpy from snapshot to snapshot (360 holes is a small sample), but the trend is steady, and the biggest late gain was in cutting bogeys.

**By hole type, 8M agent vs smart** (vs par per hole):

| hole type | holes | agent | smart |
|---|---|---|---|
| forward portal | 13 | -1.15 | -1.54 |
| green portal | 66 | -0.74 | -0.86 |
| par 3 | 76 | -0.21 | +0.34 |
| par 4 | 150 | -0.59 | -0.42 |
| par 5 | 51 | -1.33 | -0.57 |
| par 6+ | 4 | -0.50 | -0.25 |

The agent wins on all regular holes. Par 3s and par 5s are where it pulls away. Portal holes are the only place it's still behind, even with 35% oversampling. That's the obvious target for anything I try next.

**Takeaways.** The first run really was just undertrained: the same setup, run 27 times longer, went from -0.1 to -6.0. Exploration had mostly shut off by the end (0.3 deg aim spread), and the learning rate had decayed to zero, so more of the same probably gives diminishing returns. A fix aimed at portals (more oversampling, or a better portal feature) seems more promising than just training longer.
