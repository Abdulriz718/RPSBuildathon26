"""Score short escape lanes against visible shots, cover and nearby threats."""

from math import atan2, cos, dist, hypot, radians, sin, tan

import config


def _motion(me, move, boost, dt):
    x, y, z = me["pos"]
    vx, vy, vz = me["vel"]
    stats = me["stats"]
    speed = stats["boost_speed"] if boost and me["grounded"] else stats["walk_speed"]
    accel = stats["ground_accel"] if me["grounded"] else stats["air_accel"]
    for step in range(1, config.EVADE_STEPS + 1):
        dx, dy = speed * move[0] - vx, speed * move[1] - vy
        change = min(1.0, accel * dt / max(hypot(dx, dy), 1e-9))
        vx, vy = vx + dx * change, vy + dy * change
        x, y = x + vx * dt, y + vy * dt
        yield x, y, z + vz * dt * step


def _shots(obs, world, rules):
    me = obs["self"]
    center = (*me["pos"][:2], me["pos"][2] + me["stats"]["height"] / 2)
    shots = []
    for projectile in sorted(obs["projectiles"], key=lambda p: dist(p["pos"], center)):
        if len(shots) >= config.EVADE_MAX_PROJECTILES:
            break
        x, y, z = projectile["pos"]
        vx, vy, vz = projectile["vel"]
        if dist(projectile["pos"], center) > hypot(vx, vy, vz) * config.EVADE_HORIZON_S + me["stats"]["boost_speed"] * config.EVADE_HORIZON_S:
            continue
        mortar = projectile["kind"] == "mortar"
        gravity = rules["weapons"]["mortar"]["gravity"] if mortar else 0.0
        splash = rules["weapons"]["mortar"]["splash_radius"] if mortar else 0.0
        if not mortar and not world.los(projectile["pos"], center):
            continue
        shots.append((x, y, z, vx, vy, vz, gravity, splash))
    return shots


def _contact(path, shots, me, dt):
    radius = me["stats"]["radius"] + config.DODGE_BUFFER_M
    height = me["stats"]["height"]
    cost = 0.0
    for x, y, z, vx, vy, vz, gravity, splash in shots:
        previous = me["pos"]
        for step, point in enumerate(path, start=1):
            # Closest horizontal pass over the entire interval, including between bot ticks.
            start = (step - 1) * dt
            dx, dy = x + vx * start - previous[0], y + vy * start - previous[1]
            rx, ry = vx * dt - (point[0] - previous[0]), vy * dt - (point[1] - previous[1])
            along = min(1.0, max(0.0, -(dx * rx + dy * ry) / max(rx * rx + ry * ry, 1e-9)))
            t = start + along * dt
            shell_z = z + vz * t - gravity * t * t / 2
            feet = previous[2] + along * (point[2] - previous[2])
            if (hypot(dx + rx * along, dy + ry * along) <= radius + splash
                    and feet - splash <= shell_z <= feet + height + splash):
                cost += config.EVADE_CONTACT_WEIGHT * (1 + 1 / step)
                break
            previous = point
    return cost


def escape_move(obs, move, boost, tracks, bearing, world, nav, rules):
    me = obs["self"]
    x, y, _ = me["pos"]
    zone = obs["zone"]
    center = zone["center"]
    current_distance = dist((x, y), center)
    next_center = zone["next_center"]
    next_limit = max(zone["next_radius"], dist((x, y), next_center))
    yaw = atan2(move[1], move[0])
    dt = config.EVADE_HORIZON_S / config.EVADE_STEPS
    shots = _shots(obs, world, rules)
    threats = [enemy for enemy in tracks if dist(enemy.predict(0), me["pos"]) < config.EVADE_THREAT_RANGE_M]
    threats = threats[:config.EVADE_MAX_THREATS]
    if not shots and not threats and bearing is None:
        return move
    magnitude = hypot(*move)
    if magnitude == 0 and not shots:
        return move

    eyes = []
    muzzle = rules["mech"]["muzzle_height"]
    for enemy in threats:
        px, py, pz = enemy.predict(0)
        eye = (px, py, pz + muzzle)
        eyes.append((enemy, eye, dist((x, y), (px, py))))

    best = None
    for turn in config.EVADE_TURNS_DEG:
        angle = yaw + radians(turn)
        speed_fraction = magnitude or 1.0
        heading = (cos(angle) * speed_fraction, sin(angle) * speed_fraction)
        path = tuple(_motion(me, heading, boost, dt))
        end = path[-1]
        px, py, pz = end
        if (not world.in_bounds(px, py) or not nav.walkable_xy(px, py)
                or dist(end[:2], center) > max(zone["radius"], current_distance)
                or dist(end[:2], next_center) > next_limit
                or not world.los((x, y, me["pos"][2] + muzzle), (px, py, pz + muzzle))):
            continue
        score = _contact(path, shots, me, dt) + abs(turn) / 90
        for enemy, eye, original_range in eyes:
            separation = dist(end[:2], eye[:2])
            if separation < original_range:
                score += config.EVADE_ENEMY_WEIGHT * (original_range - separation) / max(original_range, 1)
            if not world.los(eye, (px, py, pz + me["stats"]["height"] / 2)):
                score -= config.EVADE_COVER_WEIGHT
                continue
            if enemy.age or enemy.aim is None:
                continue
            ax, ay = cos(enemy.aim[0]), sin(enemy.aim[0])
            target_x, target_y, target_z = path[len(path) // 2]
            dx, dy = target_x - eye[0], target_y - eye[1]
            along = dx * ax + dy * ay
            if (along > 0 and abs(dx * ay - dy * ax) <= me["stats"]["radius"] + config.DODGE_BUFFER_M
                    and abs(eye[2] + along * tan(enemy.aim[1]) - target_z - me["stats"]["height"] / 2)
                    <= me["stats"]["height"] / 2):
                score += config.EVADE_AIM_WEIGHT * (2 if enemy.charging else 1)
        if bearing is not None:
            score += config.EVADE_SOUND_WEIGHT * max(0, cos(angle - bearing))
        if best is None or score < best[0]:
            best = (score, heading)
    return move if best is None else best[1]
