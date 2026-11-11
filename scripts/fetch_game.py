"""
Downloads the Daily Holes game page and saves its game script locally.

The game runs inside https://dailyholes.com/play.html, and all of its logic
(course generation, ball physics, shot verification) lives in one big inline
<script> tag on that page. This pulls that script out and saves it to
vendor/game.js so the simulator can load it.

vendor/ is git-ignored on purpose: the game code belongs to its developer,
so everyone who uses this repo downloads their own copy instead.

Usage:
    python3 scripts/fetch_game.py
"""

import re
import sys
import urllib.request
from pathlib import Path

GAME_PAGE_URL = "https://dailyholes.com/play.html"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_FOLDER = PROJECT_ROOT / "vendor"

# Text that only appears in the real game script. Used to pick the right
# <script> tag out of the page (it also has small helper scripts).
GAME_SCRIPT_MARKERS = ["function resolveShot(", "function replayHole(", "function shotRng("]


def download_page(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def find_game_script(page_html):
    inline_scripts = re.findall(r"<script[^>]*>(.*?)</script>", page_html, re.DOTALL)
    for script_text in inline_scripts:
        if all(marker in script_text for marker in GAME_SCRIPT_MARKERS):
            return script_text
    return None


def main():
    print(f"downloading {GAME_PAGE_URL}")
    page_html = download_page(GAME_PAGE_URL)

    game_script = find_game_script(page_html)
    if game_script is None:
        sys.exit(
            "couldn't find the game script on the page. the site may have changed "
            "how it's built, so the markers in this file need updating."
        )

    VENDOR_FOLDER.mkdir(exist_ok=True)
    output_path = VENDOR_FOLDER / "game.js"
    output_path.write_text(game_script)
    print(f"saved {len(game_script):,} characters to {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
