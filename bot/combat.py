"""Phase 1 aiming, firing, and reload decisions for the arm gun."""

from math import asin, atan2, cos, dist, hypot, pi, remainder, sqrt

import config


def intercept_time(relative, velocity, speed, exit_offset=0.0):
    """Solve |relative + velocity*t| = speed*t + exit_offset for the first hit."""
    a = sum(v * v for v in velocity) - speed**2
    b = 2 * (sum(p * v for p, v in zip(relative, velocity)) - speed * exit_offset)
    c = sum(p * p for p in relative) - exit_offset**2
    if c <= 0:
        return 0.0
    if abs(a) < 1e-9:
        return -c / b if b < 0 else None
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return None
    root = sqrt(discriminant)
    return min((t for t in ((-b - root) / (2 * a), (-b + root) / (2 * a)) if t >= 0),
               default=None)


def aim_at(origin, point):
    dx, dy, dz = (p - q for p, q in zip(point, origin))
    return [atan2(dy, dx), atan2(dz, hypot(dx, dy))]


def engage(me, target, world, *, sim_step=0.0):
    """Return a partial action. The brain chooses a target and handles movement."""
    action = {"fire": [False, False]}
    gun = next(((slot, weapon) for slot, weapon in enumerate(me["weapons"])
                if weapon and weapon["kind"] == "gun"), None)
    shooter = me["stats"]
    muzzle = (*me["pos"][:2], me["pos"][2] + shooter["muzzle_height"])
    if target is not None:
        tx, ty, tz = target.predict(0)
        center = (tx, ty, tz + target.height / 2)
        action["aim"] = aim_at(muzzle, center)

    if gun is None:
        return action
    slot, weapon = gun
    stats = weapon["stats"]
    can_reload = weapon["reload"] <= 0 and weapon["ammo"] < stats["mag"]
    if target is None or target.age or not world.los(muzzle, center):
        if can_reload:
            action["reload"] = True
        return action

    offset = shooter["radius"] + 0.5
    future_center = tuple(p + v * sim_step for p, v in zip(center, target.vel))
    relative = tuple(p - q for p, q in zip(future_center, muzzle))
    flight = intercept_time(relative, target.vel, stats["speed"], offset)
    if flight is None or flight * stats["speed"] > stats["range"]:
        if can_reload:
            action["reload"] = True
        return action
    lead = tuple(p + v * flight for p, v in zip(future_center, target.vel))
    if not world.los(muzzle, lead):
        if can_reload:
            action["reload"] = True
        return action

    aim = aim_at(muzzle, lead)
    if not shooter["min_pitch"] <= aim[1] <= shooter["max_pitch"]:
        return action
    action["aim"] = aim
    tolerance = asin(min(1.0, config.GUN_AIM_FRACTION * min(target.radius, target.height / 2)
                         / max(dist(muzzle, lead), 1.0)))
    yaw_error = remainder(aim[0] - me["aim"][0], 2 * pi) * cos(aim[1])
    pitch_error = aim[1] - me["aim"][1]
    # The trigger uses actual torso aim. Keep it closed while the torso slews.
    action["fire"][slot] = (weapon["ammo"] > 0 and weapon["reload"] <= 0
                            and hypot(yaw_error, pitch_error) <= tolerance)
    return action
