"""
Trains the agent with PPO (Proximal Policy Optimization).

The loop, over and over:
  1. Play: the current network plays a batch of shots across several
     environments at once, sampling (exploring) rather than playing its best.
  2. Score: work out each shot's "advantage", meaning how much better or worse
     things went than the critic expected.
  3. Learn: nudge the network so better-than-expected shots become more
     likely and worse ones less likely, but only by a limited amount per round
     (the "proximal" part), so one lucky batch can't wreck what it knows.

Usage:
    .venv/bin/python scripts/train.py --steps 300000 --name first-run
"""

import argparse
import csv
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch

from agent.network import GolfNet
from agent.parallel_envs import ParallelEnvs

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="run")
    parser.add_argument("--steps", type=int, default=300_000, help="total shots to play while training")
    parser.add_argument("--envs", type=int, default=8, help="environments running at once")
    parser.add_argument("--rollout", type=int, default=128, help="shots per environment before each learning round")
    parser.add_argument("--epochs", type=int, default=4, help="passes over each batch of experience")
    parser.add_argument("--minibatch", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--gamma", type=float, default=1.0, help="discount; 1.0 because only the total score matters")
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip", type=float, default=0.2, help="how far one learning round may move the policy")
    parser.add_argument("--entropy-weight", type=float, default=0.005, help="bonus for staying exploratory")
    parser.add_argument("--value-weight", type=float, default=0.5)
    parser.add_argument("--max-grad-norm", type=float, default=0.5)
    parser.add_argument("--portal-share", type=float, default=0.35,
                        help="fraction of training holes deliberately picked to have a portal")
    parser.add_argument("--snapshot-every", type=int, default=500_000, help="keep a copy of the brain every N shots")
    parser.add_argument("--resume", default=None, help="checkpoint to continue from")
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args()


def compute_advantages(rewards, dones, values, next_value, gamma, gae_lambda):
    """Generalised Advantage Estimation (GAE).

    Walks backwards through the batch. At each shot, the "surprise" is:
        reward received + critic's guess for the next state - critic's guess for this state
    The advantage blends this shot's surprise with the surprises that followed
    it (fading by gae_lambda each step), which gives a steadier signal than
    looking at one shot alone. A finished hole cuts the chain, so one hole's
    luck doesn't leak into the next."""
    steps = rewards.shape[0]
    advantages = torch.zeros_like(rewards)
    running = torch.zeros_like(next_value)
    for t in reversed(range(steps)):
        not_done = 1.0 - dones[t]
        following_value = next_value if t == steps - 1 else values[t + 1]
        surprise = rewards[t] + gamma * following_value * not_done - values[t]
        running = surprise + gamma * gae_lambda * not_done * running
        advantages[t] = running
    returns = advantages + values  # what the critic should have predicted
    return advantages, returns


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    run_folder = PROJECT_ROOT / "runs" / args.name
    checkpoint_folder = PROJECT_ROOT / "checkpoints" / args.name
    run_folder.mkdir(parents=True, exist_ok=True)
    checkpoint_folder.mkdir(parents=True, exist_ok=True)

    # Learning runs on the M4's GPU ("mps") when available: about 7x faster than
    # the CPU, and it leaves the CPU free for the simulators.
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"learning on: {device}", flush=True)

    network = GolfNet().to(device)
    if args.resume:
        network.load_state_dict(torch.load(args.resume, map_location=device))
    optimizer = torch.optim.Adam(network.parameters(), lr=args.learning_rate, eps=1e-5)

    envs = ParallelEnvs(args.envs, seed=args.seed * 1000, portal_share=args.portal_share)
    maps, features = envs.reset()
    maps, features = torch.from_numpy(maps), torch.from_numpy(features)

    # Storage for one batch of experience: [shot number, environment].
    T, N = args.rollout, args.envs
    buffer_maps = torch.zeros((T, N) + tuple(maps.shape[1:]))
    buffer_features = torch.zeros((T, N, features.shape[1]))
    buffer_clubs = torch.zeros((T, N), dtype=torch.long)
    buffer_swings = torch.zeros((T, N, 2))
    buffer_log_probs = torch.zeros((T, N))
    buffer_rewards = torch.zeros((T, N))
    buffer_dones = torch.zeros((T, N))
    buffer_values = torch.zeros((T, N))

    # Recent finished holes, for progress reports. Scores here are the true
    # scores (no bonus), from exploratory play, so they run a bit worse than
    # the agent's real best.
    recent_to_par = deque(maxlen=500)
    recent_holed = deque(maxlen=500)

    log_file = open(run_folder / "log.csv", "w", newline="")
    log = csv.writer(log_file)
    log.writerow(["steps", "holes", "avg_to_par", "hole_out_rate", "policy_loss", "value_loss",
                  "entropy", "aim_spread_deg", "meter_spread", "steps_per_sec"])

    batch_size = T * N
    updates = args.steps // batch_size
    total_steps, total_holes = 0, 0
    start = time.time()

    next_snapshot = args.snapshot_every

    for update in range(1, updates + 1):
        # Learning rate shrinks steadily to zero over the run: big steps early
        # while everything is wrong, small careful ones at the end.
        for group in optimizer.param_groups:
            group["lr"] = args.learning_rate * (1.0 - (update - 1) / updates)

        # ---- 1. Play ------------------------------------------------------
        network.eval()
        for t in range(T):
            with torch.no_grad():
                club, swing, log_prob, value = network.act(maps.to(device), features.to(device))
                club, swing, log_prob, value = club.cpu(), swing.cpu(), log_prob.cpu(), value.cpu()
            buffer_maps[t], buffer_features[t] = maps, features
            buffer_clubs[t], buffer_swings[t] = club, swing
            buffer_log_probs[t], buffer_values[t] = log_prob, value

            (next_maps, next_features), rewards, dones, infos = envs.step(
                club.numpy(), swing[:, 0].numpy(), swing[:, 1].numpy()
            )
            buffer_rewards[t] = torch.from_numpy(rewards)
            buffer_dones[t] = torch.from_numpy(dones)
            for done, info in zip(dones, infos):
                if done:
                    recent_to_par.append(info["score"] - info["par"])
                    recent_holed.append(info["holed"])
                    total_holes += 1
            maps, features = torch.from_numpy(next_maps), torch.from_numpy(next_features)
        total_steps += batch_size

        # ---- 2. Score -----------------------------------------------------
        with torch.no_grad():
            next_value = network.value(maps.to(device), features.to(device)).cpu()
        advantages, returns = compute_advantages(
            buffer_rewards, buffer_dones, buffer_values, next_value, args.gamma, args.gae_lambda
        )

        # ---- 3. Learn -----------------------------------------------------
        network.train()
        flat = lambda x: x.reshape((batch_size,) + tuple(x.shape[2:]))
        b_maps, b_features = flat(buffer_maps), flat(buffer_features)
        b_clubs, b_swings, b_old_log_probs = flat(buffer_clubs), flat(buffer_swings), flat(buffer_log_probs)
        b_advantages, b_returns = flat(advantages), flat(returns)

        for epoch in range(args.epochs):
            order = torch.randperm(batch_size)
            for start_index in range(0, batch_size, args.minibatch):
                idx = order[start_index : start_index + args.minibatch]
                new_log_prob, entropy, new_value = network.evaluate_actions(
                    b_maps[idx].to(device), b_features[idx].to(device),
                    b_clubs[idx].to(device), b_swings[idx].to(device),
                )
                # Normalise advantages within the minibatch: what matters is
                # better vs worse than average, not the raw size.
                adv = b_advantages[idx].to(device)
                adv = (adv - adv.mean()) / (adv.std() + 1e-8)

                # How much more (or less) likely is this action now than when it was taken?
                ratio = (new_log_prob - b_old_log_probs[idx].to(device)).exp()
                # PPO's clipped objective: take the more pessimistic of the
                # normal and the clipped version, so there's no gain from moving
                # the policy further than `clip` in one round.
                unclipped = ratio * adv
                clipped = ratio.clamp(1 - args.clip, 1 + args.clip) * adv
                policy_loss = -torch.min(unclipped, clipped).mean()

                value_loss = 0.5 * (new_value - b_returns[idx].to(device)).pow(2).mean()
                entropy_bonus = entropy.mean()

                loss = policy_loss + args.value_weight * value_loss - args.entropy_weight * entropy_bonus
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), args.max_grad_norm)
                optimizer.step()

        # ---- Report -------------------------------------------------------
        spreads = network.swing_log_spread.exp().detach().cpu()
        steps_per_sec = total_steps / (time.time() - start)
        avg_to_par = float(np.mean(recent_to_par)) if recent_to_par else float("nan")
        hole_out_rate = float(np.mean(recent_holed)) if recent_holed else float("nan")
        log.writerow([total_steps, total_holes, f"{avg_to_par:.4f}", f"{hole_out_rate:.4f}",
                      f"{policy_loss.item():.4f}", f"{value_loss.item():.4f}", f"{entropy_bonus.item():.4f}",
                      f"{np.degrees(spreads[0].item()):.2f}", f"{spreads[1].item():.4f}", f"{steps_per_sec:.0f}"])
        log_file.flush()
        if update % 5 == 0 or update == 1:
            print(f"update {update}/{updates}  steps {total_steps}  holes {total_holes}  "
                  f"vs par {avg_to_par:+.3f}/hole ({9 * avg_to_par:+.1f}/round)  hole-outs {hole_out_rate:.1%}  "
                  f"aim spread {np.degrees(spreads[0].item()):.1f} deg  meter spread {spreads[1].item():.3f}  "
                  f"{steps_per_sec:.0f} steps/s", flush=True)
        if update % 25 == 0 or update == updates:
            torch.save(network.state_dict(), checkpoint_folder / "latest.pt")
        if total_steps >= next_snapshot:
            torch.save(network.state_dict(), checkpoint_folder / f"steps_{total_steps // 1000}k.pt")
            next_snapshot += args.snapshot_every

    envs.close()
    log_file.close()
    print(f"done. checkpoint: {checkpoint_folder / 'latest.pt'}")


if __name__ == "__main__":
    main()
