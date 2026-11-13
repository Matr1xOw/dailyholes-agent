"""
The agent's brain: one neural network with an actor (picks shots) and a
critic (predicts how many more strokes the hole will take from here).

    mini-map (14 x 64 x 64) --> CNN --+
                                       +--> shared layer --> club probabilities (9)
    24 numbers (wind, lie, ...) --> MLP +                 --> aim and meter, given the club
                                                          --> value: expected remaining reward

The club is picked first, and the aim/meter part is told which club was
picked ("autoregressive"), because the right meter depends on the club:
60% on a driver and 60% on a wedge are very different shots.
"""

import torch
import torch.nn as nn
from torch.distributions import Categorical, Normal

from agent.env import FEATURE_NAMES, MAP_LAYERS, MAX_AIM_OFFSET, METER_MAX, NUM_CLUBS

MAP_CHANNELS = len(MAP_LAYERS)
NUM_FEATURES = len(FEATURE_NAMES)


class GolfNet(nn.Module):
    def __init__(self, hidden_size=256):
        super().__init__()

        # The "eyes": three convolution layers, each halving the picture size
        # (64 -> 32 -> 16 -> 8) while building up more abstract patterns.
        self.map_encoder = nn.Sequential(
            nn.Conv2d(MAP_CHANNELS, 32, kernel_size=5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, stride=2, padding=1), nn.ReLU(),
            nn.Flatten(),
            nn.Linear(64 * 8 * 8, hidden_size), nn.ReLU(),
        )
        # The extra numbers get their own small network.
        self.feature_encoder = nn.Sequential(nn.Linear(NUM_FEATURES, 64), nn.ReLU())

        # Both summaries are joined and mixed together.
        self.shared = nn.Sequential(nn.Linear(hidden_size + 64, hidden_size), nn.ReLU())

        # Actor: which club (one score per club, turned into probabilities).
        self.club_head = nn.Linear(hidden_size, NUM_CLUBS)
        # Actor: aim and meter, given the shared summary plus which club was picked.
        self.swing_head = nn.Sequential(
            nn.Linear(hidden_size + NUM_CLUBS, 128), nn.ReLU(),
            nn.Linear(128, 2),
        )
        # How spread out the aim and meter guesses are while exploring. These
        # are learned too, and shrink as the agent gets more sure of itself.
        self.swing_log_spread = nn.Parameter(torch.tensor([-2.0, -2.0]))

        # Critic: one number, the reward it expects from here to the end of the hole.
        self.value_head = nn.Linear(hidden_size, 1)

        # Start the critic guessing about -4 (a typical par-4 score), and the
        # meter centred around 80%, so early training isn't wildly off.
        nn.init.constant_(self.value_head.bias, -4.0)
        nn.init.zeros_(self.swing_head[-1].weight)
        nn.init.constant_(self.swing_head[-1].bias[1], 0.9)

    def summarise(self, maps, features):
        return self.shared(torch.cat([self.map_encoder(maps), self.feature_encoder(features)], dim=1))

    def value(self, maps, features):
        return self.value_head(self.summarise(maps, features)).squeeze(1)

    def swing_distribution(self, summary, club_index):
        club_one_hot = nn.functional.one_hot(club_index, NUM_CLUBS).float()
        raw = self.swing_head(torch.cat([summary, club_one_hot], dim=1))
        # Squash the outputs into the allowed ranges: aim within +-46 degrees,
        # meter between 0 and 1.15.
        aim_centre = torch.tanh(raw[:, 0]) * MAX_AIM_OFFSET
        meter_centre = torch.sigmoid(raw[:, 1]) * METER_MAX
        centres = torch.stack([aim_centre, meter_centre], dim=1)
        spread = self.swing_log_spread.exp().expand_as(centres)
        return Normal(centres, spread)

    def act(self, maps, features, greedy=False):
        """Pick shots for a batch of states.

        greedy=False samples (exploring, for training).
        greedy=True takes the most likely club and the centre of the aim/meter
        guess (for actually playing)."""
        summary = self.summarise(maps, features)
        club_distribution = Categorical(logits=self.club_head(summary))
        club = club_distribution.probs.argmax(dim=1) if greedy else club_distribution.sample()
        swing_distribution = self.swing_distribution(summary, club)
        swing = swing_distribution.mean if greedy else swing_distribution.sample()
        log_prob = club_distribution.log_prob(club) + swing_distribution.log_prob(swing).sum(dim=1)
        value = self.value_head(summary).squeeze(1)
        return club, swing, log_prob, value

    def evaluate_actions(self, maps, features, club, swing):
        """For training: how likely were these past actions under the current
        network, how uncertain is it, and what does the critic say now."""
        summary = self.summarise(maps, features)
        club_distribution = Categorical(logits=self.club_head(summary))
        swing_distribution = self.swing_distribution(summary, club)
        log_prob = club_distribution.log_prob(club) + swing_distribution.log_prob(swing).sum(dim=1)
        entropy = club_distribution.entropy() + swing_distribution.entropy().sum(dim=1)
        value = self.value_head(summary).squeeze(1)
        return log_prob, entropy, value
