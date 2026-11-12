"""
The golf environment the agent trains in.

One episode is one hole. The agent sees the state, picks a shot, and gets
back the new state and a reward, until the hole is finished.

    env = GolfEnv()
    state = env.reset()
    while True:
        state, reward, done, info = env.step(club_index, aim_offset, meter)
        if done:
            break

State: a dict with two parts.
    "map":      a 13 x 64 x 64 array. A top-down picture of the hole around the
                ball, rotated so the pin is straight up. Each of the 13 layers is
                0/1 for one thing (fairway, rough, water, gust band, ...).
    "features": a short vector of numbers the picture can't show well, like
                the wind, the lie and how many strokes have been taken.

Action: three numbers.
    club_index: 0-8 (driver down to lob wedge)
    aim_offset: radians left (-) or right (+) of the line straight at the pin
    meter:      0 to 1.15, where the swing meter stops (1.0 is full)

Reward: -1 for each stroke (penalty strokes included), and when the hole ends,
minus the number of putts. So the score part of the reward for a hole is
exactly -score.

On top of that there's a small "finish near the cup" bonus, up to
CLOSE_FINISH_BONUS, for ending the hole inside the one-putt ring (the closer,
the bigger; holing out gets all of it). Without it, every spot inside the ring
scores the same and the agent has no reason to chase the cup, so it would only
ever hole out by luck. The bonus is kept well under one stroke so it can never
be worth giving up a real stroke for. When judging how good the agent is, only
the true score counts, which is always in info["score"].
"""

import base64
import random

import numpy as np

from agent.sim_client import SimClient

NUM_CLUBS = 9
METER_MAX = 1.15
MAX_AIM_OFFSET = 0.8  # radians, about 46 degrees either side of the pin
CLOSE_FINISH_BONUS = 0.5  # most the "finish near the cup" bonus can be worth, in strokes
BALL_FROM_BOTTOM = 0.1  # must match sim/server.js

# Layer order in the map. The first nine come from the ground type stored in
# the low 4 bits of each cell, the next four from the flag bits, and the last
# one marks the cup (added here in Python, since we know exactly where it is).
SURFACE_LAYERS = ["fairway", "rough", "deep", "bunker", "water", "ob", "green", "cart_or_ice", "portal"]
FLAG_LAYERS = ["gust", "mill", "one_putt", "two_putt"]
MAP_LAYERS = SURFACE_LAYERS + FLAG_LAYERS + ["pin"]

LIE_NAMES = ["tee", "fairway", "rough", "deep", "bunker", "other"]

FEATURE_NAMES = [
    "pin_distance", "view_yards", "wind_along", "wind_across", "gust_along", "gust_across",
    "has_mill", "is_dunk_hole", "one_putt_radius", "two_putt_radius", "strokes", "strokes_left", "par",
    "has_portal", "portal_on_green", "portal_ahead", "portal_across", "portal_exit_to_pin",
] + [f"lie_{name}" for name in LIE_NAMES]


