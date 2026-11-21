"""Rasterize world.json + terrain.i16 into 1 m grids. Run at docker build (tools/build_grids.py);
world.py falls back to running it at hello if the .npz is missing.

Grids (shape ny x nx, row j = y, col i = x, cell center at min + (i, j) * step):
  terrain  ground height (m)
  solid    top of the highest solid standing on the ground in this cell, else terrain
  ob, ot   overhead band (bridge / overhang): base and top, or +inf/-inf if none
"""
import json
import os

import numpy as np

GROUND_TOL = 1.0  # a prism whose base is within this of the terrain stands on the ground


def _poly_mask(xs, ys, flat):
    """Even-odd point-in-polygon for a grid of cell centers (xs: 1D, ys: 1D)."""
    px = np.asarray(flat[0::2], dtype=np.float64)
    py = np.asarray(flat[1::2], dtype=np.float64)
    X, Y = np.meshgrid(xs, ys)
    inside = np.zeros(X.shape, dtype=bool)
    n = len(px)
    for k in range(n):
        x1, y1, x2, y2 = px[k], py[k], px[(k + 1) % n], py[(k + 1) % n]
        if y1 == y2:
            continue
        cond = (y1 > Y) != (y2 > Y)
        xint = x1 + (Y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= cond & (X < xint)
    return inside


def build(map_dir: str) -> dict:
    with open(os.path.join(map_dir, "v2", "world.json")) as f:
        w = json.load(f)
    t = w["terrain"]
    nx, ny, step = t["nx"], t["ny"], t["step"]
    min_x, min_y = t["minX"], t["minY"]
    raw = np.fromfile(os.path.join(map_dir, "v2", t["file"]), dtype="<i2")
    terrain = raw.reshape(ny, nx).astype(np.float32) * float(t.get("scale", 0.01))

    solid = terrain.copy()
    ob = np.full((ny, nx), np.inf, dtype=np.float32)
    ot = np.full((ny, nx), -np.inf, dtype=np.float32)

    for p in w["prisms"]:
        ring = p["ring"]
        rx, ry = ring[0::2], ring[1::2]
        i0 = max(0, int(np.floor((min(rx) - min_x) / step)))
        i1 = min(nx - 1, int(np.ceil((max(rx) - min_x) / step)))
        j0 = max(0, int(np.floor((min(ry) - min_y) / step)))
        j1 = min(ny - 1, int(np.ceil((max(ry) - min_y) / step)))
        if i1 < i0 or j1 < j0:
            continue
        xs = min_x + np.arange(i0, i1 + 1) * step
        ys = min_y + np.arange(j0, j1 + 1) * step
        m = _poly_mask(xs, ys, ring)
        hole = p.get("holes") or []
        if hole and isinstance(hole[0], (int, float)):
            hole = [hole]
        for h in hole:
            m &= ~_poly_mask(xs, ys, h)
        if not m.any():
            continue
        sl = (slice(j0, j1 + 1), slice(i0, i1 + 1))
        base, top = float(p["base"]), float(p["top"])
        grounded = m & (base <= terrain[sl] + GROUND_TOL)
        over = m & ~grounded
        solid[sl] = np.where(grounded, np.maximum(solid[sl], top), solid[sl])
        ob[sl] = np.where(over, np.minimum(ob[sl], base), ob[sl])
        ot[sl] = np.where(over, np.maximum(ot[sl], top), ot[sl])

    meta = np.array([min_x, min_y, step, nx, ny], dtype=np.float64)
    return {"terrain": terrain, "solid": solid, "ob": ob, "ot": ot, "meta": meta}


def save(grids: dict, path: str) -> None:
    np.savez_compressed(path, **grids)
