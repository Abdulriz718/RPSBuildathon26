"""Run many duels: our real bot (bot/main.py Bot) vs scripted hunters in tools/sim.py.

  python tools/duel.py --n 100 --skill hard
  python tools/duel.py --n 100 --skill hard --set COVER_LOW_HP=0.35          # try a config change
  python tools/duel.py --n 100 --hunters 2 --skill medium                    # two hunters at once
  python tools/duel.py --n 1 --seed 5 --record replays/duel.jsonl.gz          # save one for the viewer

Hunters know where we are (the house squad shares vision), walk to us on A*, then strafe at range and
shoot with lead, aim noise and reaction delay set by --skill.
"""
import argparse
import math
import random
import statistics
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sim as S  # noqa: E402

SKILLS = {
    "easy": dict(noise_deg=2.2, react_s=0.5, lead=False, engage_m=70, hold_m=45, flip=(1.5, 3.0), boost_p=0.0),
    "medium": dict(noise_deg=1.4, react_s=0.3, lead=True, engage_m=85, hold_m=55, flip=(1.0, 2.5), boost_p=0.1),
    "hard": dict(noise_deg=0.9, react_s=0.2, lead=True, engage_m=95, hold_m=60, flip=(0.8, 2.0), boost_p=0.2),
    "expert": dict(noise_deg=0.5, react_s=0.1, lead=True, engage_m=110, hold_m=65, flip=(0.6, 1.6), boost_p=0.3),
}


