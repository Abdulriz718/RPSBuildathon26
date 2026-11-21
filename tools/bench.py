"""Replay the kit's recorded stream through the bot and report per-tick timing.
Usage: python tools/bench.py [--repeat N]"""
import argparse
import sys
import time

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

from main import Bot, mf  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
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
