"""Local mech simulator for duels: our real Brain vs scripted hunters on the real map.

Not the official server. It follows protocol.md closely enough to compare versions of our bot:
- 20 Hz sim, decisions every 2 ticks; ground/air accel, boost/jet energy, jump, gravity, step-up,
  walls from our height grid (sliding), torso slew at turn_rate/pitch_rate.
- Gun: projectiles at 252 m/s with gaussian spread, mag/reload, shots blocked by buildings.
- Laser: hold to charge, release to fire hitscan, damage by charge, half speed while charging.
- Rear hits x1.5, cube damage scaling, regen after 5 s without dealing/taking damage.
- Vision: LOS + near range (45 m any direction) or 200 m inside the 120 deg wedge, 5 s memory.
  Trees are NOT modelled (the real map's canopy blocks a lot of sight).
- Sounds: gun shots, steps, boosts, with bearing noise.
Zone, crates, drones, pickups and drops are left out: this is for fights.

Optional recording in mechreplay/1 (the play.joinbuilders.org viewer's format) to watch a duel.
"""
import copy
import gzip
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

import mechfight as mf  # noqa: E402
from nav import Nav  # noqa: E402
from world import World  # noqa: E402

STREAM = ROOT / "mechfight-kit" / "mechfight-kit" / "check" / "stream.jsonl.gz"
WEAPON_KINDS = ["gun", "mortar", "laser", "lightning"]


def base_hello():
    with gzip.open(STREAM, "rt") as f:
        hello = json.loads(f.readline())
    hello["map"]["dir"] = str(ROOT / "arena")
    return hello


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def aim_dir(yaw, pitch):
    c = math.cos(pitch)
    return c * math.cos(yaw), c * math.sin(yaw), math.sin(pitch)


class Mech:
    def __init__(self, mid, pos, cfg, weapons=("gun",), name="mech", cubes=0):
        m = cfg["mech"]
        self.id, self.name, self.cfg = mid, name, cfg
        self.stats = dict(m)
        self.pos = list(pos)
        self.vel = [0.0, 0.0, 0.0]
        self.aim = [0.0, 0.0]
        self.cmd_aim = [0.0, 0.0]
        self.cubes = cubes
        scale = 1 + cubes * cfg["cubes"]["size_per_cube"]
        self.radius, self.height = m["radius"] * scale, m["height"] * scale
        self.eye, self.muzzle = m["eye_height"] * scale, m["muzzle_height"] * scale
        self.stats.update(radius=self.radius, height=self.height, eye_height=self.eye, muzzle_height=self.muzzle)
        self.max_hp = m["hp"] * (1 + cfg["cubes"]["hp_per_cube"] * min(cubes, cfg["cubes"]["stat_cap"]))
        self.hp = self.max_hp
        self.energy, self.spent_t = m["energy"], -1e9
        self.grounded = True
        self.alive = True
        self.last_combat = -1e9
        self.action = {}
        self.events = []
        self.weapons = [None, None]
        for i, k in enumerate(weapons[:2]):
            st = dict(cfg["weapons"][k])
            w = {"kind": k, "cooldown": 0.0, "stats": st}
            if k == "gun":
                w.update(ammo=st["mag"], reload=0.0)
            if k == "laser":
                w["charge"] = 0.0
            self.weapons[i] = w
        self.release_pending = [False, False]
        self.step_t = 0.0
        # stats
        self.shots = self.hits = 0
        self.dmg_out = self.dmg_in = self.rear_in = 0.0
        self.death_t = None

    def eye_pos(self):
        return (self.pos[0], self.pos[1], self.pos[2] + self.eye)

    def center(self):
        return (self.pos[0], self.pos[1], self.pos[2] + self.height / 2)

    def charging(self):
        return any(w and w["kind"] == "laser" and w["charge"] > 0 for w in self.weapons)


