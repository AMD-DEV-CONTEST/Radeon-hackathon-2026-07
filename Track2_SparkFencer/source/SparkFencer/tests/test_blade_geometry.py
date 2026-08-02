"""Focused regression tests for pose-constrained CV blade tracking."""

import unittest

import cv2
import numpy as np

from fencing_analysis.detection.blade import BladeTracker
from fencing_analysis.detection.smoothing import KalmanSmoother


class _StaticLineDetector:
    def __init__(self, lines):
        self.lines = np.asarray(lines, dtype=np.float32).reshape(-1, 1, 4)

    def detect(self, _image):
        return self.lines.copy()


class BladeGeometryTest(unittest.TestCase):
    def test_selects_farthest_pose_aligned_endpoint(self):
        tracker = BladeTracker(sides=("left",), smoother="none")
        # One shorter valid fragment and one complete, wrist-rooted blade.
        tracker.detector = _StaticLineDetector([
            # _detect_tip passes detector-local coordinates.  The ROI origin
            # in this fixture is (50, 0), so root=(110,100), far tip=(220,100).
            [60, 100, 130, 100],
            [60, 100, 170, 100],
            # A long line behind the wrist must not be selected.
            [40, 100, 0, 100],
        ])
        tip, confidence = tracker._detect_tip(
            np.zeros((300, 300), dtype=np.uint8), None,
            wrist=np.array([100.0, 100.0]), direction=np.array([1.0, 0.0]),
            forearm_len=50.0,
        )
        np.testing.assert_allclose(tip, [220, 100])
        self.assertGreaterEqual(confidence, 0.62)

    def test_adaptive_kalman_trusts_high_confidence_observation_more(self):
        if not hasattr(cv2, "KalmanFilter"):
            self.skipTest("OpenCV build has no KalmanFilter")
        high = KalmanSmoother()
        low = KalmanSmoother()
        for smoother in (high, low):
            smoother.update([0.0, 0.0])
        high_result = high.update([100.0, 0.0], confidence=0.95)
        low_result = low.update([100.0, 0.0], confidence=0.20)
        self.assertGreater(high_result[0], low_result[0])


if __name__ == "__main__":
    unittest.main()
