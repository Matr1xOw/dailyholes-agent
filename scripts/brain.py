"""
The brain, for live play: given where a hole stands (the course, the hole and
the shots played on it so far), prints the next shot as JSON. The simulator
replays those shots exactly, so it always plans from where the ball really is.

Usage:
    .venv/bin/python scripts/brain.py <course key> <hole index 0-8> '<shots json>'
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.planner import Planner

CHECKPOINT = Path(__file__).resolve().parent.parent / "checkpoints" / "run-2" / "latest.pt"


def main():
    course_key, hole_index, shots = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])
    planner = Planner(str(CHECKPOINT))
    shot, details = planner.next_shot(course_key, hole_index, shots)
    # Where the sim says this shot ends up, as a check against the real game.
    after = planner.simulator.observe(course_key, hole_index, shots + [shot])
    details["expect"] = (
        {"done": True, "score": after["score"], "holed": after["holed"]}
        if after["done"] else {"done": False, "pin_distance": round(after["pin_distance"], 2), "lie": after["lie"]}
    )
    print(json.dumps({"shot": shot, "details": details}))
    planner.close()


if __name__ == "__main__":
    main()
