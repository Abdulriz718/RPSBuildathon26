"""Top-level decision: which mode, which target, where to go. Owner: A (B reviews).

One mode per tick, first match wins:
  ZONE     outside / about to be caught by the zone: run for the safe circle, shoot what we see
  DROP     a supply drop is landing nearby and nobody is around it: capture it (+3 cubes, full HP)
  RECOVER  low HP: legs go to cover away from the threat, torso keeps facing it, heal
  FIGHT    a mech we want to fight is in view: hide/peek around cover, else strafe; dodge shots
  AVOID    (ffa mode) a mech is in view that we don't want to fight: break line of sight
  LOOT     early game, nobody around: pickups, cubes, crates, lone NPC drones
  HOLD     walk to / hold the near side of the next zone circle

Firing and dodging come from combat.Weapons (Sahan); legs and modes live here.
"""
import gc
import math

import combat
import config
import loot
import mechfight as mf
from nav import Nav
from track import Target, Tracker
from world import World


def hdist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class LootMemory:
    """Pickups, cubes and crates are only listed while visible; remember where they were."""

    def __init__(self):
        self.items = {}  # id -> (type, kind, pos, hp)

    def update(self, obs):
        listed = set()
        for typ, key in (("pickup", "pickups"), ("cube", "cubes"), ("crate", "crates")):
            for it in obs[key]:
                self.items[it["id"]] = (typ, it.get("kind", typ), tuple(it["pos"]), it.get("hp"))
                listed.add(it["id"])
        me = obs["self"]["pos"]
        for i, item in list(self.items.items()):
            if i not in listed and hdist(item[2], me) < config.LOOT_FORGET_M:
                del self.items[i]  # should be visible from here, so it's gone
        for e in obs["events"]:
            if e["type"] == "took":
                self.items.pop(e["id"], None)


