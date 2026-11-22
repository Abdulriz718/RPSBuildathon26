"""A practice match like the scorer's: our bot vs 15 house bots playing as one squad.

From the rules: the squad shares what it sees, never fights itself, and hunts us weakest first: one hunter at the
start, more as we thin them out, all of them late. House bots only die to us (or the zone), so our place is
roughly 16 minus the house bots we outlive. Scored 16 - place, like the server.

The squad rules here are guesses; tools/practice.py --calibrate replays every scored version of our bot from git
history so the guesses can be tuned until the sim ranks those versions the way the server did.

  python tools/practice.py --n 48
  python tools/practice.py --n 48 --set ROOF_CLIMB=False
  python tools/practice.py --n 48 --bot-dir C:/tmp/bot-v123      # an older bot exported with git archive
  python tools/practice.py --compare "base:" "x:COVER_LOW_HP=0.3"
  python tools/practice.py --calibrate
"""
import argparse
import importlib
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import duel as D  # noqa: E402
import ffa as F  # noqa: E402
import sim as S  # noqa: E402

# Squad rules (calibrated with --calibrate)
SQUAD = {
    "erratic": False,       # house bots jump, jet and boost-strafe like the real ones
    "dodge": False,         # house bots sidestep our bullets they can see coming
    "wave_per_kill": 1,     # extra hunters released per house bot we kill
    "all_hunt_t": 300.0,    # after this match time every house bot hunts us
    "engage_m": 80.0,       # a non-hunter that sees us within this range fights us too
}

# Scored versions: (label, git ref or "kit", real practice score)
HISTORY = [
    ("kit example", "kit", 1.15),
    ("phase 1", "a1d4ea6", 1.52),
    ("phase 2 (broken merge)", "9444dad", 0.17),
    ("phase 3", "6cfb5ff", 1.88),
    ("phase 4", "5b7cdd2", 2.02),
    ("#6 no-retreat config", "5570130", 2.31),
    ("#7 weapon grab", "1079658", 3.23),
    ("roof climbing", "4af2045", 3.40),
    ("kite 120-170", "KITE", 3.10),
]


class SquadBot(F.FFABot):
    """A house bot: hunts us when the squad assigns it (or sees us close), never targets its own team."""

    def __init__(self, sim, mech, skill, rng, ours, squad):
        super().__init__(sim, mech, skill, rng)
        self.ours, self.squad = ours, squad

    def act(self):
        sim, m, t = self.sim, self.m, self.sim.t
        m.events = []
        hunting = self.m.id in self.squad.hunters()
        sees = math.dist(self.ours.pos, m.pos) <= SQUAD["engage_m"] and sim.sees(m, self.ours)
        target = self.ours if self.ours.alive and (hunting or sees) else None
        outside = not sim.zone.inside(t + 8.0, m.pos)
        if target is not None and not outside:
            return self.h.act(target)  # the squad shares vision: hunters always know where we are
        goal = self._wander_point()
        act = {}
        lp = None if outside else self.h.loot_goal(999, False)
        if lp is not None:
            goal = lp["pos"][:2]
            if math.hypot(goal[0] - m.pos[0], goal[1] - m.pos[1]) < 3.5:
                act["take"] = lp["id"]
        mx, my, jump, boost = self.h.nav.next_step(m.pos, goal, t, 1.0)
        act.update(move=[mx, my], jump=jump, boost=boost or outside)
        if target is not None:
            a = self.h.act(target)
            act.update(aim=a["aim"], fire=a["fire"])
        else:
            act["aim"] = [math.atan2(my, mx) if (mx or my) else m.aim[0], 0.0]
            act["fire"] = [False, False]
        return act


class Squad:
    def __init__(self, sim, bots):
        self.sim, self.bots = sim, bots  # bots in weakest-first order
        self.kills = 0

    def hunters(self):
        alive = [b.m.id for b in self.bots if b.m.alive]
        if self.sim.t >= SQUAD["all_hunt_t"]:
            return set(alive)
        return set(alive[: 1 + self.kills * SQUAD["wave_per_kill"]])


# ---- loading a bot version ------------------------------------------------------------------------------------------
_BOT_DIR = None


def _init_worker(bot_dir, squad):
    """Point imports at bot_dir. world/nav stay the current ones (the sim's physics); config/brain/etc. come from
    bot_dir so an old version plays with its own settings."""
    global _BOT_DIR
    SQUAD.update(squad)
    D.ERRATIC = bool(SQUAD.get("erratic"))
    D.DODGE = bool(SQUAD.get("dodge"))
    S.shared_world()
    if bot_dir and Path(bot_dir).resolve() != (S.ROOT / "bot").resolve():
        for mod in ("config", "main", "brain", "combat", "track", "loot", "defense", "gridbuild"):
            sys.modules.pop(mod, None)
        sys.path.insert(0, str(bot_dir))
    _BOT_DIR = bot_dir


