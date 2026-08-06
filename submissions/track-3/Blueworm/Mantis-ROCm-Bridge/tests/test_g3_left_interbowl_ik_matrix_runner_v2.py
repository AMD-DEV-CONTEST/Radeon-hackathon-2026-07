from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    path = (
        ROOT
        / ".ops/wip/g3-left-interbowl-ik-matrix-20260728"
        / "run_g3_left_interbowl_ik_matrix_20260728_v2.py"
    )
    spec = importlib.util.spec_from_file_location(
        "g3_left_interbowl_ik_matrix_runner_v2",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class G3LeftInterBowlIkMatrixRunnerV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        self.base = {
            "seed": 1039,
            "backend": "cpu",
            "cuda_visible_devices": "",
            "capture_requested": False,
            "retry_count": 0,
            "candidate_results": [
                {"candidate_id": candidate_id}
                for candidate_id in self.runner.CANDIDATES
            ],
            "negative_control_pass": True,
            "state_invariance_pass": True,
            "policy_step_delta_during_matrix": 0,
            "robot_qpos_max_delta_during_matrix": 0.0,
            "bowl_position_max_delta_during_matrix_m": 0.0,
        }

    def test_accepts_only_a_reachable_noncontrol_candidate(self) -> None:
        matrix = {
            **self.base,
            "terminal_status": "COMPLETE_IK_MATRIX_ACCEPTED",
            "reachable_candidate_count": 1,
            "selected_candidate_id": "coupled_lateral_slerp",
        }
        self.assertEqual(
            self.runner.classify_terminal(
                matrix=matrix,
                process_exit_code=0,
                capture_artifacts=[],
            ),
            ("COMPLETE_IK_MATRIX_ACCEPTED", True),
        )

    def test_preserves_a_semantically_valid_algorithmic_rejection(self) -> None:
        matrix = {
            **self.base,
            "terminal_status": "COMPLETE_IK_MATRIX_REJECTED",
            "reachable_candidate_count": 0,
            "selected_candidate_id": None,
        }
        self.assertEqual(
            self.runner.classify_terminal(
                matrix=matrix,
                process_exit_code=2,
                capture_artifacts=[],
            ),
            ("COMPLETE_IK_MATRIX_REJECTED", True),
        )

    def test_evidence_drift_is_never_promoted(self) -> None:
        matrix = {
            **self.base,
            "terminal_status": "COMPLETE_IK_MATRIX_ACCEPTED",
            "reachable_candidate_count": 1,
            "selected_candidate_id": "coupled_lateral_slerp",
        }
        for mutation in (
            {"process_exit_code": 2, "capture_artifacts": []},
            {"process_exit_code": 0, "capture_artifacts": ["episode.npz"]},
        ):
            terminal, semantic_valid = self.runner.classify_terminal(
                matrix=matrix,
                **mutation,
            )
            self.assertEqual(terminal, "FAILED_EVIDENCE_GATE")
            if mutation["capture_artifacts"]:
                self.assertFalse(semantic_valid)


if __name__ == "__main__":
    unittest.main()
