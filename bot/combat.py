"""Phase 1 aiming, firing, and reload decisions for the arm gun."""

from math import asin, atan2, ceil, cos, dist, hypot, pi, radians, remainder, sin, sqrt

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


def _direction(aim):
    yaw, pitch = aim
    return cos(yaw) * cos(pitch), sin(yaw) * cos(pitch), sin(pitch)


def _aligned(actual, wanted, tolerance, yaw_only=False):
    yaw = remainder(actual[0] - wanted[0], 2 * pi)
    if yaw_only:
        return abs(yaw) <= tolerance
    return hypot(yaw * cos(wanted[1]), actual[1] - wanted[1]) <= tolerance


def ballistic_pitches(horizontal, dz, speed, gravity):
    if horizontal <= 0:
        return ()
    speed2 = speed**2
    radicand = speed2**2 - gravity * (gravity * horizontal**2 + 2 * dz * speed2)
    if radicand < 0:
        return ()
    root = sqrt(radicand)
    return (atan2(speed2 - root, gravity * horizontal),
            atan2(speed2 + root, gravity * horizontal))


def mortar_aim(me, target, world, stats):
    """Try both arcs, rejecting blocked trajectories and nearby impact points."""
    if target.age > config.MORTAR_MAX_TRACK_AGE_S:
        return None
    shooter = me["stats"]
    origin = (*me["pos"][:2], me["pos"][2] + shooter["height"] + 0.5)
    speed, gravity = stats["speed"], stats["gravity"]
    offset = shooter["radius"] + 0.5
    safe = stats["splash_radius"] + shooter["radius"] + config.DODGE_BUFFER_M
    # Stationary targets can justify a high arc with a long flight time.
    moving = target.age > 0 or hypot(*target.vel[:2]) > config.MORTAR_STATIONARY_SPEED
    max_flight = min(stats["ttl"], config.MORTAR_MOVING_FLIGHT_S) if moving else stats["ttl"]
    for arc in (0, 1):
        flight = dz_correction = 0.0
        for _ in range(config.MORTAR_SOLVE_PASSES):
            x, y, z = target.predict(flight)
            horizontal = hypot(x - origin[0], y - origin[1])
            if horizontal <= safe:
                break
            dz = z + target.height / 2 - origin[2]
            pitches = ballistic_pitches(horizontal, dz - dz_correction, speed, gravity)
            if not pitches:
                break
            pitch = pitches[arc]
            total = horizontal / (speed * cos(pitch))
            flight = max(0.0, total - offset / speed)
            dz_correction = gravity * (total**2 - flight**2) / 2
        else:
            if flight > max_flight or not shooter["min_pitch"] <= pitch <= shooter["max_pitch"]:
                continue
            impact = (x, y, z + target.height / 2)
            future_self = tuple(p + v * flight for p, v in zip(me["pos"], me["vel"]))
            if dist(future_self[:2], impact[:2]) <= safe:
                continue
            aim = [atan2(y - origin[1], x - origin[0]), pitch]
            direction = _direction(aim)
            segments = max(1, ceil(speed * flight / config.MORTAR_SEGMENT_M))
            previous = origin
            for n in range(segments + 1):
                t = flight * n / segments
                px, py, pz = (p + d * (offset + speed * t) for p, d in zip(origin, direction))
                point = (px, py, pz - gravity * t**2 / 2)
                if not world.los(previous, point):
                    break
                previous = point
            else:
                expected = target.predict(flight)
                expected_center = (*expected[:2], expected[2] + target.height / 2)
                if dist(previous, expected_center) <= config.MORTAR_PATH_TOLERANCE_M:
                    return aim, atan2(target.radius * config.GUN_AIM_FRACTION, offset + speed * flight)
    return None


