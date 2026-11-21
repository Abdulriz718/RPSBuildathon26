#!/usr/bin/env python3
"""Time Mechfight decisions on the kit's recorded observations."""

import argparse
from math import ceil
from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

from main import Bot, mf


def percentile(samples, fraction):
    return samples[ceil(len(samples) * fraction) - 1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", type=Path, default=DEFAULT_STREAM)
    parser.add_argument("--map-dir", type=Path)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--max-p99-ms", type=float, default=25.0)
    args = parser.parse_args()
    if args.repeat <= 0 or args.max_p99_ms <= 0:
        parser.error("repeat and max-p99-ms must be positive")
    hello, observations = load_stream(args.stream, args.map_dir)
    mf.draw.caps = hello["config"]["debug"]
    samples = []
    errors = over_budget = 0
    slowest_tick = observations[0]["tick"]
    slowest_ms = 0.0
    for _ in range(args.repeat):
        bot = Bot(hello)
        for obs in observations:
            mf.draw.clear()
            started = perf_counter_ns()
            bot.act(obs)
            elapsed = (perf_counter_ns() - started) / 1_000_000
            samples.append(elapsed)
            if elapsed > slowest_ms:
                slowest_ms = elapsed
                slowest_tick = obs["tick"]
        errors += bot.errors
        over_budget += bot.over_budget

    samples.sort()
    p99 = percentile(samples, 0.99)
    print(f"{len(samples)} decisions ({args.repeat} passes), in-process elapsed time")
    print(f"p50 {median(samples):.3f} ms  p90 {percentile(samples, 0.90):.3f} ms  "
          f"p99 {p99:.3f} ms  max {slowest_ms:.3f} ms (tick {slowest_tick})")
    print(f"Fallbacks: {errors} decision errors, {over_budget} over the decision guard")
    return int(errors > 0 or over_budget > 0 or p99 >= args.max_p99_ms)


if __name__ == "__main__":
    raise SystemExit(main())
