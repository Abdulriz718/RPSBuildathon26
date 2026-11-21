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
        self.track = Tracker(cfg)
        self.weapons = combat.Weapons(cfg)
        self.crates = cfg["crates"]
        self.regen_delay = cfg["mech"]["regen_delay"]
        self.scan_yaw = None
        self.cover = None
        self.cover_checked = -math.inf
        self.cover_target = None
        self.last_exchange = -math.inf
        self.recovering = False

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
        self.weapons.update(obs)
        if any(event["type"] in ("hit", "damaged") for event in obs["events"]):
            self.last_exchange = t
        ratio = me["hp"] / me["max_hp"]
        delay = me["stats"].get("regen_delay", self.regen_delay)
        if ratio <= config.COVER_LOW_HP:
            self.recovering = True
        elif ratio >= config.COVER_RECOVER_HP and t - self.last_exchange >= delay:
            self.recovering = False
        act = {}

        if obs["offer"]:
            act["pick"] = loot.pick_upgrade(obs["offer"], me)
        take = loot.take_nearby(obs, self.reach)
        if take is not None:
            act["take"] = take

        goal, hurry = self.zone_goal(obs)
        enemies = self.track.targets_sorted("mech", max_age=config.TRACK_AIM_MEMORY_S)
        target = enemies[0] if enemies else None
        fight = self.weapons.decide(me, target, self.world)
        hiding = using_cover = False

        if not hurry and target is not None:
            cover_goal, hiding = self.cover_goal(obs, target)
            if cover_goal is not None:
                goal = cover_goal
                using_cover = True
        elif (not hurry and self.recovering and self.cover is not None
              and loot.in_next_zone(obs["zone"], self.cover[0])):
            goal = self.cover[0]
            hiding = using_cover = True
        elif not hurry and not self.recovering and self.track.threat_bearing() is None:
            opportunity = loot.want(obs, self.world)
            if opportunity is not None:
                kind, item = opportunity
                goal = item["pos"][:2]
                if kind == "crate":
                    crate = loot.crate_target(item, self.crates)
                    muzzle = (x, y, z + me["stats"]["muzzle_height"])
                    center = (*crate.pos[:2], crate.pos[2] + crate.height / 2)
                    if self.world.los(muzzle, center):
                        goal = (x, y)
                        fight = self.weapons.decide(me, crate, self.world)
        if hiding:
            fight["fire"] = [False, False]
            for weapon in me["weapons"]:
                if weapon and weapon["kind"] == "gun" and weapon["ammo"] < weapon["stats"]["mag"]:
                    fight["reload"] = weapon["reload"] <= 0

        reach = config.COVER_REACHED_M if using_cover else 2.0
        far = math.hypot(goal[0] - x, goal[1] - y) > reach
        mx, my, jump, boost = self.nav.next_step(me["pos"], goal, t, float(far), precise=using_cover)
        if not far:
            mx = my = 0.0
        if not hurry and not hiding:
            dodge = self.weapons.dodge(obs, target, self.world)
            if dodge is not None:
                dx, dy, urgent = dodge
                if urgent or not using_cover:
                    step = self.strafe(obs, dx, dy)
                    if step is not None:
                        scale = 1.0 if urgent else config.STRAFE_SPEED_FRACTION
                        mx, my = step[0] * scale, step[1] * scale
        act.update(move=[mx, my], boost=boost or (hurry and far), jump=jump)
        act["aim"] = [self.idle_yaw(mx, my, me), 0.0]
        act.update(fight)
        if target is not None:
            tx, ty, tz = target.predict(0)
            mf.draw.line([x, y, z + me["stats"]["muzzle_height"]],
                         [tx, ty, tz + target.height / 2], "#ff5040")
        for wx, wy in self.nav.path[:20]:
            mf.draw.point([wx, wy, self.world.surface(wx, wy) + 1], "#40c0ff", 2)
        mf.draw.label(f"hp {me['hp']:.0f} | {len(enemies)} seen{' | HURRY' if hurry else ''}")
        return act

    def cover_goal(self, obs, target):
        me = obs["self"]
        t = obs["t"]
        tx, ty, tz = target.predict(0)
        threat = (tx, ty, tz + target.height / 2)
        if self.cover_target is None or self.cover_target[0] != target.id:
            self.cover = None
            self.cover_checked = -math.inf
        needs_cover = self.cover is None
        if self.cover is not None:
            hide, peek = self.cover
            needs_cover = (math.dist(threat, self.cover_target[1]) > config.COVER_TARGET_MOVE_M
                           or not all(loot.in_next_zone(obs["zone"], p) for p in self.cover)
                           or math.dist(me["pos"][:2], hide) > max(config.COVER_RADII_M))
        if needs_cover and t - self.cover_checked >= config.COVER_SEARCH_INTERVAL_S:
            self.cover = self.nav.cover_pair(
                me["pos"], threat, me["stats"]["muzzle_height"],
                lambda p: loot.in_next_zone(obs["zone"], p))
            self.cover_checked = t
            self.cover_target = (target.id, threat)

        if self.cover is None or any(not loot.in_next_zone(obs["zone"], p) for p in self.cover):
            return None, False
        reloading = any(w and w["kind"] == "gun" and (w["reload"] > 0 or w["ammo"] == 0)
                        for w in me["weapons"])
        hiding = self.recovering or reloading
        return self.cover[0 if hiding else 1], hiding

    def strafe(self, obs, dx, dy):
        me = obs["self"]
        x, y, z = me["pos"]
        for sign in (1, -1):
            px = x + dx * sign * config.DODGE_STEP_M
            py = y + dy * sign * config.DODGE_STEP_M
            point = (px, py)
            if (self.world.in_bounds(px, py) and loot.in_next_zone(obs["zone"], point)
                    and self.nav.walkable_xy(px, py)
                    and abs(self.world.surface(px, py) - z) <= config.NAV_MAX_UP
                    and self.world.los((x, y, z + me["stats"]["muzzle_height"]),
                                       (px, py, z + me["stats"]["muzzle_height"]))):
                return sign * dx, sign * dy
        return None

    def idle_yaw(self, mx, my, me):
        """Look toward a recent threat, then travel direction, then sweep."""
        bearing = self.track.threat_bearing()
        if bearing is not None:
            return bearing
        if mx or my:
            self.scan_yaw = None
            return math.atan2(my, mx)
        if self.scan_yaw is None:
            self.scan_yaw = me["aim"][0]
        self.scan_yaw += config.SCAN_RAD_PER_TICK
        return (self.scan_yaw + math.pi) % (2 * math.pi) - math.pi
