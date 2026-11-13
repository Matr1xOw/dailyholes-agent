"""
Hand-written players, used as baselines for the RL agent to beat.

A player is a function that takes (observation, state, game_info) and returns
(club_index, aim_offset, meter):
    observation: the raw dict from the simulator (pin_distance, lie, wind, ...)
    state:       what the RL agent sees (the mini-map and feature vector)
    game_info:   club and lie tables from the game, fetched once at startup
"""

import math

import numpy as np

from agent.env import MAP_LAYERS

PURE_LOW, PURE_HIGH = 0.945, 1.0
SOLID_LOW = 0.72
BALL_FROM_BOTTOM = 0.1


# ---------------------------------------------------------------------------
# The game's carry formula and its inverse (copied in spirit from the game:
# a pure strike adds up to 8%, and past 100% each extra bit adds only a third).
# ---------------------------------------------------------------------------

def carry_factor(meter):
    if meter < PURE_LOW:
        smash = 1.0
    elif meter <= PURE_HIGH:
        smash = 1.0 + 0.08 * (meter - PURE_LOW) / (PURE_HIGH - PURE_LOW)
    else:
        smash = 1.08
    return (min(meter, 1.0) + max(0.0, meter - 1.0) * 0.35) * smash


def meter_for(fraction):
    """What meter position carries `fraction` of a club's full distance? (binary search)"""
    low, high = 0.02, 1.15
    for _ in range(34):
        middle = (low + high) / 2
        if carry_factor(middle) < fraction:
            low = middle
        else:
            high = middle
    return (low + high) / 2


# ---------------------------------------------------------------------------
# Player 1: aim straight at the pin and hope.
# ---------------------------------------------------------------------------

def simple_player(observation, state, game_info):
    distance = observation["pin_distance"]
    carries = [club["carry"] for club in game_info["clubs"]]
    for club_index, carry in enumerate(carries):
        if distance > carry * 0.92 or club_index == len(carries) - 1:
            meter = min(1.0, max(0.1, distance / carry * 0.9))
            return club_index, 0.0, meter


# ---------------------------------------------------------------------------
# Player 2: uses the game's own formulas, plus a look at the mini-map.
# ---------------------------------------------------------------------------

# How much the smart player likes landing on each kind of ground.
LANDING_VALUES = {
    "fairway": 0.0, "green": 0.5, "rough": -0.3, "deep": -0.8, "bunker": -0.6,
    "water": -3.0, "ob": -3.0, "cart_or_ice": -0.1, "portal": 0.0,
}
OFF_MAP_VALUE = -0.5
MILL_VALUE = -1.0
YARDS_LEFT_COST = 0.01  # per yard still to go after the shot


def expected_full_carry(club, lie, wind_along):
    """How far this club flies at 100% from this lie, in this wind (no randomness)."""
    carry = club["carry"] * lie["dist"] * (1 + wind_along * 0.0042)
    if "maxCarry" in lie:
        carry = min(carry, lie["maxCarry"])
    return carry


def landing_value(state, observation, ahead, across):
    """Score a landing spot, given in yards ahead of / to the right of the ball."""
    layers = state["map"]
    size = layers.shape[1]
    view = observation["view_yards"]
    cell = view / size
    row = size - 1 - int((ahead + BALL_FROM_BOTTOM * view) // cell)
    col = int((across + view / 2) // cell)
    if not (0 <= row < size and 0 <= col < size):
        return OFF_MAP_VALUE
    value = 0.0
    for name, ground_value in LANDING_VALUES.items():
        if layers[MAP_LAYERS.index(name), row, col] > 0:
            value = ground_value
    if layers[MAP_LAYERS.index("mill"), row, col] > 0:
        value += MILL_VALUE
    return value


HOLE_OUT_RANGE = 100  # yards: inside this, go at the pin rather than a green portal
NORMAL_SHOT_GAIN = 250  # yards a good full shot usually gains, for judging forward portals


def club_for_distance(target_distance, clubs, lie, wind_along):
    """Pick a club and meter to finish `target_distance` away, counting on some roll.

    Prefers a pure strike (straightest), then solid, then the shortest club that
    gets there with a part swing. Returns None if nothing reaches."""
    options = []
    for club_index, club in enumerate(clubs):
        full = expected_full_carry(club, lie, wind_along)
        needed_carry = max(2.0, target_distance - club["roll"] * lie["roll"] * 0.5)
        fraction = needed_carry / full
        if fraction <= carry_factor(PURE_HIGH):
            options.append((club_index, meter_for(fraction)))
    if not options:
        return None
    pure = [o for o in options if PURE_LOW <= o[1] <= PURE_HIGH]
    solid = [o for o in options if SOLID_LOW <= o[1] < PURE_LOW]
    if pure:
        return pure[-1]  # the shortest club that can be pured
    if solid:
        return max(solid, key=lambda o: o[1])
    return options[-1]


def smart_player(observation, state, game_info):
    distance = observation["pin_distance"]
    lie = game_info["lies"].get(observation["lie"], game_info["lies"]["fairway"])
    clubs = game_info["clubs"]
    wind_along = observation["wind_along"]

    # Aim into a crosswind by the amount it will push the ball (the game moves
    # the ball sideways by crosswind * carry * 0.0032 yards).
    wind_aim = -math.atan(observation["wind_across"] * 0.0032)

    # Portals first: they cost no stroke. A green portal beats anything except
    # a real hole-out chance; a forward portal is worth it if its exit leaves
    # us much closer than a normal full shot would.
    portal = observation["portal"]
    if portal["has"] and portal["ahead"] > 20:
        if portal["on_green"]:
            worth_it = distance > HOLE_OUT_RANGE
        else:
            worth_it = portal["exit_to_pin"] < distance - NORMAL_SHOT_GAIN
        if worth_it:
            portal_distance = math.hypot(portal["ahead"], portal["across"])
            choice = club_for_distance(portal_distance, clubs, lie, wind_along)
            if choice:
                club_index, meter = choice
                return club_index, math.atan2(portal["across"], portal["ahead"]) + wind_aim, meter

    # The pin is in range: go at it.
    choice = club_for_distance(distance, clubs, lie, wind_along)
    if choice:
        club_index, meter = choice
        return club_index, wind_aim, meter

    # Out of range: hit the longest club with a pure strike and use the map to
    # pick where it lands: away from trouble, and as close to the pin as possible.
    club_index = 0 if observation["lie"] == "tee" else 1  # driver only off the tee
    meter = 0.97
    club = clubs[club_index]
    total = expected_full_carry(club, lie, wind_along) * carry_factor(meter) + club["roll"] * lie["roll"] * 0.5

    best_offset, best_score = 0.0, -math.inf
    for offset in np.linspace(-0.35, 0.35, 29):
        ahead, across = total * math.cos(offset), total * math.sin(offset)
        yards_left = math.hypot(across, distance - ahead)
        score = landing_value(state, observation, ahead, across) - YARDS_LEFT_COST * yards_left
        if score > best_score:
            best_offset, best_score = offset, score
    return club_index, best_offset + wind_aim, meter


PLAYERS = {"simple": simple_player, "smart": smart_player}
