"""
Runs several golf environments at once, each in its own process with its own
simulator, so the agent gathers experience several times faster.

When a hole finishes, that environment immediately starts a new random hole,
so every environment always has a live state to act on.
"""

import multiprocessing as mp

import numpy as np

from agent.env import GolfEnv


def _worker(connection, seed, course_prefix, portal_share):
    env = GolfEnv(course_prefix=course_prefix, seed=seed, portal_share=portal_share)

    def pack(state):
        # The map is all 0s and 1s, so send it as bytes instead of floats (4x smaller).
        return state["map"].astype(np.uint8), state["features"]

    try:
        while True:
            command, data = connection.recv()
            if command == "reset":
                connection.send(pack(env.reset()))
            elif command == "step":
                club, aim, meter = data
                state, reward, done, info = env.step(club, aim, meter)
                if done:
                    state = env.reset()
                connection.send((pack(state), reward, done, info))
            elif command == "close":
                break
    finally:
        env.close()
        connection.close()


class ParallelEnvs:
    def __init__(self, count, seed=0, course_prefix="train", portal_share=0.0):
        context = mp.get_context("spawn")
        self.connections = []
        self.processes = []
        for index in range(count):
            parent_end, child_end = context.Pipe()
            process = context.Process(target=_worker, args=(child_end, seed + index, course_prefix, portal_share), daemon=True)
            process.start()
            self.connections.append(parent_end)
            self.processes.append(process)
        self.count = count

    def reset(self):
        for connection in self.connections:
            connection.send(("reset", None))
        return self._stack([connection.recv() for connection in self.connections])

    def step(self, clubs, aims, meters):
        for connection, club, aim, meter in zip(self.connections, clubs, aims, meters):
            connection.send(("step", (int(club), float(aim), float(meter))))
        results = [connection.recv() for connection in self.connections]
        states = self._stack([result[0] for result in results])
        rewards = np.array([result[1] for result in results], dtype=np.float32)
        dones = np.array([result[2] for result in results], dtype=np.float32)
        infos = [result[3] for result in results]
        return states, rewards, dones, infos

    @staticmethod
    def _stack(packed_states):
        maps = np.stack([state[0] for state in packed_states]).astype(np.float32)
        features = np.stack([state[1] for state in packed_states])
        return maps, features

    def close(self):
        for connection in self.connections:
            connection.send(("close", None))
        for process in self.processes:
            process.join(timeout=5)
