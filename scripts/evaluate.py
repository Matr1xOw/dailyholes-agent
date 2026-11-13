"""
The scoreboard: plays a player on a fixed set of test courses and reports how
it did. The test courses ("eval-0", "eval-1", ...) are never used in training,
so this measures how well a player handles holes it has never seen.

Usage:
    .venv/bin/python scripts/evaluate.py simple
    .venv/bin/python scripts/evaluate.py smart --courses 40
    .venv/bin/python scripts/evaluate.py ppo:checkpoints/first-run/latest.pt
"""

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.baselines import PLAYERS
from agent.env import GolfEnv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_player(player_name):
    """A baseline by name, or "ppo:<checkpoint path>" for a trained agent."""
    if player_name.startswith("ppo:"):
        from agent.policy_player import PolicyPlayer

        return PolicyPlayer(player_name[len("ppo:"):])
    return PLAYERS[player_name]


def hole_type(par, portal_kind):
    if portal_kind:
        return f"{portal_kind} portal"
    return f"par {min(par, 6)}{'+' if par >= 6 else ''}, no portal"


def play_course(job):
    """Play all 9 holes of one test course. Runs in its own process."""
    player_name, course_key = job
    player = get_player(player_name)
    env = GolfEnv()
    game_info = env.simulator.course_info(course_key)
    results = []
    for hole_index in range(9):
        state = env.reset(course_key=course_key, hole_index=hole_index)
        while True:
            club, aim, meter = player(env.last_observation, state, game_info)
            state, reward, done, info = env.step(club, aim, meter)
            if done:
                break
        one_putt_radius = env.last_observation["one_putt_radius"]
        finish = info["finish_pin_distance"]
        results.append({
            "course": course_key,
            "hole": hole_index + 1,
            "par": info["par"],
            "score": info["score"],
            "holed": info["holed"],
            "in_one_putt_ring": finish is not None and finish < one_putt_radius,
            "hole_type": hole_type(info["par"], game_info["portal_kinds"][hole_index]),
        })
    env.close()
    return results


def summarise(results):
    holes = len(results)
    to_par = [r["score"] - r["par"] for r in results]
    return {
        "holes": holes,
        "average_to_par_per_hole": sum(to_par) / holes,
        "average_to_par_per_round": 9 * sum(to_par) / holes,
        "hole_out_rate": sum(r["holed"] for r in results) / holes,
        "one_putt_ring_rate": sum(r["in_one_putt_ring"] for r in results) / holes,
        "birdie_or_better": sum(t < 0 for t in to_par) / holes,
        "par": sum(t == 0 for t in to_par) / holes,
        "bogey_or_worse": sum(t > 0 for t in to_par) / holes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("player", help=f"one of {sorted(PLAYERS)}, or ppo:<checkpoint path>")
    parser.add_argument("--courses", type=int, default=40)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    jobs = [(args.player, f"eval-{i}") for i in range(args.courses)]
    start = time.time()
    with Pool(args.workers) as pool:
        results = [hole for course in pool.map(play_course, jobs) for hole in course]
    summary = summarise(results)

    print(f"player: {args.player}, {summary['holes']} holes in {time.time() - start:.0f}s")
    print(f"  average vs par:   {summary['average_to_par_per_hole']:+.3f} per hole "
          f"({summary['average_to_par_per_round']:+.1f} per 9-hole round)")
    print(f"  hole-out rate:    {summary['hole_out_rate']:.1%}")
    print(f"  one-putt ring:    {summary['one_putt_ring_rate']:.1%} (including hole-outs)")
    print(f"  birdie or better: {summary['birdie_or_better']:.1%}   par: {summary['par']:.1%}   "
          f"bogey or worse: {summary['bogey_or_worse']:.1%}")

    print("  by hole type:")
    for kind in sorted({r["hole_type"] for r in results}):
        group = [r for r in results if r["hole_type"] == kind]
        average = sum(r["score"] - r["par"] for r in group) / len(group)
        print(f"    {kind:20s} {len(group):4d} holes  {average:+.2f} per hole")

    output_folder = PROJECT_ROOT / "outputs"
    output_folder.mkdir(exist_ok=True)
    safe_name = args.player.replace("ppo:", "ppo_").replace("/", "_").replace(".pt", "")
    output_path = output_folder / f"eval_{safe_name}.json"
    output_path.write_text(json.dumps({"summary": summary, "holes": results}, indent=1))
    print(f"  saved {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
