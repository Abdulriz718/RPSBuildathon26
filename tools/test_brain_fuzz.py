"""Drive Brain.decide through every mode with mutated recorded observations. Any exception fails.
The recorded match never reaches drops, the late zone, FFA or held lasers/mortars, so we fake them.
Usage: python tools/test_brain_fuzz.py"""
import copy
import random
import time
import sys
import traceback
from collections import Counter

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

import config  # noqa: E402
import mechfight as mf  # noqa: E402
from brain import Brain  # noqa: E402

RULES = {}


def mutate(obs, rng):
    o = copy.deepcopy(obs)
    me = o["self"]
    if rng.random() < 0.5:
        kind = rng.choice(["laser", "mortar", "lightning"])
        stats = dict(RULES["weapons"][kind])
        me["weapons"][1] = {"kind": kind, "cooldown": rng.choice([0, 0.5]), "stats": stats,
                            "charge": rng.choice([0, 0, 0.3, 0.8]) if kind == "laser" else 0}
    if rng.random() < 0.4:
        me["hp"] = rng.uniform(50, me["max_hp"])
    if rng.random() < 0.3:
        o["t"] = rng.uniform(300, 470)
        o["alive"] = rng.randint(2, 6)
    if rng.random() < 0.15:
        z = o["zone"]
        z["next_radius"] = rng.choice([0, 25, 70, 140])
    if rng.random() < 0.4:
        p = [me["pos"][0] + rng.uniform(-80, 80), me["pos"][1] + rng.uniform(-80, 80), me["pos"][2]]
        o["drops"] = [{"id": 20000, "pos": p, "radius": 8, "lands_in": rng.choice([0, 3, 20]),
                       "capture_s": 4, "progress": 0, "holder": rng.choice([None, me["id"], 3])}]
    if rng.random() < 0.3:
        o["offer"] = {"id": 1, "expires": o["t"] + 5, "choices": [
            {"id": "armor", "name": "", "desc": ""}, {"id": "laser_damage", "name": "", "desc": ""},
            {"id": "zzz_new", "name": "", "desc": ""}]}
    if rng.random() < 0.3:
        o["events"] = list(o["events"]) + [{"type": "damaged", "amount": 50, "weapon": "gun",
                                            "bearing": 1.0, "by": rng.choice([None, 5, 99])}]
    if rng.random() < 0.2:
        o["mechs"] = []
    if rng.random() < 0.05:
        me["in_zone"] = False
    return o


def main():
    global RULES
    hello, observations = load_stream(DEFAULT_STREAM)
    RULES = hello["config"]
    mf.draw.caps = hello["config"]["debug"]
    rng = random.Random(7)
    modes, failures = Counter(), Counter()
    times = []
    for mode_setting in ("farm", "ffa"):
        config.MODE = mode_setting
        for run in range(4):
            brain = Brain(hello)
            for obs in observations:
                o = mutate(obs, rng)
                try:
                    t0 = time.perf_counter()
                    act = brain.decide(o)
                    times.append((time.perf_counter() - t0) * 1000)
                    assert isinstance(act.get("move"), list) and len(act["move"]) == 2
                    assert isinstance(act.get("aim"), list) and len(act["aim"]) == 2
                except Exception:  # noqa: BLE001
                    tb = traceback.format_exc().strip().splitlines()
                    failures[tb[-1]] += 1
                    if failures[tb[-1]] == 1:
                        print("\n".join(tb[-6:]))
                modes[(mode_setting, brain.mode)] += 1
                mf.draw.clear()
    print("modes reached:", dict(sorted(modes.items())))
    times.sort()
    print(f"decide ms: p99 {times[int(.99 * len(times))]:.1f}  max {times[-1]:.1f}")
    if times[int(.99 * len(times))] > 25:
        failures["p99 over 25 ms"] += 1
    if failures:
        sys.exit(f"FAIL: {sum(failures.values())} exceptions: {dict(failures)}")
    print("PASS: no exceptions")


if __name__ == "__main__":
    main()
