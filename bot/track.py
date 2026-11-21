"""Track actors and recent attack bearings for one match."""

from dataclasses import dataclass, replace
from math import dist

import config

Vec3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class Target:
    id: int
    kind: str
    pos: Vec3
    vel: Vec3
    hp: float | None = None
    weapons: tuple[str, ...] = ()
    charging: bool = False
    aim: tuple[float, float] | None = None
    last_seen: float = 0.0
    age: float = 0.0
    radius: float = 2.5
    height: float = 9.0

    def predict(self, seconds: float) -> Vec3:
        return tuple(p + v * (self.age + seconds) for p, v in zip(self.pos, self.vel))


class Tracker:
    def __init__(self, rules):
        self.targets: dict[int, Target] = {}
        self.me_pos = (0.0, 0.0, 0.0)
        self.now = 0.0
        self.memory_s = rules["vision"]["memory_s"]
        self.mech = rules["mech"]
        self.npc = rules["npc"]
        self.size_per_cube = rules["cubes"]["size_per_cube"]
        self.last_damage: tuple[float, float] | None = None
        self.last_nearby_shot: tuple[float, float] | None = None

    def update(self, obs) -> None:
        self.me_pos = obs["self"]["pos"]
        self.now = obs["t"]
        for actor in obs["mechs"]:
            actor_id = actor["id"]
            old = self.targets.get(actor_id)
            pos = tuple(actor["pos"])
            velocity = actor.get("vel")
            if velocity is None:
                dt = self.now - old.last_seen if old else 0.0
                if 0 < dt <= config.TRACK_VELOCITY_GAP_S:
                    velocity = tuple((p - q) / dt for p, q in zip(pos, old.pos))
                else:
                    velocity = (0.0, 0.0, 0.0)
            dimensions = self.mech if actor["kind"] == "mech" else self.npc
            scale = 1 + actor.get("cubes", 0) * self.size_per_cube
            aim = actor.get("aim")
            self.targets[actor_id] = Target(
                id=actor_id, kind=actor["kind"], pos=pos, vel=tuple(velocity),
                hp=actor.get("hp"), weapons=tuple(actor.get("weapons", ())),
                charging=actor.get("charging", False),
                aim=tuple(aim) if aim is not None else None, last_seen=self.now,
                radius=dimensions["radius"] * scale, height=dimensions["height"] * scale,
            )

        for event in obs["events"]:
            if event["type"] == "kill":
                self.targets.pop(event["target"], None)
            elif event["type"] == "damaged" and event.get("bearing") is not None:
                self.last_damage = (self.now, event["bearing"])
        for sound in obs["sounds"]:
            if sound["dist"] != "near" or sound["kind"] not in config.TRACK_SHOT_SOUNDS:
                continue
            at = self.now - sound["age"]
            if self.last_nearby_shot is None or at > self.last_nearby_shot[0]:
                self.last_nearby_shot = (at, sound["bearing"])

        self.targets = {key: target for key, target in self.targets.items()
                        if self.now - target.last_seen <= self.memory_s}

    def targets_sorted(self, kind: str = "mech", *, max_age: float | None = None) -> list[Target]:
        """Prefer current reports, nearest first, then recently lost tracks."""
        if max_age is None:
            max_age = self.memory_s
        candidates = (replace(target, age=self.now - target.last_seen)
                      for target in self.targets.values()
                      if target.kind == kind and self.now - target.last_seen <= max_age)
        return sorted(candidates, key=lambda target: (target.age > 0, dist(target.predict(0), self.me_pos)))

    def threat_bearing(self) -> float | None:
        if self.last_damage is not None:
            at, bearing = self.last_damage
            if self.now - at < config.HURT_LOOK_S:
                return bearing
        if self.last_nearby_shot is not None:
            at, bearing = self.last_nearby_shot
            if self.now - at < config.TRACK_SOUND_LOOK_S:
                return bearing
        return None