def decode_map(observation):
    """Turn the simulator's packed bytes into a (14, size, size) array of 0s and 1s."""
    size = observation["map_size"]
    cells = np.frombuffer(base64.b64decode(observation["map"]), dtype=np.uint8).reshape(size, size)
    surface = cells & 0x0F
    layers = np.zeros((len(MAP_LAYERS), size, size), dtype=np.float32)
    for index in range(len(SURFACE_LAYERS)):
        layers[index] = surface == index
    for flag_number in range(len(FLAG_LAYERS)):
        layers[len(SURFACE_LAYERS) + flag_number] = (cells >> (4 + flag_number)) & 1

    # The cup is always dead ahead (the map is rotated that way), at the pin
    # distance. It sits on the line between the two middle columns, so both
    # get marked. If the pin is further than the map reaches, nothing is marked.
    cell_yards = observation["view_yards"] / size
    rows_ahead = int((observation["pin_distance"] + BALL_FROM_BOTTOM * observation["view_yards"]) // cell_yards)
    pin_row = size - 1 - rows_ahead
    if 0 <= pin_row < size:
        layers[MAP_LAYERS.index("pin"), pin_row, size // 2 - 1 : size // 2 + 1] = 1.0
    return layers


def close_finish_bonus(finish_pin_distance, one_putt_radius):
    """Up to CLOSE_FINISH_BONUS for finishing inside the one-putt ring, more the closer you are."""
    if finish_pin_distance is None or finish_pin_distance >= one_putt_radius:
        return 0.0
    closeness = 1.0 - finish_pin_distance / one_putt_radius  # 1 at the cup, 0 at the ring's edge
    return CLOSE_FINISH_BONUS * closeness**2


def build_features(observation):
    """The extra numbers, each scaled to land roughly between -1 and 1."""
    lie_one_hot = [1.0 if observation["lie_index"] == i else 0.0 for i in range(len(LIE_NAMES))]
    portal = observation["portal"]
    return np.array(
        [
            observation["pin_distance"] / 300.0,
            observation["view_yards"] / 360.0,
            observation["wind_along"] / 30.0,
            observation["wind_across"] / 30.0,
            observation["gust_along"] / 40.0,
            observation["gust_across"] / 40.0,
            1.0 if observation["has_mill"] else 0.0,
            1.0 if observation["is_dunk_hole"] else 0.0,
            observation["one_putt_radius"] / 20.0,
            observation["two_putt_radius"] / 40.0,
            observation["strokes"] / 10.0,
            observation["strokes_left"] / 10.0,
            observation["par"] / 7.0,
            1.0 if portal["has"] else 0.0,
            1.0 if portal["on_green"] else 0.0,
            portal["ahead"] / 300.0,
            portal["across"] / 300.0,
            portal["exit_to_pin"] / 300.0,
        ]
        + lie_one_hot,
        dtype=np.float32,
    )


class GolfEnv:
    def __init__(self, simulator=None, course_prefix="train", seed=None, portal_share=0.0):
        # Courses are named "<prefix>-<number>". Training and evaluation use
        # different prefixes so the agent is always tested on holes it never saw.
        # The prefix must start with a letter: the game switches some rules on by
        # comparing the course key to dates like "2026-10-13" as text, and
        # letters sort after digits, so lettered keys always get the current rules.
        #
        # portal_share: when picking a random hole, how often to deliberately
        # pick one with a portal. Portals are on only about 1 hole in 5 and are
        # worth a lot, so training can show them more often than real courses
        # do ("oversampling"). 0 means pick holes exactly as they come.
        self.simulator = simulator or SimClient()
        self.course_prefix = course_prefix
        self.portal_share = portal_share
        self.random = random.Random(seed)
        self.course_key = None
        self.hole_index = None
        self.shots = []
        self.last_observation = None

    def reset(self, course_key=None, hole_index=None):
        """Start a new hole. With no arguments it picks a random course and hole."""
        self.course_key = course_key or f"{self.course_prefix}-{self.random.randrange(10**9)}"
        if hole_index is None:
            hole_index = self.random.randrange(9)
            if self.portal_share > 0 and self.random.random() < self.portal_share:
                kinds = self.simulator.course_info(self.course_key)["portal_kinds"]
                portal_holes = [index for index, kind in enumerate(kinds) if kind]
                if portal_holes:
                    hole_index = self.random.choice(portal_holes)
        self.hole_index = hole_index
        self.shots = []
        self.last_observation = self.simulator.observe(self.course_key, self.hole_index, self.shots)
        return self._make_state(self.last_observation)

    def step(self, club_index, aim_offset, meter):
        """Hit one shot. Returns (state, reward, done, info)."""
        if self.last_observation is None or self.last_observation["done"]:
            raise RuntimeError("call reset() before step()")

        club_index = int(np.clip(club_index, 0, NUM_CLUBS - 1))
        aim_offset = float(np.clip(aim_offset, -MAX_AIM_OFFSET, MAX_AIM_OFFSET))
        meter = float(np.clip(meter, 0.0, METER_MAX))

        # The game wants an absolute aim angle, so we add the offset to the
        # direction of the pin from where the ball is now.
        aim_angle = self.last_observation["pin_bearing"] + aim_offset
        self.shots.append([club_index, aim_angle, meter])

        strokes_before = self.last_observation["strokes"]
        observation = self.simulator.observe(self.course_key, self.hole_index, self.shots)
        self.last_observation = observation

        if observation["done"]:
            # Everything from here to the final score: this shot, any penalty, and the putts.
            reward = -(observation["score"] - strokes_before)
            reward += close_finish_bonus(observation["finish_pin_distance"], observation["one_putt_radius"])
            info = {
                "score": observation["score"],
                "par": observation["par"],
                "ace": observation["ace"],
                "holed": observation["holed"],
                "finish_pin_distance": observation["finish_pin_distance"],
            }
            return None, float(reward), True, info

        reward = -(observation["strokes"] - strokes_before)
        info = {"ball": observation["ball"], "lie": observation["lie"], "pin_distance": observation["pin_distance"]}
        return self._make_state(observation), float(reward), False, info

    def _make_state(self, observation):
        return {
            "map": decode_map(observation),
            "features": build_features(observation),
        }

    def close(self):
        self.simulator.close()
