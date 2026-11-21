"""Top-level decision: which mode, which target, where to go. Owner: A (B reviews)."""
import math

import combat
import config
import loot
import mechfight as mf
from nav import Nav
from track import Tracker
from world import World


class Brain:
    def __init__(self, hello):
        cfg = hello["config"]
        self.reach = cfg["loot"]["pickup_radius"]
        self.world = World.load(hello["map"]["dir"])
        self.nav = Nav(self.world)
        self.track = Tracker()

    def decide(self, obs) -> dict:
        me = obs["self"]
        x, y, z = me["pos"]
        self.track.update(obs)
        act = {}

        if obs["offer"]:
            act["pick"] = loot.pick_upgrade(obs["offer"])
        take = loot.take_nearby(obs, self.reach)
        if take is not None:
            act["take"] = take

        goal = obs["zone"]["next_center"]
        mx, my, jump, boost = self.nav.next_step(me["pos"], goal)
        yaw = math.atan2(goal[1] - y, goal[0] - x)
        act.update(
            move=[mx, my], aim=[yaw, 0.0],
            boost=boost or not me["in_zone"],
            jump=jump or obs["tick"] % config.JUMP_EVERY_TICKS == 0,
        )

        enemies = self.track.targets_sorted("mech")
        if enemies:
            act.update(combat.engage(me, enemies[0], self.world))
            t = enemies[0].pos
            mf.draw.line([x, y, z + 7], [t[0], t[1], t[2] + 4.5], "#ff5040")
        mf.draw.label(f"hp {me['hp']:.0f} | {len(enemies)} seen")
        return act