def export_version(ref, dest):
    """Write bot/ at git ref into dest (kit: the kit's example bot behind a main.Bot shim)."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if ref == "KITE":
        for f in (S.ROOT / "bot").glob("*.py"):
            shutil.copy(f, dest / f.name)
        cfgp = dest / "config.py"
        cfgp.write_text(cfgp.read_text(encoding="utf-8").replace('STYLE = "default"', 'STYLE = "kite"'), encoding="utf-8")
        return dest
    if ref == "kit":
        kit = S.ROOT / "mechfight-kit" / "mechfight-kit" / "python"
        src = (kit / "example_bot.py").read_text(encoding="utf-8").replace("mf.run(Bot)", "")
        (dest / "main.py").write_text(src, encoding="utf-8")
        return dest
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, "bot/"], cwd=S.ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    for f in files:
        data = subprocess.run(["git", "show", f"{ref}:{f}"], cwd=S.ROOT, capture_output=True, check=True).stdout
        (dest / Path(f).name).write_bytes(data)
    return dest


def run_match(args):
    seed, overrides, max_t = args
    import config
    importlib.reload(config)
    S.patch_brain_for_speed()
    import nav as _nav
    for k in ("NAV_BUDGET_MS", "COVER_PAIR_BUDGET_MS"):
        setattr(_nav.config, k, 1000.0)
    start_weapons = tuple(overrides.get("_weapons", ("gun",)))  # "what if" upper bounds, not bot settings
    start_cubes = int(overrides.get("_cubes", 0))
    for k, v in overrides.items():
        if not k.startswith("_"):
            setattr(config, k, v)
    import main
    world, nav = S.shared_world()
    rng = random.Random(seed)
    hello = S.base_hello()
    hello["slot"] = 0
    cfg = hello["config"]
    sim = S.Sim(cfg, world, seed=seed)
    sim.zone = S.Zone(cfg["zone"], random.Random(seed * 13 + 5))
    pts = F.spawn16(rng, nav, world, cfg)
    order = list(range(16))
    rng.shuffle(order)
    ours = S.Mech(0, pts[order[0]], cfg, start_weapons, "ours", cubes=start_cubes)
    ours.aim = [rng.uniform(-math.pi, math.pi), 0.0]
    sim.add(ours)
    bots = []
    for i, skill in enumerate(F.HOUSE_MIX, start=1):
        mm = S.Mech(i, pts[order[i]], cfg, ("gun",), skill)
        mm.team = "house"
        mm.aim = [rng.uniform(-math.pi, math.pi), 0.0]
        sim.add(mm)
        bots.append(SquadBot(sim, mm, skill, random.Random(seed * 97 + i), ours, None))
    squad = Squad(sim, bots)
    for b in bots:
        b.squad = squad
    sim.spawn_pickups(random.Random(seed * 7 + 1), nav, cfg["loot"]["floor_count"])
    sim.spawn_drones(random.Random(seed * 3 + 2), nav, cfg["npc"]["count"])
    bot = main.Bot(hello)
    memory, last_obs_t = {}, -1.0
    dead_before = 0
    kill_log = []  # (t, our hp, hunters within 120 m) at each kill
    while sim.t < max_t and ours.alive and any(b.m.alive for b in bots):
        if sim.tick % 2 == 0:
            obs = sim.observe(ours, memory, last_obs_t)
            last_obs_t = sim.t
            S.mf.draw.clear()
            try:
                a = bot.act(obs) or {}
            except Exception:  # noqa: BLE001  a crashing version keeps its last action, like the server
                a = {}
            a = dict(a)
            a.pop("debug", None)
            ours.action = a
            for b in bots:
                if b.m.alive:
                    b.m.action = b.act()
            sim.prune_sounds()
        else:
            for m in sim.mechs.values():
                m.action = dict(m.action, jump=False, reload=False, take=None, drop=None)
        sim.step()
        dead = sum(not b.m.alive for b in bots)
        if dead != dead_before:
            squad.kills += dead - dead_before
            dead_before = dead
            kill_log.append((round(sim.t), round(ours.hp), sum(1 for b in bots if b.m.alive and math.dist(b.m.pos, ours.pos) < 120)))
    if ours.alive:
        alive = [m for m in sim.mechs.values() if m.alive and m.kind == "mech"]
        place = 1 + sum(1 for m in alive if m is not ours and m.hp > ours.hp)
    else:
        same = sum(1 for (dt_, _) in sim.deaths if abs(dt_ - ours.death_t) < 1e-9)
        before = sum(1 for (dt_, _) in sim.deaths if dt_ < ours.death_t - 1e-9)
        place = 16 - before - same + 1
    return {"seed": seed, "score": 16 - place, "place": place, "t": ours.death_t or sim.t,
            "kills": sum(not b.m.alive for b in bots), "alive": ours.alive,
            "loadout": "+".join(w["kind"] for w in ours.weapons if w),
            "shots": ours.shots, "hits": ours.hits,
            "h_shots": sum(b.m.shots for b in bots), "h_hits": sum(b.m.hits for b in bots),
            "near_at_death": sum(1 for b in bots if b.m.alive and math.dist(b.m.pos, ours.pos) < 120),
            "kill_log": kill_log, "cubes": ours.cubes, "upgrades": list(ours.upgrades),
            "drones_killed": sum(1 for b in sim.npc_brains if not b["m"].alive)}


def run(n, overrides=None, bot_dir=None, seed=1, workers=12, max_t=480):
    jobs = [(seed + i, overrides or {}, max_t) for i in range(n)]
    with Pool(workers, initializer=_init_worker, initargs=(str(bot_dir) if bot_dir else None, dict(SQUAD))) as pool:
        return pool.map(run_match, jobs)


def line(label, rs, base=None):
    sc = [r["score"] for r in rs]
    out = f"{label:<28} score {statistics.mean(sc):5.2f} +-{statistics.stdev(sc) / math.sqrt(len(sc)):.2f}"
    if base is not None:
        d = [a - b for a, b in zip(sc, [r["score"] for r in base])]
        out += f" | vs base {statistics.mean(d):+.2f} +-{statistics.stdev(d) / math.sqrt(len(d)):.2f}"
    acc = 100 * sum(r["hits"] for r in rs) / max(1, sum(r["shots"] for r in rs))
    hacc = 100 * sum(r["h_hits"] for r in rs) / max(1, sum(r["h_shots"] for r in rs))
    out += f" | hit% ours {acc:.0f} theirs {hacc:.0f}"
    out += (f" | kills {statistics.mean(r['kills'] for r in rs):.1f} | survived {statistics.median(r['t'] for r in rs):.0f}s"
            f" | alive at end {sum(r['alive'] for r in rs)}")
    print(out, flush=True)


def deaths_report(rs):
    """How do we die? Hunters close at death, loadout, and HP/hunters at each kill."""
    from collections import Counter
    print("hunters within 120 m at our death:", dict(sorted(Counter(r["near_at_death"] for r in rs if not r["alive"]).items())))
    lo = Counter(r["loadout"] for r in rs)
    print("score by loadout:", ", ".join(f"{k} {statistics.mean(r['score'] for r in rs if r['loadout'] == k):.2f} (n={v})"
                                         for k, v in lo.most_common()))
    gaps = [b[0] - a[0] for r in rs for a, b in zip(r["kill_log"], r["kill_log"][1:])]
    hp = [k[1] for r in rs for k in r["kill_log"]]
    near = Counter(k[2] for r in rs for k in r["kill_log"])
    if hp:
        print(f"at each kill: our HP median {statistics.median(hp):.0f}, hunters within 120 m {dict(sorted(near.items()))}"
              f", seconds between kills median {statistics.median(gaps) if gaps else 0:.0f}")
    print("death time (s) quartiles:", [round(x) for x in statistics.quantiles([r["t"] for r in rs], n=4)])
    print(f"our cubes at end: median {statistics.median(r['cubes'] for r in rs)}, mean {statistics.mean(r['cubes'] for r in rs):.1f}"
          f" | drones killed per match {statistics.mean(r['drones_killed'] for r in rs):.1f}"
          f" | upgrades taken {Counter(u for r in rs for u in r['upgrades']).most_common(6)}")


def calibrate(n, workers):
    tmp = Path(tempfile.gettempdir()) / "mech-versions"
    rows = []
    for label, ref, real in HISTORY:
        d = export_version(ref, tmp / ref)
        rs = run(n, bot_dir=d, workers=workers)
        sim_score = statistics.mean(r["score"] for r in rs)
        rows.append((label, real, sim_score))
        print(f"{label:<26} real {real:5.2f} | sim {sim_score:5.2f} | kills {statistics.mean(r['kills'] for r in rs):.1f}",
              flush=True)
    reals = [r[1] for r in rows]
    sims = [r[2] for r in rows]
    mr, ms = statistics.mean(reals), statistics.mean(sims)
    cov = sum((a - mr) * (b - ms) for a, b in zip(reals, sims))
    corr = cov / math.sqrt(sum((a - mr) ** 2 for a in reals) * sum((b - ms) ** 2 for b in sims))
    print(f"correlation sim vs real: {corr:.2f} | squad rules {SQUAD}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--bot-dir")
    ap.add_argument("--set", nargs="*")
    ap.add_argument("--squad", nargs="*", help="squad rule overrides, e.g. all_hunt_t=240 engage_m=120")
    ap.add_argument("--compare", nargs="+", metavar="LABEL:KEY=VAL,KEY=VAL")
    ap.add_argument("--calibrate", action="store_true")
    a = ap.parse_args()
    SQUAD.update(D.parse_overrides(a.squad))
    if a.calibrate:
        calibrate(a.n, a.workers)
        return
    if a.compare:
        base = None
        for item in a.compare:
            label, _, rest = item.partition(":")
            rs = run(a.n, D.parse_overrides([kv for kv in D.split_top(rest) if kv]), a.bot_dir, a.seed, a.workers)
            line(label, rs, base)
            base = base or rs
        return
    rs = run(a.n, D.parse_overrides(a.set), a.bot_dir, a.seed, a.workers)
    line("practice", rs)
    deaths_report(rs)


if __name__ == "__main__":
    main()
