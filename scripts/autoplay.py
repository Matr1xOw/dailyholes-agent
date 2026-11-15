"""
The autopilot: watches a practice round of the real game and plays it, start
to finish, with no one at the keyboard.

    .venv/bin/python scripts/autoplay.py
    .venv/bin/python scripts/autoplay.py --course "Stonemoor"

It opens a Chrome window (your installed Chrome, but its own profile, kept in
.browser-profile/) on dailyholes.com. Start a practice round in that window
(Practice, then pick a course) and it takes over from the first tee. Or pass
--course with part of a course's name and it opens that one itself, through
the normal Practice menu (so the usual practice limit still applies).

For every shot:
  1. read the real game: course, hole, and the shots played on it so far,
  2. the brain (agent + search, agent/planner.py) picks the next shot,
  3. the hands (hands/hands.js, running inside the game page) play it,
  4. check the real result against what the simulator predicted.

It only ever plays practice rounds. If the round on screen is ranked, it
won't touch it. Practice rounds aren't sent anywhere, so nothing it does ends
up on a leaderboard.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.planner import Planner

HANDS_SOURCE = (PROJECT_ROOT / "hands" / "hands.js").read_text()
SITE = "https://dailyholes.com/"

# How exact the hands must be for a shot. For a planned hole-out, a fraction of
# that shot's margin. For anything else (drives, layups, portal entries) the
# brain replans from wherever the ball really ends up, so close is fine, and a
# looser tolerance means the hands rarely wait for the meter to come round.
LOOSE_TOLERANCES = {"aim_deg": 0.02, "meter": 0.002}
MARGIN_SHARE = 0.4


def tolerances_for(details):
    if "aim_margin_deg" not in details:
        return LOOSE_TOLERANCES
    return {
        "aim_deg": min(max(details["aim_margin_deg"] * MARGIN_SHARE, 0.001), 0.05),
        "meter": min(max(details["meter_margin"] * MARGIN_SHARE, 0.0002), 0.003),
    }


def find_game_frame(page):
    for frame in page.frames:
        if "play.html" in frame.url:
            return frame
    return None


def read_state(frame):
    """The game's state as the hands see it, loading the hands first if needed."""
    has_hands = frame.evaluate("() => typeof window.hands === 'object'")
    if not has_hands:
        ready = frame.evaluate("() => { try { return typeof st === 'object' && !!course; } catch (e) { return false; } }")
        if not ready:
            return None
        frame.evaluate("() => {\n" + HANDS_SOURCE + "\n}")
    return frame.evaluate("() => hands.state()")


def open_practice_round(page, course_name):
    """Practice -> pick the course, by clicking the menu like a player would."""
    deadline = time.time() + 30
    frame = None
    while frame is None and time.time() < deadline:
        frame = find_game_frame(page) or page.main_frame
        try:
            frame.get_by_text("Practice", exact=True).first.click(timeout=3000)
        except Exception:
            frame = None
            time.sleep(1)
    row = frame.get_by_text(course_name, exact=False).first
    row.click(timeout=10000)
    print(f"Opened a practice round: {row.inner_text().strip()}")


