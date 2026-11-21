"""Focused weapon, dodge, cover, and loot checks the kit replay misses."""

from copy import deepcopy
from math import atan2
import sys
import unittest

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

from combat import Weapons, mortar_aim
from loot import pick_upgrade, want
from nav import Nav
from track import Target
from world import FlatWorld


class Wall(FlatWorld):
    def los(self, a, b):
        if (a[0] < 50 <= b[0]) or (b[0] < 50 <= a[0]):
            fraction = (50 - a[0]) / (b[0] - a[0])
            y = a[1] + (b[1] - a[1]) * fraction
            z = a[2] + (b[2] - a[2]) * fraction
            return abs(y) > 2 or z > 30
        return True


class PhaseTwoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hello, obs = load_stream(DEFAULT_STREAM)
        cls.rules = hello["config"]
        cls.initial = obs[0]

    def setUp(self):
        self.obs = deepcopy(self.initial)
        self.me = self.obs["self"]
        self.me.update(pos=[0, 0, 0], vel=[0, 0, 0], aim=[0, atan2(-2.5, 30)])
        self.weapons = Weapons(self.rules)
        self.world = FlatWorld()

    def equip(self, kind, **state):
        weapon = dict(kind=kind, stats=self.rules["weapons"][kind], cooldown=0, **state)
        self.me["weapons"][1] = weapon
        return weapon

    def test_laser_charges_releases_and_observes_short(self):
        laser = self.equip("laser", charge=0)
        target = Target(1, "mech", (30, 0, 0), (0, 0, 0), weapons=("mortar",))
        self.assertTrue(self.weapons.decide(self.me, target, self.world)["fire"][1])
        laser["charge"] = laser["stats"]["charge"]
        self.assertFalse(self.weapons.decide(self.me, target, self.world)["fire"][1])
        laser["charge"] = 0
        self.obs["events"] = [{"type": "effect", "effect": "short"}]
        self.weapons.update(self.obs)
        self.assertFalse(self.weapons.decide(self.me, target, self.world)["fire"][1])

    def test_lightning_respects_cone_range_and_energy(self):
        self.equip("lightning")
        target = Target(1, "mech", (30, 0, 0), (0, 0, 0), weapons=("laser",))
        self.assertTrue(self.weapons.decide(self.me, target, self.world)["fire"][1])
        self.me["aim"] = [1.0, 0.0]
        self.assertFalse(self.weapons.decide(self.me, target, self.world)["fire"][1])
        self.me["aim"] = [0, 0]
        far = Target(1, "mech", (60, 0, 0), (0, 0, 0))
        self.assertFalse(self.weapons.decide(self.me, far, self.world)["fire"][1])
        self.me["energy"] = 0
        self.assertFalse(self.weapons.decide(self.me, target, self.world)["fire"][1])

    def test_mortar_lobs_over_wall_and_checks_self_splash(self):
        stats = self.rules["weapons"]["mortar"]
        target = Target(1, "mech", (140, 0, 0), (0, 0, 0))
        low, _ = mortar_aim(self.me, target, self.world, stats)
        high, _ = mortar_aim(self.me, target, Wall(), stats)
        self.assertGreater(high[1], low[1])
        nearby = Target(1, "mech", (8, 0, 0), (0, 0, 0))
        self.assertIsNone(mortar_aim(self.me, nearby, self.world, stats))

    def test_dodge_projectile_and_charged_laser(self):
        self.obs["projectiles"] = [{"kind": "gun", "pos": [-25, 0, 4.5], "vel": [252, 0, 0]}]
        self.assertEqual(self.weapons.dodge(self.obs, None, self.world), (0, 1, True))
        self.obs["projectiles"] = []
        self.obs["mechs"] = [{"pos": [-25, 0, 0], "aim": [0, atan2(-2.5, 25)], "charging": True}]
        self.assertEqual(self.weapons.dodge(self.obs, None, self.world), (0, 1, True))

    def test_cover_pair_has_a_hidden_and_a_visible_position(self):
        world = Wall()
        enemy = (80, 0, 4.5)
        hide, peek = Nav(world).cover_pair((47, 0, 0), enemy, 7, lambda point: True)
        self.assertFalse(world.los((*hide, 7), enemy))
        self.assertTrue(world.los((*peek, 7), enemy))

    def test_early_loot_stays_inside_next_zone_and_armor_wins(self):
        self.obs["zone"].update(next_center=[0, 0], next_radius=12)
        self.obs["pickups"] = [{"id": 8010, "kind": "laser", "pos": [13, 0, 0]}]
        self.obs["crates"] = [{"id": 1000, "pos": [7, 0, 0], "hp": 300}]
        self.assertEqual(want(self.obs, self.world)[0], "crate")
        offer = {"choices": [{"id": "laser_damage"}, {"id": "armor"}, {"id": "sensors"}]}
        self.assertEqual(pick_upgrade(offer, self.me), 1)


if __name__ == "__main__":
    unittest.main()
