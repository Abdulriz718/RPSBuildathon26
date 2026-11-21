"""Top-level decision: which mode, which target, where to go. Owner: A (B reviews).

Modes, checked in order each tick:
  ZONE    outside the zone or about to be caught: run for the safe circle, shoot what we see
  RETREAT low HP (or reloading up close): legs go to cover, torso keeps facing the threat
  HEAL    in cover, waiting for regen up to HEAL_TO_HP
  FIGHT   a mech is in view: strafe and shoot
  LOOT    early game, nobody around: pickups, cubes, crates, lone NPC drones
  HOLD    walk to / hold the near side of the next zone circle
"""
import math

import combat
import config
import loot
import mechfight as mf
from nav import Nav
from track import Target, Tracker
from world import World


def zone_now(z, t):
    """Current circle (cx, cy, r), interpolating during the shrink window."""
    if t <= z["shrink_start"] or z["shrink_end"] <= z["shrink_start"]:
        return z["center"][0], z["center"][1], z["radius"]
    f = min(1.0, (t - z["shrink_start"]) / (z["shrink_end"] - z["shrink_start"]))
    cx = z["center"][0] + (z["next_center"][0] - z["center"][0]) * f
    cy = z["center"][1] + (z["next_center"][1] - z["center"][1]) * f
    return cx, cy, z["radius"] + (z["next_radius"] - z["radius"]) * f


def hdist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class LootMemory:
    """Pickups, cubes and crates are only listed while visible; remember where they were."""

    def __init__(self):
        self.items = {}  # id -> (type, kind, pos)

    def update(self, obs):
        listed = set()
        for typ, key in (("pickup", "pickups"), ("cube", "cubes"), ("crate", "crates")):
            for it in obs[key]:
                self.items[it["id"]] = (typ, it.get("kind", typ), tuple(it["pos"]))
                listed.add(it["id"])
        me = obs["self"]["pos"]
        for i, (_, _, pos) in list(self.items.items()):
            if i not in listed and hdist(pos, me) < config.LOOT_FORGET_M:
                del self.items[i]  # should be visible from here, so it's gone
        for e in obs["events"]:
            if e["type"] in ("took",):
                self.items.pop(e["id"], None)