def describe(club_names, shot, details):
    text = f"{club_names[shot[0]]:>3}  meter {shot[2]:.3f}  [{details['source']}"
    if "aim_margin_deg" in details:
        text += f", margin {details['aim_margin_deg']:.3f} deg / {details['meter_margin']:.4f}"
    return text + "]"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", help="part of a course name from the Practice list, to start it automatically")
    parser.add_argument("--checkpoint", default=str(PROJECT_ROOT / "checkpoints" / "run-2" / "latest.pt"))
    args = parser.parse_args()

    print("Loading the brain...")
    planner = Planner(args.checkpoint)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch_persistent_context(
            str(PROJECT_ROOT / ".browser-profile"), channel="chrome", headless=False, viewport=None,
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(SITE)
        if args.course:
            open_practice_round(page, args.course)
        else:
            print("Start a practice round in the Chrome window (Practice, then pick a course).")

        log, warned_ranked, course_key, club_names = [], False, None, None
        while True:
            frame = find_game_frame(page)
            state = read_state(frame) if frame else None
            if state is None or state["phase"] in (None, "watch"):
                time.sleep(0.5)
                continue
            if not state["practice"]:
                if not warned_ranked:
                    print("That's a ranked round. The autopilot only plays practice rounds, so it's leaving this one alone.")
                    warned_ranked = True
                time.sleep(1)
                continue
            warned_ranked = False

            if course_key != state["course_key"]:
                course_key = state["course_key"]
                info = planner.course_info(course_key)
                club_names = [club["id"] for club in info["clubs"]]
                print(f"\n{info['name']} ({course_key}), practice. Par {sum(info['pars'])}.")

            if state["round_over"]:
                break
            if state["phase"] == "holeend":
                if not page.is_closed():
                    frame.evaluate("() => hands.nextHole()")
                time.sleep(0.5)
                continue
            if state["phase"] != "aim":
                time.sleep(0.3)  # ball in the air, a windmill, an animal running off with it...
                continue

            hole_index, shots = state["hole_index"], state["hole_shots"]
            if not shots:
                print(f"\nHole {hole_index + 1}: par {info['pars'][hole_index]}, {info['lengths'][hole_index]} yd"
                      + (f", {info['portal_kinds'][hole_index]} portal" if info["portal_kinds"][hole_index] else ""))
            started = time.time()
            shot, details = planner.next_shot(course_key, hole_index, shots)
            think_seconds = time.time() - started
            expected = planner.simulator.observe(course_key, hole_index, shots + [shot])
            tolerances = tolerances_for(details)
            print(f"  {describe(club_names, shot, details)}  (thought for {think_seconds:.0f}s)", flush=True)

            try:
                report = frame.evaluate("([c, a, m, t]) => hands.shoot(c, a, m, t)", [shot[0], shot[1], shot[2], tolerances])
            except Exception as error:  # the hands refuse rather than hit a bad shot
                print(f"  the hands stopped: {error}")
                print("  Leaving the round where it is so you can take over.")
                break

            # What really happened, compared with what the simulator said would.
            real = planner.simulator.observe(course_key, hole_index, report["hole_shots"])
            if real["done"]:
                outcome = "holed!" if real["holed"] else f"finished {real['finish_pin_distance']:.1f} yd away"
                real_score = report["scores"][hole_index] if len(report["scores"]) > hole_index else None
                agrees = real_score == real["score"]
            else:
                outcome = f"{real['lie']}, {real['pin_distance']:.1f} yd left"
                ball = report["ball"]
                agrees = math.hypot(ball["x"] - real["ball"]["x"], ball["y"] - real["ball"]["y"]) < 0.01
            as_planned = expected["done"] == real["done"] and (not real["done"] or expected["score"] == real["score"])
            print(f"     -> {outcome}   (aim off {report['aim_error_deg']:+.4f} deg, meter off {report['meter_error']:+.5f}, "
                  f"swing took {report['seconds_to_swing']:.1f}s"
                  + ("" if as_planned else ", not what was planned")
                  + ("" if agrees else ", SIMULATOR DISAGREES WITH THE GAME") + ")", flush=True)
            if real["done"]:
                to_par = real["score"] - info["pars"][hole_index]
                print(f"     score {real['score']} ({to_par:+d})")
            log.append({"hole": hole_index, "shot": shot, "details": details, "tolerances": tolerances,
                        "played": report["played"], "aim_error_deg": report["aim_error_deg"],
                        "meter_error": report["meter_error"], "seconds_to_swing": report["seconds_to_swing"],
                        "agrees_with_simulator": agrees})

        if course_key and state and state.get("round_over"):
            scores = state["scores"]
            total = sum(scores) - sum(info["pars"][: len(scores)])
            print(f"\nRound over: {scores}  total {sum(scores)}, {total:+d}")
            out = PROJECT_ROOT / "outputs" / f"autoplay_{course_key}_{time.strftime('%Y%m%d-%H%M%S')}.json"
            out.write_text(json.dumps({"course": course_key, "scores": scores, "to_par": total, "shots": log}, indent=1))
            print(f"saved {out}")
        try:
            input("Press Enter to close the browser.")
        except EOFError:
            time.sleep(5)
        browser.close()
    planner.close()


if __name__ == "__main__":
    main()
