import importlib.util
from pathlib import Path
import unittest

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_mobile_pi05_visual_pairing.py"
SPEC = importlib.util.spec_from_file_location("audit_mobile_pi05_visual_pairing", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _row(*, action_delta: float = 0.0) -> dict:
    return {
        "episode_index": 0,
        "frame_index": 1,
        "task_index": 2,
        "observation.stage_id": [0],
        "observation.state": [0.0, 1.0],
        "action": [0.0, 1.0 + action_delta],
    }


class AuditMobilePI05VisualPairingTests(unittest.TestCase):
    def test_exact_pair_passes(self) -> None:
        report = MODULE._compare_aligned_rows(
            [_row()], [_row()], np, state_atol=1e-6, action_atol=1e-6
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["action_max_abs_error"], 0.0)

    def test_action_drift_fails_single_factor_gate(self) -> None:
        report = MODULE._compare_aligned_rows(
            [_row()],
            [_row(action_delta=1e-3)],
            np,
            state_atol=1e-6,
            action_atol=1e-6,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["action_violation_frames"], 1)

    def test_frame_count_mismatch_fails(self) -> None:
        report = MODULE._compare_aligned_rows(
            [_row()], [], np, state_atol=1e-6, action_atol=1e-6
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["alignment_mismatches"], 1)


if __name__ == "__main__":
    unittest.main()
