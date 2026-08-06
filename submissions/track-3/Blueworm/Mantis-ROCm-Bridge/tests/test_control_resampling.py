from __future__ import annotations

import math
import unittest

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.control_resampling import resample_topp_trace


class ControlResamplingTests(unittest.TestCase):
    def test_fixed_clock_preserves_endpoints_and_limit(self) -> None:
        result = resample_topp_trace(
            [0.0, 0.004, 0.008],
            [[0.0, 0.0], [0.002, 0.0], [0.004, 0.004]],
            target_hz=30.0,
            velocity_limits_per_s=[1.0, 1.0],
        )
        self.assertEqual(result["positions"][0], [0.0, 0.0])
        self.assertEqual(result["positions"][-1], [0.004, 0.004])
        self.assertEqual(result["time_scale_factor"], 1.0)
        self.assertTrue(
            all(
                abs(velocity) <= 1.0 + 1e-9
                for row in result["velocities_per_s"]
                for velocity in row
            )
        )
        intervals = [
            right - left
            for left, right in zip(result["timestamps_s"], result["timestamps_s"][1:])
        ]
        self.assertTrue(all(math.isclose(value, 1.0 / 30.0) for value in intervals))

    def test_uniform_retiming_stretches_fast_source_trace(self) -> None:
        result = resample_topp_trace(
            [0.0, 0.004],
            [[0.0], [0.02]],
            target_hz=30.0,
            velocity_limits_per_s=[1.0],
        )
        self.assertAlmostEqual(result["time_scale_factor"], 5.0)
        self.assertAlmostEqual(result["retimed_duration_s"], 0.02)
        self.assertEqual(result["positions"][-1], [0.02])
        self.assertLess(result["endpoint_hold_lag_s"], 1.0 / 30.0)

    def test_left_right_coordination_uses_one_scale_factor(self) -> None:
        result = resample_topp_trace(
            [0.0, 0.004],
            [[0.0, 0.0], [0.02, 0.002]],
            target_hz=30.0,
            velocity_limits_per_s=[1.0, 1.0],
        )
        final = result["positions"][-1]
        self.assertAlmostEqual(final[0] / final[1], 10.0)
        self.assertAlmostEqual(result["time_scale_factor"], 5.0)

    def test_endpoint_only_or_malformed_trace_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            resample_topp_trace(
                [0.0], [[0.0]], target_hz=30.0, velocity_limits_per_s=[1.0]
            )
        with self.assertRaises(ContractError):
            resample_topp_trace(
                [0.0, 0.0], [[0.0], [0.1]], target_hz=30.0, velocity_limits_per_s=[1.0]
            )
        with self.assertRaises(ContractError):
            resample_topp_trace(
                [0.0, 0.004],
                [[0.0], [float("nan")]],
                target_hz=30.0,
                velocity_limits_per_s=[1.0],
            )


if __name__ == "__main__":
    unittest.main()
