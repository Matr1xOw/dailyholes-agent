"""
Draws what the agent sees: the mini-map at each shot of a hole, played by a
simple aim-at-the-pin player. Useful for checking the maps match the real game.

Usage:
    .venv/bin/python scripts/show_minimap.py [course_key] [hole_number]
    .venv/bin/python scripts/show_minimap.py 2026-11-15 1

Saves a PNG to outputs/ (which is gitignored).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from agent.env import GolfEnv, MAP_LAYERS

# One colour per ground type, in the same order as the map layers.
GROUND_COLOURS = {
    "fairway": (0.62, 0.82, 0.45),
    "rough": (0.42, 0.65, 0.32),
    "deep": (0.22, 0.42, 0.20),
    "bunker": (0.93, 0.85, 0.62),
    "water": (0.30, 0.58, 0.85),
    "ob": (0.55, 0.55, 0.55),
    "green": (0.45, 0.92, 0.55),
    "cart_or_ice": (0.75, 0.70, 0.62),
    "portal": (0.62, 0.35, 0.80),
}
CLUB_CARRIES = [278, 243, 221, 199, 179, 156, 131, 97, 63]
CLUB_NAMES = ["DR", "3W", "5W", "4i", "6i", "8i", "PW", "SW", "LW"]


def map_to_image(layers):
    size = layers.shape[1]
    image = np.zeros((size, size, 3))
    for name, colour in GROUND_COLOURS.items():
        image[layers[MAP_LAYERS.index(name)] > 0] = colour
    # Overlays: gust band lightened, windmill tinted red, putt rings tinted yellow.
    gust = layers[MAP_LAYERS.index("gust")] > 0
    image[gust] = image[gust] * 0.6 + 0.4
    mill = layers[MAP_LAYERS.index("mill")] > 0
    image[mill] = image[mill] * 0.5 + np.array([0.5, 0.1, 0.1])
    two_putt = layers[MAP_LAYERS.index("two_putt")] > 0
    image[two_putt] = image[two_putt] * 0.7 + np.array([0.3, 0.3, 0.0])
    one_putt = layers[MAP_LAYERS.index("one_putt")] > 0
    image[one_putt] = np.array([1.0, 0.85, 0.1])
    pin = layers[MAP_LAYERS.index("pin")] > 0
    image[pin] = np.array([0.85, 0.05, 0.05])
    return image


def simple_shot(pin_distance):
    for club in range(len(CLUB_CARRIES)):
        if pin_distance > CLUB_CARRIES[club] * 0.92 or club == len(CLUB_CARRIES) - 1:
            meter = min(1.0, max(0.1, pin_distance / CLUB_CARRIES[club] * 0.9))
            return club, meter


def main():
    course_key = sys.argv[1] if len(sys.argv) > 1 else "2026-11-15"
    hole_number = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    env = GolfEnv()
    info = env.simulator.course_info(course_key)
    state = env.reset(course_key=course_key, hole_index=hole_number - 1)

    panels = []
    while True:
        observation = env.last_observation
        club, meter = simple_shot(observation["pin_distance"])
        panels.append((state["map"], observation, club, meter))
        state, reward, done, result = env.step(club, 0.0, meter)
        if done:
            break
    env.close()

    figure, axes = plt.subplots(1, len(panels), figsize=(4 * len(panels), 4.6), squeeze=False)
    for axis, (layers, observation, club, meter) in zip(axes[0], panels):
        axis.imshow(map_to_image(layers), interpolation="nearest")
        size = layers.shape[1]
        ball_row = size - 1 - 0.1 * size
        axis.plot([size / 2 - 0.5], [ball_row], "wo", markersize=6, markeredgecolor="k")
        axis.set_title(
            f"{observation['pin_distance']:.0f} yds to pin, lie: {observation['lie']}\n"
            f"view {observation['view_yards']:.0f} yds wide, hit {CLUB_NAMES[club]} at {meter:.0%}",
            fontsize=9,
        )
        axis.set_xticks([])
        axis.set_yticks([])
    figure.suptitle(
        f"{info['name']} ({course_key}), hole {hole_number}: par {info['pars'][hole_number - 1]}, "
        f"{info['lengths'][hole_number - 1]} yds. Simple player scored {result['score']}.",
        fontsize=11,
    )
    figure.tight_layout()

    output_folder = Path(__file__).resolve().parent.parent / "outputs"
    output_folder.mkdir(exist_ok=True)
    output_path = output_folder / f"minimap_{course_key}_hole{hole_number}.png"
    figure.savefig(output_path, dpi=110)
    print(f"saved {output_path}")


if __name__ == "__main__":
    main()
