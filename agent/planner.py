"""
The "super player": the trained agent plus a search for hole-outs.

The agent knows how to play golf in general and gets the ball close, but it
can't see the random number that decides each bounce, so it can't aim for the
cup itself. The simulator can: for any exact shot it says exactly where the
ball ends up. So for each shot we:

  1. ask the agent what it would do,
  2. search the shots around that suggestion (nearby clubs, aims, meters) for
     ones that hole out,
  3. if there are any, play the one with the most room for error, otherwise
     play the agent's shot.

Shots are returned the way the game records them: [club, absolute aim in
radians, meter].
"""

import math

import numpy as np
import torch

from agent.env import GolfEnv
from agent.policy_player import PolicyPlayer

SEARCH_MAX_PIN_DISTANCE = 330  # past this nothing can drop, so don't bother searching
SEARCH_CLUB_RANGE = 2  # try this many clubs either side of the agent's pick
SEARCH_AIM_HALF_WIDTH = math.radians(3.0)
SEARCH_AIM_STEP = math.radians(0.02)
SEARCH_METER_HALF_WIDTH = 0.15
SEARCH_METER_STEP = 0.001
WIDE_SEARCH_MAX_PIN_DISTANCE = 200
WIDE_SEARCH_AIM_HALF_WIDTH = math.radians(21.0)
# The simulator skips the parts of a hole-out search where a coarse pass shows
# the ball never comes within this many yards of the pin. Checked against the
# full search: same hole-outs, a fraction of the time (NOTES.md, 2026-11-17).
SEARCH_PRUNE_YARDS = 6
MIN_INSET_STEPS = 1
# Zooming in on hole-outs narrower than the search grid. The hands land
# within about 0.0003 deg and 0.0003 meter, and only tap inside 0.004 deg /
# 0.0004, so a margin a bit beyond that is safe.
FINE_AIM_HALF_WIDTH = math.radians(0.03)
FINE_AIM_STEP = math.radians(0.001)
FINE_METER_HALF_WIDTH = 0.0015
FINE_METER_STEP = 0.0001
HANDS_SAFE_AIM_DEG = 0.006
HANDS_SAFE_METER = 0.0006
# The lookahead: try a fan of shots in the simulator, roughly rank where they
# leave the ball, then let the agent's own value estimate judge the best few.
LOOKAHEAD_AIM_OFFSETS_DEG = list(range(-30, 31, 2))
LOOKAHEAD_METERS = [0.35, 0.5, 0.65, 0.75, 0.85, 0.92, 0.97, 1.0, 1.05, 1.1]
LOOKAHEAD_SHORTLIST = 60
LOOKAHEAD_MIN_GAIN = 0.3  # strokes a shot must look better than the agent's own to replace it
LIE_COST = {"tee": 0.0, "fairway": 0.0, "green": 0.0, "rough": 0.15, "deep": 0.4, "bunker": 0.4, "leaves": 0.4}
PORTAL_MIN_GAIN = 30  # yards the portal must save to be worth it
PORTAL_MAX_REACH = 320  # further than a driver and roll can go
PORTAL_AIM_HALF_WIDTH = math.radians(5.0)
PORTAL_AIM_STEP = math.radians(0.1)
PORTAL_METER_STEP = 0.005  # a hole-out needs at least this much room for error to be worth trying


