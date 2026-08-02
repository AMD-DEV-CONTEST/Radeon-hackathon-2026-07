import unittest

import numpy as np

from fencing_analysis.analysis.scorecard import build_scorecard, render_scorecard_markdown


class _Timeline:
    dt = 1 / 30
    tip_img = {
        "left": np.array([[0, 0], [10, 0], [20, 0], [30, 0]], dtype=float),
        "right": np.array([[30, 0], [20, 0], [10, 0], [0, 0]], dtype=float),
    }
    tip_conf = {"left": np.array([1, 1, 1, 1], dtype=float), "right": np.array([1, 1, 1, 1], dtype=float)}


def _events():
    side_stats = {
        "footwork": {"lunge_count": 2},
        "reaction": {"count": 2, "median_sec": 0.52},
        "attack_count": 2,
        "defense_count": 1,
    }
    return {
        "stats": {"left": side_stats, "right": {**side_stats, "reaction": {"count": 0}}},
        "actions": [
            {"fencer": "right", "type": "attack", "start_sec": 1.0},
            {"fencer": "left", "type": "parry", "start_sec": 1.0,
             "features": {"against_attack_of": "right"}},
        ],
        "style": {"profiles": {"left": {"detail": {}}, "right": {"detail": {}}}},
    }


class ScorecardTest(unittest.TestCase):
    def test_builds_metrics_and_three_improvements(self):
        card = build_scorecard(_events(), _Timeline())
        left = card["sides"]["left"]
        self.assertEqual(left["metrics"]["tip_detection_rate"], 1.0)
        self.assertEqual(left["metrics"]["defense_conversion"]["rate"], 1.0)
        self.assertEqual(len(left["improvements"]), 3)
        markdown = render_scorecard_markdown(card)
        self.assertIn("单场成绩卡", markdown)
        self.assertIn("峰值剑尖速度", markdown)


if __name__ == "__main__":
    unittest.main()
