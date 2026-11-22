"""Replay the kit's recorded stream through the bot and report per-tick timing.
Usage: python tools/bench.py [--repeat N]"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import secrets
import sys
import time

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

from main import Bot, mf  # noqa: E402


def evaluation_job(args):
    from duel import run_duel
    return run_duel(args, evaluation=True)


def match_suite(seeds, workers, mode, overrides):
    from duel import BENCH_LOADOUTS
    from sim import base_hello
    duration = base_hello()["config"]["match"]["duration_s"]
    jobs = [(seed, "expert", opponents, ours, theirs, duration, None, {**overrides, "MODE": mode}, 40 if opponents == 15 else 0, opponents == 15)
            for seed in seeds for ours in BENCH_LOADOUTS for opponents in (1, 15)
            for theirs in (BENCH_LOADOUTS if opponents == 1 else [("gun",)])]
    directions, avoided, weapons = Counter(), Counter(), {}
    scores, zone, gain, energy = [], [], 0., 0.
    duel_wins = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for job, result in zip(jobs, pool.map(evaluation_job, jobs)):
            if result["errors"]:
                raise RuntimeError(f"decision error for {job[:5]}")
            gain += result["jet_gain"]
            energy += result["jet_energy"]
            if job[2] == 15:
                scores.append(result["points"])
                zone.append(result["zone_survived"])
            else:
                duel_wins += result["win"]
                directions.update(result["directions"])
                avoided.update(result["avoided"])
                w = weapons.setdefault(job[4][-1], [0, 0])
                w[0] += sum(result["avoided"].values())
                w[1] += sum(result["directions"].values())
    def rate(a, b):
        return a / b if b else None
    score = sum(scores) / len(scores)
    print(json.dumps(dict(mode=mode, overrides=overrides, seeds=seeds, arena_points=scores,
                          overall_score=score, official_reference=3.4, zone_survival_rate=sum(zone)/len(zone),
                          jetpack_efficiency=rate(gain, energy), jet_metres=gain, jet_energy=energy,
                          directional_evasion_breakdown={d: [avoided[d], directions[d]] for d in directions},
                          per_weapon=weapons, duel_wins=duel_wins, duel_count=len(jobs)-len(scores),
                          **{"1v1_evasion_rate":rate(sum(avoided.values()), sum(directions.values()))})))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--matches", action="store_true")
    ap.add_argument("--seeds", nargs="+", type=int, default=[1])
    ap.add_argument("--random-seeds", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--modes", nargs="+", choices=("farm", "ffa"), default=["farm", "ffa"])
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    args = ap.parse_args()
    if args.matches:
        if args.workers < 1 or args.random_seeds < 0:
            ap.error("invalid worker or random seed count")
        seeds = args.seeds + [secrets.randbits(24) for _ in range(args.random_seeds)]
        from duel import parse_overrides
        overrides = parse_overrides(args.set)
        for mode in args.modes:
            match_suite(seeds, args.workers, mode, overrides)
        return
    if args.repeat < 1:
        ap.error("repeat must be at least 1")
    hello, observations = load_stream(DEFAULT_STREAM)
    mf.draw.caps = hello["config"]["debug"]

    times = []
    init_ms = []
    errors = 0
    over_budget = 0
    for _ in range(args.repeat):
        started = time.perf_counter()
        bot = Bot(hello)
        init_ms.append((time.perf_counter() - started) * 1000)
        for obs in observations:
            mf.draw.clear()
            t = time.perf_counter()
            bot.act(obs)
            times.append((time.perf_counter() - t) * 1000)
        errors += bot.errors
        over_budget += bot.over_budget
    times.sort()
    pct = lambda p: times[min(len(times) - 1, int(p * len(times)))]
    print(f"max init {max(init_ms):.0f} ms | ticks {len(times)} | "
          f"p50 {pct(.5):.2f} p99 {pct(.99):.2f} max {times[-1]:.2f} ms")
    print(f"Fallbacks: {errors} decision errors, {over_budget} over the decision guard")
    if errors:
        sys.exit("bot decision errors on the replay")
    if pct(.99) > 25:
        sys.exit("p99 over 25 ms budget")


if __name__ == "__main__":
    main()
