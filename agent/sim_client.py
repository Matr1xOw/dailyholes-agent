"""
Talks to the Node simulator (sim/server.js) from Python.

The simulator runs as a separate process that stays alive the whole time.
We send it one JSON request per line on its stdin and read one JSON response
per line from its stdout.
"""

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = PROJECT_ROOT / "sim" / "server.js"


class SimulatorError(RuntimeError):
    pass


class SimClient:
    def __init__(self):
        self.process = subprocess.Popen(
            ["node", str(SERVER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # let simulator errors show up in our terminal
            text=True,
            bufsize=1,  # line buffered
        )
        self.request({"cmd": "ping"})

    def request(self, message):
        """Send one request and wait for its answer."""
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise SimulatorError("the simulator process stopped unexpectedly")
        response = json.loads(line)
        if not response["ok"]:
            raise SimulatorError(response["error"])
        return response["result"]

    def request_batch(self, messages):
        """Send several requests in one go. Returns one answer per request, in order."""
        answers = self.request({"cmd": "batch", "requests": messages})
        for answer in answers:
            if not answer["ok"]:
                raise SimulatorError(answer["error"])
        return [answer["result"] for answer in answers]

    def observe(self, course_key, hole_index, shots):
        return self.request({"cmd": "observe", "key": course_key, "hole": hole_index, "shots": shots})

    def course_info(self, course_key):
        return self.request({"cmd": "course", "key": course_key})

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
