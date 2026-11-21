"""Check the geometry used by defensive movement."""

import sys
import unittest

from replay_eval import ROOT

sys.path.insert(0, str(ROOT / "bot"))

from defense import _contact, escape_move
from world import FlatWorld


class Walkable:
    def walkable_xy(self, x, y):
        return True


class DefenseTests(unittest.TestCase):
    def setUp(self):
        self.me = {"pos": [0, 0, 0], "vel": [0, 0, 0], "grounded": True,
                   "stats": {"radius": 2.5, "height": 9.0, "walk_speed": 11.7,
                             "boost_speed": 19.5, "ground_accel": 58.5}}

    def test_fast_straight_shot_crosses_between_samples(self):
        path = [(0, 0, 0)] * 5
        self.assertGreater(_contact(path, [(-12, 0, 5, 252, 0, 0, 0, 0)], self.me, 0.1), 0)
        self.assertEqual(_contact(path, [(-12, 0, 14, 252, 0, 0, 0, 0)], self.me, 0.1), 0)

    def test_mortar_gravity_brings_shell_into_contact(self):
        path = [(0, 0, 0)] * 5
        self.assertEqual(_contact(path, [(-28, 0, 17, 72, 0, 0, 0, 7)], self.me, 0.1), 0)
        self.assertGreater(_contact(path, [(-28, 0, 17, 72, 0, 0, 22, 7)], self.me, 0.1), 0)

    def test_escape_turns_off_a_projectile_line(self):
        zone = dict(center=[0, 0], radius=100, next_center=[0, 0], next_radius=90)
        shot = {"kind": "gun", "pos": [115, 0, 5], "vel": [-252, 0, 0]}
        obs = {"self": self.me, "zone": zone, "projectiles": [shot]}
        rules = {"weapons": {}, "mech": {"muzzle_height": 7}}
        move = escape_move(obs, (1, 0), False, [], None, FlatWorld(), Walkable(), rules)
        self.assertGreater(abs(move[1]), 0.2)


if __name__ == "__main__":
    unittest.main()
