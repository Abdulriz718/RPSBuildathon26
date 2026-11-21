"""Pickups, crates, cubes, upgrades. Owner: B."""
import math

import config
from track import Target


def take_nearby(obs, reach: float):
    """Id of a pickup we should take this tick, or None. Phase 0: any non-gun weapon into an empty slot."""
    me = obs["self"]
    if me["weapons"][1] is not None:
        return None
    x, y, z = me["pos"]
    held = {w["kind"] for w in me["weapons"] if w}
    for p in obs["pickups"]:
        if (p["kind"] not in held and p["kind"] != "gun"
                and abs(p["pos"][2] - z) <= config.LOOT_VERTICAL_REACH_M
                and math.dist(p["pos"][:2], (x, y)) <= reach):
            return p["id"]
    return None


def in_next_zone(zone, point):
    return math.dist(zone["next_center"], point[:2]) <= max(
        0, zone["next_radius"] - config.LOOT_ZONE_MARGIN_M)


def want(obs, world):
    """Return an early loot opportunity within the next zone."""
    if obs["t"] >= config.LOOT_WINDOW_S:
        return None
    me = obs["self"]
    held = {w["kind"] for w in me["weapons"] if w}
    pos = me["pos"]
    candidates = []
    if None in me["weapons"]:
        candidates.extend((math.dist(pos, p["pos"]) - config.LOOT_PICKUP_BONUS_M, "pickup", p)
                          for p in obs["pickups"] if p["kind"] not in held and p["kind"] != "gun")
    candidates.extend((math.dist(pos, p["pos"]), "cube", p) for p in obs["cubes"])
    candidates.extend((math.dist(pos, p["pos"]), "crate", p) for p in obs["crates"]
                      if math.dist(pos, p["pos"]) <= config.LOOT_CRATE_RANGE_M)
    best = min(
        (item for item in candidates if in_next_zone(obs["zone"], item[2]["pos"])
         and abs(world.surface(*item[2]["pos"][:2]) - pos[2]) <= config.LOOT_VERTICAL_REACH_M),
        key=lambda item: (item[0], item[2]["id"]), default=None)
    return (best[1], best[2]) if best is not None else None


def crate_target(crate, dimensions):
    return Target(crate["id"], "crate", tuple(crate["pos"]), (0, 0, 0),
                  hp=crate["hp"], radius=dimensions["radius"], height=dimensions["height"])


def pick_upgrade(offer, me) -> int:
    """Prefer survivability, then upgrades for weapons currently held."""
    held = {w["kind"] for w in me["weapons"] if w}
    rank = {u: i for i, u in enumerate(config.UPGRADE_PRIORITY)
            if u.partition("_")[0] not in ("gun", "mortar", "laser", "lightning")
            or u.partition("_")[0] in held}
    choices = offer["choices"]
    return min(range(len(choices)), key=lambda i: rank.get(choices[i]["id"], len(rank)))
