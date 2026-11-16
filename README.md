# dailyholes-agent

This is an experiment in teaching a reinforcement learning agent to play [Daily Holes](https://dailyholes.com), the daily nine-hole golf game. Everyone gets the same course each day, and I wanted to see if a model could actually get good at the game in general, rather than just brute-forcing one day's answer.

It isn't affiliated with Daily Holes in any way. Nothing here is ever submitted to the site, and none of it touches the leaderboard. It's a personal project for learning RL.

## How it works

The game generates its courses and runs its ball physics in the browser, seeded off the date. Feed it a different seed and you get a brand new course, so the agent can practice on thousands of courses locally without ever hitting their server.

The agent has two parts.

The brain is the RL side. It looks at a top-down mini-map of the hole around the ball, rotated so the pin is always straight ahead, along with the wind and the current lie. From that it picks a club, an aim angle, and how far up the meter to swing. It's trained with PPO, which I'm writing from scratch so I actually understand what's going on.

The hands play in the real browser. The aim swings back and forth and the meter rises and falls on a fixed timer, so the hands can work out exactly when to click, then learn a small correction for browser lag. That part exists so I can watch the agent play a practice round, which is honestly the fun part.

## The game code isn't included

The game's code belongs to its developer, so it isn't in this repo. You download your own copy:

```
python3 scripts/fetch_game.py
```

That saves it to `vendor/game.js`, which is gitignored. If the site changes how it's built, the script may need updating.

## Setup

You'll need Python 3 and Node.

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
python3 scripts/fetch_game.py
```

## Status

The simulator works. `sim/load_game.js` runs the game's own script in a Node sandbox, with fake stand-ins for the browser bits, and `sim/parity.js` checks it against the real game. Both give identical results on 324 test shots, and it runs at roughly 48,000 shots a second on one core. 

The training environment works too. `sim/server.js` keeps the simulator running in the background, and `agent/env.py` wraps it in the usual `reset()` / `step()` setup. Each state is a 64x64 mini-map rotated so the pin is straight up, plus a few numbers like wind and lie. `scripts/show_minimap.py` draws those maps so you can check them against the real game. 

For a fair comparison, `scripts/evaluate.py` plays any player on the same 40 test courses (360 holes) that training never touches. Two hand-written baselines, then the RL agent:

| player | vs par per round | hole-outs | finishes in one-putt ring |
|---|---|---|---|
| simple (aim at the pin) | +7.4 | 1.9% | 38.6% |
| smart (game formulas plus the map) | -2.4 | 2.8% | 49.2% |
| smart, plus going for portals | -3.6 | 1.9% | 39.7% |
| PPO, first run (300k shots, ~40 min) | -0.1 | 1.1% | 44.7% |
| PPO, run two (8M shots, ~10.5 hours) | -6.0 | 2.2% | 56.4% |

The smart one is the real bar. If the RL agent can't beat a page of if-statements, it isn't learning much. For a sense of scale, a good human round is around -6 or -7, and winning days can go as low as -13.

The first PPO run went from random (about +48 a round) to -0.1 in 40 minutes and was still improving when it stopped. Most of the gap to the smart player is on portal holes, which only show up on about one hole in five, so it hasn't had much practice with them yet.

Run two trained overnight on 8 million shots and came out at -6.0 a round on the test courses. That's 2.4 strokes better than the smart player and about where my own typical round sits. It beats the smart player on every kind of hole except portal holes, where the smart player still does slightly better. The 7.5M snapshot actually scored a bit better (-6.2), but that gap is within the noise for 360 holes.

## The super player

-6 a round is good but not great, and I wanted something that beats me. The problem is that holing out depends on a random number seeded for each stroke, which the agent can't see, so it can only learn to finish close. The simulator can see it, though. So the full player is the trained agent plus a search:

- **Hole-outs.** For each shot the simulator searches around the agent's idea (and a wider fan on short shots) for any shot that drops, and picks the one with the most room for error.
- **Forward portals.** Always taken, then the hole-out search runs from the exit.
- **Lookahead.** Before trusting the agent's shot, try a few thousand others and let the agent's own value estimate judge where they leave the ball. This is what saved the mostly-water hole that sank the first autopilot round.

`hands/hands.js` plays the shots in the real browser by timing the game's own taps to the frame (aim within about 0.0003 deg). Practice only, nothing is ever submitted.

To use it, run `./autopilot`. That opens the game in its own Chrome window with an Autopilot panel in the corner. Play as normal and switch it on whenever you want, even halfway through a hole, and it takes over from wherever the ball is. "Play one shot" does just the next shot, and switching it off hands back after the current shot. It won't play a ranked round. `./autopilot --course "Ferngate"` opens that practice course and plays the whole round by itself.

| round | result |
|---|---|
| Ferngate Old Course, real game, brain + hands | -20 |
| Stonemoor Links, real game, autopilot (before the lookahead) | -16 |
| All three recent courses replanned with the full brain | -21 to -24, eagle or better on every hole |

## Video and what's next

There's a 50 second showcase video in `video/`, built with Remotion from a real recorded autopilot round (-21). `cd video && npm install && npm run render` builds it, after running `scripts/make_audio.py` for the sound. The footage itself isn't in the repo.

The full status, gotchas, and the list of next steps are at the bottom of `NOTES.md`.

