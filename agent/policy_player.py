"""
Wraps a trained network as a player the scoreboard can use, same as the
hand-written baselines. It plays "greedy": the most likely club and the centre
of its aim/meter guess, with no exploring.
"""

import torch

from agent.network import GolfNet


class PolicyPlayer:
    def __init__(self, checkpoint_path):
        torch.set_num_threads(1)  # the scoreboard runs several of these side by side
        self.network = GolfNet()
        self.network.load_state_dict(torch.load(checkpoint_path, map_location="cpu"))
        self.network.eval()

    def __call__(self, observation, state, game_info):
        maps = torch.from_numpy(state["map"]).unsqueeze(0)
        features = torch.from_numpy(state["features"]).unsqueeze(0)
        with torch.no_grad():
            club, swing, _, _ = self.network.act(maps, features, greedy=True)
        return int(club[0]), float(swing[0, 0]), float(swing[0, 1])
