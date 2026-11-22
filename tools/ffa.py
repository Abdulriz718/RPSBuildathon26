"""Full 16-mech free-for-all in the local sim: our real bot vs 15 scripted bots that fight each other.

This is the final's format (and close to the play.joinbuilders.org rooms): bots only attack what they can
see or who hit them, loot weapons, and keep inside the shrinking zone. Scored like the server:
16 - place, deaths on the same tick share a place, survivors at the end ranked by HP.

  python tools/ffa.py --n 24
  python tools/ffa.py --n 24 --set ZONE_MARGIN=0.9
  python tools/ffa.py --n 1 --seed 3 --record replays/ffa-3.jsonl.gz
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

import duel as D  # noqa: E402
import sim as S  # noqa: E402

HOUSE_MIX = ["easy"] * 4 + ["medium"] * 4 + ["hard"] * 4 + ["expert"] * 3


class FFABot:
    """A house-style bot for a free-for-all: fight what you see (or who hit you), else loot and hold the zone."""

    def __init__(self, sim, mech, skill, rng):
        self.sim, self.m, self.rng = sim, mech, rng
        self.h = D.Hunter(sim, mech, skill, rng)
        self.seen = {}
        self.attacker = None  # (id, t)
        self.wander = None  # (phase start, (x, y))

    def _wander_point(self):
        ph = self.sim.zone.phase(self.sim.t)
        if self.wander is None or self.wander[0] != ph["start"]:
            nav = self.h.nav
            for _ in range(40):
                a = self.rng.uniform(-math.pi, math.pi)
                r = ph["next_radius"] * 0.7 * math.sqrt(self.rng.random())
                p = (ph["next_center"][0] + r * math.cos(a), ph["next_center"][1] + r * math.sin(a))
                if nav.walkable_xy(*p):
                    break
            self.wander = (ph["start"], p)
        return self.wander[1]

    def act(self):
        sim, m, t = self.sim, self.m, self.sim.t
        for e in m.events:
            if e["type"] == "damaged" and e.get("by") is not None:
                self.attacker = (e["by"], t)
        m.events = []
        cands = []
        for o in sim.mechs.values():
            if o is m or not o.alive or o.kind != "mech":
                continue
            d = math.dist(o.pos, m.pos)
            if d <= 200 and sim.sees(m, o):
                self.seen[o.id] = t
            if t - self.seen.get(o.id, -1e9) <= 5.0:
                cands.append((d, o))
        target = None
        if self.attacker and t - self.attacker[1] < 3.0:
            att = sim.mechs.get(self.attacker[0])
            if att is not None and att.alive:
                target = att
        if target is None and cands:
            target = min(cands, key=lambda c: c[0])[1]
        outside = not sim.zone.inside(t + 8.0, m.pos)  # where the circle will be shortly
        if target is not None and not outside:
            return self.h.act(target)
        goal = self._wander_point()
        act = {}
        lp = None if outside else self.h.loot_goal(999, False)
        if lp is not None:
            goal = lp["pos"][:2]
            if math.hypot(goal[0] - m.pos[0], goal[1] - m.pos[1]) < 3.5:
                act["take"] = lp["id"]
        mx, my, jump, boost = self.h.nav.next_step(m.pos, goal, t, 1.0)
        act.update(move=[mx, my], jump=jump, boost=boost or outside)
        if target is not None:  # running for the zone: still shoot back
            a = self.h.act(target)
            act.update(aim=a["aim"], fire=a["fire"])
        else:
            act["aim"] = [math.atan2(my, mx) if (mx or my) else m.aim[0], 0.0]
            act["fire"] = [False, False]
        return act


def spawn16(rng, nav, world, cfg):
    zc, zr = cfg["zone"]["start_center"], cfg["zone"]["start_radius"] * cfg["match"]["spawn_zone_fraction"]
    sep = cfg["match"]["spawn_min_separation"]
    cells = [c for c in range(len(nav.main)) if nav.main[c] and not nav.roof[c]]
    cells = [c for c in cells if math.dist(nav.to_xy(c % nav.cnx, c // nav.cnx), zc) <= zr]
    for _ in range(200):
        pts = []
        for _ in range(3000):
            c = rng.choice(cells)
            p = nav.to_xy(c % nav.cnx, c // nav.cnx)
            if all(math.dist(p, q) >= sep for q in pts):
                pts.append(p)
                if len(pts) == 16:
                    return [(x, y, world.surface(x, y)) for x, y in pts]
        sep *= 0.9  # the walkable area is irregular: relax if 16 don't fit
    raise RuntimeError("no spawn layout")


def run_match(args):
    seed, overrides, max_t, record = args
    # Worker processes run many jobs: start each from the defaults in bot/config.py, or one variant's
    # overrides leak into the next (this silently mixed MODE='ffa' into later variants once).
    import importlib
    import config
    importlib.reload(config)
    S.patch_brain_for_speed()
    for k, v in overrides.items():
        setattr(config, k, v)
    from main import Bot
    world, nav = S.shared_world()
    rng = random.Random(seed)
    hello = S.base_hello()
    hello["slot"] = 0
    cfg = hello["config"]
    sim = S.Sim(cfg, world, seed=seed, record=record)
    if record:
        sim.start_record()
    sim.zone = S.Zone(cfg["zone"], random.Random(seed * 13 + 5))
    pts = spawn16(rng, nav, world, cfg)
    slots = list(range(16))
    rng.shuffle(slots)
    ours = S.Mech(0, pts[slots[0]], cfg, ("gun",), "ours")
    ours.aim = [rng.uniform(-math.pi, math.pi), 0.0]
    sim.add(ours)
    bots = []
    for i, skill in enumerate(HOUSE_MIX, start=1):
        mm = S.Mech(i, pts[slots[i]], cfg, ("gun",), skill)
        mm.aim = [rng.uniform(-math.pi, math.pi), 0.0]
        sim.add(mm)
        b = FFABot(sim, mm, skill, random.Random(seed * 97 + i))
        bots.append(b)
    sim.spawn_pickups(random.Random(seed * 7 + 1), nav, cfg["loot"]["floor_count"])
    sim.spawn_drones(random.Random(seed * 3 + 2), nav, cfg["npc"]["count"])
    bot = Bot(hello)
    memory, last_obs_t = {}, -1.0
    modes = Counter()
    while sim.t < max_t and ours.alive and sum(m.alive and m.kind == "mech" for m in sim.mechs.values()) > 1:
        if sim.tick % 2 == 0:
            obs = sim.observe(ours, memory, last_obs_t)
            last_obs_t = sim.t
            S.mf.draw.clear()
            a = bot.act(obs)
            a.pop("debug", None)
            ours.action = a
            modes[bot.brain.mode] += 1
            for b in bots:
                if b.m.alive:
                    b.m.action = b.act()
            sim.prune_sounds()
        else:
            for m in sim.mechs.values():
                m.action = dict(m.action, jump=False, reload=False, take=None, drop=None)
        sim.step()
    # placement
    if ours.alive:
        alive = [m for m in sim.mechs.values() if m.alive and m.kind == "mech"]
        place = 1 + sum(1 for m in alive if m is not ours and m.hp > ours.hp)
    else:
        same_tick = [mid for (dt_, mid) in sim.deaths if abs(dt_ - ours.death_t) < 1e-9]
        before = sum(1 for (dt_, _) in sim.deaths if dt_ < ours.death_t - 1e-9)
        place = 16 - before - len(same_tick) + 1
    if record:
        sim.write_record(record, D._sample_header())
    killer = None
    if not ours.alive:
        killer = "zone" if getattr(ours, "zone_in", 0) and ours.hp <= 0 and sim.zone and not sim.zone.inside(ours.death_t, ours.pos) else "mech"
    return {"seed": seed, "place": place, "score": 16 - place, "alive": ours.alive,
            "t": ours.death_t if ours.death_t is not None else sim.t, "kills": sum(
                1 for (dt_, mid) in sim.deaths if mid != 0 and mid in sim.mechs and sim.mechs[mid].dmg_in > 0) and None,
            "dmg_out": ours.dmg_out, "dmg_in": ours.dmg_in, "zone_in": getattr(ours, "zone_in", 0.0),
            "killer": killer, "modes": dict(modes), "errors": bot.errors,
            "loadout": "+".join(w["kind"] for w in ours.weapons if w)}


def summarize(rs, label):
    n = len(rs)
    sc = [r["score"] for r in rs]
    se = statistics.stdev(sc) / math.sqrt(n) if n > 1 else 0
    modes = Counter()
    for r in rs:
        modes.update(r["modes"])
    tot = sum(modes.values()) or 1
    print(f"{label} matches {n} | score {statistics.mean(sc):.2f} +-{se:.2f} (16 - place) | "
          f"median survival {statistics.median(r['t'] for r in rs):.0f}s | won {sum(r['place'] == 1 for r in rs)}")
    print(f"  deaths: {Counter(r['killer'] for r in rs if not r['alive'])} | dmg out/in per match "
          f"{statistics.mean(r['dmg_out'] for r in rs):.0f}/{statistics.mean(r['dmg_in'] for r in rs):.0f} "
          f"(zone {statistics.mean(r['zone_in'] for r in rs):.0f})")
    print("  modes: " + ", ".join(f"{k} {100 * v / tot:.0f}%" for k, v in modes.most_common()))
    print("  places: " + " ".join(str(r["place"]) for r in sorted(rs, key=lambda r: r["seed"])))
    errs = sum(r["errors"] for r in rs)
    if errs:
        print(f"  !! {errs} bot decision errors")


def compare(variants, n, seed=1, workers=12):
    """Paired comparison on the same seeds: mean score of each variant and its difference from the first."""
    res = {}
    with Pool(workers) as pool:
        for label, ov in variants:
            res[label] = pool.map(run_match, [(seed + i, ov, 480, None) for i in range(n)])
    base_label = variants[0][0]
    base = [r["score"] for r in res[base_label]]
    for label, _ in variants:
        sc = [r["score"] for r in res[label]]
        diff = [a - b for a, b in zip(sc, base)]
        se = statistics.stdev(diff) / math.sqrt(n) if label != base_label else 0.0
        early = sum(r["place"] >= 13 for r in res[label])
        print(f"{label:<40} score {statistics.mean(sc):5.2f} | vs base {statistics.mean(diff):+.2f} +-{se:.2f} | "
              f"died 13th-16th {early}/{n} | won {sum(r['place'] == 1 for r in res[label])}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--max-t", type=float, default=480)
    ap.add_argument("--record")
    ap.add_argument("--set", nargs="*")
    ap.add_argument("--compare", nargs="+", metavar="LABEL:KEY=VAL,KEY=VAL",
                    help="paired comparison on the same seeds; first is the base, e.g. base: ffa:MODE='ffa'")
    a = ap.parse_args()
    if a.compare:
        variants = []
        for item in a.compare:
            label, _, rest = item.partition(":")
            variants.append((label, D.parse_overrides([kv for kv in D.split_top(rest) if kv])))
        compare(variants, a.n, a.seed, a.workers)
        return
    ov = D.parse_overrides(a.set)
    jobs = [(a.seed + i, ov, a.max_t, a.record if a.n == 1 else None) for i in range(a.n)]
    if a.workers > 1 and a.n > 1:
        with Pool(a.workers) as pool:
            rs = pool.map(run_match, jobs)
    else:
        rs = [run_match(j) for j in jobs]
    summarize(rs, f"[ffa{' ' + str(ov) if ov else ''}]")


if __name__ == "__main__":
    main()
