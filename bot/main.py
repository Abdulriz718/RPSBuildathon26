"""Mechfight entry point and the guard around each bot decision."""

from pathlib import Path
import sys
from time import perf_counter

if __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import mechfight as mf
from brain import Brain


class Bot:
    name = config.NAME

    def __init__(self, hello):
        self.brain = Brain(hello)
        tick_budget_ms = hello["config"]["bot"]["tick_budget_ms"]
        self.budget_s = min(config.TICK_SOFT_LIMIT_MS, tick_budget_ms) / 1000
        self.last_safe = {}
        self.errors = 0
        self.over_budget = 0

    def act(self, obs):
        started = perf_counter()
        try:
            action = dict(self.brain.decide(obs))
            action["tick"] = obs["tick"]
            continuous = {key: tuple(action[key]) for key in ("move", "aim") if key in action}
            if "boost" in action:
                continuous["boost"] = action["boost"]
        except Exception as error:
            self.errors += 1
            if self.errors <= 3:
                mf.log(f"Decision failed at tick {obs['tick']}: {error!r}")
        else:
            if perf_counter() - started < self.budget_s:
                self.last_safe = continuous
                return action
            self.over_budget += 1

        mf.draw.clear()
        return {"tick": obs["tick"], **self.last_safe}


if __name__ == "__main__":
    mf.run(Bot)
