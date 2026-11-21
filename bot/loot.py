"""Pickups, crates, cubes, upgrades. Owner: B."""
import math

import config


def take_nearby(obs, reach: float):
    """Id of a pickup we should take this tick, or None. Phase 0: any non-gun weapon into an empty slot."""
    me = obs["self"]
    if me["weapons"][1] is not None:
        return None
    x, y = me["pos"][0], me["pos"][1]
    held = {w["kind"] for w in me["weapons"] if w}
    for p in obs["pickups"]:
        if p["kind"] not in held and p["kind"] != "gun" and math.dist(p["pos"][:2], (x, y)) < reach:
            return p["id"]
    return None


def want(obs):
    """A loot goal [x, y] worth walking to, or None. Phase 2."""
    return None


def pick_upgrade(offer) -> int:
    """Index into offer['choices'] by config.UPGRADE_PRIORITY."""
    rank = {u: i for i, u in enumerate(config.UPGRADE_PRIORITY)}
    choices = offer["choices"]
    return min(range(len(choices)), key=lambda i: rank.get(choices[i]["id"], len(rank)))
