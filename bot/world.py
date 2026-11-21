"""Static map model: terrain height, buildings, line of sight. Owner: A."""
import math
import sys

import numpy as np

import gridbuild

LOS_STEP = 1.0  # m between samples along a sight line


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
        g = gridbuild.build(map_dir)
        self.min_x, self.min_y, self.step, nx, ny = g["meta"]
        self.nx, self.ny = int(nx), int(ny)
        self.terrain = g["terrain"]
        self.solid = g["solid"]  # top of grounded solids, else terrain
        self.ob, self.ot = g["ob"], g["ot"]  # overhead band
        self.max_x = self.min_x + (self.nx - 1) * self.step
        self.max_y = self.min_y + (self.ny - 1) * self.step

    # ---- point queries -------------------------------------------------
    def cell(self, x: float, y: float):
        i = int((x - self.min_x) / self.step + 0.5)
        j = int((y - self.min_y) / self.step + 0.5)
        if i < 0:
            i = 0
        elif i >= self.nx:
            i = self.nx - 1
        if j < 0:
            j = 0
        elif j >= self.ny:
            j = self.ny - 1
        return i, j

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

    def surface(self, x: float, y: float) -> float:
        """Highest grounded surface at (x, y): roof top or terrain."""
        i, j = self.cell(x, y)
        return self.solid.item(j, i)

    def in_bounds(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    # ---- sight lines ---------------------------------------------------
    def _blocked(self, a, b):
        """Bool array over samples from a to b: True where the segment is inside solid."""
        ax, ay, az = a
        bx, by, bz = b
        n = max(2, int(math.dist(a, b) / LOS_STEP) + 1)
        s = np.linspace(0.0, 1.0, n)[1:-1]  # skip both endpoints (they sit on mechs)
        xs, ys, zs = ax + (bx - ax) * s, ay + (by - ay) * s, az + (bz - az) * s
        i = np.clip(np.rint((xs - self.min_x) / self.step).astype(np.int32), 0, self.nx - 1)
        j = np.clip(np.rint((ys - self.min_y) / self.step).astype(np.int32), 0, self.ny - 1)
        return (zs < self.solid[j, i]) | ((zs >= self.ob[j, i]) & (zs <= self.ot[j, i])), s

    def los(self, a, b) -> bool:
        """True if nothing solid (building, terrain, bridge) is between 3D points a and b. Trees ignored."""
        blocked, _ = self._blocked(a, b)
        return not blocked.any()

    def ray_hit(self, a, b):
        """Fraction 0..1 along a->b of the first solid sample, or None if clear."""
        blocked, s = self._blocked(a, b)
        idx = np.flatnonzero(blocked)
        return float(s[idx[0]]) if idx.size else None


class FlatWorld:
    """Fallback when the map can't be read: flat ground, everything visible."""

    min_x, min_y, max_x, max_y = -512.0, -333.0, 555.0, 388.0

    def ground(self, x: float, y: float) -> float:
        return 0.0

    def surface(self, x: float, y: float) -> float:
        return 0.0

    def in_bounds(self, x: float, y: float) -> bool:
        return True

    def los(self, a, b) -> bool:
        return True

    def ray_hit(self, a, b):
        return None
