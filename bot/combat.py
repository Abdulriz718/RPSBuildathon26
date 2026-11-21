"""Aiming, weapon use, dodging. Owner: B. Phase 0: aim straight at target, hold both triggers."""
import math

import config


def engage(me, target, world) -> dict:
    """Partial action for fighting `target`: aim and fire. Phase 1: lead, LOS, reload, weapon choice."""
    x, y, z = me["pos"]
    t = target.pos
    yaw = math.atan2(t[1] - y, t[0] - x)
    pitch = math.atan2(t[2] - z - config.AIM_Z_OFFSET, math.dist(t[:2], (x, y)))
    return {"aim": [yaw, pitch], "fire": [True, True]}