class Planner:
    def __init__(self, checkpoint_path, simulator=None):
        self.policy = PolicyPlayer(checkpoint_path)
        self.env = GolfEnv(simulator)
        self.simulator = self.env.simulator
        self.course_info_cache = {}

    def allowed_clubs(self, course_key, lie):
        """Club indexes the game lets you pick from this lie."""
        info = self.course_info(course_key)
        cap = info["lies"].get(lie, {}).get("maxCarry")
        return [index for index, club in enumerate(info["clubs"]) if cap is None or club["carry"] <= cap]

    def course_info(self, course_key):
        if course_key not in self.course_info_cache:
            self.course_info_cache[course_key] = self.simulator.course_info(course_key)
        return self.course_info_cache[course_key]

    def next_shot(self, course_key, hole_index, shots):
        """Returns (shot, details) for the next shot on this hole."""
        observation = self.simulator.observe(course_key, hole_index, shots)
        if observation["done"]:
            raise ValueError("this hole is already finished")
        state = self.env._make_state(observation)
        club, aim_offset, meter = self.policy(observation, state, self.course_info(course_key))
        aim = observation["pin_bearing"] + aim_offset
        # The game greys out clubs that carry further than the lie allows (a
        # bunker or a pile of leaves caps it at 160 yd). The simulator doesn't
        # stop you, so the planner has to: only ever consider playable clubs.
        allowed = self.allowed_clubs(course_key, observation["lie"])
        self.allowed = allowed
        if club not in allowed:
            club = min(allowed)  # the longest club that's allowed
        agent_shot = [club, aim, meter]
        details = {"source": "agent", "pin_distance": observation["pin_distance"], "lie": observation["lie"]}

        if observation["pin_distance"] > SEARCH_MAX_PIN_DISTANCE:
            portal_shot = self.forward_portal_shot(course_key, hole_index, shots, observation)
            if portal_shot is not None:
                details.update(portal_shot[1])
                return portal_shot[0], details
            return self.lookahead(course_key, hole_index, shots, observation, agent_shot, details)

        clubs = [c for c in range(club - SEARCH_CLUB_RANGE, club + SEARCH_CLUB_RANGE + 1) if c in allowed]
        found = self.simulator.request({
            "cmd": "search", "key": course_key, "hole": hole_index, "shots": shots, "clubs": clubs,
            "aim": aim, "aim_half_width": SEARCH_AIM_HALF_WIDTH, "aim_step": SEARCH_AIM_STEP,
            "meter": meter, "meter_half_width": SEARCH_METER_HALF_WIDTH, "meter_step": SEARCH_METER_STEP,
            "prune": SEARCH_PRUNE_YARDS,
        })
        if not (found["found"] and found["inset_steps"] >= MIN_INSET_STEPS) and observation["pin_distance"] <= WIDE_SEARCH_MAX_PIN_DISTANCE:
            # Nothing near the agent's idea. On shorter shots, try a much wider
            # fan of aims around the pin and the whole meter, since a bounce off
            # a slope can make a shot well off line the one that drops.
            wide = self.simulator.request({
                "cmd": "search", "key": course_key, "hole": hole_index, "shots": shots, "clubs": clubs,
                "aim": observation["pin_bearing"], "aim_half_width": WIDE_SEARCH_AIM_HALF_WIDTH,
                "aim_step": SEARCH_AIM_STEP, "meter": 0.6, "meter_half_width": 0.55, "meter_step": 0.002,
                "prune": SEARCH_PRUNE_YARDS,
            })
            if wide["found"] and (not found["found"] or wide["inset_steps"] > found["inset_steps"]):
                found = wide
        if found["found"] and found["inset_steps"] >= MIN_INSET_STEPS:
            # The grid only samples every 0.02 deg / 0.001 meter, and a thin
            # strip of misses can hide between its points (a lip-out band
            # 0.0002 wide cost a hole-out once). So check the pick on the fine
            # grid and take the spot there with the most real room.
            pick = [found["club"], found["aim"], found["meter"]]
            checked = self.refine(course_key, hole_index, shots, [pick] + found["samples"])
            if checked is not None:
                details.update({"source": "hole-out search", "hits": found["hits"],
                                "aim_margin_deg": checked["aim_margin_deg"], "meter_margin": checked["meter_margin"]})
                return [checked["club"], checked["aim"], checked["meter"]], details
            details.update({
                "source": "hole-out search (unchecked)",
                "hits": found["hits"],
                "aim_margin_deg": min(found["aim_margin_deg"], HANDS_SAFE_AIM_DEG),
                "meter_margin": min(found["meter_margin"], HANDS_SAFE_METER),
            })
            return pick, details
        if found["found"]:
            refined = self.refine(course_key, hole_index, shots, found["samples"])
            if refined is not None:
                details.update({"source": "hole-out search (fine)", "hits": found["hits"],
                                "aim_margin_deg": refined["aim_margin_deg"], "meter_margin": refined["meter_margin"]})
                return [refined["club"], refined["aim"], refined["meter"]], details
            details["note"] = f"{found['hits']} hole-outs found but all too tight to trust"
        portal_shot = self.forward_portal_shot(course_key, hole_index, shots, observation)
        if portal_shot is not None:
            shot, portal_details = portal_shot
            details.update(portal_details)
            return shot, details
        return self.lookahead(course_key, hole_index, shots, observation, agent_shot, details)

    def lookahead(self, course_key, hole_index, shots, observation, agent_shot, details):
        """
        Check the agent's shot against a fan of others before playing it. The
        agent can be badly wrong on holes unlike anything it trained on (say,
        one that's mostly water), and it can't see that a shot is doomed. The
        simulator can. Each candidate is scored as strokes it costs plus the
        agent's own estimate of strokes still to come from where it lands
        (the value head). The agent's shot is kept unless something is clearly
        better.
        """
        strokes_before = observation["strokes"]
        bearing = observation["pin_bearing"]
        candidates = [agent_shot] + [
            [club, bearing + math.radians(offset), meter]
            for club in self.allowed for offset in LOOKAHEAD_AIM_OFFSETS_DEG for meter in LOOKAHEAD_METERS
        ]
        outcomes = self.simulator.request({"cmd": "outcomes", "key": course_key, "hole": hole_index,
                                           "shots": shots, "candidates": candidates})

        def rough_cost(outcome):
            if outcome is None:
                return math.inf
            if outcome["done"]:
                return outcome["score"] - strokes_before
            return (outcome["strokes"] - strokes_before) + 1.0 + outcome["pin_distance"] / 250 + LIE_COST.get(outcome["lie"], 0.3)

        order = sorted(range(1, len(candidates)), key=lambda k: rough_cost(outcomes[k]))
        shortlist = [0] + order[:LOOKAHEAD_SHORTLIST]
        costs = {}
        maps, features, waiting = [], [], []
        for k in shortlist:
            outcome = outcomes[k]
            if outcome is None:
                costs[k] = math.inf
            elif outcome["done"]:
                costs[k] = outcome["score"] - strokes_before
            else:
                after = self.simulator.observe(course_key, hole_index, shots + [candidates[k]])
                state = self.env._make_state(after)
                maps.append(state["map"])
                features.append(state["features"])
                waiting.append((k, after["strokes"] - strokes_before))
        if waiting:
            with torch.no_grad():
                values = self.policy.network.value(torch.from_numpy(np.stack(maps)), torch.from_numpy(np.stack(features)))
            for (k, strokes_used), value in zip(waiting, values.tolist()):
                costs[k] = strokes_used - value  # value is about minus the strokes still to come

        best = min(shortlist, key=lambda k: costs[k])
        details["agent_expected_strokes"] = round(costs[0], 2)
        if best != 0 and costs[best] < costs[0] - LOOKAHEAD_MIN_GAIN:
            details.update({"source": "lookahead", "expected_strokes": round(costs[best], 2)})
            return candidates[best], details
        return agent_shot, details

    def refine(self, course_key, hole_index, shots, samples):
        """
        Some hole-outs are narrower than the search grid (0.02 deg, 0.001 meter),
        so they look like single lucky points. The hands are far more precise
        than that grid, though, so zoom in on each one with a 20x finer grid and
        keep the first whose real margin comfortably beats the hands' error.
        """
        best = None
        for club, aim, meter in samples:
            fine = self.simulator.request({
                "cmd": "search", "key": course_key, "hole": hole_index, "shots": shots, "clubs": [club],
                "aim": aim, "aim_half_width": FINE_AIM_HALF_WIDTH, "aim_step": FINE_AIM_STEP,
                "meter": meter, "meter_half_width": FINE_METER_HALF_WIDTH, "meter_step": FINE_METER_STEP,
            })
            if not fine["found"]:
                continue
            if best is None or fine["inset_steps"] > best["inset_steps"]:
                best = fine
        if best and best["aim_margin_deg"] >= HANDS_SAFE_AIM_DEG and best["meter_margin"] >= HANDS_SAFE_METER:
            return best
        return None

    def forward_portal_shot(self, course_key, hole_index, shots, observation):
        """
        A forward portal is always worth taking: it's free and skips hundreds
        of yards, and the exit is a fixed spot, so the hole-out search runs
        from there on the next shot. (Green portals are different: they end
        the hole in one or two putts, so a hole-out beats them and the agent
        is left to weigh them up.)
        """
        portal = observation["portal"]
        if not portal["has"] or portal["on_green"]:
            return None
        if portal["exit_to_pin"] >= observation["pin_distance"] - PORTAL_MIN_GAIN:
            return None  # already past it, or it wouldn't move us forward
        portal_distance = math.hypot(portal["ahead"], portal["across"])
        if portal_distance > PORTAL_MAX_REACH:
            return None
        bearing = observation["pin_bearing"] + math.atan2(portal["across"], portal["ahead"])
        found = self.simulator.request({
            "cmd": "search", "goal": "portal", "key": course_key, "hole": hole_index, "shots": shots,
            "clubs": self.allowed, "aim": bearing, "aim_half_width": PORTAL_AIM_HALF_WIDTH,
            "aim_step": PORTAL_AIM_STEP, "meter": 0.675, "meter_half_width": 0.475, "meter_step": PORTAL_METER_STEP,
        })
        if not found["found"]:
            return None
        return [found["club"], found["aim"], found["meter"]], {
            "source": "forward portal",
            "aim_margin_deg": found["aim_margin_deg"],
            "meter_margin": found["meter_margin"],
        }

    def close(self):
        self.env.close()