class Weapons:
    def __init__(self, rules):
        self.rules = rules
        self.sim_step = 1 / rules["match"]["tick_hz"]
        self.decision_s = self.sim_step * rules["match"]["decide_every"]
        self.shorted_until = 0.0
        self.charge_started = None
        self.now = 0.0

    def update(self, obs):
        self.now = obs["t"]
        charge = next((w["charge"] for w in obs["self"]["weapons"]
                       if w and w.get("charge")), 0.0)
        if not charge:
            self.charge_started = None
        elif self.charge_started is None:
            self.charge_started = self.now - charge
        if any(e["type"] == "effect" and e.get("effect") == "short" for e in obs["events"]):
            self.shorted_until = self.now + self.rules["weapons"]["lightning"]["short_s"]
            self.charge_started = None

    def _score(self, kind, stats, target):
        cycle = stats["cooldown"] + stats.get("charge", 0)
        damage = stats["damage"] + stats.get("splash", 0)
        if kind == "gun":
            cycle += stats["reload"] / stats["mag"]
        if config.COUNTERS.get(kind) in target.weapons:
            damage *= config.COUNTER_BONUS
        if any(config.COUNTERS.get(held) == kind for held in target.weapons):
            damage *= config.COUNTER_PENALTY
        if kind == "laser" and "mortar" in target.weapons:
            damage *= 1 + stats["cookoff"]
        return damage / cycle

    def decide(self, me, target, world):
        action = engage(me, target, world, sim_step=self.sim_step)
        muzzle = (*me["pos"][:2], me["pos"][2] + me["stats"]["muzzle_height"])
        primary = None
        for slot, weapon in enumerate(me["weapons"]):
            if not weapon:
                continue
            kind, stats = weapon["kind"], weapon["stats"]
            charge = weapon.get("charge", 0)
            if kind == "laser" and self.now < self.shorted_until:
                continue
            if charge:
                elapsed = charge if self.charge_started is None else max(charge, self.now - self.charge_started)
                can_hold = elapsed + self.decision_s < stats["charge"] + stats["hold_s"]
                action["fire"][slot] = can_hold
            if target is None or (weapon["cooldown"] > self.decision_s and not charge):
                continue
            if kind == "gun":
                if action["fire"][slot]:
                    shot = (self._score(kind, stats, target), action["aim"], True)
                else:
                    continue
            elif kind == "mortar":
                solution = mortar_aim(me, target, world, stats)
                if solution is None:
                    continue
                aim, tolerance = solution
                shot = (self._score(kind, stats, target), aim, _aligned(me["aim"], aim, tolerance))
            else:
                x, y, z = target.predict(config.LASER_LEAD_S)
                point = (x, y, z + target.height / 2)
                distance = dist(muzzle, point)
                if target.age or distance > stats["range"] or not world.los(muzzle, point):
                    if charge:
                        return action
                    continue
                aim = aim_at(muzzle, point)
                if kind == "lightning":
                    if me["energy"] < stats["energy"]:
                        continue
                    tolerance = radians(stats["cone_deg"]) / 2
                    shot = (self._score(kind, stats, target), aim,
                            _aligned(me["aim"], aim, tolerance, yaw_only=True))
                else:
                    if not charge and abs(target.vel[2]) > config.LASER_MAX_VERTICAL_SPEED:
                        continue
                    if not me["stats"]["min_pitch"] <= aim[1] <= me["stats"]["max_pitch"]:
                        continue
                    tolerance = asin(min(1, target.radius * config.GUN_AIM_FRACTION
                                         / max(distance, 1.0)))
                    aligned = _aligned(me["aim"], aim, tolerance)
                    if charge:
                        action.update(aim=aim, fire=[False, False])
                        action["fire"][slot] = can_hold and not (charge >= stats["charge"] and aligned)
                        return action
                    shot = (self._score(kind, stats, target), aim, aligned)
            if primary is None or shot[0] > primary[0]:
                primary = (*shot, slot)
        if primary is not None:
            _, aim, fire, slot = primary
            action["aim"] = aim
            action["fire"] = [False, False]
            action["fire"][slot] = fire
        return action

    def dodge(self, obs, target, world):
        """Return a perpendicular unit direction and whether a shot is imminent."""
        me = obs["self"]
        x, y, z = me["pos"]
        vx, vy, vz = me["vel"]
        center = (x, y, z + me["stats"]["height"] / 2)
        radius = me["stats"]["radius"] + config.DODGE_BUFFER_M
        incoming = None
        soonest = config.DODGE_LOOKAHEAD_S
        for projectile in obs["projectiles"]:
            px, py, pz = projectile["pos"]
            wx, wy, wz = projectile["vel"]
            dx, dy = wx - vx, wy - vy
            speed2 = dx * dx + dy * dy
            eta = ((x - px) * dx + (y - py) * dy) / speed2 if speed2 else 0.0
            if not 0 <= eta < soonest:
                continue
            margin = radius
            if projectile["kind"] == "mortar":
                mortar = self.rules["weapons"]["mortar"]
                pz -= mortar["gravity"] * eta**2 / 2
                margin += mortar["splash_radius"]
            if (hypot(px - x + dx * eta, py - y + dy * eta) <= margin
                    and abs(pz - center[2] + (wz - vz) * eta) <= me["stats"]["height"] / 2 + margin
                    and world.los(projectile["pos"], center)):
                incoming = (dx, dy)
                soonest = eta
        if incoming is None:
            for actor in obs["mechs"]:
                if not actor.get("charging") or not actor.get("aim"):
                    continue
                ax, ay, az = actor["pos"]
                scale = 1 + actor.get("cubes", 0) * self.rules["cubes"]["size_per_cube"]
                origin = (ax, ay, az + self.rules["mech"]["muzzle_height"] * scale)
                dx, dy, dz = _direction(actor["aim"])
                delta = (x - ax, y - ay, center[2] - origin[2])
                along = delta[0] * dx + delta[1] * dy + delta[2] * dz
                if (0 < along <= self.rules["weapons"]["laser"]["range"]
                        and hypot(delta[0] - dx * along, delta[1] - dy * along) <= radius
                        and abs(delta[2] - dz * along) <= me["stats"]["height"] / 2
                        and world.los(origin, center)):
                    incoming = (dx, dy)
                    break
        urgent = incoming is not None
        if incoming is None and target is not None and target.kind == "mech" and not target.age:
            tx, ty, tz = target.pos
            if world.los(center, (tx, ty, tz + target.height / 2)):
                incoming = (tx - x, ty - y)
        if incoming is None or not (length := hypot(*incoming)):
            return None
        dx, dy = -incoming[1] / length, incoming[0] / length
        if vx * dx + vy * dy < 0:
            dx, dy = -dx, -dy
        return dx, dy, urgent
