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
        "g3_left_interbowl_coupled_descent_dynamic_v3_tool",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class G3LeftInterBowlCoupledDescentDynamicV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = _load_tool()
        self.contract = json.loads(
            (
                ROOT
                / "configs/g3-left-interbowl-coupled-descent-dynamic-v3.json"
            ).read_text(encoding="utf-8")
        )

    def test_contract_freezes_single_intervention_and_exact_panel(self) -> None:
        self.assertEqual(
            self.contract["single_intervention"]["candidate"],
            "coupled_descent_slerp",
        )
        self.assertEqual(
            self.contract["diagnostic_panel"]["seeds_in_order"],
            [1039, 1074, 1086, 1208],
        )
        self.assertEqual(
            self.contract["diagnostic_panel"]["backend"],
            "cpu",
        )
        self.assertEqual(
            self.contract["diagnostic_panel"]["cuda_visible_devices"],
            "",
        )
        self.assertFalse(self.contract["diagnostic_panel"]["capture"])
        self.assertEqual(
            self.contract["diagnostic_panel"]["retry_count"],
            0,
        )

    def test_selected_schedule_preserves_positions_and_endpoints(self) -> None:
        grasp = (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0)
        transit = (math.sqrt(0.75), 0.0, 0.5, 0.0)
        route = self.tool.build_consecutive_left_transition_positions(
            previous_retreat_position_xyz_m=(0.0, -0.1678, 0.93),
            next_front_clearance_position_xyz_m=(-0.24, 0.03, 0.90),
            clearance_tcp_z_m=1.02,
            cartesian_waypoints_per_segment=8,
        )
        rows = self.tool.build_consecutive_left_transition_ik_candidates(
            route_positions=route,
            grasp_orientation_wxyz=grasp,
            transit_orientation_wxyz=transit,
        )["coupled_descent_slerp"]
        self.assertEqual(len(rows), 24)
        self.assertEqual(
            [row["stage"] for row in rows],
            ["vertical_clearance"] * 8
            + ["lateral_clearance"] * 8
            + ["descend_to_front_clearance"] * 8,
        )
        self.assertEqual(
            [row["position_xyz_m"] for row in rows[:8]],
            route["vertical_clearance"],
        )
        self.assertEqual(
            [row["position_xyz_m"] for row in rows[8:16]],
            route["lateral_clearance"],
        )
        self.assertEqual(
            [row["position_xyz_m"] for row in rows[16:]],
            route["descend_to_front_clearance"],
        )
        self.assertEqual(rows[0]["orientation_wxyz"], grasp)
        self.assertEqual(rows[15]["orientation_wxyz"], grasp)
        self.assertTrue(
            all(
                abs(left - right) <= 1e-15
                for left, right in zip(
                    rows[-1]["orientation_wxyz"],
                    transit,
                )
            )
        )

    def test_dynamic_runtime_is_explicit_and_receipted(self) -> None:
        source = (
            ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"--consecutive-left-orientation-schedule"',
            source,
        )
        self.assertIn(
            '"--consecutive-left-dynamic-contract"',
            source,
        )
        self.assertIn(
            '== "coupled_descent_slerp"',
            source,
        )
        self.assertIn('"orientation_schedule_id"', source)
        self.assertIn('"executed_transition_stages"', source)
        self.assertIn('"orientation_waypoints_wxyz"', source)
        self.assertIn(
            'if "reorient_at_clearance" in (',
            source,
        )

    def test_default_schedule_remains_v1(self) -> None:
        self.assertEqual(
            self.tool.G3_LEFT_DYNAMIC_ORIENTATION_SCHEDULES,
            (
                "fixed_position_reorient_v1",
                "coupled_descent_slerp",
            ),
        )


if __name__ == "__main__":
    unittest.main()
