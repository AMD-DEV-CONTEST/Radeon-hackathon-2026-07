import unittest

import numpy as np

from parcel_sorter.mobile_depth_sidecar import depth_risk_scale_cap


class DepthSidecarTests(unittest.TestCase):
    def test_clear_metric_depth_preserves_full_authority(self) -> None:
        decision = depth_risk_scale_cap(np.full((32, 32), 1.5, dtype=np.float32))
        self.assertEqual(decision.scale_cap, 1.0)
        self.assertFalse(decision.fail_closed)

    def test_near_camera_occluder_caps_authority(self) -> None:
        depth = np.full((32, 32), 1.5, dtype=np.float32)
        depth[12:20, 12:20] = 0.12
        decision = depth_risk_scale_cap(depth)
        self.assertLess(decision.scale_cap, 1.0)
        self.assertIn("depth_near_plane_cap", decision.reasons)

    def test_missing_or_invalid_depth_fails_closed(self) -> None:
        self.assertTrue(depth_risk_scale_cap(None).fail_closed)
        decision = depth_risk_scale_cap(np.full((16, 16), np.inf, dtype=np.float32))
        self.assertEqual(decision.scale_cap, 0.0)
        self.assertTrue(decision.fail_closed)


if __name__ == "__main__":
    unittest.main()