class Brain:
    def __init__(self, hello):
        cfg = hello["config"]
        self.cfg = cfg
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
        self.loot = LootMemory()
        self.sim_step = 1 / cfg["match"]["tick_hz"]
        self.scan_yaw = None
        self.mode = "HOLD"
        self.cover = None  # (x, y, computed_at, threat_id)
        self.strafe_sign = 1
        self.strafe_t = 0.0
        self.last_hurt_t = -1e9
        self.threat = None  # last mech that hurt us or that we fought: Target

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

    def in_safe(self, obs, p, frac=1.0):
        z = obs["zone"]
        return hdist(p, z["next_center"]) <= z["next_radius"] * frac

    # ---- target choice ---------------------------------------------------
    def pick_mech(self):
        """Visible mech to fight: nearest, but prefer a clearly weaker one at similar range."""
        mechs = self.track.targets_sorted("mech", max_age=config.TRACK_AIM_MEMORY_S)
        if not mechs:
            return None
        near = hdist(mechs[0].pos, self.track.me_pos)
        close = [m for m in mechs if hdist(m.pos, self.track.me_pos) < near * 1.4 + 10]
        return min(close, key=lambda m: (m.hp if m.hp is not None else 1e9))

    def loot_goal(self, obs):
        """(goal_xy, shoot_target or None, label) for the best loot, or None."""
        me = obs["self"]
        pos = me["pos"]
        held = {w["kind"] for w in me["weapons"] if w}
        slot_free = me["weapons"][1] is None
        best = None
        for iid, (typ, kind, p) in self.loot.items.items():
            d = hdist(p, pos)
            if d > config.LOOT_RADIUS or not self.in_safe(obs, p, config.LOOT_ZONE_FRAC):
                continue
            if p[2] - self.world.ground(p[0], p[1]) > 3:
                continue  # on a roof: not reachable without jetting yet
            if typ == "pickup":
                if not slot_free or kind in held or kind == "gun":
                    continue
                score = d * 0.6  # weapons matter most
            elif typ == "cube":
                score = d * 0.8
            else:
                score = d * 1.0
            if best is None or score < best[0]:
                best = (score, iid, typ, p)
        if best is None:
            return None
        _, iid, typ, p = best
        if typ == "crate" and hdist(p, pos) < config.CRATE_SHOOT_M:
            eye = (pos[0], pos[1], pos[2] + me["stats"].get("muzzle_height", 7))
            if self.world.los(eye, (p[0], p[1], p[2] + 1.0)):
                tgt = Target(id=iid, kind="crate", pos=p, vel=(0.0, 0.0, 0.0), radius=1.5, height=2.0)
                return (pos[0], pos[1]), tgt, "crate"
        return (p[0], p[1]), None, typ

    def pick_npc(self, me):
        if me["hp"] < me["max_hp"] * config.NPC_FARM_HP:
            return None
        npcs = self.track.targets_sorted("npc", max_age=0.0)
        if npcs and hdist(npcs[0].pos, me["pos"]) < config.NPC_FARM_M:
            return npcs[0]
        return None

    # ---- movement helpers --------------------------------------------------
    def strafe(self, me, target, t):
        """Unit move perpendicular to the target line, flipping every STRAFE_S or at walls.
        Also opens range on lightning carriers."""
        x, y = me["pos"][0], me["pos"][1]
        dx, dy = target.pos[0] - x, target.pos[1] - y
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        if t - self.strafe_t > config.STRAFE_S:
            self.strafe_sign = -self.strafe_sign
            self.strafe_t = t
        px, py = -uy * self.strafe_sign, ux * self.strafe_sign
        if not self.nav.walkable_xy(x + px * config.STRAFE_PROBE_M, y + py * config.STRAFE_PROBE_M):
            self.strafe_sign = -self.strafe_sign
            self.strafe_t = t
            px, py = -px, -py
        back = 0.0
        if "lightning" in target.weapons and d < config.KEEP_OFF_LIGHTNING_M:
            back = 0.8
        mx, my = px - ux * back, py - uy * back
        n = math.hypot(mx, my) or 1.0
        return mx / n, my / n

    def cover_goal(self, obs, threat, t):
        me = obs["self"]
        if self.cover and t - self.cover[2] < config.COVER_CACHE_S and self.cover[3] == threat.id:
            return self.cover[:2]
        cz = zone_now(obs["zone"], t)
        c = self.nav.cover_from(me["pos"], threat.pos, (cz[0], cz[1], cz[2] * 0.95))
        if c is None:  # open ground: back straight away from them
            x, y = me["pos"][0], me["pos"][1]
            dx, dy = x - threat.pos[0], y - threat.pos[1]
            d = math.hypot(dx, dy) or 1.0
            c = (x + dx / d * 30, y + dy / d * 30)
        self.cover = (c[0], c[1], t, threat.id)
        return c

    def hidden_from(self, me, threat):
        p = me["pos"]
        eye = (threat.pos[0], threat.pos[1], threat.pos[2] + 8.0)
        return not (self.world.los(eye, (p[0], p[1], p[2] + 4.5)) or self.world.los(eye, (p[0], p[1], p[2] + 8.5)))

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
        self.loot.update(obs)
        act = {}

        for e in obs["events"]:
            if e["type"] == "damaged":
                self.last_hurt_t = t
                if e.get("by") is not None and e["by"] in self.track.targets:
                    self.threat = self.track.targets[e["by"]]

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
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        zgoal, hurry = self.zone_goal(obs)
        mech = self.pick_mech()
        if mech is not None:
            self.threat = mech
        threat = self.threat if self.threat and t - self.threat.last_seen < 6.0 else None

        gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
        reloading = gun is not None and gun["reload"] > 0
        target = mech
        goal = zgoal
        stand = False
        strafe_move = None

        # mode selection
        if hurry and not self.in_safe(obs, (x, y), 0.98):
            mode = "ZONE"
        elif threat and (hp_frac < config.RETREAT_HP or (
                self.mode in ("RETREAT", "HEAL") and hp_frac < config.HEAL_TO_HP)):
            mode = "HEAL" if self.hidden_from(me, threat) else "RETREAT"
        elif mech and reloading and hdist(mech.pos, me["pos"]) < config.RETREAT_ON_RELOAD_M:
            mode = "RETREAT"
        elif mech:
            mode = "FIGHT"
        else:
            mode = "HOLD"
            if t < config.LOOT_UNTIL_S and not hurry and t - self.last_hurt_t > 3.0:
                npc = self.pick_npc(me)
                lg = self.loot_goal(obs)
                if npc is not None:
                    mode, target, stand = "LOOT", npc, True
                elif lg is not None:
                    mode = "LOOT"
                    goal, shoot, _ = lg
                    if shoot is not None:
                        target, stand = shoot, True

        if mode in ("RETREAT", "HEAL"):
            goal = self.cover_goal(obs, threat, t)
            stand = mode == "HEAL"
        elif mode == "FIGHT":
            strafe_move = self.strafe(me, mech, t)
        self.mode = mode

        # legs
        if strafe_move is not None:
            mx, my, jump, boost = strafe_move[0], strafe_move[1], False, False
        else:
            far = hdist(goal, (x, y)) > 2.0 and not stand
            mx, my, jump, boost = self.nav.next_step(me["pos"], goal, t, 1.0 if far else 0.0)
            if not far:
                mx = my = 0.0
            boost = boost or (mode == "ZONE" and far) or (mode == "RETREAT" and me["energy"] > 30)
        act.update(move=[mx, my], boost=boost, jump=jump)

        # torso
        act["aim"] = [self.idle_yaw(mx, my, me), 0.0]
        if target is None and threat is not None and mode in ("RETREAT", "HEAL"):
            act["aim"] = [math.atan2(threat.pos[1] - y, threat.pos[0] - x), 0.0]  # never show our back
        act.update(combat.engage(me, target, self.world, sim_step=self.sim_step))

        # debug
        if target is not None:
            tx, ty, tz = target.predict(0)
            mf.draw.line([x, y, z + me["stats"]["muzzle_height"]], [tx, ty, tz + target.height / 2], "#ff5040")
        if mode in ("RETREAT", "HEAL") and self.cover:
            mf.draw.point([self.cover[0], self.cover[1], self.world.surface(self.cover[0], self.cover[1]) + 1], "#40ff80", 8)
        for wx, wy in self.nav.path[:20]:
            mf.draw.point([wx, wy, self.world.surface(wx, wy) + 1], "#40c0ff", 2)
        mf.draw.label(f"{mode} hp {me['hp']:.0f}")
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