class Brain:
    def __init__(self, hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.reach = cfg["loot"]["pickup_radius"]
        self.crate_dims = cfg["crates"]
        self.regen_delay = cfg["mech"]["regen_delay"]
        self.world = World.load(hello["map"]["dir"])
        self.nav = Nav(self.world, cfg.get("mech", {}))
        self.track = Tracker(cfg)
        self.weapons = combat.Weapons(cfg)
        self.loot = LootMemory()
        self.scan_yaw = None
        self.mode = "HOLD"
        self.retreat = None  # (x, y, computed_at, threat_id)
        self.pair = None  # (hide, peek, computed_at, target_id, target_pos)
        self.strafe_sign = 1
        self.strafe_t = 0.0
        self.last_exchange = -1e9
        self.recovering = False
        self.threat = None  # last mech that hurt us or that we fought
        self.hurt_by = {}  # mech id -> last time it damaged us
        self.anchor = None  # (circle, refresh time, position)
        # The map and nav grids are big and live all match: move them out of the GC's scans
        # so a collection can't stall a tick.
        gc.collect()
        gc.freeze()

    # ---- zone ------------------------------------------------------------
    def zone_goal(self, obs):
        """Where to stand inside the next circle. Returns (goal_xy, must_hurry)."""
        me = obs["self"]
        x, y = me["pos"][0], me["pos"][1]
        z, t = obs["zone"], obs["t"]
        nx_, ny_, nr = z["next_center"][0], z["next_center"][1], z["next_radius"]
        dx, dy = x - nx_, y - ny_
        d = math.hypot(dx, dy)
        frac = config.ZONE_MARGIN
        late = config.LATE_ZONE and nr < config.LATE_ZONE_RADIUS
        if late:
            frac = config.ZONE_MARGIN_LATE
        keep = nr * frac
        if late:
            goal = self.late_anchor(obs, (nx_, ny_), keep)
        elif d <= keep:
            goal = (x, y)
        else:
            goal = (nx_ + dx / d * keep, ny_ + dy / d * keep)
        need = max(0.0, d - keep) / max(1.0, me["stats"].get("walk_speed", 11.7))
        time_left = z["shrink_end"] - t
        hurry = not me["in_zone"] or need > time_left - config.ZONE_SAFETY_S
        return goal, hurry

    def late_anchor(self, obs, center, radius):
        """Pick a central walkable point, favoring elevation and cover from recent shots."""
        if radius <= config.LATE_TINY_RADIUS_M:
            return center
        key = (*center, radius)
        now = obs["t"]
        if self.anchor is not None and self.anchor[0] == key and now < self.anchor[1]:
            return self.anchor[2]
        world = self.world
        me = obs["self"]
        bearing = self.track.recent_shot_bearing(config.LATE_ANCHOR_SOUND_AGE_S)
        sound = None
        if bearing is not None:
            sound = (math.cos(bearing), math.sin(bearing))
            source = tuple(p + d * config.LATE_ANCHOR_SOUND_DISTANCE_M
                           for p, d in zip(me["pos"][:2], sound))
            source_eye = (*source, world.surface(*source) + me["stats"]["eye_height"])
        offset = min(radius, config.LATE_ANCHOR_MAX_OFFSET_M)
        points = [center]
        for i in range(config.COVER_ANGLES):
            angle = i * math.tau / config.COVER_ANGLES
            points.append((center[0] + offset * math.cos(angle), center[1] + offset * math.sin(angle)))
        best = None
        center_height = world.ground(*center)
        for point in points:
            if not world.in_bounds(*point) or not self.nav.walkable_xy(*point):
                continue
            surface = world.surface(*point)
            if surface - world.ground(*point) > config.NAV_MAX_UP:
                continue  # walkable roof cells may still need a jet ascent to reach
            score = (config.LATE_ANCHOR_HEIGHT_WEIGHT * (surface - center_height)
                     - config.LATE_ANCHOR_CENTER_WEIGHT * hdist(point, center))
            if sound is not None:
                score -= config.LATE_ANCHOR_AWAY_WEIGHT * sum(
                    (p - c) * d for p, c, d in zip(point, center, sound))
                if not world.los(source_eye, (*point, surface + me["stats"]["eye_height"])):
                    score += config.LATE_ANCHOR_COVER_BONUS_M
            if best is None or score > best[0]:
                best = (score, point)
        anchor = center if best is None else best[1]
        self.anchor = (key, now + config.LATE_ANCHOR_REFRESH_S, anchor)
        return anchor

    def in_safe(self, obs, p, frac=1.0):
        z = obs["zone"]
        return hdist(p, z["next_center"]) <= z["next_radius"] * frac

    # ---- choices ---------------------------------------------------------
    def pick_mech(self):
        """Visible mech to fight: nearest, but prefer a clearly weaker one at similar range."""
        mechs = self.track.targets_sorted("mech", max_age=config.TRACK_AIM_MEMORY_S)
        if not mechs:
            return None
        near = hdist(mechs[0].pos, self.track.me_pos)
        close = [m for m in mechs if hdist(m.pos, self.track.me_pos) < near * 1.4 + 10]
        return min(close, key=lambda m: (m.hp if m.hp is not None else 1e9))

    def ffa_target(self, t):
        """Prefer a recent attacker, otherwise finish a weak isolated report."""
        enemies = self.track.targets_sorted("mech", max_age=config.TRACK_AIM_MEMORY_S)
        attacker = next((m for m in enemies if t - self.hurt_by.get(m.id, -math.inf)
                         < config.FFA_GRUDGE_S), None)
        if attacker is not None:
            return attacker
        if len(enemies) == 1:
            mech = enemies[0]
            if (not mech.age and mech.hp is not None and mech.hp < config.FFA_FINISH_HP
                    and hdist(mech.pos, self.track.me_pos) < config.FFA_FINISH_M):
                return mech
        return None

    def drop_goal(self, obs):
        """Supply drop worth going for: (x, y) or None."""
        if not config.DROPS:
            return None
        tracks = self.track.targets_sorted("mech", max_age=config.DROP_TRACK_S)
        return loot.supply_goal(obs, tracks)

    def loot_goal(self, obs, *, allow_crates=True):
        """(goal_xy, shoot_target or None) for the best loot, or None."""
        me = obs["self"]
        pos = me["pos"]
        held = {w["kind"] for w in me["weapons"] if w}
        slot_free = None in me["weapons"]
        best = None
        for iid, (typ, kind, p, hp) in self.loot.items.items():
            if typ == "crate" and not allow_crates:
                continue
            d = hdist(p, pos)
            if d > config.LOOT_RADIUS or not self.in_safe(obs, p, config.LOOT_ZONE_FRAC):
                continue
            if p[2] - self.world.ground(p[0], p[1]) > 3:
                continue  # on a roof: not reachable without jetting yet
            if typ == "pickup":
                if not slot_free or kind in held or kind == "gun":
                    continue
                score = d * 0.6
            elif typ == "cube":
                score = d * 0.8
            else:
                score = d
            if best is None or score < best[0]:
                best = (score, iid, typ, p, hp)
        if best is None:
            return None
        _, iid, typ, p, hp = best
        if typ == "crate" and hdist(p, pos) < config.CRATE_SHOOT_M:
            crate = loot.crate_target({"id": iid, "pos": p, "hp": hp}, self.crate_dims)
            muzzle = (pos[0], pos[1], pos[2] + me["stats"]["muzzle_height"])
            if self.world.los(muzzle, (p[0], p[1], p[2] + crate.height / 2)):
                return (pos[0], pos[1]), crate
        return (p[0], p[1]), None

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
        back = 0.8 if "lightning" in target.weapons and d < config.KEEP_OFF_LIGHTNING_M else 0.0
        mx, my = px - ux * back, py - uy * back
        n = math.hypot(mx, my) or 1.0
        return mx / n, my / n

    def retreat_goal(self, obs, threat, t):
        """Cover far enough to heal behind, or straight away from the threat on open ground."""
        me = obs["self"]
        if self.retreat and t - self.retreat[2] < config.COVER_CACHE_S and self.retreat[3] == threat.id:
            return self.retreat[:2]
        zone = obs["zone"]
        c = self.nav.cover_from(me["pos"], threat.pos, (*zone["center"], zone["radius"] * 0.95))
        if c is None:
            x, y = me["pos"][0], me["pos"][1]
            dx, dy = x - threat.pos[0], y - threat.pos[1]
            d = math.hypot(dx, dy) or 1.0
            c = (x + dx / d * 30, y + dy / d * 30)
        self.retreat = (c[0], c[1], t, threat.id)
        return c

    def fight_spot(self, obs, target, t):
        """(hide, peek) pair near us against target, cached; None on open ground."""
        me = obs["self"]
        tp = target.predict(0)
        if (self.pair and self.pair[3] == target.id and t - self.pair[2] < config.COVER_SEARCH_INTERVAL_S
                and math.dist(tp, self.pair[4]) < config.COVER_TARGET_MOVE_M):
            return self.pair[:2] if self.pair[0] is not None else None
        threat = (tp[0], tp[1], tp[2] + target.height / 2)
        pair = self.nav.cover_pair(me["pos"], threat, me["stats"]["muzzle_height"],
                                   lambda p: loot.in_next_zone(obs["zone"], p))
        hide, peek = pair if pair else (None, None)
        self.pair = (hide, peek, t, target.id, tp)
        return pair

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
        self.loot.update(obs)
        act = {}

        for e in obs["events"]:
            if e["type"] in ("hit", "damaged"):
                self.last_exchange = t
            if e["type"] == "damaged" and e.get("by") is not None:
                self.hurt_by[e["by"]] = t
                if e["by"] in self.track.targets:
                    self.threat = self.track.targets[e["by"]]

        late = config.ENDGAME and (obs["alive"] <= config.ENDGAME_ALIVE or t >= config.ENDGAME_T)
        low = config.ENDGAME_LOW_HP if late else config.COVER_LOW_HP
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        delay = me["stats"].get("regen_delay", self.regen_delay)
        if hp_frac <= low:
            self.recovering = True
        elif hp_frac >= config.COVER_RECOVER_HP and t - self.last_exchange >= delay:
            self.recovering = False

        if obs["offer"]:
            act["pick"] = loot.pick_upgrade(obs["offer"], me)
        take = loot.take_nearby(obs, self.reach)
        if take is not None:
            act["take"] = take

        zgoal, hurry = self.zone_goal(obs)
        mech = self.pick_mech()
        ffa = config.MODE == "ffa"
        target = self.ffa_target(t) if ffa else mech
        if mech is not None:
            self.threat = target if target is not None else mech
        threat = self.threat if self.threat and t - self.threat.last_seen < 6.0 else None
        visible_mech = mech is not None and mech.age == 0
        dgoal = None if (visible_mech and not self.recovering) or hurry else self.drop_goal(obs)

        goal = zgoal
        stand = hide = False
        move = None  # direct move override (strafe)
        tiny_zone = config.LATE_ZONE and obs["zone"]["next_radius"] <= config.LATE_TINY_RADIUS_M
        precise = tiny_zone

        center_needed = tiny_zone and hdist(zgoal, (x, y)) > config.LATE_TINY_REACH_M
        if (not me["in_zone"] or center_needed
                or (hurry and not self.in_safe(obs, (x, y), 0.98))):
            mode = "ZONE"
        elif dgoal is not None:
            mode, goal, precise = "DROP", dgoal, True
            stand = hdist(dgoal, (x, y)) < config.DROP_STAND_M
        elif self.recovering and threat is not None:
            mode = "RECOVER"
            goal = self.retreat_goal(obs, threat, t)
            stand = self.hidden_from(me, threat)
            hide = True
        elif target is not None:
            mode = "FIGHT"
            pair = self.fight_spot(obs, target, t)
            reloading = any(w and w["kind"] == "gun" and (w["reload"] > 0 or w["ammo"] == 0)
                            for w in me["weapons"])
            if pair is not None:
                goal, precise = (pair[0] if reloading else pair[1]), True
                hide = reloading
            else:
                move = self.strafe(me, target, t)
        elif mech is not None:
            mode = "AVOID"
            goal = self.retreat_goal(obs, mech, t)
            stand = self.hidden_from(me, mech)
            target = None
        else:
            mode = "HOLD"
            if (t < config.LOOT_UNTIL_S and not late and not self.recovering
                    and t - self.last_exchange > 3.0):
                npc = None if ffa else self.pick_npc(me)
                lg = self.loot_goal(obs, allow_crates=not ffa)
                if npc is not None:
                    mode, target, stand = "LOOT", npc, True
                elif lg is not None:
                    mode = "LOOT"
                    goal, shoot = lg
                    if shoot is not None:
                        target, stand = shoot, True
        self.mode = mode

        # legs
        if move is not None:
            mx, my, jump, boost = move[0], move[1], False, False
        else:
            reach = config.COVER_REACHED_M if precise else 2.0
            if tiny_zone and mode in ("ZONE", "HOLD"):
                reach = config.LATE_TINY_REACH_M
            far = hdist(goal, (x, y)) > reach and not stand
            mx, my, jump, boost = self.nav.next_step(me["pos"], goal, t, 1.0 if far else 0.0, precise=precise)
            if not far:
                mx = my = 0.0
            boost = boost or (mode == "ZONE" and far) or (mode in ("RECOVER", "AVOID") and far and me["energy"] > 30)
        if mode in ("FIGHT", "DROP", "HOLD", "LOOT") or (mode != "ZONE" and (ffa or late)):
            dodge = self.weapons.dodge(obs, target, self.world)
            if dodge is not None:
                dx, dy, urgent = dodge
                if urgent or (move is not None and not hide):
                    step = self.dodge_step(obs, dx, dy)
                    if step is not None:
                        s = 1.0 if urgent else config.STRAFE_SPEED_FRACTION
                        mx, my = step[0] * s, step[1] * s
        act.update(move=[mx, my], boost=boost, jump=jump)

        # torso
        act["aim"] = [self.idle_yaw(mx, my, me), 0.0]
        if target is None and threat is not None and mode in ("RECOVER", "AVOID"):
            act["aim"] = [math.atan2(threat.pos[1] - y, threat.pos[0] - x), 0.0]  # never show our back
        fight = self.weapons.decide(me, target, self.world)
        if hide or (ffa and target is None):
            fight["fire"] = [False, False]
            gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
            if gun and gun["reload"] <= 0 and gun["ammo"] < gun["stats"]["mag"]:
                fight["reload"] = True
        act.update(fight)

        # debug
        if target is not None:
            tx, ty, tz = target.predict(0)
            mf.draw.line([x, y, z + me["stats"]["muzzle_height"]], [tx, ty, tz + target.height / 2], "#ff5040")
        if mode in ("RECOVER", "AVOID", "FIGHT", "DROP"):
            mf.draw.point([goal[0], goal[1], self.world.surface(goal[0], goal[1]) + 1], "#40ff80", 8)
        for wx, wy in self.nav.path[:20]:
            mf.draw.point([wx, wy, self.world.surface(wx, wy) + 1], "#40c0ff", 2)
        mf.draw.label(f"{mode} hp {me['hp']:.0f}")
        return act

    def dodge_step(self, obs, dx, dy):
        """Pick the side of (dx, dy) that's walkable, open and in the zone."""
        me = obs["self"]
        x, y, z = me["pos"]
        mh = me["stats"]["muzzle_height"]
        for sign in (1, -1):
            px, py = x + dx * sign * config.DODGE_STEP_M, y + dy * sign * config.DODGE_STEP_M
            if (self.world.in_bounds(px, py) and loot.in_next_zone(obs["zone"], (px, py))
                    and self.nav.walkable_xy(px, py)
                    and abs(self.world.surface(px, py) - z) <= config.NAV_MAX_UP
                    and self.world.los((x, y, z + mh), (px, py, z + mh))):
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
