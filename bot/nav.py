"""Pathfinding and cover. Owner: A. Phase 0: straight line toward the goal."""
import math


class Nav:
    def __init__(self, world):
        self.world = world

    def next_step(self, pos, goal):
        """Returns (move_x, move_y, jump, boost). Phase 1: A* on a walkable grid + stuck recovery."""
        dx, dy = goal[0] - pos[0], goal[1] - pos[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return 0.0, 0.0, False, False
        return dx / d, dy / d, False, False

    def cover_from(self, pos, threat_pos):
        """A nearby point with no LOS to threat_pos, or None. Phase 2."""
        return None
