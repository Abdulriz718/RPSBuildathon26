"""Check Phase 3 policy choices in observations the kit replay lacks."""

from copy import deepcopy
from math import atan2
import sys
import unittest
from unittest.mock import patch

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

from brain import Brain
import config
from loot import supply_goal
from nav import Nav
from track import Target
from world import FlatWorld


class PhaseThreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, observations = load_stream(DEFAULT_STREAM)
        cls.first = observations[0]

    def setUp(self):
        self.obs = deepcopy(self.first)
        self.obs.update(t=80.0, alive=12, mechs=[], events=[], sounds=[], projectiles=[])
        self.obs["self"].update(pos=[0, 0, 0], aim=[0, atan2(-2.5, 40)])
        self.obs["zone"].update(center=[0, 0], radius=300, next_center=[0, 0],
                                next_radius=240, shrink_end=110)

    def test_drop_skips_contested_and_soon_unsafe_ring(self):
        drop = {"id": 20000, "pos": [25, 0, 0], "radius": 8, "holder": None, "lands_in": 0}
        self.obs["drops"] = [drop]
        self.assertEqual(supply_goal(self.obs, []), (25, 0))
        enemy = Target(1, "mech", (38, 0, 0), (0, 0, 0))
        self.assertIsNone(supply_goal(self.obs, [enemy]))
        self.obs["zone"]["next_radius"] = 20
        self.assertIsNone(supply_goal(self.obs, []))

    def test_ffa_retaliates_against_attacker_during_zone_escape(self):
        self.obs["self"]["in_zone"] = False
        self.obs["mechs"] = [
            {"id": 1, "kind": "mech", "pos": [40, 0, 0], "vel": [0, 0, 0], "hp": 1000},
            {"id": 2, "kind": "mech", "pos": [30, 20, 0], "vel": [0, 0, 0], "hp": 100},
        ]
        with patch.object(config, "MODE", "ffa"), patch("brain.World.load", return_value=FlatWorld()):
            brain = Brain(self.hello)
            self.assertEqual(brain.decide(self.obs)["fire"], [False, False])
            self.assertEqual(brain.mode, "ZONE")
            self.obs["events"] = [{"type": "damaged", "by": 1, "bearing": 0.0}]
            self.assertEqual(brain.decide(self.obs)["fire"], [True, False])

    def test_late_anchor_uses_cover_away_from_shots(self):
        class CoverWorld(FlatWorld):
            def los(self, a, b):
                return b[0] >= 0

        world = CoverWorld()
        with patch("brain.World.load", return_value=world):
            brain = Brain(self.hello)
        brain.nav = Nav(world)
        self.obs["sounds"] = [{"kind": "gun", "dist": "near", "bearing": 0.0, "age": 0.0}]
        brain.track.update(self.obs)
        goal = brain.late_anchor(self.obs, (0, 0), 15)
        self.assertLess(goal[0], 0)
        self.assertEqual(brain.late_anchor(self.obs, (0, 0), 0), (0, 0))


if __name__ == "__main__":
    unittest.main()
