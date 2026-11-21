"""Static map model: terrain height, buildings, line of sight. Owner: A."""
import json
import os
import sys

import numpy as np


class World:
    @classmethod
    def load(cls, map_dir: str):
        """Try the given dir, then /arena. Never raise: a bot without a map still plays."""
        for d in (map_dir, "/arena"):
            try:
                return cls(d)
            except Exception as e:  # noqa: BLE001
                print(f"map load failed from {d!r}: {e}", file=sys.stderr, flush=True)
        return FlatWorld()

    def __init__(self, map_dir: str):
        with open(os.path.join(map_dir, "v2", "world.json")) as f:
            w = json.load(f)
        t = w["terrain"]
        self.min_x, self.min_y = t["minX"], t["minY"]
        self.step, self.nx, self.ny = t["step"], t["nx"], t["ny"]
        raw = np.fromfile(os.path.join(map_dir, "v2", t["file"]), dtype="<i2")
        self.terrain = raw.reshape(self.ny, self.nx).astype(np.float32) * t.get("scale", 0.01)
        self.prisms = w["prisms"]
        self.bounds = w["bounds"]

    def ground(self, x: float, y: float) -> float:
        """Terrain height at (x, y), bilinear. Ignores buildings."""
        fx = min(max((x - self.min_x) / self.step, 0.0), self.nx - 1.001)
        fy = min(max((y - self.min_y) / self.step, 0.0), self.ny - 1.001)
        i, j = int(fx), int(fy)
        dx, dy = fx - i, fy - j
        h = self.terrain
        return float(
            h[j, i] * (1 - dx) * (1 - dy) + h[j, i + 1] * dx * (1 - dy)
            + h[j + 1, i] * (1 - dx) * dy + h[j + 1, i + 1] * dx * dy
        )

    def los(self, a, b) -> bool:
        """Line of sight between two 3D points. Stub: always True until the height grid lands (Phase 1)."""
        return True


class FlatWorld:
    """Fallback when the map can't be read: flat ground, everything visible."""

    def ground(self, x: float, y: float) -> float:
        return 0.0

    def los(self, a, b) -> bool:
        return True
