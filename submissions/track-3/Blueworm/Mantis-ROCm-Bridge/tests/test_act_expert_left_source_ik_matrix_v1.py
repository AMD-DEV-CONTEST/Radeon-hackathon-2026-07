from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = os.environ.get("ACT_LEFT_SOURCE_IK_PACKAGE_ROOT")
if PACKAGE_ROOT:
    ROOT = Path(PACKAGE_ROOT)
    WIP = ROOT
    CONTRACT = ROOT / "act-expert-left-source-ik-matrix-v1.json"
else:
    ROOT = Path(__file__).resolve().parents[1]
    WIP = ROOT / ".ops/wip/act-expert-left-source-ik-matrix-20260730"
    CONTRACT = ROOT / "configs/act-expert-left-source-ik-matrix-v1.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LeftSourceIkMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = _load(
            "act_left_source_ik_probe_v1",
            WIP / "probe_act_expert_left_source_ik_matrix_20260730_v1.py",
        )
        cls.driver = _load(
            "act_left_source_ik_driver_v1",
            WIP / "run_act_expert_left_source_ik_matrix_20260730_v1.py",
        )
        cls.contract = json.loads(
            CONTRACT.read_text(encoding="utf-8")
        )
        cls.transit = (math.sqrt(0.75), 0.0, 0.5, 0.0)
        cls.pregrasp = (
            math.cos(math.radians(40.0)),
            0.0,
            math.sin(math.radians(40.0)),
            0.0,
        )
        cls.grasp = (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0)
        cls.candidates = cls.probe.build_source_approach_candidates(
            source_x_m=-0.1218992527979787,
            grasp_y_m=-0.21712642895396492,
            front_y_m=0.03,
            clearance_z_m=0.90,
            pregrasp_z_m=0.875,
            grasp_z_m=0.84,
            transit_orientation_wxyz=cls.transit,
            pregrasp_orientation_wxyz=cls.pregrasp,
            grasp_orientation_wxyz=cls.grasp,
        )

    def test_contract_and_code_freeze_same_candidate_order(self) -> None:
        self.assertEqual(
            tuple(self.contract["matrix"]["candidate_ids_in_order"]),
            self.probe.CANDIDATE_IDS,
        )
        self.assertEqual(self.probe.CANDIDATE_IDS, self.driver.CANDIDATES)
        self.assertEqual(tuple(self.contract["panel"][index]["seed"] for index in range(4)), self.driver.SEEDS)

    def test_all_routes_preserve_exact_front_and_grasp_endpoints(self) -> None:
        for candidate_id, rows in self.candidates.items():
            self.assertEqual(rows[0]["stage"], "front_clearance")
            self.assertEqual(rows[0]["position_xyz_m"], [-0.1218992527979787, 0.03, 0.90])
            self.assertEqual(rows[-1]["position_xyz_m"], [-0.1218992527979787, -0.21712642895396492, 0.84])
            self.assertTrue(
                all(
                    abs(left - right) <= 1e-15
                    for left, right in zip(
                        rows[-1]["orientation_wxyz"], self.grasp
                    )
                ),
                candidate_id,
            )

    def test_candidate_counts_are_frozen(self) -> None:
        self.assertEqual(
            [len(rows) for rows in self.candidates.values()],
            [4, 13, 13, 17, 13],
        )

    def test_noncontrol_routes_move_monotonically_toward_source(self) -> None:
        for candidate_id in self.probe.CANDIDATE_IDS[1:]:
            rows = self.candidates[candidate_id]
            y_values = [row["position_xyz_m"][1] for row in rows]
            z_values = [row["position_xyz_m"][2] for row in rows]
            self.assertTrue(
                all(
                    y_values[index + 1] <= y_values[index] + 1e-15
                    for index in range(len(y_values) - 1)
                ),
                candidate_id,
            )
            self.assertTrue(
                all(
                    z_values[index + 1] <= z_values[index] + 1e-15
                    for index in range(len(z_values) - 1)
                ),
                candidate_id,
            )

    def test_slerp_is_normalized_and_sign_invariant(self) -> None:
        ordinary = self.probe.quaternion_slerp_wxyz(
            self.transit, self.grasp, 0.5
        )
        flipped = self.probe.quaternion_slerp_wxyz(
            self.transit, tuple(-value for value in self.grasp), 0.5
        )
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in ordinary)), 1.0, places=15
        )
        self.assertTrue(
            all(
                abs(left - right) <= 1e-15
                for left, right in zip(ordinary, flipped)
            )
        )

    def test_classifier_uses_panel_wide_slack_and_preserves_rejection(self) -> None:
        results = []
        for seed in self.driver.SEEDS:
            candidate_results = []
            for index, candidate_id in enumerate(self.driver.CANDIDATES):
                baseline_reachable = seed in self.driver.CONTROLS
                candidate_results.append(
                    {
                        "candidate_id": candidate_id,
                        "fully_reachable": (
                            baseline_reachable if index == 0 else index in (1, 2)
                        ),
                        "minimum_normalized_slack": (
                            0.5 - 0.01 * seed if index == 1 else 0.2
                        ),
                        "waypoint_count": 13 if index != 3 else 17,
                    }
                )
            results.append(
                {
                    "seed": seed,
                    "backend": "cpu",
                    "cuda_visible_devices": "",
                    "capture_requested": False,
                    "retry_count": 0,
                    "candidate_scene_step_delta": 0,
                    "robot_qpos_max_delta_during_matrix": 0.0,
                    "bowl_pose_max_delta_during_matrix": 0.0,
                    "candidate_results": candidate_results,
                }
            )
        terminal, selected, _ = self.driver.classify_panel(results)
        self.assertEqual(terminal, "COMPLETE_SOURCE_IK_MATRIX_ACCEPTED")
        self.assertEqual(selected, self.driver.CANDIDATES[2])
        results[0]["candidate_results"][2]["fully_reachable"] = False
        results[0]["candidate_results"][1]["fully_reachable"] = False
        terminal, selected, _ = self.driver.classify_panel(results)
        self.assertEqual(terminal, "COMPLETE_SOURCE_IK_MATRIX_REJECTED")
        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