class Hunter:
    def __init__(self, sim, mech, skill, rng):
        self.sim, self.m, self.k, self.rng = sim, mech, SKILLS[skill], rng
        self.nav = S.fresh_nav()
        self.sign = 1
        self.flip_at = 0.0
        self.vel_hist = []
        self.noise = (0.0, 0.0)
        self.boost = False
        self.loot = True

    def loot_goal(self, target_d, los):
        """House bots grab a 2nd weapon fast. Hunters know all pickups (the squad shares vision)."""
        if not self.loot or self.m.weapons[1] is not None or (los and target_d < 90):
            return None
        best = None
        for p in self.sim.pickups.values():
            if p["pos"][2] - self.sim.world.ground(p["pos"][0], p["pos"][1]) > 3:
                continue
            d = math.hypot(p["pos"][0] - self.m.pos[0], p["pos"][1] - self.m.pos[1])
            if d < 80 and (best is None or d < best[0]):
                best = (d, p)
        return best[1] if best else None

    def act(self, target):
        sim, m, k = self.sim, self.m, self.k
        t = sim.t
        world = sim.world
        self.vel_hist.append((t, tuple(target.vel)))
        while self.vel_hist and t - self.vel_hist[0][0] > k["react_s"] + 0.2:
            self.vel_hist.pop(0)
        vel = next((v for (ts, v) in self.vel_hist if t - ts <= k["react_s"]), target.vel)
        dx, dy = target.pos[0] - m.pos[0], target.pos[1] - m.pos[1]
        d = math.hypot(dx, dy) or 1.0
        center = target.center()
        muzzle = (m.pos[0], m.pos[1], m.pos[2] + m.muzzle)
        los = world.los(m.eye_pos(), center) or world.los(m.eye_pos(), (target.pos[0], target.pos[1], target.pos[2] + target.height))
        act = {}
        lp = self.loot_goal(d, los)
        if lp is not None:
            mx, my, jump, boost = self.nav.next_step(m.pos, lp["pos"][:2], t, 1.0)
            act.update(move=[mx, my], jump=jump, boost=boost)
            if math.hypot(lp["pos"][0] - m.pos[0], lp["pos"][1] - m.pos[1]) < 3.5:
                act["take"] = lp["id"]
        elif not los or d > k["engage_m"]:
            mx, my, jump, boost = self.nav.next_step(m.pos, target.pos[:2], t, 1.0)
            act.update(move=[mx, my], jump=jump, boost=boost or d > 150)
        else:
            if t >= self.flip_at:
                self.sign = -self.sign
                self.flip_at = t + self.rng.uniform(*k["flip"])
                self.boost = self.rng.random() < k["boost_p"]
            ux, uy = dx / d, dy / d
            radial = max(-0.6, min(0.6, (d - k["hold_m"]) / 30))
            mx, my = -uy * self.sign + ux * radial, ux * self.sign + uy * radial
            n = math.hypot(mx, my) or 1.0
            mx, my = mx / n, my / n
            if not self.nav.walkable_xy(m.pos[0] + mx * 4, m.pos[1] + my * 4):
                self.sign = -self.sign
                mx, my = -mx, -my
            act.update(move=[mx, my], boost=self.boost and m.energy > 30)
        # aim
        if int(t * 10) % 3 == 0:
            s = math.radians(k["noise_deg"])
            self.noise = (self.rng.gauss(0, s), self.rng.gauss(0, s))
        aim_pt = center
        if k["lead"]:
            flight = math.dist(muzzle, center) / 252.0
            aim_pt = (center[0] + vel[0] * flight, center[1] + vel[1] * flight, center[2] + vel[2] * flight)
        yaw = math.atan2(aim_pt[1] - muzzle[1], aim_pt[0] - muzzle[0]) + self.noise[0]
        pitch = math.atan2(aim_pt[2] - muzzle[2], math.hypot(aim_pt[0] - muzzle[0], aim_pt[1] - muzzle[1])) + self.noise[1]
        act["aim"] = [yaw, pitch]
        err = math.hypot(S.wrap(yaw - m.aim[0]), pitch - m.aim[1])
        tol = math.atan2(target.radius * 1.2, d)
        act["fire"] = [bool(los and d < 225 and err < tol), False]
        w1 = m.weapons[1]
        if w1 and w1["kind"] == "laser":
            act["fire"][1] = bool(los and d < 270 and (w1["charge"] < w1["stats"]["charge"] or err > tol))
        elif w1 and w1["kind"] == "lightning":
            act["fire"][1] = bool(los and d < w1["stats"]["range"] and abs(S.wrap(yaw - m.aim[0])) < 0.25)
        elif w1 and w1["kind"] == "mortar" and 25 < d < 200:
            st = w1["stats"]
            x = min(1.0, st["gravity"] * d / st["speed"] ** 2)
            act["aim"] = [yaw, 0.5 * math.asin(x)]
            act["fire"] = [False, abs(S.wrap(yaw - m.aim[0])) < 0.05 and abs(act["aim"][1] - m.aim[1]) < 0.05]
        return act


