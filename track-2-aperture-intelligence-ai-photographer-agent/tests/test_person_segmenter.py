from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tools.person_segmenter import (
    _fallback_candidate_indices,
    _iou,
    _pixel_box,
    _require_local_checkpoint,
)


class PersonSegmenterUtilsTests(unittest.TestCase):
    def test_fallback_prefers_high_confidence_people(self) -> None:
        candidates = [
            {"score": 0.98, "box": (0.0, 0.0, 90.0, 200.0)},
            {"score": 0.99, "box": (0.0, 0.0, 50.0, 100.0)},
            {"score": 0.99, "box": (0.0, 0.0, 80.0, 120.0)},
        ]
        self.assertEqual(
            _fallback_candidate_indices(candidates, {0, 1, 2}, 2),
            [2, 1],
        )

    def test_missing_checkpoint_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.pth"
            with self.assertRaisesRegex(FileNotFoundError, "offline-only"):
                _require_local_checkpoint(missing)

    def test_pixel_box_converts_normalized_coordinates(self) -> None:
        self.assertEqual(
            _pixel_box([250, 100, 750, 900], 800, 600),
            (200.0, 60.0, 600.0, 540.0),
        )

    def test_iou_matches_overlapping_people(self) -> None:
        self.assertEqual(_iou((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)
        self.assertAlmostEqual(
            _iou((0, 0, 10, 10), (5, 5, 15, 15)),
            25 / 175,
        )


if __name__ == "__main__":
    unittest.main()
