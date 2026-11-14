"""
Plays one full course with one player and prints every shot, so you can read
a round the way you'd watch it. Runs offline in the simulator.

Usage:
    .venv/bin/python scripts/play_course.py ppo:checkpoints/run-2/latest.pt 2026-11-16
    .venv/bin/python scripts/play_course.py smart 2026-11-16
"""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.env import GolfEnv
from scripts.evaluate import get_player


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("player")
    parser.add_argument("course_key")
    args = parser.parse_args()

    player = get_player(args.player)
    env = GolfEnv()
    info = env.simulator.course_info(args.course_key)
    clubs = [club["id"] for club in info["clubs"]]
    print(f"{info['name']} ({args.course_key}), played by {args.player}\n")

    total_to_par = 0
    round_shots = []
    for hole_index in range(9):
        state = env.reset(course_key=args.course_key, hole_index=hole_index)
        observation = env.last_observation
        portal = info["portal_kinds"][hole_index]
        print(f"Hole {hole_index + 1}: par {info['pars'][hole_index]}, {info['lengths'][hole_index]} yd"
              + (f", {portal} portal" if portal else ""))
        while True:
            club, aim, meter = player(observation, state, info)
            before = observation["pin_distance"]
            state, reward, done, result = env.step(club, aim, meter)
            line = (f"  {clubs[club]:>3}  aim {math.degrees(aim):+5.1f} deg  meter {meter:.3f}"
                    f"  from {before:5.1f} yd")
            if done:
                finish = result["finish_pin_distance"]
                where = "holed!" if result["holed"] else (f"finished {finish:.1f} yd away" if finish is not None else "finished")
                print(line + f"  -> {where}")
                break
            observation = env.last_observation
            print(line + f"  -> {observation['lie']}, {observation['pin_distance']:.1f} yd left")
        round_shots.append(list(env.shots))
        to_par = result["score"] - result["par"]
        total_to_par += to_par
        print(f"  score {result['score']} ({to_par:+d})\n")
    print(f"Total: {total_to_par:+d}")
    safe_name = args.player.replace(":", "_").replace("/", "_")
    out_path = Path(__file__).resolve().parent.parent / "outputs" / f"round_{safe_name}_{args.course_key}.json"
    out_path.write_text(json.dumps({"course": args.course_key, "player": args.player, "shots": round_shots}))
    print(f"saved {out_path}")
    env.close()


if __name__ == "__main__":
    main()
