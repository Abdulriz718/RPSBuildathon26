"""Top-level decision: which mode, which target, where to go. Owner: A (B reviews)."""
import math

import combat
import config
import loot
import mechfight as mf
from nav import Nav
from track import Tracker
from world import World


def zone_now(z, t):
    """Current circle (cx, cy, r), interpolating during the shrink window."""
    if t <= z["shrink_start"] or z["shrink_end"] <= z["shrink_start"]:
        return z["center"][0], z["center"][1], z["radius"]
    f = min(1.0, (t - z["shrink_start"]) / (z["shrink_end"] - z["shrink_start"]))
    cx = z["center"][0] + (z["next_center"][0] - z["center"][0]) * f
    cy = z["center"][1] + (z["next_center"][1] - z["center"][1]) * f
    return cx, cy, z["radius"] + (z["next_radius"] - z["radius"]) * f


class Brain:
    def __init__(self, hello):
        cfg = hello["config"]
        self.reach = cfg["loot"]["pickup_radius"]
        self.world = World.load(hello["map"]["dir"])
        self.nav = Nav(self.world, cfg.get("mech", {}))
        self.track = Tracker()
        self.hurt_bearing = None
        self.hurt_t = -1e9
        self.scan_yaw = None

    # ---- zone ------------------------------------------------------------
    def zone_goal(self, obs):
        """Where to stand: the near side of the next circle, ZONE_MARGIN of its radius from center.
        Returns (goal_xy, must_hurry)."""
        me = obs["self"]
        x, y = me["pos"][0], me["pos"][1]
        z, t = obs["zone"], obs["t"]
        nx_, ny_, nr = z["next_center"][0], z["next_center"][1], z["next_radius"]
        dx, dy = x - nx_, y - ny_
        d = math.hypot(dx, dy)
        keep = nr * config.ZONE_MARGIN
        if d <= keep:
            goal = (x, y)
        else:
            goal = (nx_ + dx / d * keep, ny_ + dy / d * keep)
        need = max(0.0, d - keep) / max(1.0, me["stats"].get("walk_speed", 11.7))
        time_left = z["shrink_end"] - t
        hurry = not me["in_zone"] or need > time_left - config.ZONE_SAFETY_S
        return goal, hurry

    # ---- main ------------------------------------------------------------
    def decide(self, obs) -> dict:
        me = obs["self"]
        x, y, z = me["pos"]
        t = obs["t"]
        self.track.update(obs)
        act = {}

        for e in obs["events"]:
            if e["type"] == "damaged" and e.get("bearing") is not None:
                self.hurt_bearing, self.hurt_t = e["bearing"], t

        if obs["offer"]:
            act["pick"] = loot.pick_upgrade(obs["offer"])
        take = loot.take_nearby(obs, self.reach)
        if take is not None:
            act["take"] = take

        goal, hurry = self.zone_goal(obs)
        far = math.hypot(goal[0] - x, goal[1] - y) > 2.0
        mx, my, jump, boost = self.nav.next_step(me["pos"], goal, t, 1.0 if far else 0.0)
        if not far:
            mx = my = 0.0
        act.update(move=[mx, my], boost=boost or (hurry and far), jump=jump)
        act["aim"] = [self.idle_yaw(t, mx, my, me), 0.0]

        enemies = self.track.targets_sorted("mech")
        if enemies:
            act.update(combat.engage(me, enemies[0], self.world))
            tp = enemies[0].pos
            mf.draw.line([x, y, z + 7], [tp[0], tp[1], tp[2] + 4.5], "#ff5040")
        for wx, wy in self.nav.path[:20]:
            mf.draw.point([wx, wy, self.world.surface(wx, wy) + 1], "#40c0ff", 2)
        mf.draw.label(f"hp {me['hp']:.0f} | {len(enemies)} seen{' | HURRY' if hurry else ''}")
        return act

    def idle_yaw(self, t, mx, my, me):
        """Aim when nobody is in sight: toward whoever hit us last, else where we walk, else sweep."""
        if t - self.hurt_t < config.HURT_LOOK_S:
            return self.hurt_bearing
        if mx or my:
            self.scan_yaw = None
            return math.atan2(my, mx)
        if self.scan_yaw is None:
            self.scan_yaw = me["aim"][0]
        self.scan_yaw += config.SCAN_RAD_PER_TICK
        return (self.scan_yaw + math.pi) % (2 * math.pi) - math.pi
