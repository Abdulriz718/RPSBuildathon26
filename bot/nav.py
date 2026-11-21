"""Pathfinding and movement. Owner: A.

A coarse grid (NAV_CELL m) over the map. A cell is walkable when no surface within the mech's radius
rises more than step_up above it (that would be a wall) and nothing overhead is lower than the mech.
Moves may go up at most NAV_MAX_UP per cell, and down any amount (dropping off a roof is fine).
A* runs incrementally: at most NAV_BUDGET_MS per tick, picking up where it left off on the next tick.
"""
import heapq
import math
import time

import numpy as np

import config

SQ2 = math.sqrt(2.0)
NEIGH = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]


class Nav:
    def __init__(self, world, mech_cfg=None):
        self.world = world
        mech_cfg = mech_cfg or {}
        self.step_up = float(mech_cfg.get("step_up", 1.2))
        self.radius = float(mech_cfg.get("radius", 2.5))
        self.height = float(mech_cfg.get("height", 9.0))
        self.ok = hasattr(world, "solid")
        self.path = []  # list of (x, y) waypoints
        self.goal = None
        self.search = None
        self.last_plan_t = -1e9
        self.hist = []  # (t, x, y) for stuck detection
        self.unstick_until = -1.0
        self.unstick_dir = (0.0, 0.0)
        if self.ok:
            self._build()

    # ---- grid ------------------------------------------------------------
    def _build(self):
        w = self.world
        s = w.solid
        r = int(math.ceil(self.radius))
        ny, nx = s.shape
        pad = np.pad(s, r, mode="edge")
        mx = s.copy()
        for dj in range(-r, r + 1):
            for di in range(-r, r + 1):
                if di * di + dj * dj <= r * r:
                    mx = np.maximum(mx, pad[r + dj:r + dj + ny, r + di:r + di + nx])
        wall = (mx - s) > self.step_up
        low_roof = (w.ob - s) < self.height
        blocked1 = wall | low_roof

        c = config.NAV_CELL
        k = int(round(c / w.step))
        self.k = k
        self.cnx, self.cny = (nx + k - 1) // k, (ny + k - 1) // k
        ci = np.minimum(np.arange(self.cnx) * k + k // 2, nx - 1)
        cj = np.minimum(np.arange(self.cny) * k + k // 2, ny - 1)
        self.H = s[np.ix_(cj, ci)].astype(np.float64)
        self.B = blocked1[np.ix_(cj, ci)]
        self.Hl = self.H.ravel().tolist()
        self.Bl = self.B.ravel().tolist()
        G = w.terrain[np.ix_(cj, ci)]
        self.roof = ((self.H - G) > 1.0).ravel().tolist()  # cell top is a roof, not ground
        self.ci, self.cj = ci, cj
        self.main = self._main_region()

    def _main_region(self):
        """Bool list: cell is in the largest region connected by walkable two-way moves."""
        n, Hl, Bl, up = self.cnx, self.Hl, self.Bl, config.NAV_MAX_UP
        lab = [-1] * len(Hl)
        sizes = []
        for s in range(len(Hl)):
            if Bl[s] or lab[s] >= 0:
                continue
            k = len(sizes)
            lab[s] = k
            q, c = [s], 0
            while q:
                cur = q.pop()
                c += 1
                ci, cj = cur % n, cur // n
                for di, dj, _ in NEIGH:
                    i, j = ci + di, cj + dj
                    if 0 <= i < n and 0 <= j < self.cny:
                        nb = j * n + i
                        if lab[nb] < 0 and not Bl[nb] and abs(Hl[nb] - Hl[cur]) <= up:
                            lab[nb] = k
                            q.append(nb)
            sizes.append(c)
        if not sizes:
            return [True] * len(Hl)
        big = max(range(len(sizes)), key=sizes.__getitem__)
        return [x == big for x in lab]

    def to_cell(self, x, y):
        w = self.world
        i = int((x - w.min_x) / (w.step * self.k))
        j = int((y - w.min_y) / (w.step * self.k))
        return min(max(i, 0), self.cnx - 1), min(max(j, 0), self.cny - 1)

    def to_xy(self, i, j):
        w = self.world
        return w.min_x + float(self.ci[i]) * w.step, w.min_y + float(self.cj[j]) * w.step

    def walkable_xy(self, x, y) -> bool:
        if not self.ok:
            return True
        i, j = self.to_cell(x, y)
        return not self.Bl[j * self.cnx + i]

    def nearest_walkable(self, x, y, max_r=20, ground_only=True):
        """Closest walkable (ground-level by default) cell center to (x, y), searching outward in rings."""
        if not self.ok:
            return x, y
        i0, j0 = self.to_cell(x, y)
        for r in range(max_r + 1):
            best = None
            for j in range(j0 - r, j0 + r + 1):
                for i in range(i0 - r, i0 + r + 1):
                    if max(abs(i - i0), abs(j - j0)) != r or not (0 <= i < self.cnx and 0 <= j < self.cny):
                        continue
                    c = j * self.cnx + i
                    if self.main[c] and not (ground_only and self.roof[c]):
                        d = (i - i0) ** 2 + (j - j0) ** 2
                        if best is None or d < best[0]:
                            best = (d, i, j)
            if best:
                return self.to_xy(best[1], best[2])
        return x, y

    # ---- A* --------------------------------------------------------------
    def _start_search(self, pos, goal):
        si, sj = self.to_cell(pos[0], pos[1])
        gx, gy = self.nearest_walkable(goal[0], goal[1])
        gi, gj = self.to_cell(gx, gy)
        n = self.cnx
        s, g = sj * n + si, gj * n + gi
        h0 = math.hypot(si - gi, sj - gj) * config.NAV_HEURISTIC_W
        self.search = {
            "open": [(h0, 0.0, s)], "g": {s: 0.0}, "came": {s: -1}, "goal": g,
            "gi": gi, "gj": gj, "best": (h0, s), "closed": set(), "expanded": 0,
        }

    def _step_search(self, budget_s):
        S = self.search
        n, Hl, Bl, up = self.cnx, self.Hl, self.Bl, config.NAV_MAX_UP
        openl, gs, came, closed = S["open"], S["g"], S["came"], S["closed"]
        goal, gi, gj = S["goal"], S["gi"], S["gj"]
        hw = config.NAV_HEURISTIC_W
        t_end = time.perf_counter() + budget_s
        while openl:
            if (S["expanded"] & 63) == 0 and time.perf_counter() > t_end:
                return False
            _, gc, cur = heapq.heappop(openl)
            if cur in closed:
                continue
            closed.add(cur)
            S["expanded"] += 1
            if cur == goal:
                S["best"] = (0.0, cur)
                return True
            ci, cj = cur % n, cur // n
            hc = Hl[cur]
            for di, dj, cost in NEIGH:
                i, j = ci + di, cj + dj
                if i < 0 or j < 0 or i >= n or j >= self.cny:
                    continue
                nb = j * n + i
                dh = Hl[nb] - hc
                if dh > up or (Bl[nb] and dh > -config.NAV_DROP):
                    continue
                if di and dj and (Bl[cj * n + i] or Bl[j * n + ci]):
                    continue  # no corner cutting past walls
                ng = gc + cost
                if ng < gs.get(nb, 1e18):
                    gs[nb] = ng
                    came[nb] = cur
                    h = math.hypot(i - gi, j - gj) * hw
                    if h < S["best"][0]:
                        S["best"] = (h, nb)
                    heapq.heappush(openl, (ng + h, ng, nb))
            if S["expanded"] > config.NAV_MAX_EXPAND:
                return True
        return True  # open set empty: goal unreachable, use best

    def _finish_search(self):
        S = self.search
        node = S["best"][1]
        n, came = self.cnx, S["came"]
        cells = []
        while node != -1:
            cells.append(node)
            node = came[node]
        cells.reverse()
        self.path = [self.to_xy(c % n, c // n) for c in cells[1:]]
        self.search = None

    # ---- per tick --------------------------------------------------------
    def next_step(self, pos, goal, t=0.0, speed=0.0, *, precise=False):
        """Returns (move_x, move_y, jump, boost) toward goal."""
        x, y = pos[0], pos[1]
        if not self.ok:
            return self._direct(x, y, goal) + (False, False)

        jump = boost = False
        stuck = self._stuck(t, x, y, speed)
        if stuck:
            jump = True
            boost = True
            self.path = []

        if t < self.unstick_until:
            return self.unstick_dir[0], self.unstick_dir[1], True, True

        tolerance = config.COVER_REACHED_M if precise else config.NAV_REPLAN_GOAL_MOVE
        goal_changed = self.goal is None or math.dist(goal, self.goal) > tolerance
        if precise and goal_changed:
            self.search = None
            self.path = []
        replan = goal_changed or t - self.last_plan_t > config.NAV_REPLAN_S or not self.path
        if replan and self.search is None:
            self.goal = (goal[0], goal[1])
            self._start_search(pos, goal)
            self.last_plan_t = t
        if self.search is not None:
            if self._step_search(config.NAV_BUDGET_MS / 1000.0):
                self._finish_search()

        # drop waypoints we've reached
        while self.path and math.hypot(self.path[0][0] - x, self.path[0][1] - y) < config.NAV_CELL * 1.2:
            self.path.pop(0)
        if not self.path:
            return self._direct(x, y, goal) + (jump, boost)
        # look ahead to smooth the zigzag
        k = min(len(self.path) - 1, config.NAV_LOOKAHEAD)
        tx, ty = self.path[k]
        return self._direct(x, y, (tx, ty)) + (jump, boost)

    def _direct(self, x, y, goal):
        dx, dy = goal[0] - x, goal[1] - y
        d = math.hypot(dx, dy)
        if d < 0.5:
            return 0.0, 0.0
        return dx / d, dy / d

    def _stuck(self, t, x, y, speed):
        """True once when we've barely moved for STUCK_S while trying to move."""
        self.hist.append((t, x, y))
        while self.hist and t - self.hist[0][0] > config.STUCK_S:
            self.hist.pop(0)
        if t - self.hist[0][0] < config.STUCK_S * 0.8 or speed < 0.5:
            return False
        t0, x0, y0 = self.hist[0]
        if math.hypot(x - x0, y - y0) < config.STUCK_DIST:
            self.hist.clear()
            a = math.atan2(y - y0, x - x0) + math.pi / 2 + (math.pi if int(t * 10) % 2 else 0)
            self.unstick_dir = (math.cos(a), math.sin(a))
            self.unstick_until = t + config.UNSTICK_S
            return True
        return False

    def cover_pair(self, pos, threat_pos, height, allowed):
        """Find covered ground with a nearby walkable firing position."""
        x, y, z = pos
        threat_x, threat_y, _ = threat_pos
        away = math.atan2(y - threat_y, x - threat_x)
        angles = tuple(away + i * math.pi / 4 for i in (0, 1, -1, 2, -2, 3, -3, 4))
        world = self.world

        def muzzle(px, py):
            return px, py, world.surface(px, py) + height

        def valid(point):
            px, py = point
            return (world.in_bounds(px, py) and allowed(point) and self.walkable_xy(px, py)
                    and abs(world.surface(px, py) - z) <= config.NAV_MAX_UP)

        for radius in (0, *config.COVER_RADII_M):
            for angle in angles if radius else (away,):
                hide = (x + radius * math.cos(angle), y + radius * math.sin(angle))
                if not valid(hide) or world.los(muzzle(*hide), threat_pos):
                    continue
                for peek_angle in angles:
                    step = config.DODGE_STEP_M
                    peek = (hide[0] + step * math.cos(peek_angle),
                            hide[1] + step * math.sin(peek_angle))
                    if (valid(peek) and world.los(muzzle(*peek), threat_pos)
                            and world.los(muzzle(*hide), muzzle(*peek))):
                        return hide, peek
    def cover_from(self, pos, threat_pos, zone=None):
        """Nearest walkable ground point the threat can't see (eye to our chest and head), or None.
        zone: optional (cx, cy, r) the point must stay inside."""
        if not self.ok:
            return None
        w = self.world
        x, y = pos[0], pos[1]
        teye = (threat_pos[0], threat_pos[1], threat_pos[2] + 8.0)
        d_threat = math.hypot(x - threat_pos[0], y - threat_pos[1])
        best = None
        for r in config.COVER_RINGS:
            for k in range(config.COVER_ANGLES):
                a = 2 * math.pi * k / config.COVER_ANGLES
                px, py = x + r * math.cos(a), y + r * math.sin(a)
                if not w.in_bounds(px, py):
                    continue
                i, j = self.to_cell(px, py)
                c = j * self.cnx + i
                if not self.main[c] or self.roof[c]:
                    continue
                if math.hypot(px - threat_pos[0], py - threat_pos[1]) < d_threat * 0.8:
                    continue  # don't run toward them
                if zone and math.hypot(px - zone[0], py - zone[1]) > zone[2]:
                    continue
                gz = self.Hl[c]
                if w.los(teye, (px, py, gz + 4.5)) or w.los(teye, (px, py, gz + 8.5)):
                    continue
                if best is None or r < best[0]:
                    best = (r, px, py)
            if best:
                return best[1], best[2]
        return None

    def cover_from(self, pos, threat_pos):
        pair = self.cover_pair(pos, threat_pos, 7.0, lambda point: True)
        return pair[0] if pair is not None else None
