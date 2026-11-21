"""Mechfight entry point and the guard around each bot decision."""

import math
from pathlib import Path
import sys
from time import perf_counter

if __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# A clean checkout can run before the teammate-owned kit copy is in bot/.
if not Path(__file__).with_name("mechfight.py").exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mechfight-kit"
                           / "mechfight-kit" / "python"))

import mechfight as mf

from config import DECISION_BUDGET_MS


class Starter:
    """The kit's starter decisions for the initial submission."""

    def __init__(self, hello):
        self.reach = hello["config"]["loot"]["pickup_radius"]

    def decide(self, obs):
        me = obs["self"]
        x, y, z = me["pos"]
        goal = obs["zone"]["next_center"]
        yaw = math.atan2(goal[1] - y, goal[0] - x)
        action = {
            "move": [math.cos(yaw), math.sin(yaw)],
            "aim": [yaw, 0.0],
            "boost": not me["in_zone"],
            "jump": obs["tick"] % 40 == 0,
        }
        if obs["offer"]:
            action["pick"] = 0
        pickup = next((p for p in obs["pickups"]
                       if math.dist(p["pos"][:2], (x, y)) < self.reach), None)
        if me["weapons"][1] is None and pickup and pickup["kind"] != "gun":
            action["take"] = pickup["id"]

        enemies = [m for m in obs["mechs"] if m["kind"] == "mech"]
        if enemies:
            tx, ty, tz = min(enemies, key=lambda m: math.dist(m["pos"], me["pos"]))["pos"]
            action["aim"] = [
                math.atan2(ty - y, tx - x),
                math.atan2(tz - z - 2.5, math.hypot(tx - x, ty - y)),
            ]
            action["fire"] = [True, True]
            mf.draw.line([x, y, z + 7], [tx, ty, tz + 4.5], "#ff5040")
        mf.draw.point([*goal, z], "#40c0ff", 6)
        mf.draw.label(f"hp {me['hp']:.0f} · {len(enemies)} in sight")
        return action


class Bot:
    name = "example-py"

    def __init__(self, hello, decide=None):
        self.decide = decide if decide is not None else Starter(hello).decide
        self.budget_s = min(DECISION_BUDGET_MS, hello["config"]["bot"]["tick_budget_ms"]) / 1000
        self.last_safe = {}
        self.errors = 0
        self.over_budget = 0

    def act(self, obs):
        started = perf_counter()
        try:
            action = dict(self.decide(obs))
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

        # Drop one-shot commands, fire, and drawings when reusing the previous intent.
        mf.draw.clear()
        return {"tick": obs["tick"], **self.last_safe}


if __name__ == "__main__":
    mf.run(Bot)
