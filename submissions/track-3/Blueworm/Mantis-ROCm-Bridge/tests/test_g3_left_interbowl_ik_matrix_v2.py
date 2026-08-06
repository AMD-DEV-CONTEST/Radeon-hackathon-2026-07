from __future__ import annotations

import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_tool():
    path = ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py"
    spec = importlib.util.spec_from_file_location(
        "g3_left_interbowl_ik_matrix_tool",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _angle_from_start(start, quaternion) -> float:
    dot = abs(sum(left * right for left, right in zip(start, quaternion)))
    return 2.0 * math.acos(min(1.0, max(-1.0, dot)))


class G3LeftInterBowlIkMatrixV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = _load_tool()
        self.contract = json.loads(
            (
                ROOT
                / "configs/g3-left-interbowl-clearance-ik-matrix-v2.json"
            ).read_text(encoding="utf-8")
        )
        self.grasp = (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0)
        self.transit = (math.sqrt(0.75), 0.0, 0.5, 0.0)
        self.route = self.tool.build_consecutive_left_transition_positions(
            previous_retreat_position_xyz_m=(0.0, -0.1678, 0.93),
            next_front_clearance_position_xyz_m=(-0.24, 0.03, 0.90),
            clearance_tcp_z_m=1.02,
            cartesian_waypoints_per_segment=8,
        )
        self.candidates = (
            self.tool.build_consecutive_left_transition_ik_candidates(
                route_positions=self.route,
                grasp_orientation_wxyz=self.grasp,
                transit_orientation_wxyz=self.transit,
            )
        )

    def test_contract_freezes_exact_candidate_order_and_isolation(self) -> None:
        matrix = self.contract["matrix"]
        self.assertEqual(
            tuple(
                candidate["candidate_id"]
                for candidate in matrix["candidates_in_order"]
            ),
            self.tool.G3_LEFT_IK_MATRIX_CANDIDATES,
        )
        self.assertEqual(matrix["seed"], 1039)
        self.assertEqual(matrix["backend"], "cpu")
        self.assertEqual(matrix["cuda_visible_devices"], "")
        self.assertFalse(matrix["capture"])
        self.assertEqual(matrix["retry_count"], 0)

    def test_slerp_is_normalized_sign_invariant_and_exact_at_endpoints(self) -> None:
        start = self.tool.quaternion_slerp_wxyz(
            self.grasp,
            self.transit,
            0.0,
        )
        end = self.tool.quaternion_slerp_wxyz(
            self.grasp,
            self.transit,
            1.0,
        )
        sign_flipped = self.tool.quaternion_slerp_wxyz(
            self.grasp,
            tuple(-value for value in self.transit),
            0.5,
        )
        ordinary = self.tool.quaternion_slerp_wxyz(
            self.grasp,
            self.transit,
            0.5,
        )
        self.assertTrue(
            all(
                abs(left - right) <= 1e-15
                for left, right in zip(start, self.grasp)
            )
        )
        self.assertTrue(
            all(
                abs(left - right) <= 1e-15
                for left, right in zip(end, self.transit)
            )
        )
        self.assertTrue(
            all(
                abs(left - right) <= 1e-15
                for left, right in zip(sign_flipped, ordinary)
            )
        )
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in ordinary)),
            1.0,
            places=15,
        )

    def test_slerp_rejects_malformed_inputs(self) -> None:
        for args in (
            ((1.0, 0.0, 0.0), self.transit, 0.5),
            ((0.0, 0.0, 0.0, 0.0), self.transit, 0.5),
            (self.grasp, self.transit, -0.1),
            (self.grasp, self.transit, True),
        ):
            with self.assertRaises(ValueError):
                self.tool.quaternion_slerp_wxyz(*args)

    def test_candidate_counts_and_position_route_are_exact(self) -> None:
        self.assertEqual(
            tuple(self.candidates),
            self.tool.G3_LEFT_IK_MATRIX_CANDIDATES,
        )
        self.assertEqual(
            [len(rows) for rows in self.candidates.values()],
            [25, 24, 24, 24],
        )
        for candidate_id, rows in self.candidates.items():
            by_stage = {}
            for row in rows:
                by_stage.setdefault(row["stage"], []).append(
                    row["position_xyz_m"]
                )
            self.assertEqual(
                by_stage["vertical_clearance"],
                self.route["vertical_clearance"],
                candidate_id,
            )
            self.assertEqual(
                by_stage["lateral_clearance"],
                self.route["lateral_clearance"],
                candidate_id,
            )
            self.assertEqual(
                by_stage["descend_to_front_clearance"],
                self.route["descend_to_front_clearance"],
                candidate_id,
            )

    def test_all_candidates_preserve_start_and_final_orientation_semantics(self) -> None:
        for candidate_id, rows in self.candidates.items():
            self.assertTrue(
                all(
                    abs(left - right) <= 1e-15
                    for left, right in zip(
                        rows[0]["orientation_wxyz"],
                        self.grasp,
                    )
                )
            )
            self.assertTrue(
                all(
                    abs(left - right) <= 1e-15
                    for left, right in zip(
                        rows[-1]["orientation_wxyz"],
                        self.transit,
                    )
                )
            )
            self.assertEqual(
                rows[-1]["position_xyz_m"],
                self.route["descend_to_front_clearance"][-1],
                candidate_id,
            )

    def test_coupled_slerp_candidates_have_monotonic_angular_progress(self) -> None:
        for candidate_id in self.tool.G3_LEFT_IK_MATRIX_CANDIDATES[1:]:
            angles = [
                _angle_from_start(self.grasp, row["orientation_wxyz"])
                for row in self.candidates[candidate_id]
            ]
            self.assertTrue(
                all(
                    angles[index] <= angles[index + 1] + 1e-15
                    for index in range(len(angles) - 1)
                ),
                candidate_id,
            )
            self.assertGreater(angles[-1], 0.0)

    def test_matrix_runtime_is_explicit_non_capture_and_exclusive(self) -> None:
        source = (
            ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"--transition-ik-matrix-only"', source)
        self.assertIn("raise_on_tolerance_failure=False", source)
        self.assertIn('"candidate_solve_advances_physics": False', source)
        self.assertIn('"transition_ik_matrix_level_2.json"', source)
        self.assertIn('matrix_receipt_path.open(\n                            "x"', source)
        self.assertIn('"training_data_claim": False', source)


if __name__ == "__main__":
    unittest.main()