def spawn_points(rng, nav, world, n, min_sep=130, max_sep=220, circle=None):
    cells = [c for c in range(len(nav.main)) if nav.main[c] and not nav.roof[c]]
    if circle:
        center, radius = circle
        pts = []
        for c in rng.sample(cells, len(cells)):
            p = nav.to_xy(c % nav.cnx, c // nav.cnx)
            if math.dist(p, center) <= radius and all(math.dist(p, q) >= min_sep for q in pts):
                pts.append(p)
                if len(pts) == n:
                    return [(x, y, world.surface(x, y)) for x, y in pts]
        raise ValueError("insufficient walkable spawns inside the initial zone")
    while True:
        c = rng.choice(cells)
        a = nav.to_xy(c % nav.cnx, c // nav.cnx)
        pts = [a]
        tries = 0
        while len(pts) < n and tries < 500:
            tries += 1
            c = rng.choice(cells)
            p = nav.to_xy(c % nav.cnx, c // nav.cnx)
            if min_sep <= math.dist(p, a) <= max_sep and all(math.dist(p, q) > 40 for q in pts[1:]):
                pts.append(p)
        if len(pts) == n:
            return [(x, y, world.surface(x, y)) for x, y in pts]


def run_duel(args, evaluation=False):
    seed, skill, n_hunters, our_w, hunter_w, max_t, record, overrides, n_pickups, hunter_loot = args
    # Worker processes run many jobs: start each from the defaults in bot/config.py, or one variant's
    # overrides leak into the next (this silently mixed MODE='ffa' into later variants once).
    import importlib
    import config
    importlib.reload(config)
    S.patch_brain_for_speed()
    for key, val in overrides.items():
        setattr(config, key, val)
    from main import Bot
    world, nav = S.shared_world()
    rng = random.Random(seed)
    hello = S.base_hello()
    hello["slot"] = 0
    cfg = hello["config"]
    arena = evaluation and n_hunters == 15
    circle = (cfg["zone"]["start_center"], cfg["zone"]["start_radius"]) if arena else None
    pts = spawn_points(rng, nav, world, 1 + n_hunters, circle=circle)
    sim = S.Sim(cfg, world, seed=seed, record=record)
    if arena:
        sim.zone = S.Zone(cfg["zone"], random.Random(seed * 13 + 5))
    directions, avoided = Counter(), Counter()
    if record:
        sim.start_record()
    ours = S.Mech(0, pts[0], cfg, our_w, "ours")
    ours.aim = [rng.uniform(-math.pi, math.pi), 0.0]
    sim.add(ours)
    sim.spawn_pickups(random.Random(seed * 7 + 1), nav, n_pickups)
    hunters = []
    for i in range(n_hunters):
        kit = BENCH_LOADOUTS[i % len(BENCH_LOADOUTS)] if arena else hunter_w
        hm = S.Mech(i + 1, pts[i + 1], cfg, kit, skill)
        sim.add(hm)
        h = Hunter(sim, hm, skill, random.Random(seed * 31 + i))
        h.loot = hunter_loot
        hunters.append(h)
    bot = Bot(hello)
    memory, last_obs_t = {}, -1.0
    modes = Counter()
    weapon_t = None
    last_tid, switches, multi_ticks, split_ticks, both_seen = None, 0, 0, 0, 0
    while sim.t < max_t and sum(m.alive for m in sim.mechs.values()) > 1 and (arena or ours.alive):
        if weapon_t is None and ours.weapons[1] is not None:
            weapon_t = sim.t
        if sim.tick % 2 == 0:
            obs = sim.observe(ours, memory, last_obs_t)
            if sim.zone:
                cx, cy, radius = sim.zone.circle(sim.t)
                obs["zone"].update(center=[cx, cy], radius=radius)
            last_obs_t = sim.t
            S.mf.draw.clear()
            a = bot.act(obs) if ours.alive else {}
            a.pop("debug", None)
            ours.action = a
            modes[bot.brain.mode] += 1
            tid = getattr(bot.brain, "last_target", None)
            if tid is not None and tid < 100:
                if last_tid is not None and tid != last_tid:
                    switches += 1
                last_tid = tid
            live = [h.m for h in hunters if h.m.alive]
            if len(live) >= 2:
                multi_ticks += 1
                a, b = live[0], live[1]
                ya = math.atan2(a.pos[1] - ours.pos[1], a.pos[0] - ours.pos[0])
                yb = math.atan2(b.pos[1] - ours.pos[1], b.pos[0] - ours.pos[0])
                if abs(S.wrap(ya - yb)) > math.pi / 2:
                    split_ticks += 1
                if sim.sees(ours, a) and sim.sees(ours, b):
                    both_seen += 1
            for h in hunters:
                if h.m.alive:
                    target = min((m for m in sim.mechs.values() if m.alive and m is not h.m),
                                 key=lambda m: math.dist(m.pos, h.m.pos)) if arena else ours
                    h.m.action = h.act(target)
                    if arena and math.dist(h.m.pos[:2], obs["zone"]["center"]) > obs["zone"]["radius"]:
                        mx, my, jump, boost = h.nav.next_step(h.m.pos, obs["zone"]["next_center"], sim.t, 1)
                        h.m.action.update(move=[mx, my], jump=jump, boost=True)
            sim.prune_sounds()
        else:
            for m in sim.mechs.values():
                m.action = dict(m.action, jump=False, reload=False, take=None, drop=None)
        if evaluation and not arena:
            pressure = bool(sim.projectiles) and any(p["owner"] != 0 for p in sim.projectiles)
            pressure |= any(h.m.alive and any(h.m.action.get("fire", ())) for h in hunters)
            damage = ours.dmg_in
            mx, my = ours.action.get("move", (0, 0))
            direction = "still"
            if math.hypot(mx, my) > 0.05:
                octant = round(S.wrap(math.atan2(my, mx) - ours.aim[0]) / (math.pi / 4)) % 8
                direction = ("front","front-left","left","back-left","back","back-right","right","front-right")[octant]
        sim.step()
        if evaluation and not arena and pressure:
            directions[direction] += 1
            avoided[direction] += ours.dmg_in == damage
    if record:
        sim.write_record(record, _sample_header())
    hs = [h.m for h in hunters]
    return {
        "points": sum((not h.alive and (ours.alive or h.death_t <= ours.death_t))
                      or (ours.alive and h.alive and ours.hp >= h.hp) for h in hs),
        "zone_survived": not ours.zone_death, "jet_gain": ours.jet_gain, "jet_energy": ours.jet_energy,
        "directions": dict(directions), "avoided": dict(avoided),
        "seed": seed, "win": ours.alive and not any(m.alive for m in hs),
        "timeout": ours.alive and any(m.alive for m in hs), "t": sim.t,
        "hp": ours.hp if ours.alive else 0.0, "kills": sum(not m.alive for m in hs),
        "dmg_out": ours.dmg_out, "dmg_in": ours.dmg_in, "rear_in": ours.rear_in,
        "shots": ours.shots, "hits": ours.hits,
        "h_shots": sum(m.shots for m in hs), "h_hits": sum(m.hits for m in hs),
        "modes": dict(modes), "errors": bot.errors,
        "loadout": "+".join(w["kind"] for w in ours.weapons if w),
        "weapon_t": weapon_t,
        "h_loadout": ["+".join(w["kind"] for w in m.weapons if w) for m in hs],
        "switches": switches, "multi": multi_ticks, "split": split_ticks, "both_seen": both_seen,
        "first_death_t": min([m.death_t for m in hs if m.death_t is not None], default=None),
    }


def _sample_header():
    import gzip
    import json
    p = S.ROOT / "replays" / "mechanics-v2-16.jsonl.gz"
    with gzip.open(p, "rt") as f:
        return json.loads(f.readline())


def split_top(text, sep=","):
    """Split on sep outside brackets/braces/quotes, so KEY={'a':1,'b':2},OTHER=3 stays two items."""
    out, depth, quote, cur = [], 0, None, ""
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur:
        out.append(cur)
    return out


def parse_overrides(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        try:
            out[k] = eval(v, {}, {})  # numbers, tuples, strings in quotes, True/False
        except Exception:  # noqa: BLE001
            out[k] = v
    return out


def summarize(rs, label=""):
    n = len(rs)
    wins = sum(r["win"] for r in rs)
    p = wins / n
    se = math.sqrt(p * (1 - p) / n) if n else 0
    win_t = [r["t"] for r in rs if r["win"]]
    modes = Counter()
    for r in rs:
        modes.update(r["modes"])
    tot = sum(modes.values()) or 1
    shots, hits = sum(r["shots"] for r in rs), sum(r["hits"] for r in rs)
    hs, hh = sum(r["h_shots"] for r in rs), sum(r["h_hits"] for r in rs)
    din = sum(r["dmg_in"] for r in rs) or 1
    print(f"{label} duels {n} | win {100 * p:.0f}% +-{100 * se:.0f} | timeouts {sum(r['timeout'] for r in rs)} | "
          f"kills/duel {sum(r['kills'] for r in rs) / n:.2f}")
    print(f"  win time median {statistics.median(win_t) if win_t else 0:.0f}s, HP left on win "
          f"{statistics.mean([r['hp'] for r in rs if r['win']]) if win_t else 0:.0f}")
    print(f"  our hit rate {100 * hits / max(shots, 1):.0f}% ({shots / n:.0f} shots/duel) | hunter hit rate "
          f"{100 * hh / max(hs, 1):.0f}% | dmg out/in {sum(r['dmg_out'] for r in rs) / din:.2f} | "
          f"rear share of dmg taken {100 * sum(r['rear_in'] for r in rs) / din:.0f}%")
    print("  modes: " + ", ".join(f"{k} {100 * v / tot:.0f}%" for k, v in modes.most_common()))
    lo = Counter(r["loadout"] for r in rs)
    wt = [r["weapon_t"] for r in rs if r["weapon_t"] is not None]
    hl = Counter(x for r in rs for x in r["h_loadout"])
    print("  win% by our end loadout: " + ", ".join(
        f"{k} {100 * sum(r['win'] for r in rs if r['loadout'] == k) / v:.0f}% (n={v})" for k, v in lo.most_common()))
    print("  our end loadout: " + ", ".join(f"{k} {v}" for k, v in lo.most_common())
          + (f" | 2nd weapon at median {statistics.median(wt):.0f}s" if wt else "")
          + " | hunters: " + ", ".join(f"{k} {v}" for k, v in hl.most_common()))
    multi = sum(r["multi"] for r in rs)
    if multi:
        fd = [r["first_death_t"] for r in rs if r["first_death_t"] is not None]
        print(f"  2+ hunters alive: hunters >90 deg apart {100 * sum(r['split'] for r in rs) / multi:.0f}% of the time, "
              f"both in sight {100 * sum(r['both_seen'] for r in rs) / multi:.0f}% | target switches/duel "
              f"{sum(r['switches'] for r in rs) / n:.1f} | first kill median "
              f"{statistics.median(fd) if fd else 0:.0f}s ({len(fd)} duels)")
    errs = sum(r["errors"] for r in rs)
    if errs:
        print(f"  !! {errs} bot decision errors")


BENCH_LOADOUTS = (("gun",), ("gun","laser"), ("gun","mortar"), ("gun","lightning"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--skill", default="hard", choices=list(SKILLS))
    ap.add_argument("--hunters", type=int, default=1)
    ap.add_argument("--ours", default="gun", help="our weapons, e.g. gun,laser")
    ap.add_argument("--theirs", default="gun", help="hunter weapons, e.g. gun,laser")
    ap.add_argument("--max-t", type=float, default=120)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--record", help="write a mechreplay/1 file (use with --n 1)")
    ap.add_argument("--set", nargs="*", help="config overrides KEY=VALUE")
    ap.add_argument("--pickups", type=int, default=40, help="floor weapons on the map (game: 40)")
    ap.add_argument("--no-hunter-loot", action="store_true", help="hunters keep their starting weapons")
    a = ap.parse_args()
    ov = parse_overrides(a.set)
    jobs = [(a.seed + i, a.skill, a.hunters, tuple(a.ours.split(",")), tuple(a.theirs.split(",")),
             a.max_t, a.record if a.n == 1 else None, ov, a.pickups, not a.no_hunter_loot) for i in range(a.n)]
    if a.workers > 1 and a.n > 1:
        with Pool(a.workers) as pool:
            rs = pool.map(run_duel, jobs)
    else:
        rs = [run_duel(j) for j in jobs]
    summarize(rs, f"[{a.skill} x{a.hunters}, ours {a.ours} vs {a.theirs}{' ' + str(ov) if ov else ''}]")


if __name__ == "__main__":
    main()
