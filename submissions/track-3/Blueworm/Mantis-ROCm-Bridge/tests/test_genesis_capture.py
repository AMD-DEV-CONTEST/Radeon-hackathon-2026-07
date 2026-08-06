from __future__ import annotations

import unittest

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.genesis_capture import PolicyCaptureClock


class PolicyCaptureClockTests(unittest.TestCase):
    def test_250hz_physics_to_30hz_policy_schedule_is_non_early(self) -> None:
        clock = PolicyCaptureClock(physics_dt_s=0.004, policy_hz=30.0)
        ticks = [clock.tick(frame) for frame in range(5)]
        self.assertEqual([tick.physics_step for tick in ticks], [0, 9, 17, 25, 34])
        self.assertTrue(
            all(0.0 <= tick.sampling_skew_s < 0.004 for tick in ticks)
        )
        self.assertEqual(ticks[3].policy_timestamp_s, 0.1)
        self.assertEqual(ticks[3].physics_timestamp_s, 0.1)

    def test_invalid_clock_and_frame_are_rejected(self) -> None:
        with self.assertRaises(ContractError):
            PolicyCaptureClock(physics_dt_s=0.0, policy_hz=30.0)
        clock = PolicyCaptureClock(physics_dt_s=0.004, policy_hz=30.0)
        with self.assertRaises(ContractError):
            clock.tick(-1)


if __name__ == "__main__":
    unittest.main()
