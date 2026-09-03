from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    path = (
        ROOT
        / ".ops/wip/g3-left-interbowl-coupled-descent-dynamic-20260728"
        / "run_g3_left_coupled_descent_dynamic_20260728_v3.py"
    )
    spec = importlib.util.spec_from_file_location(
        "g3_left_coupled_descent_dynamic_runner_v3",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class G3LeftCoupledDescentDynamicRunnerV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def _accepted_rows(self):
        return [
            {
                "seed": seed,
                "exit_code": 0 if seed == 1039 else 1,
                "completed": seed == 1039,
                "transition_receipt_valid": True,
                "corrected_transition_collision": False,
                "capture_artifact_count": 0,
                "infrastructure_failure": False,
            }
            for seed in self.runner.SEEDS
        ]

    def test_accepts_exact_semantic_panel(self) -> None:
        self.assertEqual(
            self.runner.classify_terminal(self._accepted_rows()),
            "COMPLETE_COUPLED_DESCENT_DYNAMIC_ACCEPTED",
        )

    def test_dynamic_collision_is_algorithmic_rejection(self) -> None:
        rows = self._accepted_rows()
        rows[2]["corrected_transition_collision"] = True
        self.assertEqual(
            self.runner.classify_terminal(rows),
            "COMPLETE_COUPLED_DESCENT_DYNAMIC_REJECTED",
        )

    def test_missing_control_completion_is_algorithmic_rejection(self) -> None:
        rows = self._accepted_rows()
        rows[0]["completed"] = False
        rows[0]["exit_code"] = 1
        self.assertEqual(
            self.runner.classify_terminal(rows),
            "COMPLETE_COUPLED_DESCENT_DYNAMIC_REJECTED",
        )

    def test_isolation_or_order_drift_fails_evidence_gate(self) -> None:
        rows = self._accepted_rows()
        rows[0]["capture_artifact_count"] = 1
        self.assertEqual(
            self.runner.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )
        rows = self._accepted_rows()
        rows[0], rows[1] = rows[1], rows[0]
        self.assertEqual(
            self.runner.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )

    def test_collision_scan_is_limited_to_corrected_stages(self) -> None:
        self.assertTrue(
            self.runner.corrected_transition_collision(
                "robot_nonselected_bowl_contact "
                "bowl3:inter_bowl_descend_to_front_clearance"
            )
        )
        self.assertFalse(
            self.runner.corrected_transition_collision(
                "robot_nonselected_bowl_contact bowl3:place"
            )
        )


if __name__ == "__main__":
    unittest.main()
