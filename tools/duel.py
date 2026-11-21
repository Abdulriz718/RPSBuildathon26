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
        if not los or d > k["engage_m"]:
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
        act["fire"] = [bool(los and d < 225 and err < tol), True]  # slot 1 (laser if held) charges and releases
        laser = m.weapons[1]
        if laser and laser["kind"] == "laser":
            act["fire"][1] = bool(los and d < 270 and (laser["charge"] < laser["stats"]["charge"] or err > tol))
        return act


def spawn_points(rng, nav, world, n, min_sep=130, max_sep=220):
    cells = [c for c in range(len(nav.main)) if nav.main[c] and not nav.roof[c]]
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


def run_duel(args):
    seed, skill, n_hunters, our_w, hunter_w, max_t, record, overrides = args
    S.patch_brain_for_speed()
    import config
    for key, val in overrides.items():
        setattr(config, key, val)
    from main import Bot
    world, nav = S.shared_world()
    rng = random.Random(seed)
    hello = S.base_hello()
    hello["slot"] = 0
    cfg = hello["config"]
    pts = spawn_points(rng, nav, world, 1 + n_hunters)
    sim = S.Sim(cfg, world, seed=seed, record=record)
    if record:
        sim.start_record()
    ours = S.Mech(0, pts[0], cfg, our_w, "ours")
    ours.aim = [rng.uniform(-math.pi, math.pi), 0.0]
    sim.add(ours)
    hunters = []
    for i in range(n_hunters):
        hm = S.Mech(i + 1, pts[i + 1], cfg, hunter_w, skill)
        sim.add(hm)
        hunters.append(Hunter(sim, hm, skill, random.Random(seed * 31 + i)))
    bot = Bot(hello)
    memory, last_obs_t = {}, -1.0
    modes = Counter()
    while sim.t < max_t and ours.alive and any(h.m.alive for h in hunters):
        if sim.tick % 2 == 0:
            obs = sim.observe(ours, memory, last_obs_t)
            last_obs_t = sim.t
            S.mf.draw.clear()
            a = bot.act(obs)
            a.pop("debug", None)
            ours.action = a
            modes[bot.brain.mode] += 1
            for h in hunters:
                if h.m.alive:
                    h.m.action = h.act(ours)
            sim.prune_sounds()
        else:
            for m in sim.mechs.values():
                m.action = dict(m.action, jump=False, reload=False)
        sim.step()
    if record:
        sim.write_record(record, _sample_header())
    hs = [h.m for h in hunters]
    return {
        "seed": seed, "win": ours.alive and not any(m.alive for m in hs),
        "timeout": ours.alive and any(m.alive for m in hs), "t": sim.t,
        "hp": ours.hp if ours.alive else 0.0, "kills": sum(not m.alive for m in hs),
        "dmg_out": ours.dmg_out, "dmg_in": ours.dmg_in, "rear_in": ours.rear_in,
        "shots": ours.shots, "hits": ours.hits,
        "h_shots": sum(m.shots for m in hs), "h_hits": sum(m.hits for m in hs),
        "modes": dict(modes), "errors": bot.errors,
    }


def _sample_header():
    import gzip
    import json
    p = S.ROOT / "replays" / "mechanics-v2-16.jsonl.gz"
    with gzip.open(p, "rt") as f:
        return json.loads(f.readline())


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
    errs = sum(r["errors"] for r in rs)
    if errs:
        print(f"  !! {errs} bot decision errors")


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
    a = ap.parse_args()
    ov = parse_overrides(a.set)
    jobs = [(a.seed + i, a.skill, a.hunters, tuple(a.ours.split(",")), tuple(a.theirs.split(",")),
             a.max_t, a.record if a.n == 1 else None, ov) for i in range(a.n)]
    if a.workers > 1 and a.n > 1:
        with Pool(a.workers) as pool:
            rs = pool.map(run_duel, jobs)
    else:
        rs = [run_duel(j) for j in jobs]
    summarize(rs, f"[{a.skill} x{a.hunters}, ours {a.ours} vs {a.theirs}{' ' + str(ov) if ov else ''}]")


if __name__ == "__main__":
    main()
