"""Enemy tracking: positions, velocity, last seen. Owner: B."""
import math
from dataclasses import dataclass, field


@dataclass
class Target:
    id: int
    kind: str  # "mech" | "npc"
    pos: list
    vel: list
    hp: float
    weapons: list = field(default_factory=list)
    charging: bool = False
    aim: list = field(default_factory=lambda: [0.0, 0.0])
    last_seen: float = 0.0


class Tracker:
    def __init__(self):
        self.targets: dict[int, Target] = {}
        self.me_pos = [0.0, 0.0, 0.0]

    def update(self, obs) -> None:
        self.me_pos = obs["self"]["pos"]
        t = obs["t"]
        seen = {}
        for m in obs["mechs"]:
            seen[m["id"]] = Target(
                id=m["id"], kind=m["kind"], pos=m["pos"], vel=m.get("vel", [0, 0, 0]),
                hp=m.get("hp", 0), weapons=m.get("weapons", []), charging=m.get("charging", False),
                aim=m.get("aim", [0.0, 0.0]), last_seen=t,
            )
        self.targets = seen  # Phase 1: keep memory of unseen targets, sounds

    def targets_sorted(self, kind: str = "mech") -> list:
        """Nearest first."""
        return sorted(
            (x for x in self.targets.values() if x.kind == kind),
            key=lambda x: math.dist(x.pos, self.me_pos),
        )