class Sim:
    def __init__(self, cfg, world, seed=0, record=None):
        self.cfg, self.world = cfg, world
        self.rng = random.Random(seed)
        self.dt = 1.0 / cfg["match"]["tick_hz"]
        self.tick = 0
        self.mechs = {}
        self.projectiles = []  # dicts: id, owner, kind, pos, vel, left
        self.next_pid = 1
        self.pickups = {}  # id -> {"id", "kind", "pos"}
        self.next_pickup = 8000
        self.sounds = []  # (t, kind, pos, source_id)
        self.record = record
        self.frames = []

    @property
    def t(self):
        return self.tick * self.dt

    def add(self, mech):
        self.mechs[mech.id] = mech

    # ---- world helpers -----------------------------------------------------
    def surface_under(self, x, y):
        return self.world.surface(x, y)

    def wall_at(self, m, x, y, z):
        """True if standing at (x, y) with feet at z would put the cylinder into a wall."""
        w = self.world
        if not w.in_bounds(x, y):
            return True
        r = m.radius * 0.8
        for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)):
            px, py = x + dx, y + dy
            s = w.surface(px, py)
            if s > z + m.stats["step_up"]:
                return True
            i, j = w.cell(px, py)
            ob, ot = float(w.ob[j, i]), float(w.ot[j, i])
            if ob <= z + m.height and ot >= z + 0.5:
                return True
        return False

    # ---- one tick ---------------------------------------------------------
    def step(self):
        dt = self.dt
        for m in self.mechs.values():
            if m.alive:
                self._move(m, dt)
                self._weapons(m, dt)
        self._projectiles(dt)
        for m in self.mechs.values():
            if m.alive and self.t - m.last_combat >= m.stats["regen_delay"]:
                m.hp = min(m.max_hp, m.hp + m.stats["regen_per_s"] * dt)
        if self.record is not None and self.tick % 2 == 0:
            self._frame()
        self.tick += 1

    def _move(self, m, dt):
        a, st = m.action, m.stats
        mv = a.get("move", [0.0, 0.0])
        n = math.hypot(mv[0], mv[1])
        if n > 1:
            mv = [mv[0] / n, mv[1] / n]
            n = 1.0
        boosting = bool(a.get("boost")) and m.energy > 0
        speed = st["boost_speed"] if boosting and m.grounded and n > 0.05 else st["walk_speed"]
        if m.charging():
            speed *= st.get("charge_move_mult", 0.5)
        want = (mv[0] * speed, mv[1] * speed)
        acc = st["ground_accel"] if m.grounded else st["air_accel"]
        dvx, dvy = want[0] - m.vel[0], want[1] - m.vel[1]
        dv = math.hypot(dvx, dvy)
        lim = acc * dt
        if dv > lim:
            dvx, dvy = dvx / dv * lim, dvy / dv * lim
        m.vel[0] += dvx
        m.vel[1] += dvy
        spent = False
        if boosting and m.grounded and n > 0.05:
            m.energy -= st["boost_drain"] * dt
            spent = True
        if a.get("jump") and m.grounded:
            m.vel[2] = st["jump_speed"]
            m.grounded = False
        if boosting and not m.grounded:
            m.vel[2] = min(st["max_rise_speed"], m.vel[2] + st["jet_accel"] * dt)
            m.energy -= st["jet_drain"] * dt
            spent = True
        m.energy = max(0.0, m.energy)
        if spent:
            m.spent_t = self.t
        elif self.t - m.spent_t >= st["energy_regen_delay"]:
            m.energy = min(st["energy"], m.energy + st["energy_regen"] * dt)
        if not m.grounded:
            m.vel[2] -= st["gravity"] * dt
        # horizontal with sliding
        x, y, z = m.pos
        nx, ny = x + m.vel[0] * dt, y + m.vel[1] * dt
        if not self.wall_at(m, nx, ny, z):
            x, y = nx, ny
        elif not self.wall_at(m, nx, y, z):
            x, m.vel[1] = nx, 0.0
        elif not self.wall_at(m, x, ny, z):
            y, m.vel[0] = ny, 0.0
        else:
            m.vel[0] = m.vel[1] = 0.0
        # vertical
        z += m.vel[2] * dt
        g = self.surface_under(x, y)
        if z <= g or (m.grounded and g - z <= st["step_up"] and g >= z):
            z, m.vel[2], m.grounded = g, 0.0, True
        elif m.grounded and z - g > 0.3:
            m.grounded = False  # walked off an edge
        m.pos = [x, y, z]
        # steps make noise
        if m.grounded and math.hypot(m.vel[0], m.vel[1]) > self.cfg["sound"]["step_speed"]:
            if self.t - m.step_t >= self.cfg["sound"]["step_every"]:
                m.step_t = self.t
                self.sounds.append((self.t, "boost" if boosting else "step", tuple(m.pos), m.id))
        # torso slew
        cy, cp = a.get("aim", m.cmd_aim)
        m.cmd_aim = [cy, max(st["min_pitch"], min(st["max_pitch"], cp))]
        dy = wrap(m.cmd_aim[0] - m.aim[0])
        lim = st["turn_rate"] * dt
        m.aim[0] = wrap(m.aim[0] + max(-lim, min(lim, dy)))
        dp = m.cmd_aim[1] - m.aim[1]
        lim = st["pitch_rate"] * dt
        m.aim[1] += max(-lim, min(lim, dp))

    def spawn_pickups(self, rng, nav, n, roof_frac=0.25, kinds=("mortar", "laser", "lightning")):
        """Floor weapons over the whole map, like loot.floor_count (a quarter on roofs)."""
        ground = [c for c in range(len(nav.main)) if nav.main[c] and not nav.roof[c]]
        roofs = [c for c in range(len(nav.roof)) if nav.roof[c] and not nav.Bl[c]]
        for _ in range(n):
            pool = roofs if roofs and rng.random() < roof_frac else ground
            c = rng.choice(pool)
            x, y = nav.to_xy(c % nav.cnx, c // nav.cnx)
            self.add_pickup(rng.choice(kinds), (x, y, self.world.surface(x, y)))

    def add_pickup(self, kind, pos):
        pid = self.next_pickup
        self.next_pickup += 1
        self.pickups[pid] = {"id": pid, "kind": kind, "pos": [round(v, 2) for v in pos]}
        return pid

    def _take(self, m):
        a = m.action
        pid = a.get("take")
        if pid is None:
            if a.get("drop") in (0, 1) and m.weapons[a["drop"]]:
                self._drop_slot(m, a["drop"])
            return
        p = self.pickups.get(pid)
        reach = self.cfg["loot"]["pickup_radius"]
        if p is None:
            m.events.append({"type": "take_failed", "id": pid, "reason": "gone"})
            return
        if math.hypot(p["pos"][0] - m.pos[0], p["pos"][1] - m.pos[1]) > reach or abs(p["pos"][2] - m.pos[2]) > 4:
            m.events.append({"type": "take_failed", "id": pid, "reason": "range"})
            return
        if any(w and w["kind"] == p["kind"] for w in m.weapons):
            m.events.append({"type": "take_failed", "id": pid, "reason": "have"})
            return
        slot = next((i for i, w in enumerate(m.weapons) if w is None), None)
        if slot is None:
            slot = a.get("drop")
            if slot not in (0, 1):
                m.events.append({"type": "take_failed", "id": pid, "reason": "full"})
                return
            self._drop_slot(m, slot)
        del self.pickups[pid]
        st = dict(self.cfg["weapons"][p["kind"]])
        w = {"kind": p["kind"], "cooldown": max(self.cfg["loot"]["equip_s"], st["cooldown"]), "stats": st}
        if p["kind"] == "gun":
            w.update(ammo=st["mag"], reload=0.0)
        if p["kind"] == "laser":
            w["charge"] = 0.0
        m.weapons[slot] = w
        m.events.append({"type": "took", "id": pid, "kind": p["kind"], "slot": slot})
        self._ev({"e": "weapon", "op": "take", "id": pid, "kind": p["kind"], "by": m.id, "slot": slot})

    def _drop_slot(self, m, slot):
        w = m.weapons[slot]
        if w is None or (w["kind"] == "laser" and w["charge"] > 0):
            return
        pid = self.add_pickup(w["kind"], m.pos)
        m.weapons[slot] = None
        m.events.append({"type": "dropped", "id": pid, "kind": w["kind"], "slot": slot})

    def _lightning(self, m, w):
        st = w["stats"]
        if m.energy < st["energy"]:
            return
        m.energy -= st["energy"]
        m.spent_t = self.t
        w["cooldown"] = st["cooldown"]
        m.shots += 1
        self.sounds.append((self.t, "lightning", tuple(m.pos), m.id))
        o = (m.pos[0], m.pos[1], m.pos[2] + m.muzzle)
        cone = math.radians(st["cone_deg"]) / 2
        best = None
        for t in self.mechs.values():
            if t is m or not t.alive:
                continue
            d = math.hypot(t.pos[0] - o[0], t.pos[1] - o[1])
            yaw = math.atan2(t.pos[1] - o[1], t.pos[0] - o[0])
            if d <= st["range"] and abs(wrap(yaw - m.aim[0])) <= cone and self.world.los(o, t.center()):
                if best is None or d < best[0]:
                    best = (d, t)
        if best is None:
            return
        hit = best[1]
        self._damage(hit, m, st["damage"] * self._dmg_mult(m), "lightning", (o[0] - hit.pos[0], o[1] - hit.pos[1]))
        self._ev({"e": "zap", "id": m.id, "path": [list(o), list(hit.center())], "hits": [hit.id]})

    def _mortar(self, m, w):
        st = w["stats"]
        d = aim_dir(*m.aim)
        o = (m.pos[0], m.pos[1], m.pos[2] + m.height + 0.5)
        out = m.radius + 0.5
        start = (o[0] + d[0] * out, o[1] + d[1] * out, o[2] + d[2] * out)
        self.projectiles.append({"id": self.next_pid, "owner": m.id, "kind": "mortar", "pos": list(start),
                                 "vel": [d[0] * st["speed"], d[1] * st["speed"], d[2] * st["speed"]],
                                 "left": 1e9, "ttl": st["ttl"], "dmg": st["damage"] * self._dmg_mult(m),
                                 "splash": st["splash"] * self._dmg_mult(m), "r": st["splash_radius"],
                                 "edge": st.get("splash_edge", 0.3), "g": st["gravity"]})
        self.next_pid += 1
        w["cooldown"] = st["cooldown"]
        m.shots += 1
        self.sounds.append((self.t, "mortar", tuple(m.pos), m.id))
        self._ev({"e": "fire", "id": m.id, "w": "mortar"})

    def _explode(self, p, at, direct=None):
        owner = self.mechs.get(p["owner"])
        if direct is not None:
            self._damage(direct, owner, p["dmg"], "mortar", (at[0] - direct.pos[0] + 1e-6, at[1] - direct.pos[1]))
        for t in self.mechs.values():
            if not t.alive or t is direct:
                continue
            dist = math.dist(at, t.center())
            if dist > p["r"] + t.radius or not self.world.los(at, t.center()):
                continue
            f = max(p["edge"], 1 - (1 - p["edge"]) * max(0.0, dist - t.radius) / p["r"])
            amt = p["splash"] * f * (self.cfg["mech"]["self_damage_mult"] if t is owner else 1.0)
            self._damage(t, owner if t is not owner else None, amt, "mortar",
                         (at[0] - t.pos[0] + 1e-6, at[1] - t.pos[1]))
        self.sounds.append((self.t, "explosion", tuple(at), p["owner"]))
        self._ev({"e": "boom", "p": p["id"], "at": [round(v, 2) for v in at], "r": p["r"]})

    def _weapons(self, m, dt):
        if m.action.get("take") is not None or m.action.get("drop") is not None:
            self._take(m)
            m.action = dict(m.action, take=None, drop=None)
        fire = m.action.get("fire", [False, False])
        for i, w in enumerate(m.weapons):
            if not w:
                continue
            w["cooldown"] = max(0.0, w["cooldown"] - dt)
            st = w["stats"]
            held = bool(fire[i]) if i < len(fire) else False
            if w["kind"] == "gun":
                if w["reload"] > 0:
                    w["reload"] = max(0.0, w["reload"] - dt)
                    if w["reload"] == 0:
                        w["ammo"] = st["mag"]
                    continue
                if m.action.get("reload") and w["ammo"] < st["mag"]:
                    w["reload"] = st["reload"]
                    continue
                if held and w["cooldown"] <= 0 and w["ammo"] > 0:
                    self._shoot_gun(m, w)
                    w["cooldown"] = st["cooldown"]
                    w["ammo"] -= 1
                    if w["ammo"] == 0:
                        w["reload"] = st["reload"]
            elif w["kind"] == "lightning":
                if held and w["cooldown"] <= 0:
                    self._lightning(m, w)
            elif w["kind"] == "mortar":
                if held and w["cooldown"] <= 0:
                    self._mortar(m, w)
            elif w["kind"] == "laser":
                if w["cooldown"] > 0 and w["charge"] == 0:
                    continue
                if held or (m.release_pending[i] and w["charge"] < st["min_charge"]):
                    if w["charge"] == 0:
                        self.sounds.append((self.t, "laser_charge", tuple(m.pos), m.id))
                    w["charge"] += dt
                    if not held:
                        m.release_pending[i] = True
                    if w["charge"] >= st["charge"] + st["hold_s"] or (m.release_pending[i] and w["charge"] >= st["min_charge"]):
                        self._fire_laser(m, w)
                        m.release_pending[i] = False
                elif w["charge"] > 0:
                    if w["charge"] >= st["min_charge"]:
                        self._fire_laser(m, w)
                    else:
                        m.release_pending[i] = True

    def _dmg_mult(self, m):
        c = self.cfg["cubes"]
        return 1 + c["damage_per_cube"] * min(m.cubes, c["stat_cap"])

    def _shoot_gun(self, m, w):
        st = w["stats"]
        s = math.radians(st["spread_deg"])
        yaw = m.aim[0] + self.rng.gauss(0, s)
        pitch = m.aim[1] + self.rng.gauss(0, s)
        d = aim_dir(yaw, pitch)
        out = m.radius + 0.5
        o = (m.pos[0], m.pos[1], m.pos[2] + m.muzzle)
        start = (o[0] + d[0] * out, o[1] + d[1] * out, o[2] + d[2] * out)
        if self.world.ray_hit(o, start) is not None:
            start = o
        self.projectiles.append({"id": self.next_pid, "owner": m.id, "kind": "gun", "pos": list(start),
                                 "vel": [d[0] * st["speed"], d[1] * st["speed"], d[2] * st["speed"]],
                                 "left": st["range"], "dmg": st["damage"] * self._dmg_mult(m)})
        self.next_pid += 1
        m.shots += 1
        self.sounds.append((self.t, "gun", tuple(m.pos), m.id))
        self._ev({"e": "fire", "id": m.id, "w": "gun"})

    def _fire_laser(self, m, w):
        st = w["stats"]
        frac = st["min_frac"] + (1 - st["min_frac"]) * min(1.0, w["charge"] / st["charge"])
        dmg = st["damage"] * frac * self._dmg_mult(m)
        d = aim_dir(*m.aim)
        o = (m.pos[0], m.pos[1], m.pos[2] + m.muzzle)
        end = (o[0] + d[0] * st["range"], o[1] + d[1] * st["range"], o[2] + d[2] * st["range"])
        wall = self.world.ray_hit(o, end)
        reach = st["range"] * (wall if wall is not None else 1.0)
        best = None
        for t in self.mechs.values():
            if t is m or not t.alive:
                continue
            along = self._ray_cyl(o, d, reach, t)
            if along is not None and (best is None or along < best[0]):
                best = (along, t)
        m.shots += 1
        self.sounds.append((self.t, "laser", tuple(m.pos), m.id))
        self._ev({"e": "charge", "id": m.id, "dur": round(w["charge"], 2)})
        hit_to = o if best is None else None
        if best is not None:
            if any(x and x["kind"] == "mortar" for x in best[1].weapons):
                dmg *= 1 + st["cookoff"]
            self._damage(best[1], m, dmg, "laser", (-d[0], -d[1]))
            hit_to = (o[0] + d[0] * best[0], o[1] + d[1] * best[0], o[2] + d[2] * best[0])
        else:
            hit_to = (o[0] + d[0] * reach, o[1] + d[1] * reach, o[2] + d[2] * reach)
        self._ev({"e": "laser", "id": m.id, "from": [round(v, 2) for v in o], "to": [round(v, 2) for v in hit_to],
                  "hits": [best[1].id] if best else []})
        w["charge"] = 0.0
        w["cooldown"] = st["cooldown"]

    @staticmethod
    def _ray_cyl(o, d, reach, t):
        """Distance along ray o + s*d (s <= reach) where it first enters t's cylinder, or None."""
        step = 1.0
        s = 0.0
        tx, ty, tz = t.pos
        r2 = t.radius * t.radius
        while s <= reach:
            px, py, pz = o[0] + d[0] * s, o[1] + d[1] * s, o[2] + d[2] * s
            if (px - tx) ** 2 + (py - ty) ** 2 <= r2 and tz <= pz <= tz + t.height:
                return s
            s += step
        return None

    def _projectiles(self, dt):
        keep = []
        for p in self.projectiles:
            if p["kind"] == "mortar":
                p["vel"][2] -= p["g"] * dt
                p["ttl"] -= dt
            a = tuple(p["pos"])
            b = (a[0] + p["vel"][0] * dt, a[1] + p["vel"][1] * dt, a[2] + p["vel"][2] * dt)
            if p["kind"] == "mortar" and (p["ttl"] <= 0 or not self.world.in_bounds(b[0], b[1])):
                continue
            seg = math.dist(a, b)
            wall = self.world.ray_hit(a, b)
            lim = 1.0 if wall is None else wall
            hit = None
            n = 6
            for k in range(1, n + 1):
                f = lim * k / n
                q = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
                for t in self.mechs.values():
                    if t.id == p["owner"] or not t.alive:
                        continue
                    if (q[0] - t.pos[0]) ** 2 + (q[1] - t.pos[1]) ** 2 <= t.radius ** 2 and t.pos[2] <= q[2] <= t.pos[2] + t.height:
                        hit = t
                        break
                if hit:
                    break
            if hit is not None:
                owner = self.mechs.get(p["owner"])
                v = p["vel"]
                if p["kind"] == "mortar":
                    self._explode(p, q, direct=hit)
                else:
                    self._damage(hit, owner, p["dmg"], "gun", (-v[0], -v[1]))
                continue
            p["left"] -= seg
            if p["kind"] == "mortar" and (wall is not None or b[2] < self.world.surface(b[0], b[1])):
                f = 1.0 if wall is None else wall
                self._explode(p, (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f))
                continue
            if wall is not None or p["left"] <= 0:
                continue
            p["pos"] = list(b)
            keep.append(p)
        self.projectiles = keep

    def _damage(self, t, src, amt, weapon, toward_src):
        """toward_src: horizontal direction from target back to where the shot came from."""
        bearing = math.atan2(toward_src[1], toward_src[0])
        rear = abs(wrap(bearing - t.aim[0])) > math.radians(t.stats["front_arc_deg"]) / 2
        if rear:
            amt *= t.stats["rear_mult"]
            t.rear_in += amt
        amt = min(amt, t.hp)
        t.hp -= amt
        t.dmg_in += amt
        t.last_combat = self.t
        t.events.append({"type": "damaged", "amount": round(amt), "weapon": weapon, "bearing": bearing,
                         "by": src.id if src else None, "rear": rear})
        if src:
            src.hits += 1
            src.dmg_out += amt
            src.last_combat = self.t
            src.events.append({"type": "hit", "target": t.id, "amount": round(amt), "weapon": weapon, "rear": rear})
        self._ev({"e": "hit", "src": src.id if src else None, "dst": t.id, "amt": round(amt), "w": weapon})
        if t.hp <= 0 and t.alive:
            t.alive = False
            t.death_t = self.t
            self.sounds.append((self.t, "death", tuple(t.pos), t.id))
            self._ev({"e": "death", "id": t.id, "by": src.id if src else None})
            if src:
                src.events.append({"type": "kill", "target": t.id})

    # ---- observations ------------------------------------------------------
    def sees(self, a, b):
        d = math.dist(a.pos, b.pos)
        v = self.cfg["vision"]
        if d > v["range"]:
            return False
        if d > v["near_range"]:
            yaw = math.atan2(b.pos[1] - a.pos[1], b.pos[0] - a.pos[0])
            if abs(wrap(yaw - a.aim[0])) > math.radians(v["fov_deg"]) / 2:
                return False
        eye = a.eye_pos()
        return self.world.los(eye, b.center()) or self.world.los(eye, (b.pos[0], b.pos[1], b.pos[2] + b.height))

    def sees_point(self, a, p):
        d = math.dist(a.pos, p)
        v = self.cfg["vision"]
        if d > v["range"]:
            return False
        if d > v["near_range"]:
            yaw = math.atan2(p[1] - a.pos[1], p[0] - a.pos[0])
            if abs(wrap(yaw - a.aim[0])) > math.radians(v["fov_deg"]) / 2:
                return False
        return self.world.los(a.eye_pos(), (p[0], p[1], p[2] + 0.5))

    def observe(self, m, memory, last_obs_t):
        """Build the protocol obs for mech m. memory: dict id -> last seen t (updated)."""
        mechs = []
        for o in self.mechs.values():
            if o is m or not o.alive:
                continue
            if self.sees(m, o):
                memory[o.id] = self.t
            if self.t - memory.get(o.id, -1e9) <= self.cfg["vision"]["memory_s"]:
                mechs.append({"id": o.id, "kind": "mech", "pos": [round(v, 2) for v in o.pos],
                              "vel": [round(v, 2) for v in o.vel], "aim": [round(o.aim[0], 3), round(o.aim[1], 3)],
                              "hp": round(o.hp), "max_hp": round(o.max_hp), "cubes": o.cubes,
                              "weapons": [w["kind"] for w in o.weapons if w], "charging": o.charging()})
        projectiles = []
        eye = m.eye_pos()
        for p in self.projectiles:
            if p["owner"] == m.id or math.dist(eye, p["pos"]) > 200:
                continue
            if self.world.los(eye, p["pos"]):
                projectiles.append({"id": p["id"], "kind": p["kind"], "pos": [round(v, 2) for v in p["pos"]],
                                    "vel": [round(v, 2) for v in p["vel"]]})
        pickups = [dict(p) for p in self.pickups.values() if self.sees_point(m, p["pos"])]
        sounds = []
        sc = self.cfg["sound"]
        noise = math.radians(sc["bearing_noise_deg"])
        for (st, kind, pos, src) in self.sounds:
            if src == m.id or st <= last_obs_t:
                continue
            d = math.dist(pos, m.pos)
            if d > sc["range"].get(kind, 0):
                continue
            bearing = wrap(math.atan2(pos[1] - m.pos[1], pos[0] - m.pos[0]) + self.rng.gauss(0, noise))
            sounds.append({"kind": kind, "bearing": round(bearing, 3),
                           "dist": "near" if d < sc["near"] else "mid" if d < sc["mid"] else "far",
                           "age": round(self.t - st, 2)})
        events, m.events = m.events, []
        weapons = [copy.deepcopy(w) for w in m.weapons]
        cx = sum(o.pos[0] for o in self.mechs.values()) / len(self.mechs)
        cy = sum(o.pos[1] for o in self.mechs.values()) / len(self.mechs)
        return {
            "type": "obs", "tick": self.tick, "t": round(self.t, 2),
            # a duel stands in for part of a 16-mech match: report the rest as still alive
            "alive": self.cfg["match"]["mechs"] - sum(1 for o in self.mechs.values() if not o.alive),
            "self": {"id": m.id, "pos": [round(v, 2) for v in m.pos], "vel": [round(v, 2) for v in m.vel],
                     "aim": [round(m.aim[0], 3), round(m.aim[1], 3)], "hp": round(m.hp, 1), "max_hp": round(m.max_hp),
                     "energy": round(m.energy, 1), "max_energy": m.stats["energy"], "grounded": m.grounded,
                     "cubes": m.cubes, "upgrades": [], "weapons": weapons, "stats": dict(m.stats), "in_zone": True},
            "mechs": mechs, "projectiles": projectiles, "crates": [], "cubes": [], "pickups": pickups,
            "sounds": sounds, "beams": [], "events": events, "drops": [],
            "zone": {"center": [cx, cy], "radius": 560, "next_center": [cx, cy], "next_radius": 380,
                     "shrink_start": 1e4, "shrink_end": 1e4 + 50, "dps": 20},
            "offer": None,
        }

    def prune_sounds(self):
        self.sounds = [s for s in self.sounds if self.t - s[0] < 1.0]

    # ---- recording (mechreplay/1) -------------------------------------------
    def _ev(self, e):
        if self.record is not None:
            e = dict(e)
            e["t"] = self.tick
            self._evbuf.append(e)

    def start_record(self):
        self._evbuf = []
        self.frames = []

    def _frame(self):
        m_rows = []
        for m in self.mechs.values():
            if not m.alive:
                continue
            flags = (1 if m.grounded else 0) | (2 if m.action.get("boost") else 0) | (4 if m.charging() else 0)
            slots = [WEAPON_KINDS.index(w["kind"]) if w else -1 for w in m.weapons]
            m_rows.append([m.id, round(m.pos[0], 2), round(m.pos[1], 2), round(m.pos[2], 2), round(m.aim[0], 3),
                           round(m.aim[1], 3), round(m.hp), round(m.energy), flags, m.cubes, round(m.max_hp), *slots])
        p_rows = [[p["id"], 0, round(p["pos"][0], 2), round(p["pos"][1], 2), round(p["pos"][2], 2)] for p in self.projectiles]
        f = {"t": self.tick, "m": m_rows, "n": [], "p": p_rows, "z": [0, 0, 560]}
        if self._evbuf:
            f["ev"], self._evbuf = self._evbuf, []
        self.frames.append(f)

    def write_record(self, path, sample_header):
        h = copy.deepcopy(sample_header)
        h.update(seed=0, npcs=[], crates=[], pickups=list(self.pickups.values()), drops=[],
                 zone=[{"center": [0, 0], "radius": 560, "shrink_start": 0, "shrink_end": 0}])
        h["bots"] = [m.name for m in self.mechs.values()]
        h["mechs"] = [{"id": m.id, "name": m.name, "weapons": [w["kind"] for w in m.weapons if w],
                       "slots": [w["kind"] if w else None for w in m.weapons], "spawn": [round(v, 2) for v in m.pos]}
                      for m in self.mechs.values()]
        result = {"type": "result", "ticks": self.tick, "mechs": [
            {"id": m.id, "name": m.name, "place": 1 if m.alive else 2, "kills": 0, "damage_dealt": round(m.dmg_out),
             "damage_taken": round(m.dmg_in), "death_t": m.death_t} for m in self.mechs.values()]}
        with gzip.open(path, "wt") as f:
            f.write(json.dumps(h) + "\n")
            for fr in self.frames:
                f.write(json.dumps(fr, separators=(",", ":")) + "\n")
            f.write(json.dumps(result) + "\n")


# ---- shared map/nav so each duel doesn't rebuild them -----------------------
_WORLD = None
_NAV = None


def shared_world():
    global _WORLD, _NAV
    if _WORLD is None:
        _WORLD = World(str(ROOT / "arena"))
        _NAV = Nav(_WORLD, base_hello()["config"]["mech"])
    return _WORLD, _NAV


def fresh_nav():
    _, base = shared_world()
    n = copy.copy(base)
    n.path, n.goal, n.search, n.last_plan_t = [], None, None, -1e9
    n.hist, n.unstick_until, n.unstick_dir = [], -1.0, (0.0, 0.0)
    return n


def patch_brain_for_speed():
    """Make Brain reuse the shared World/Nav instead of rebuilding them per duel (0.5 s each)."""
    import brain
    world, _ = shared_world()
    brain.World.load = classmethod(lambda cls, d: world)
    brain.Nav = lambda w, cfg=None: fresh_nav()
    brain.gc.freeze = lambda: None
    brain.gc.collect = lambda: None
    mf.draw.caps = base_hello()["config"]["debug"]
