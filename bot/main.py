"""Entry point. Wraps Brain with a time guard; the kit wrapper already catches exceptions."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import mechfight as mf  # noqa: E402
from brain import Brain  # noqa: E402


class Bot:
    name = config.NAME

    def __init__(self, hello):
        self.brain = Brain(hello)
        self.last = {}
        self.slow = 0

    def act(self, obs):
        t0 = time.perf_counter()
        action = self.brain.decide(obs)
        ms = (time.perf_counter() - t0) * 1000
        if ms > config.TICK_SOFT_LIMIT_MS:
            self.slow += 1
            if self.slow <= 5 or self.slow % 100 == 0:
                mf.log(f"slow tick {obs['tick']}: {ms:.1f} ms ({self.slow} so far)")
        self.last = {k: action[k] for k in ("move", "aim", "boost") if k in action}
        return action


if __name__ == "__main__":
    mf.run(Bot)
