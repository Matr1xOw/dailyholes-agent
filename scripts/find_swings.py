"""
For the video's sound: finds the exact moment of each swing in a recorded
round. The game's action button is green ("Swing") while the meter runs and
turns grey the instant the ball is struck, so the swing is the first frame
where it stops being green. Adds a "swing_t" to each shot_end event in
video/src/footage.json.

Usage: .venv/bin/python scripts/find_swings.py
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FFMPEG_DIR = ROOT / "video" / "node_modules" / "@remotion" / "compositor-darwin-arm64"
VIDEO = ROOT / "video" / "public" / "footage" / "round.webm"
FOOTAGE_JSON = ROOT / "video" / "src" / "footage.json"
BUTTON_PIXEL = (640, 910)  # inside the action button, in the 1600x1000 recording
RECORDING_FPS = 25
LOOK_BACK_SECONDS = 6


def is_green(path):
    r, g, b = Image.open(path).convert("RGB").getpixel(BUTTON_PIXEL)
    return g > r + 40 and g > b + 20


def main():
    footage = json.loads(FOOTAGE_JSON.read_text())
    env = {**os.environ, "DYLD_LIBRARY_PATH": str(FFMPEG_DIR)}
    for event in footage["events"]:
        if event["kind"] != "shot_end":
            continue
        start = max(0.0, event["t"] - LOOK_BACK_SECONDS)
        folder = tempfile.mkdtemp()
        subprocess.run([str(FFMPEG_DIR / "ffmpeg"), "-v", "error", "-ss", str(start), "-t", str(LOOK_BACK_SECONDS + 0.5),
                        "-i", str(VIDEO), os.path.join(folder, "f%03d.png")], env=env, check=True)
        frames = sorted(os.listdir(folder))
        greens = [is_green(os.path.join(folder, name)) for name in frames]
        swing = None
        for index in range(1, len(greens)):
            if greens[index - 1] and not greens[index]:
                swing = round(start + index / RECORDING_FPS, 2)
        shutil.rmtree(folder)
        event["swing_t"] = swing
        print(f"hole {event['hole'] + 1} shot {event['shot'] + 1}: swing {swing}, ends {event['t']}"
              + ("  (holed)" if event.get("holed") else ""))
    FOOTAGE_JSON.write_text(json.dumps(footage, indent=1))


if __name__ == "__main__":
    main()
