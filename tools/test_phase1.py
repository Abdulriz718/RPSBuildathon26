"""Regression checks for Phase 1 tracking and gun behavior."""

from copy import deepcopy
from math import hypot
import sys
import unittest
from unittest.mock import Mock

from replay_eval import DEFAULT_STREAM, ROOT, load_stream

sys.path.insert(0, str(ROOT / "bot"))

from combat import engage, intercept_time
from track import Target, Tracker


class PhaseOneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hello, cls.observations = load_stream(DEFAULT_STREAM)
        cls.rules = hello["config"]

    def setUp(self):
        self.obs = deepcopy(self.observations[0])
        self.me = self.obs["self"]
        self.me.update(pos=[0, 0, 0], aim=[0, 0])
        self.target = Target(5, "mech", (100, 0, 0), (0, 10, 0))
        self.world = Mock()
        self.world.los.return_value = True

    def test_intercept_matches_travel_distance(self):
        flight = intercept_time((100, 0, 0), (0, 10, 0), 252, 3)
        self.assertAlmostEqual(hypot(100, 10 * flight), 3 + 252 * flight)
        self.assertIsNone(intercept_time((100, 0, 0), (300, 0, 0), 252))

    def test_lead_and_wait_for_torso_alignment(self):
        action = engage(self.me, self.target, self.world, sim_step=0.05)
        self.assertGreater(action["aim"][0], 0)
        self.assertEqual(action["fire"], [False, False])
        self.me["aim"] = action["aim"]
        self.assertEqual(engage(self.me, self.target, self.world, sim_step=0.05)["fire"],
                         [True, False])

    def test_cover_blocks_lead_and_reloads_partial_magazine(self):
        self.me["weapons"][0]["ammo"] -= 1
        self.world.los.side_effect = [True, False]
        action = engage(self.me, self.target, self.world)
        self.assertEqual(action["fire"], [False, False])
        self.assertTrue(action["reload"])
        self.assertTrue(engage(self.me, None, self.world)["reload"])

    def test_estimate_velocity_and_prefer_current_report(self):
        tracker = Tracker(self.rules)
        one = {"id": 1, "kind": "mech", "pos": [2, 0, 0]}
        two = {"id": 2, "kind": "mech", "pos": [30, 0, 0], "vel": [1, 0, 0]}
        self.obs["mechs"] = [one, two]
        tracker.update(self.obs)

        self.obs["t"] += 0.1
        one["pos"] = [3, 0, 0]
        tracker.update(self.obs)
        self.assertAlmostEqual(tracker.targets_sorted()[0].vel[0], 10)

        self.obs["t"] += 0.1
        self.obs["mechs"] = [two]
        self.obs["events"] = [{"type": "damaged", "bearing": -0.5}]
        tracker.update(self.obs)
        self.assertEqual([target.id for target in tracker.targets_sorted()], [2, 1])
        self.assertEqual(tracker.threat_bearing(), -0.5)
        self.assertEqual(engage(self.me, tracker.targets_sorted()[1], self.world)["fire"],
                         [False, False])

        self.obs["t"] += self.rules["vision"]["memory_s"] + 0.1
        self.obs["mechs"] = []
        self.obs["events"] = []
        tracker.update(self.obs)
        self.assertEqual(tracker.targets_sorted(), [])
        self.assertIsNone(tracker.threat_bearing())


if __name__ == "__main__":
    unittest.main()
