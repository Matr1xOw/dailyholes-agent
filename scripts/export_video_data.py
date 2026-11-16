"""
Gathers the numbers the showcase video needs into video/public/data.json:
the training curve, the test score of every snapshot, the baselines, a planned
round's scorecard, and a "hit map" (which nearby shots hole out) for one shot.

Usage:
    .venv/bin/python scripts/export_video_data.py 2026-11-11
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "video" / "public" / "data.json"


def training_curve(points=160):
    rows = list(csv.DictReader(open(PROJECT_ROOT / "runs" / "run-2" / "log.csv")))
    window = max(1, len(rows) // points)
    curve = []
    for start in range(0, len(rows) - window + 1, window):
        chunk = rows[start:start + window]
        curve.append({
            "steps": int(chunk[-1]["steps"]),
            "to_par_round": round(9 * sum(float(r["avg_to_par"]) for r in chunk) / len(chunk), 3),
        })
    return curve


def snapshot_ladder():
    ladder = []
    for path in sorted(PROJECT_ROOT.glob("outputs/eval_ppo_checkpoints_run-2_steps_*k.json"),
                       key=lambda p: int(p.stem.split("_")[-1][:-1])):
        summary = json.load(open(path))["summary"]
        ladder.append({"steps": int(path.stem.split("_")[-1][:-1]) * 1000,
                       "to_par_round": round(summary["average_to_par_per_round"], 2)})
    return ladder


def main():
    course_key = sys.argv[1]
    plan = json.load(open(PROJECT_ROOT / "outputs" / f"plan_{course_key}.json"))
    hitmap = json.loads(subprocess.run(
        ["node", str(PROJECT_ROOT / "scripts" / "hitmap.js"), course_key, "0", json.dumps(plan["shots"][0][0])],
        capture_output=True, text=True, check=True).stdout)
    data = {
        "curve": training_curve(),
        "ladder": snapshot_ladder(),
        "baselines": {"simple": 7.4, "smart": -2.4, "smart_portals": -3.6, "me_typical": -6.5, "me_best": -13},
        "hitmap": hitmap,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data))
    print(f"saved {OUT} ({len(data['curve'])} curve points, {len(data['ladder'])} snapshots, "
          f"{hitmap['hits']} hole-outs in the hit map)")


if __name__ == "__main__":
    main()
