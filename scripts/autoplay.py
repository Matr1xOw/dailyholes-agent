"""
The autopilot: watches a practice round of the real game and plays it, start
to finish, with no one at the keyboard.

    .venv/bin/python scripts/autoplay.py
    .venv/bin/python scripts/autoplay.py --course "Stonemoor"

It opens a Chrome window (your installed Chrome, but its own profile, kept in
.browser-profile/) on dailyholes.com, with a small Autopilot panel in the
corner. Play as normal; switch the autopilot on whenever you like (even
mid-hole) and it takes over from wherever the ball is, or use "Play one shot"
for a single shot. Switch it off and it hands back after the current shot.

With --course and part of a course's name, it opens that practice round itself
through the normal Practice menu (so the usual practice limit still applies)
and plays the whole thing.

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


# A small control panel added to the browser window, so the autopilot can be
# switched on and off from the page instead of the terminal. It lives in the
# top page (not the game), so it never gets in the game's way.
PANEL_SCRIPT = """
if (window.top === window) {
  window.__autopilot = { on: false, once: false };
  const build = () => {
    if (document.getElementById('autopilot-panel')) return;
    const panel = document.createElement('div');
    panel.id = 'autopilot-panel';
    panel.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;width:230px;padding:12px;' +
      'border-radius:12px;background:#14231b;color:#e8f2ea;font:13px/1.4 -apple-system,system-ui,sans-serif;' +
      'box-shadow:0 6px 24px rgba(0,0,0,.25)';
    panel.innerHTML =
      '<div style="font-weight:600;margin-bottom:8px">Autopilot</div>' +
      '<button id="autopilot-toggle" style="width:100%;padding:8px;border:0;border-radius:8px;font-weight:600;cursor:pointer"></button>' +
      '<button id="autopilot-once" style="width:100%;margin-top:6px;padding:6px;border:1px solid #3d5c48;border-radius:8px;' +
      'background:transparent;color:#e8f2ea;cursor:pointer">Play one shot</button>' +
      '<div id="autopilot-status" style="margin-top:8px;color:#a9c4b1;min-height:2.8em"></div>';
    document.body.appendChild(panel);
    const toggle = panel.querySelector('#autopilot-toggle');
    const paint = () => {
      toggle.textContent = window.__autopilot.on ? 'On: playing' : 'Off: you play';
      toggle.style.background = window.__autopilot.on ? '#4caf6e' : '#2c4235';
      toggle.style.color = window.__autopilot.on ? '#0d1a12' : '#e8f2ea';
    };
    toggle.onclick = () => { window.__autopilot.on = !window.__autopilot.on; paint(); };
    panel.querySelector('#autopilot-once').onclick = () => { window.__autopilot.once = true; };
    window.__autopilotPaint = paint;
    window.__autopilotStatus = (text) => { panel.querySelector('#autopilot-status').textContent = text; };
    paint();
  };
  if (document.body) build(); else document.addEventListener('DOMContentLoaded', build);
}
"""


# Game phases that mean a round is actually being played (not the menu).
PLAYING_PHASES = {"aim", "power", "flight", "settle", "putting", "holeend", "trapped", "thief"}


class Panel:
    """The page's control panel, as seen from Python."""

    def __init__(self, page):
        self.page = page
        self.last_status = None

    def wanted(self):
        try:
            return self.page.evaluate("() => window.__autopilot ? { ...window.__autopilot } : { on: false, once: false }")
        except Exception:
            return {"on": False, "once": False}

    def set(self, on=None, once=None):
        changes = {k: v for k, v in (("on", on), ("once", once)) if v is not None}
        try:
            self.page.evaluate("(c) => { if (!window.__autopilot) return; Object.assign(window.__autopilot, c);"
                               " window.__autopilotPaint && window.__autopilotPaint(); }", changes)
        except Exception:
            pass

    def status(self, text):
        if text == self.last_status:
            return
        self.last_status = text
        try:
            self.page.evaluate("(t) => window.__autopilotStatus && window.__autopilotStatus(t)", text)
        except Exception:
            pass


