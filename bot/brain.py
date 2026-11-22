"""Top-level decision: which mode, which target, where to go. Owner: A (B reviews).

One mode per tick, first match wins:
  ZONE     outside / about to be caught by the zone: run for the safe circle, shoot what we see
  DROP     a supply drop is landing nearby and nobody is around it: capture it (+3 cubes, full HP)
  RECOVER  low HP: legs go to cover away from the threat, torso keeps facing it, heal
  WEAPON   fetch the best floor weapon we've seen (laser > lightning > mortar), shooting on the way;
           swap up to a better one close by
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
import defense
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
        self.danger = []  # (time, world bearing) of fights we heard or saw that weren't aimed at us
        self.zig_sign, self.zig_t = 1, -1e9  # zig-zag under fire
        self.next_hop, self.hop_until = -1e9, -1e9  # little jump-and-jet hops under fire
        self.roam = None  # (until, (x, y)) waypoint while searching for a laser
        self.style_boost = False
        self.roof_spot = None  # (computed at, (x, y, z)) for STYLE "roof"
        self.anchor = None  # (circle, refresh time, position)
        self.ffa_on = config.MODE == "ffa"
        self.last_hurt = -1e9  # last time anything (incl. the zone) damaged us
        self.healing = False   # HEAL_BETWEEN
        self.our_kills = set()  # mech ids we killed (AUTO_FFA)
        self.alive_max = 0
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

    def note_danger(self, obs, t):
        """Remember where fights are happening that don't involve us: combat sounds we heard, and mechs we see
        firing at someone else. Sounds don't say who fired, so skip them while we're trading shots ourselves."""
        x, y = obs["self"]["pos"][0], obs["self"]["pos"][1]
        if t - self.last_exchange > 2.0:
            for snd in obs["sounds"]:
                if snd["kind"] in config.DANGER_SOUNDS and snd["dist"] in config.DANGER_SOUND_DISTS:
                    self.danger.append((t - snd["age"], snd["bearing"]))
        for m in obs["mechs"]:
            aim = m.get("aim")
            if m.get("kind") != "mech" or aim is None or t - self.hurt_by.get(m["id"], -1e9) < 3.0:
                continue
            to_us = math.atan2(y - m["pos"][1], x - m["pos"][0])
            if abs((aim[0] - to_us + math.pi) % (2 * math.pi) - math.pi) > math.radians(30):
                if m.get("charging") or any(e for e in obs["beams"] if e.get("by") == m["id"]):
                    self.danger.append((t, math.atan2(m["pos"][1] - y, m["pos"][0] - x)))
        if config.AVOID_PEOPLE:
            for m in obs["mechs"]:
                if m.get("kind") == "mech" and math.dist(m["pos"][:2], (x, y)) <= config.AVOID_PEOPLE_M:
                    self.danger.append((t, math.atan2(m["pos"][1] - y, m["pos"][0] - x)))
        self.danger = [d for d in self.danger if t - d[0] <= config.DANGER_MEMORY_S][-32:]

    def away_from_danger(self, obs, goal):
        """Shift a holding goal away from recent fights, staying inside the next circle."""
        if not (config.AVOID_FIGHT_SOUNDS or config.AVOID_PEOPLE) or not self.danger:
            return goal
        me = obs["self"]
        x, y = me["pos"][0], me["pos"][1]
        ax = -sum(math.cos(b) for _, b in self.danger)
        ay = -sum(math.sin(b) for _, b in self.danger)
        n = math.hypot(ax, ay)
        if n < 1e-6:
            return goal
        gx, gy = x + ax / n * config.DANGER_STEP_M, y + ay / n * config.DANGER_STEP_M
        z = obs["zone"]
        cx, cy, r = z["next_center"][0], z["next_center"][1], z["next_radius"] * config.DANGER_ZONE_FRAC
        d = math.hypot(gx - cx, gy - cy)
        if d > r and d > 0:
            gx, gy = cx + (gx - cx) / d * r, cy + (gy - cy) / d * r
        if not self.nav.walkable_xy(gx, gy):
            gx, gy = self.nav.nearest_walkable(gx, gy)
        return gx, gy

    def known_attackers(self, t, x, y):
        """Mech ids we can place as threats now: tracked within 120 m, or hit us in the last 2 s."""
        ids = {m.id for m in self.track.targets_sorted("mech", max_age=2.0) if hdist(m.pos, (x, y)) < 120}
        ids |= {mid for mid, ht in self.hurt_by.items() if t - ht <= 2.0}
        return ids

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

    def weapon_goal(self, obs, mech):
        """(pickup id, (x, y, z), drop slot or None) for the weapon worth fetching now, or None."""
        if not config.WEAPON_GRAB:
            return None
        me = obs["self"]
        pos = me["pos"]
        slot1 = me["weapons"][1]
        held = {w["kind"] for w in me["weapons"] if w}
        if slot1 is not None and (slot1.get("charge") or slot1["kind"] not in config.WEAPON_RANK):
            return None
        have = config.WEAPON_RANK.get(slot1["kind"], 0) if slot1 else 0
        mech_d = hdist(mech.pos, pos) if mech is not None and mech.age == 0 else None
        best = None
        for iid, (typ, kind, p, _) in self.loot.items.items():
            if typ != "pickup" or kind in held or kind not in config.WEAPON_RANK:
                continue
            if config.WEAPON_RANK[kind] <= have:
                continue
            on_roof = p[2] - self.world.ground(p[0], p[1]) > 3
            if on_roof and not config.ROOF_CLIMB:
                continue
            d = hdist(p, pos)
            limit = config.WEAPON_MAX_M if slot1 is None else config.WEAPON_SWAP_M
            if d > limit:
                continue
            if mech_d is not None and mech_d < config.WEAPON_FIGHT_M and d > config.WEAPON_GRAB_IN_FIGHT_M:
                continue  # someone is on us: only grab it if it's right here
            score = d - config.WEAPON_BONUS.get(kind, 0) + (config.ROOF_COST_M if on_roof else 0)
            if on_roof and not self.nav.roof_reachable(p) and not self.nav.on_roof_of(pos, p):
                continue
            if best is None or score < best[0]:
                best = (score, iid, p)
        if best is None:
            return None
        return best[1], best[2], (1 if slot1 is not None else None)

    def cube_goal(self, obs, fighting_d):
        """Nearest remembered cube worth walking to: within CUBE_MAX_M when nobody is close, or within
        CUBE_FIGHT_M (a few steps) even mid-fight, since the dead mech's cubes land where it fell."""
        if not config.CUBE_COLLECT:
            return None
        pos = obs["self"]["pos"]
        limit = config.CUBE_MAX_M if fighting_d is None or fighting_d > config.CUBE_SAFE_M else config.CUBE_FIGHT_M
        best = None
        for iid, (typ, _, p, _) in self.loot.items.items():
            if typ != "cube" or abs(p[2] - pos[2]) > 4:
                continue
            d = hdist(p, pos)
            if d <= limit and (best is None or d < best[0]):
                best = (d, p)
        return None if best is None else (best[1][0], best[1][1])

    def forget_broken_crates(self, obs):
        """A remembered crate that is in plain view but not listed is gone (we or someone broke it)."""
        me = obs["self"]
        listed = {c["id"] for c in obs["crates"]}
        vis = self.cfg["vision"]
        eye = (me["pos"][0], me["pos"][1], me["pos"][2] + me["stats"]["eye_height"])
        for iid, (typ, _, p, _) in list(self.loot.items.items()):
            if typ != "crate" or iid in listed:
                continue
            d = hdist(p, eye)
            if d > vis["range"] - 10:
                continue
            off = abs(math.remainder(math.atan2(p[1] - eye[1], p[0] - eye[0]) - me["aim"][0], math.tau))
            if (d <= vis["near_range"] - 5 or off < math.radians(vis["fov_deg"]) / 2 - 0.1)                     and self.world.los(eye, (p[0], p[1], p[2] + 1.2)):
                del self.loot.items[iid]

    def crate_goal(self, obs):
        """(goal_xy, crate target to shoot or None) for the nearest remembered ground crate, or None."""
        me = obs["self"]
        pos = me["pos"]
        best = None
        for iid, (typ, _, p, hp) in self.loot.items.items():
            if typ != "crate" or p[2] - self.world.ground(p[0], p[1]) > 3:
                continue
            d = hdist(p, pos)
            if d > config.CRATE_HUNT_M or not self.in_safe(obs, p, config.LOOT_ZONE_FRAC):
                continue
            if best is None or d < best[0]:
                best = (d, iid, p, hp)
        if best is None:
            return None
        d, iid, p, hp = best
        if d < config.CRATE_SHOOT_M:
            crate = loot.crate_target({"id": iid, "pos": p, "hp": hp}, self.crate_dims)
            muzzle = (pos[0], pos[1], pos[2] + me["stats"]["muzzle_height"])
            if self.world.los(muzzle, (p[0], p[1], p[2] + crate.height / 2)):
                return (pos[0], pos[1]), crate
        return (p[0], p[1]), None

    @staticmethod
    def has_laser(me):
        return any(w and w["kind"] == "laser" for w in me["weapons"])

    def roam_point(self, obs, t):
        """A waypoint inside the next circle to walk to while scanning for a laser; new one every LASER_ROAM_S."""
        x, y = obs["self"]["pos"][0], obs["self"]["pos"][1]
        if self.roam is None or t > self.roam[0] or hdist(self.roam[1], (x, y)) < 6:
            z = obs["zone"]
            cx, cy, r = z["next_center"][0], z["next_center"][1], z["next_radius"] * 0.7
            k = int(t * 7) % 12
            a = math.atan2(y - cy, x - cx) + (k - 6) * 0.35
            px, py = x + config.LASER_ROAM_STEP_M * math.cos(a), y + config.LASER_ROAM_STEP_M * math.sin(a)
            d = math.hypot(px - cx, py - cy)
            if d > r:
                px, py = cx + (px - cx) / d * r, cy + (py - cy) / d * r
            self.roam = (t + config.LASER_ROAM_S, self.nav.nearest_walkable(px, py))
        return self.roam[1]

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
        if config.CRATE_HUNT:
            self.forget_broken_crates(obs)
        act = {}

        for e in obs["events"]:
            if e["type"] in ("hit", "damaged"):
                self.last_exchange = t
            if e["type"] == "kill" and isinstance(e.get("target"), int) and e["target"] < 100:
                self.our_kills.add(e["target"])
            if e["type"] == "damaged":
                self.last_hurt = t
            if e["type"] == "damaged" and e.get("by") is not None:
                self.hurt_by[e["by"]] = t
                if e["by"] in self.track.targets:
                    self.threat = self.track.targets[e["by"]]

        if config.AVOID_FIGHT_SOUNDS or config.AVOID_PEOPLE:
            self.note_danger(obs, t)
        if config.AUTO_FFA and not self.ffa_on and t < config.AUTO_FFA_MAX_T:
            self.alive_max = max(self.alive_max, obs["alive"])
            if self.alive_max - obs["alive"] - len(self.our_kills) >= config.AUTO_FFA_DEATHS:
                self.ffa_on = True

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
        ffa = self.ffa_on
        target = self.ffa_target(t) if ffa else mech
        if mech is not None:
            self.threat = target if target is not None else mech
        threat = self.threat if self.threat and t - self.threat.last_seen < 6.0 else None
        visible_mech = mech is not None and mech.age == 0
        # HEAL starts only between fights (nobody in sight, no hits either way for a while); being hit ends it
        if not config.HEAL_BETWEEN or t - self.last_hurt < 0.5 or hp_frac >= config.HEAL_DONE:
            self.healing = False
        elif hp_frac < config.HEAL_START and not visible_mech and t - self.last_exchange >= config.HEAL_CALM_S:
            self.healing = True
        dgoal = None if (visible_mech and not self.recovering) or hurry else self.drop_goal(obs)
        defensive_tracks = (self.track.targets_sorted("mech", max_age=config.TRACK_AIM_MEMORY_S)
                            if config.DEFENSIVE_EVASION else [])
        close_enemies = [enemy for enemy in defensive_tracks if not enemy.age
                         and hdist(enemy.pos, me["pos"]) <= config.EVADE_MULTI_RANGE_M]
        pressured = len(close_enemies) > 1
        if pressured:
            # Face the most recent attacker. The order is nearest-first for ties.
            threat = max(close_enemies, key=lambda enemy: self.hurt_by.get(enemy.id, -math.inf))
            self.threat = threat
            if not ffa:
                target = threat

        wgoal = None if hurry or self.recovering else self.weapon_goal(obs, mech)
        crgoal = None
        if (config.CRATE_HUNT and not ffa and not hurry and not self.recovering and not self.has_laser(me)
                and t < config.CRATE_HUNT_UNTIL_S and t - self.last_hurt >= config.CRATE_CALM_S
                and not (visible_mech and hdist(mech.pos, (x, y)) < config.CRATE_FIGHT_M)):
            crgoal = self.crate_goal(obs)
        cgoal = None if hurry else self.cube_goal(obs, hdist(target.pos, (x, y)) if target is not None else None)
        roof_goal = None
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
        elif pressured and threat is not None:
            mode = "AVOID"
            goal = self.retreat_goal(obs, threat, t)
            stand = all(self.hidden_from(me, enemy) for enemy in close_enemies)
        elif (config.STYLE == "roof" and t < config.ROOF_STYLE_UNTIL_S and not self.on_any_roof(me)
              and (target is None or hdist(target.pos, (x, y)) > config.ROOF_STYLE_FIGHT_M)
              and self.style_roof_spot(obs, t) is not None):
            mode = "ROOFUP"
            spot = self.style_roof_spot(obs, t)
            goal, roof_goal = (spot[0], spot[1]), spot
        elif cgoal is not None and (target is None or hdist(cgoal, (x, y)) <= config.CUBE_FIGHT_M):
            mode, goal = "CUBES", cgoal
        elif wgoal is not None:
            mode, goal = "WEAPON", (wgoal[1][0], wgoal[1][1])
            if wgoal[1][2] - self.world.ground(wgoal[1][0], wgoal[1][1]) > 3:
                roof_goal = wgoal[1]
            if hdist(wgoal[1], (x, y)) <= self.reach - 0.5 and abs(wgoal[1][2] - z) <= 4:
                act["take"] = wgoal[0]
                if wgoal[2] is not None:
                    act["drop"] = wgoal[2]
        elif crgoal is not None:
            mode, (goal, shoot) = "CRATE", crgoal
            target = shoot
            stand = shoot is not None
        elif self.healing and not ffa:
            mode, hide = "HEAL", True
            foe = threat or mech
            if foe is not None:
                goal = self.retreat_goal(obs, foe, t)
                stand = self.hidden_from(me, foe)
            else:
                goal, stand = (x, y), True
            target = None
        elif (config.MULTI_DISENGAGE and target is not None and len(self.known_attackers(t, x, y)) >= 2
              and not (target.hp is not None and target.hp < config.MULTI_FINISH_HP)):
            mode = "DISENGAGE"
            goal = self.retreat_goal(obs, target, t)
            stand = self.hidden_from(me, target)
        elif (config.AVOID_PEOPLE and target is not None and target.kind == "mech"
              and t - self.hurt_by.get(target.id, -1e9) > config.AVOID_PROVOKED_S
              and hdist(target.pos, (x, y)) > config.AVOID_ENGAGE_M):
            mode = "KEEPAWAY"
            goal = self.retreat_goal(obs, target, t)
            stand = self.hidden_from(me, target)
            target = None  # don't provoke it
        elif target is not None:
            mode = "FIGHT"
            style_move = self.style_fight(me, target, t)
            pair = None if style_move is not None else self.fight_spot(obs, target, t)
            reloading = any(w and w["kind"] == "gun" and (w["reload"] > 0 or w["ammo"] == 0)
                            for w in me["weapons"])
            if style_move is not None:
                move = style_move
            elif pair is not None:
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
            goal = self.away_from_danger(obs, goal)
            if config.STYLE == "roof" and self.on_any_roof(me):
                goal, stand = (x, y), True
            if (config.STYLE == "assassin" and me["hp"] >= config.ASSASSIN_HP * me["max_hp"]
                    and t < config.ASSASSIN_UNTIL_S):
                mode, goal = "HUNT", self.hunt_point(obs, t)
            if config.LASER_ROAM and not self.has_laser(me) and not self.danger and t < config.LASER_ROAM_UNTIL_S:
                mode, goal = "SEARCH", self.roam_point(obs, t)
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
        roof = None
        if roof_goal is not None:
            roof = self.nav.roof_step(me["pos"], roof_goal, t, me["energy"], me["grounded"])
        if move is not None:
            mx, my, jump, boost = move[0], move[1], False, self.style_boost
        elif roof is not None:
            mx, my, jump, boost = roof
        else:
            reach = config.COVER_REACHED_M if precise else 2.0
            if tiny_zone and mode in ("ZONE", "HOLD"):
                reach = config.LATE_TINY_REACH_M
            far = hdist(goal, (x, y)) > reach and not stand
            mx, my, jump, boost = self.nav.next_step(me["pos"], goal, t, 1.0 if far else 0.0, precise=precise)
            if not far:
                mx = my = 0.0
            boost = boost or (mode == "ZONE" and far) or (mode in ("RECOVER", "AVOID", "DISENGAGE", "HEAL") and far and me["energy"] > 30)
        bearing = None
        if config.DEFENSIVE_EVASION:
            bearing = self.track.recent_shot_bearing(config.LATE_ANCHOR_SOUND_AGE_S)
        duel_evasion = (config.DUEL_EVASION and mech is not None
                        and mode in ("FIGHT", "RECOVER", "AVOID")
                        and len(self.known_attackers(t, x, y)) == 1)
        if config.DEFENSIVE_EVASION and mode in ("RECOVER", "AVOID"):
            mx, my = defense.escape_move(
                obs, (mx, my), boost, defensive_tracks, bearing, self.world, self.nav, self.cfg)
        elif mode in ("FIGHT", "DROP", "HOLD", "LOOT", "CUBES", "CRATE") or (mode != "ZONE" and (ffa or late)):
            dodge = self.weapons.dodge(obs, target, self.world)
            if dodge is not None:
                dx, dy, urgent = dodge
                if urgent or (move is not None and not hide):
                    step = self.dodge_step(obs, dx, dy)
                    if step is not None:
                        s = 1.0 if urgent else config.STRAFE_SPEED_FRACTION
                        mx, my = step[0] * s, step[1] * s
        if config.ZIGZAG_UNDER_FIRE:
            mx, my, jump, boost = self.zigzag(obs, target, t, mx, my, jump, boost)
        act.update(move=[mx, my], boost=boost, jump=jump)

        # torso
        act["aim"] = [self.idle_yaw(mx, my, me, sweep=config.SWEEP_FOR_WEAPONS and (not self.has_laser(me) if config.SWEEP_UNTIL_LASER else me["weapons"][1] is None)), 0.0]
        if target is None and threat is not None and mode in ("RECOVER", "AVOID", "HEAL"):
            act["aim"] = [math.atan2(threat.pos[1] - y, threat.pos[0] - x), 0.0]  # never show our back
        elif (config.DEFENSIVE_EVASION and mode == "HOLD" and target is None
              and threat is None and bearing is None and (mx or my)):
            phase = int(t / config.EVADE_SCAN_PERIOD_S) % 2
            act["aim"] = [math.atan2(my, mx) + math.radians(config.EVADE_SCAN_ANGLE_DEG) * (1 - 2 * phase), 0.0]
        fight = self.weapons.decide(me, target, self.world)
        if hide or (ffa and target is None):
            fight["fire"] = [False, False]
            gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
            if gun and gun["reload"] <= 0 and gun["ammo"] < gun["stats"]["mag"]:
                fight["reload"] = True
        act.update(fight)

        self.last_target = target.id if target is not None else None  # for tools/duel.py stats
        self.draw_debug(obs, act, mode, target, goal, hide)
        return act

    def draw_debug(self, obs, act, mode, target, goal, hide):
        """What the viewer's bot-debug overlay (B) shows: why we're doing what we do.
        Kept to ~10 items a tick so a full match stays far under the 8 MB debug cap."""
        me = obs["self"]
        x, y, z = me["pos"]
        mh = me["stats"]["muzzle_height"]
        muzzle = [x, y, z + mh]
        # where the torso actually points (yellow) vs where we want it (white)
        for (yaw, pitch), color, length in ((me["aim"], "#ffd040", 40), (act["aim"], "#ffffff", 25)):
            c = math.cos(pitch)
            mf.draw.line(muzzle, [x + c * math.cos(yaw) * length, y + c * math.sin(yaw) * length,
                                  z + mh + math.sin(pitch) * length], color)
        if target is not None:
            tx, ty, tz = target.predict(0)
            mf.draw.line(muzzle, [tx, ty, tz + target.height / 2], "#ff5040")
        # legs: goal and the next few path waypoints
        prev = [x, y, z + 1]
        for wx, wy in self.nav.path[:4]:
            p = [wx, wy, self.world.surface(wx, wy) + 1]
            mf.draw.line(prev, p, "#40c0ff")
            prev = p
        if mode != "HOLD" or hdist(goal, (x, y)) > 2:
            mf.draw.point([goal[0], goal[1], self.world.surface(goal[0], goal[1]) + 1], "#40ff80", 8)

        weapons = []
        for w in me["weapons"]:
            if not w:
                continue
            if w["kind"] == "gun":
                weapons.append(f"gun {w['ammo']}/{w['stats']['mag']}" + (" R" if w["reload"] > 0 else ""))
            elif w.get("charge"):
                weapons.append(f"{w['kind']} {w['charge']:.2f}s")
            else:
                weapons.append(w["kind"] + (" cd" if w["cooldown"] > 0 else ""))
        fire = act.get("fire", [False, False])
        tgt = "-"
        if target is not None:
            tgt = f"{target.kind[0]}{target.id} {hdist(target.pos, (x, y)):.0f}m"
            if target.hp is not None:
                tgt += f" {target.hp:.0f}hp"
        mf.draw.label(f"{mode} {tgt} | {me['hp']:.0f}/{me['max_hp']:.0f} c{me['cubes']}")
        mf.draw.text(" ".join(weapons) + f" | fire {'G' if fire[0] else '-'}{'2' if len(fire) > 1 and fire[1] else '-'}"
                     + (" HIDE" if hide else "") + (" REC" if self.recovering else ""))

    # ---- play styles (config.STYLE) ---------------------------------------------------------------------------
    def style_fight(self, me, target, t):
        """Unit move while fighting for STYLE kite/rush/roof, or None for the default (cover peek / strafe)."""
        self.style_boost = False
        style = config.STYLE
        if style not in ("kite", "rush", "roof"):
            return None
        x, y = me["pos"][0], me["pos"][1]
        dx, dy = target.pos[0] - x, target.pos[1] - y
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        sx, sy = self.strafe(me, target, t)
        if style == "roof" and self.on_any_roof(me):
            return 0.0, 0.0  # hold the high ground; the torso keeps shooting
        if style == "roof":
            return None
        if style == "kite":
            if d < config.KITE_MIN_M:
                mx, my = -ux + sx * 0.4, -uy + sy * 0.4
                self.style_boost = me["energy"] > config.KITE_BOOST_ENERGY
            elif d > config.KITE_MAX_M:
                mx, my = ux + sx * 0.5, uy + sy * 0.5
            else:
                return sx, sy
        else:  # rush
            if d > config.RUSH_RANGE_M:
                mx, my = ux + sx * 0.5, uy + sy * 0.5
                self.style_boost = me["energy"] > config.RUSH_BOOST_ENERGY
            else:
                return sx, sy
        if not self.nav.walkable_xy(x + mx * config.STRAFE_PROBE_M, y + my * config.STRAFE_PROBE_M):
            return sx, sy
        n = math.hypot(mx, my) or 1.0
        return mx / n, my / n

    def on_any_roof(self, me):
        return me["pos"][2] - self.world.ground(me["pos"][0], me["pos"][1]) > 3

    def style_roof_spot(self, obs, t):
        """Nearest climbable roof at least ROOF_STYLE_MIN_H tall, inside the next circle. Cached ROOF_STYLE_CACHE_S."""
        if self.roof_spot is not None and t - self.roof_spot[0] < config.ROOF_STYLE_CACHE_S:
            return self.roof_spot[1]
        me = obs["self"]
        x, y = me["pos"][0], me["pos"][1]
        z = obs["zone"]
        nav, w = self.nav, self.world
        best = None
        r = int(config.ROOF_STYLE_SEARCH_M / config.NAV_CELL)
        ci, cj = nav.to_cell(x, y)
        for j in range(max(0, cj - r), min(nav.cny, cj + r + 1), 2):
            for i in range(max(0, ci - r), min(nav.cnx, ci + r + 1), 2):
                c = j * nav.cnx + i
                if not nav.roof[c] or nav.Bl[c]:
                    continue
                px, py = nav.to_xy(i, j)
                if math.hypot(px - z["next_center"][0], py - z["next_center"][1]) > z["next_radius"] * 0.85:
                    continue
                h = nav.Hl[c] - w.ground(px, py)
                if h < config.ROOF_STYLE_MIN_H or h > config.ROOF_MAX_CLIMB_M:
                    continue
                d = math.hypot(px - x, py - y)
                if best is None or d < best[0]:
                    if nav.roof_reachable((px, py)):
                        best = (d, (px, py, nav.Hl[c]))
        self.roof_spot = (t, None if best is None else best[1])
        return self.roof_spot[1]

    def hunt_point(self, obs, t):
        """STYLE assassin: head for the latest fight or gunshot we heard; else roam the safe circle."""
        x, y = obs["self"]["pos"][0], obs["self"]["pos"][1]
        shot = self.track.recent_shot_bearing(config.ASSASSIN_SOUND_S)
        if shot is None:
            for snd in obs["sounds"]:
                if snd["kind"] in config.DANGER_SOUNDS:
                    shot = snd["bearing"]
                    break
        if shot is not None:
            px, py = x + 60 * math.cos(shot), y + 60 * math.sin(shot)
            return self.nav.nearest_walkable(px, py)
        return self.roam_point(obs, t)

    def zigzag(self, obs, target, t, mx, my, jump, boost):
        """Being shot at (hit recently, or a shot about to land): weave side to side across the attacker's line,
        flipping every ZIGZAG_S, keep some of the intended movement, and hop with a short jet burst now and then."""
        me = obs["self"]
        hurt = self.track.last_damage
        bearing = None
        if hurt is not None and t - hurt[0] <= config.ZIGZAG_HURT_S:
            bearing = hurt[1]
        else:
            incoming = self.weapons.dodge(obs, target, self.world)
            if incoming is not None:
                bearing = math.atan2(-incoming[0], incoming[1])  # dodge gives the sidestep; shots come across it
        if bearing is None:
            return mx, my, jump, boost
        if t - self.zig_t >= config.ZIGZAG_S:
            self.zig_sign, self.zig_t = -self.zig_sign, t
        px, py = -math.sin(bearing) * self.zig_sign, math.cos(bearing) * self.zig_sign
        x, y = me["pos"][0], me["pos"][1]
        if not self.nav.walkable_xy(x + px * config.STRAFE_PROBE_M, y + py * config.STRAFE_PROBE_M):
            self.zig_sign, self.zig_t = -self.zig_sign, t
            px, py = -px, -py
        zx, zy = px + mx * config.ZIGZAG_KEEP, py + my * config.ZIGZAG_KEEP
        n = math.hypot(zx, zy) or 1.0
        mx, my = zx / n, zy / n
        if me["grounded"] and t >= self.next_hop and me["energy"] >= config.ZIGZAG_HOP_ENERGY:
            jump = True
            self.next_hop = t + config.ZIGZAG_HOP_EVERY_S
            self.hop_until = t + config.ZIGZAG_JET_S
        if not me["grounded"] and t < self.hop_until:
            boost = True  # a little lift off the jump
        return mx, my, jump, boost

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

    def idle_yaw(self, mx, my, me, sweep=False):
        """Look toward a recent threat, then travel direction, then sweep.
        sweep=True keeps turning while walking too: pickups only show while seen."""
        bearing = self.track.threat_bearing()
        if bearing is not None:
            return bearing
        if (mx or my) and not sweep:
            self.scan_yaw = None
            return math.atan2(my, mx)
        if self.scan_yaw is None:
            self.scan_yaw = me["aim"][0]
        self.scan_yaw += config.SCAN_RAD_PER_TICK
        return (self.scan_yaw + math.pi) % (2 * math.pi) - math.pi
