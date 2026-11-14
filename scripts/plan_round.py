"""
Plays a full course offline with the planner (agent + hole-out search) and
prints every shot. Also saves the planned shots.

Usage:
    .venv/bin/python scripts/plan_round.py checkpoints/run-2/latest.pt 2026-11-16
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.planner import Planner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint")
    parser.add_argument("course_key")
    args = parser.parse_args()

    planner = Planner(args.checkpoint)
    info = planner.course_info(args.course_key)
    clubs = [club["id"] for club in info["clubs"]]
    print(f"{info['name']} ({args.course_key}), agent + hole-out search\n")
    started = time.time()
    total_to_par, round_shots = 0, []
    for hole_index in range(9):
        shots = []
        print(f"Hole {hole_index + 1}: par {info['pars'][hole_index]}, {info['lengths'][hole_index]} yd")
        while True:
            shot, details = planner.next_shot(args.course_key, hole_index, shots)
            shots.append(shot)
            line = f"  {clubs[shot[0]]:>3}  meter {shot[2]:.3f}  from {details['pin_distance']:5.1f} yd  [{details['source']}"
            if "aim_margin_deg" in details:
                line += f", margin {details['aim_margin_deg']:.2f} deg / {details['meter_margin']:.3f}"
            line += "]"
            if "note" in details:
                line += f" ({details['note']})"
            observation = planner.simulator.observe(args.course_key, hole_index, shots)
            if observation["done"]:
                print(line + ("  -> holed!" if observation["holed"] else f"  -> finished {observation['finish_pin_distance']:.1f} yd away"))
                break
            print(line + f"  -> {observation['lie']}, {observation['pin_distance']:.1f} yd left")
        to_par = observation["score"] - observation["par"]
        total_to_par += to_par
        round_shots.append(shots)
        print(f"  score {observation['score']} ({to_par:+d})\n")
    print(f"Total: {total_to_par:+d}   ({time.time() - started:.0f}s of planning)")
    out_path = Path(__file__).resolve().parent.parent / "outputs" / f"plan_{args.course_key}.json"
    out_path.write_text(json.dumps({"course": args.course_key, "shots": round_shots}))
    print(f"saved {out_path}")
    planner.close()


if __name__ == "__main__":
    main()
