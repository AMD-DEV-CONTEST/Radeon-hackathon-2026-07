from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    path = (
        ROOT
        / ".ops/wip/g3-left-interbowl-clearance-20260728"
        / "run_g3_left_interbowl_clearance_diagnostic_20260728_v1.py"
    )
    spec = importlib.util.spec_from_file_location(
        "g3_left_interbowl_clearance_diagnostic_runner",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LeftInterBowlDiagnosticRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_runner()

    def accepted_rows(self):
        rows = []
        for seed in self.module.SEEDS:
            rows.append(
                {
                    "seed": seed,
                    "exit_code": 0 if seed == self.module.CONTROL_SEED else 1,
                    "completed": seed == self.module.CONTROL_SEED,
                    "transition_receipt_valid": True,
                    "corrected_transition_collision": False,
                    "capture_artifact_count": 0,
                    "infrastructure_failure": False,
                }
            )
        return rows

    def test_exact_frozen_panel(self) -> None:
        self.assertEqual(
            self.module.SEEDS,
            (1039, 1074, 1086, 1208),
        )

    def test_accepts_control_and_transition_only_diagnostics(self) -> None:
        self.assertEqual(
            self.module.classify_terminal(self.accepted_rows()),
            "COMPLETE_TRANSITION_CORRECTION_ACCEPTED",
        )

    def test_rejects_control_regression(self) -> None:
        rows = self.accepted_rows()
        rows[0]["completed"] = False
        rows[0]["exit_code"] = 1
        self.assertEqual(
            self.module.classify_terminal(rows),
            "COMPLETE_TRANSITION_CORRECTION_REJECTED",
        )

    def test_rejects_any_corrected_transition_collision(self) -> None:
        rows = self.accepted_rows()
        rows[2]["corrected_transition_collision"] = True
        self.assertEqual(
            self.module.classify_terminal(rows),
            "COMPLETE_TRANSITION_CORRECTION_REJECTED",
        )

    def test_rejects_capture_artifact(self) -> None:
        rows = self.accepted_rows()
        rows[1]["capture_artifact_count"] = 1
        self.assertEqual(
            self.module.classify_terminal(rows),
            "COMPLETE_TRANSITION_CORRECTION_REJECTED",
        )

    def test_fails_closed_on_seed_order_or_infrastructure(self) -> None:
        rows = self.accepted_rows()
        rows.reverse()
        self.assertEqual(
            self.module.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )
        rows = self.accepted_rows()
        rows[1]["infrastructure_failure"] = True
        self.assertEqual(
            self.module.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )

    def test_collision_classifier_is_stage_specific(self) -> None:
        self.assertTrue(
            self.module.corrected_transition_collision(
                "safety failure during bowl3:inter_bowl_lateral_clearance: "
                "robot_nonselected_bowl_contact"
            )
        )
        self.assertFalse(
            self.module.corrected_transition_collision(
                "safety failure during bowl3:front_clearance: "
                "robot_nonselected_bowl_contact"
            )
        )


if __name__ == "__main__":
    unittest.main()
