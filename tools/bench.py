"""Replay the kit's recorded stream through the bot and report per-tick timing.
Usage: python tools/bench.py [--repeat N]"""
import argparse
import gzip
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot"))

from main import Bot  # noqa: E402

STREAM = os.path.join(ROOT, "mechfight-kit", "mechfight-kit", "check", "stream.jsonl.gz")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    msgs = [json.loads(line) for line in gzip.open(STREAM, "rt") if line.strip()]
    hello = msgs[0]
    hello["map"]["dir"] = os.path.join(ROOT, "arena")
    obs = [m for m in msgs if m.get("type") == "obs"]

    t0 = time.perf_counter()
    bot = Bot(hello)
    init_ms = (time.perf_counter() - t0) * 1000

    times = []
    for _ in range(args.repeat):
        for o in obs:
            t = time.perf_counter()
            bot.act(o)
            times.append((time.perf_counter() - t) * 1000)
    times.sort()
    pct = lambda p: times[min(len(times) - 1, int(p * len(times)))]
    print(f"init {init_ms:.0f} ms | ticks {len(times)} | p50 {pct(.5):.2f} p99 {pct(.99):.2f} max {times[-1]:.2f} ms")
    if pct(.99) > 25:
        sys.exit("p99 over 25 ms budget")


if __name__ == "__main__":
    main()
