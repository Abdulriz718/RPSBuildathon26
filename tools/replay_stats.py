"""Per-mech stats from a mechreplay/1 file (the format play.joinbuilders.org's viewer loads with ?replay=).

Usage:
  python tools/replay_stats.py replays/mechanics-v2-16.jsonl.gz            # table for all mechs
  python tools/replay_stats.py replays/x.jsonl.gz --mech 3                  # + that mech's timeline

Columns:
  place, name, kills, dmg out / in, loadout, first weapon (s), death (s), killed with,
  cubes max, drops, hit% per weapon (hits / shots), median hit range (m), avg speed (m/s),
  boost %, roof % (feet > 3 m above terrain), zone % (avg distance to zone center / zone radius)
"""
import argparse
import gzip
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))


def load(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    header = next(l for l in lines if l.get("type") == "header")
    result = next((l for l in lines if l.get("type") == "result"), None)
    frames = [l for l in lines if "type" not in l]
    return header, frames, result


def analyse(header, frames, terrain=None):
    mf = header["fields"]["m"]
    I = {k: i for i, k in enumerate(mf)}
    hz = header["tick_hz"]
    pos_at = {}  # tick -> {id: (x, y, z)}
    shots = defaultdict(lambda: defaultdict(int))
    hits = defaultdict(lambda: defaultdict(int))
    hit_ranges = defaultdict(list)
    path = defaultdict(float)
    alive_ticks = defaultdict(int)
    boost = defaultdict(int)
    roof = defaultdict(int)
    zone_frac = defaultdict(list)
    last = {}
    timeline = defaultdict(list)
    for f in frames:
        t = f["t"]
        z = f.get("z")
        snap = {}
        for m in f.get("m", []):
            mid, x, y, zz = m[I["id"]], m[I["x"]], m[I["y"]], m[I["z"]]
            snap[mid] = (x, y, zz)
            alive_ticks[mid] += 1
            if m[I["flags"]] & 2:
                boost[mid] += 1
            if terrain is not None and zz - terrain(x, y) > 3:
                roof[mid] += 1
            if z:
                zone_frac[mid].append(math.hypot(x - z[0], y - z[1]) / max(z[2], 1.0))
            if mid in last:
                path[mid] += math.hypot(x - last[mid][0], y - last[mid][1])
            last[mid] = (x, y)
        pos_at[t] = snap
        for e in f.get("ev", []):
            k = e["e"]
            if k == "fire":
                shots[e["id"]][e["w"]] += 1
            elif k == "charge":
                shots[e["id"]]["laser"] += 1
            elif k == "zap":
                shots[e["id"]]["lightning"] += 1
            elif k == "hit" and e.get("src") is not None and e["src"] < 100 and e.get("w") != "zone":
                src, dst = e["src"], e["dst"]
                hits[src][e["w"]] += 1
                if dst < 100 and src in snap and dst in snap:
                    hit_ranges[src].append(math.dist(snap[src], snap[dst]))
            ts = t / hz
            if k == "death":
                timeline[e["id"]].append((ts, f"died, killed by {e.get('by')}"))
                if e.get("by") is not None:
                    timeline[e["by"]].append((ts, f"killed {e['id']}"))
            elif k == "weapon" and e.get("by") is not None:
                timeline[e["by"]].append((ts, f"{e['op']} {e['kind']} (slot {e.get('slot')})"))
            elif k == "upgrade":
                timeline[e["id"]].append((ts, f"upgrade {e['up']}"))
            elif k in ("pickup", "crate") and e.get("by") is not None:
                timeline[e["by"]].append((ts, "cube" if k == "pickup" else f"broke crate {e['id']}"))
            elif k == "drop" and e.get("op") == "take":
                timeline[e["by"]].append((ts, f"captured drop {e['id']}"))
    dt = header["frame_every"] / hz
    out = {}
    for mid in alive_ticks:
        n = alive_ticks[mid]
        out[mid] = {
            "shots": dict(shots[mid]), "hits": dict(hits[mid]),
            "range": statistics.median(hit_ranges[mid]) if hit_ranges[mid] else None,
            "speed": path[mid] / max(n * dt, 1e-9),
            "boost": 100 * boost[mid] / n, "roof": 100 * roof[mid] / n,
            "zone": statistics.mean(zone_frac[mid]) if zone_frac[mid] else None,
        }
    return out, timeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("--mech", type=int, help="also print this mech's timeline")
    args = ap.parse_args()
    header, frames, result = load(args.replay)
    terrain = None
    try:
        from world import World
        w = World(str(ROOT / "arena"))
        terrain = w.ground
    except Exception as e:  # noqa: BLE001
        print(f"(no roof stats: {e})")
    stats, timeline = analyse(header, frames, terrain)
    res = {m["id"]: m for m in (result or {}).get("mechs", [])}
    names = {m["id"]: m["name"] for m in header["mechs"]}
    print(f"{header['format']} seed {header['seed']} | {len(frames)} frames | "
          f"{frames[-1]['t'] / header['tick_hz']:.0f} s | bots: {', '.join(sorted(set(header.get('bots', []))))}")
    hdr = (f"{'pl':>2} {'id':>2} {'name':<10} {'K':>2} {'dmgOut':>6} {'dmgIn':>6} {'loadout':<16} {'1stW':>5} "
           f"{'death':>5} {'killedWith':<10} {'cub':>3} {'drp':>3} {'hit% gun/las/lig/mor':<22} {'rng':>4} "
           f"{'spd':>4} {'bst%':>4} {'roof%':>5} {'zone':>4}")
    print(hdr)
    print("-" * len(hdr))
    order = sorted(stats, key=lambda i: res.get(i, {}).get("place", 99))
    for mid in order:
        r, s = res.get(mid, {}), stats[mid]
        hp = []
        for wk in ("gun", "laser", "lightning", "mortar"):
            n = s["shots"].get(wk, 0)
            hp.append(f"{100 * s['hits'].get(wk, 0) / n:.0f}" if n else "-")
        fw = r.get("first_weapon_t")
        print(f"{r.get('place', '?'):>2} {mid:>2} {names.get(mid, '?'):<10} {r.get('kills', 0):>2} "
              f"{r.get('damage_dealt', 0):>6} {r.get('damage_taken', 0):>6} {'+'.join(r.get('loadout', [])):<16} "
              f"{fw if fw is not None else '-':>5} {r.get('death_t') or 'alive':>5} {r.get('killed_with') or '-':<10} "
              f"{r.get('cubes_max', 0):>3} {r.get('drops_taken', 0):>3} {'/'.join(hp):<22} "
              f"{s['range'] or 0:>4.0f} {s['speed']:>4.1f} {s['boost']:>4.0f} {s['roof']:>5.0f} "
              f"{s['zone'] if s['zone'] is not None else 0:>4.2f}")
    if args.mech is not None:
        print(f"\ntimeline for mech {args.mech} ({names.get(args.mech)}), upgrades {res.get(args.mech, {}).get('upgrades')}")
        for t, what in sorted(timeline[args.mech]):
            print(f"  {t:6.1f}s  {what}")


if __name__ == "__main__":
    main()