def check_against_simulator(planner, course_key, hole_index, report):
    """What really happened, and whether the simulator agrees with the game."""
    real = planner.simulator.observe(course_key, hole_index, report["hole_shots"])
    if real["done"]:
        real_score = report["scores"][hole_index] if len(report["scores"]) > hole_index else None
        outcome = "holed!" if real["holed"] else f"finished {real['finish_pin_distance']:.1f} yd away"
        return real, outcome, real_score == real["score"]
    ball = report["ball"]
    agrees = math.hypot(ball["x"] - real["ball"]["x"], ball["y"] - real["ball"]["y"]) < 0.01
    return real, f"{real['lie']}, {real['pin_distance']:.1f} yd left", agrees


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", help="part of a course name from the Practice list: opens it and plays the whole round")
    parser.add_argument("--checkpoint", default=str(PROJECT_ROOT / "checkpoints" / "run-2" / "latest.pt"))
    args = parser.parse_args()

    print("Loading the brain...")
    planner = Planner(args.checkpoint)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch_persistent_context(
            str(PROJECT_ROOT / ".browser-profile"), channel="chrome", headless=False, viewport=None,
        )
        browser.add_init_script(PANEL_SCRIPT)
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(SITE)
        panel = Panel(page)
        if args.course:
            open_practice_round(page, args.course)
            panel.set(on=True)
        print("Use the Autopilot panel in the bottom-right of the Chrome window to switch it on and off.")
        print("It takes over from wherever you are, even mid-hole. Close the window to quit.")

        course_key, info, club_names = None, None, None
        log, saved_rounds = [], set()
        while not page.is_closed():
            try:
                wanted = panel.wanted()
                frame = find_game_frame(page)
                state = read_state(frame) if frame else None
            except Exception:  # the page is navigating or closing
                time.sleep(0.5)
                continue
            in_round = state is not None and (state["phase"] in PLAYING_PHASES or state["round_over"])
            if not in_round:
                panel.status("Waiting for a round to start." + (" Switch me on any time." if not wanted["on"] else ""))
                time.sleep(0.5)
                continue

            if course_key != state["course_key"]:
                course_key = state["course_key"]
                info = planner.course_info(course_key)
                club_names = [club["id"] for club in info["clubs"]]
                log = []
                print(f"\n{info['name']} ({course_key}){', practice' if state['practice'] else ''}. Par {sum(info['pars'])}.")

            to_par = sum(state["scores"]) - sum(info["pars"][: len(state["scores"])])
            if state["round_over"]:
                panel.set(on=False, once=False)
                panel.status(f"Round over: {to_par:+d}.")
                round_id = (course_key, tuple(state["scores"]))
                if state["practice"] and round_id not in saved_rounds and log:
                    saved_rounds.add(round_id)
                    out = PROJECT_ROOT / "outputs" / f"autoplay_{course_key}_{time.strftime('%Y%m%d-%H%M%S')}.json"
                    out.write_text(json.dumps({"course": course_key, "scores": state["scores"], "to_par": to_par,
                                               "shots": log}, indent=1))
                    print(f"\nRound over: {state['scores']}  {to_par:+d}   saved {out}")
                time.sleep(0.5)
                continue

            if not (wanted["on"] or wanted["once"]):
                panel.status(f"Off. Hole {state['hole_index'] + 1}, {to_par:+d} so far.")
                time.sleep(0.3)
                continue
            if not state["practice"]:
                # Ranked rounds are yours alone. Switch off and leave it be.
                panel.set(on=False, once=False)
                panel.status("This is a ranked round. The autopilot only plays practice.")
                print("Refused: that's a ranked round.")
                continue

            if state["phase"] == "holeend":
                frame.evaluate("() => hands.nextHole()")
                if wanted["once"] and not wanted["on"]:
                    panel.set(once=False)
                time.sleep(0.5)
                continue
            if state["phase"] != "aim":
                panel.status("Waiting for the ball (or for your swing to finish).")
                time.sleep(0.3)
                continue

            hole_index, shots = state["hole_index"], state["hole_shots"]
            if not shots:
                print(f"\nHole {hole_index + 1}: par {info['pars'][hole_index]}, {info['lengths'][hole_index]} yd"
                      + (f", {info['portal_kinds'][hole_index]} portal" if info["portal_kinds"][hole_index] else ""))
            panel.status(f"Hole {hole_index + 1}, shot {len(shots) + 1}: thinking...")
            started = time.time()
            shot, details = planner.next_shot(course_key, hole_index, shots)
            think_seconds = time.time() - started
            expected = planner.simulator.observe(course_key, hole_index, shots + [shot])
            tolerances = tolerances_for(details)
            plan_text = describe(club_names, shot, details)
            print(f"  {plan_text}  (thought for {think_seconds:.0f}s)", flush=True)
            goal = "going for the hole" if expected["done"] and expected["holed"] else details["source"]
            panel.status(f"Hole {hole_index + 1}: {club_names[shot[0]]}, {goal}.")

            try:
                report = frame.evaluate("([c, a, m, t]) => hands.shoot(c, a, m, t)", [shot[0], shot[1], shot[2], tolerances])
            except Exception as error:  # the hands refuse rather than hit a bad shot
                print(f"  the hands stopped: {error}")
                panel.set(on=False, once=False)
                panel.status("Stopped (" + str(error)[:80] + "). Your shot.")
                continue
            if wanted["once"]:
                panel.set(once=False)

            real, outcome, agrees = check_against_simulator(planner, course_key, hole_index, report)
            as_planned = expected["done"] == real["done"] and (not real["done"] or expected["score"] == real["score"])
            print(f"     -> {outcome}   (aim off {report['aim_error_deg']:+.4f} deg, meter off {report['meter_error']:+.5f}, "
                  f"swing took {report['seconds_to_swing']:.1f}s"
                  + ("" if as_planned else ", not what was planned")
                  + ("" if agrees else ", SIMULATOR DISAGREES WITH THE GAME") + ")", flush=True)
            if real["done"]:
                print(f"     score {real['score']} ({real['score'] - info['pars'][hole_index]:+d})")
            log.append({"hole": hole_index, "shot": shot, "details": details, "tolerances": tolerances,
                        "played": report["played"], "aim_error_deg": report["aim_error_deg"],
                        "meter_error": report["meter_error"], "seconds_to_swing": report["seconds_to_swing"],
                        "agrees_with_simulator": agrees})
        print("Window closed.")
    planner.close()


if __name__ == "__main__":
    main()
