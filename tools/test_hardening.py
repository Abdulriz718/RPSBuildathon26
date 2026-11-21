"""Phase 4 hardening checks that the recorded 37 s replay can't cover.

1. Sparse observations: enemy hp hidden (vision.show_enemy_hp false), vel/aim/weapons/cubes
   missing, empty lists. The protocol may also add fields; unknown ones must be ignored.
2. A full 8-minute match (4800 decisions) with a shrinking zone: no exceptions, per-tick time
   stays flat, and memory doesn't grow without bound.
Usage: python tools/test_hardening.py
"""
import copy
import random
import sys
import time
import gc

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

import mechfight as mf  # noqa: E402
from main import Bot  # noqa: E402

OPTIONAL_ACTOR = ("hp", "max_hp", "vel", "aim", "weapons", "cubes", "charging")


def sparse(obs, rng):
    o = copy.deepcopy(obs)
    for m in o["mechs"]:
        for k in OPTIONAL_ACTOR:
            if rng.random() < 0.5:
                m.pop(k, None)
        m["future_field"] = {"x": 1}
    o["future_top_level"] = [1, 2, 3]
    o["self"]["future_self"] = True
    for key in ("projectiles", "crates", "cubes", "pickups", "sounds", "beams", "events"):
        if rng.random() < 0.2:
            o[key] = []
    return o


def check_sparse(hello, observations):
    rng = random.Random(11)
    bot = Bot(hello)
    for obs in observations:
        mf.draw.clear()
        act = bot.act(sparse(obs, rng))
        assert act["tick"] == obs["tick"]
    assert bot.errors == 0, f"{bot.errors} decision errors on sparse observations"
    print("sparse observations: PASS")


def full_match(hello, observations):
    """Loop the replay out to 8 minutes, shifting time/tick and walking the zone through its phases."""
    radii = [560, 380, 240, 140, 70, 25, 0]
    bot = Bot(hello)
    times, mem = [], []
    n = len(observations)
    for k in range(4800):
        o = copy.deepcopy(observations[k % n])
        t = k * 0.1
        o["t"], o["tick"] = t, 2 * k
        phase = min(int(t // 65), len(radii) - 2)
        z = o["zone"]
        z["radius"], z["next_radius"] = radii[phase], radii[phase + 1]
        z["center"], z["next_center"] = [0.0, 0.0], [0.0, 0.0]
        z["shrink_start"], z["shrink_end"] = phase * 65 + 30, phase * 65 + 60
        o["alive"] = max(2, 16 - k // 400)
        mf.draw.clear()
        t0 = time.perf_counter()
        bot.act(o)
        times.append((time.perf_counter() - t0) * 1000)
        if k % 600 == 0:
            mem.append(len(gc.get_objects()))
    assert bot.errors == 0, f"{bot.errors} decision errors over a full match"
    first, last = sorted(times[:600]), sorted(times[-600:])
    p99 = lambda xs: xs[int(0.99 * len(xs))]
    print(f"full match: p99 first minute {p99(first):.1f} ms, last minute {p99(last):.1f} ms, "
          f"max {max(times):.1f} ms; GC-tracked objects by minute {mem}")
    assert p99(last) < 25, "late-match ticks too slow"
    assert mem[-1] - mem[1] < 20000, "objects keep piling up"
    print("full match: PASS")


def main():
    hello, observations = load_stream(DEFAULT_STREAM)
    mf.draw.caps = hello["config"]["debug"]
    check_sparse(hello, observations)
    full_match(hello, observations)


if __name__ == "__main__":
    main()
