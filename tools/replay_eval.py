#!/usr/bin/env python3
"""Compare target forecasts against later observations in a Mechfight replay."""

import argparse
from collections import defaultdict
import gzip
import json
from math import dist, sqrt
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "mechfight-kit" / "mechfight-kit"
ROOT_STREAM = ROOT / "check" / "stream.jsonl.gz"
DEFAULT_STREAM = ROOT_STREAM if ROOT_STREAM.exists() else KIT / "check" / "stream.jsonl.gz"


def load_stream(path, map_dir=None):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        messages = [json.loads(line) for line in stream if line.strip()]
    if not messages or messages[0].get("type") != "hello":
        raise ValueError("Replay must begin with a hello message.")
    hello = messages[0]
    default_map = ROOT / "arena"
    if not (default_map / "v2" / "world.json").exists():
        default_map = KIT / "arena"
    hello["map"]["dir"] = str(Path(map_dir or default_map).resolve())
    observations = [message for message in messages if message.get("type") == "obs"]
    if not observations:
        raise ValueError("Replay has no observations.")
    return hello, observations


def tracking_errors(hello, observations, horizons):
    sys.path.insert(0, str(ROOT / "bot"))
    from track import Tracker

    tracker = Tracker(hello["config"])
    tick_hz = hello["config"]["match"]["tick_hz"]
    by_tick = {obs["tick"]: {actor["id"]: actor["pos"] for actor in obs["mechs"]}
               for obs in observations}
    errors = defaultdict(list)
    for obs in observations:
        tracker.update(obs)
        for target in tracker.targets_sorted(max_age=0):
            for horizon in horizons:
                ticks = round(horizon * tick_hz)
                truth = by_tick.get(obs["tick"] + ticks, {}).get(target.id)
                if truth is None:
                    continue
                errors[horizon].append((dist(target.pos, truth),
                                        dist(target.predict(ticks / tick_hz), truth)))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", type=Path, default=DEFAULT_STREAM)
    parser.add_argument("--horizons", nargs="+", type=float, default=[0.1, 0.2, 0.5, 1.0])
    args = parser.parse_args()
    if any(horizon <= 0 for horizon in args.horizons):
        parser.error("prediction horizons must be positive")
    hello, observations = load_stream(args.stream)
    tick_hz = hello["config"]["match"]["tick_hz"]
    horizons = sorted({round(h * tick_hz) / tick_hz for h in args.horizons if round(h * tick_hz)})
    errors = tracking_errors(hello, observations, horizons)
    print(f"{len(observations)} observations. Error is 3D position RMSE in meters.")
    print("horizon   samples    stationary        tracker")
    for horizon in horizons:
        samples = errors[horizon]
        if samples:
            metrics = [sqrt(mean(e * e for e in column)) for column in zip(*samples)]
            print(f"{horizon:6.2f}s {len(samples):8d} {metrics[0]:13.3f} {metrics[1]:14.3f}")
        else:
            print(f"{horizon:6.2f}s {0:8d}")
    return 0 if any(errors.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
