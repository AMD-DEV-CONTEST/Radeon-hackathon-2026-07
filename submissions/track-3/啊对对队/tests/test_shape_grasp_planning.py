from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.shape_grasp_planning import (
    ShapeGraspPlannerConfig,
    build_shape_grasp_plan,
    generate_shape_grasp_pose_candidates,
    rank_shape_grasp_pose_evaluations,
    select_shape_grasp_pose_evaluation,
)
from parcel_sorter.grasp_planning import rank_grasp_pose_evaluations


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ShapeGraspPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
        self.box = replace(
            randomizer.sample_profile("large_narrow_carton", 20_000_001),
            dimensions_m=(0.320, 0.070, 0.160),
            position_xy=(0.60, 0.0),
            yaw_rad=0.0,
        )
        self.canister = replace(
            randomizer.sample_profile("upright_canister", 20_000_002),
            dimensions_m=(0.060, 0.060, 0.140),
            position_xy=(0.60, -0.06),
            yaw_rad=0.0,
        )
        self.tube = replace(
            randomizer.sample_profile("mailing_tube", 20_000_003),
            dimensions_m=(0.240, 0.050, 0.050),
            position_xy=(0.60, 0.06),
            yaw_rad=0.0,
            rolling_friction=0.005,
        )
        self.box_pose = (0.60, 0.0, 0.08, 1.0, 0.0, 0.0, 0.0)
        self.canister_pose = (0.60, -0.06, 0.07, 1.0, 0.0, 0.0, 0.0)
        self.tube_pose = (0.60, 0.06, 0.025, 0.7071067811865476, 0.0, 0.7071067811865476, 0.0)

    def test_dispatches_box_without_broadening_box_scope(self) -> None:
        plan = build_shape_grasp_plan(
            self.box,
            self.box_pose,
            hand_clearance_m=0.105,
        )

        self.assertTrue(plan.supported)
        self.assertTrue(plan.activation_eligible)
        self.assertEqual(plan.reason, "supported")
        self.assertGreater(len(plan.candidates), 0)
        self.assertTrue(all(item.approach_variant == "top_down" for item in plan.candidates))

    def test_dispatches_upright_cylinder_with_explicit_candidates(self) -> None:
        plan = build_shape_grasp_plan(
            self.canister,
            self.canister_pose,
            hand_clearance_m=0.105,
        )

        self.assertTrue(plan.supported)
        self.assertTrue(plan.activation_eligible)
        self.assertEqual(plan.reason, "supported")
        self.assertEqual(len(plan.candidates), 4)
        self.assertEqual(
            {round(item.vertical_offset_m, 3) for item in plan.candidates},
            {0.0, 0.04},
        )
        self.assertTrue(all(item.approach_variant == "upright_top_down_radial" for item in plan.candidates))

    def test_dispatches_horizontal_tube_and_preserves_axis_family(self) -> None:
        candidates = generate_shape_grasp_pose_candidates(
            self.tube,
            self.tube_pose,
            hand_clearance_m=0.105,
        )

        self.assertEqual(len(candidates), 6)
        self.assertTrue(all(item.approach_variant == "horizontal_cross_diameter" for item in candidates))
        self.assertEqual(len({item.candidate_id for item in candidates}), len(candidates))

    def test_unsupported_handling_class_is_explicitly_empty(self) -> None:
        boundary = replace(
            self.tube,
            handling_class="cradle_required",
            dimensions_m=(0.50, 0.10, 0.10),
        )
        plan = build_shape_grasp_plan(
            boundary,
            self.tube_pose,
            hand_clearance_m=0.105,
        )

        self.assertFalse(plan.supported)
        self.assertFalse(plan.activation_eligible)
        self.assertEqual(plan.reason, "unsupported_handling_class:cradle_required")
        self.assertEqual(plan.candidates, ())

    def test_cylinder_can_be_disabled_without_raising(self) -> None:
        plan = build_shape_grasp_plan(
            self.canister,
            self.canister_pose,
            hand_clearance_m=0.105,
            config=ShapeGraspPlannerConfig(cylinder_enabled=False),
        )

        self.assertFalse(plan.supported)
        self.assertFalse(plan.activation_eligible)
        self.assertEqual(plan.reason, "cylinder_planner_disabled")
        self.assertEqual(plan.candidates, ())

    def test_zero_offset_and_threshold_ablation_remains_representable(self) -> None:
        config = ShapeGraspPlannerConfig(
            cylinder_min_aperture_margin_m=0.0,
            cylinder_min_horizontal_rolling_friction=0.0,
            cylinder_max_upright_vertical_offset_m=0.0,
            cylinder_max_horizontal_axial_offset_m=0.0,
        )

        upright = build_shape_grasp_plan(
            self.canister,
            self.canister_pose,
            hand_clearance_m=0.105,
            config=config,
        )
        horizontal = build_shape_grasp_plan(
            self.tube,
            self.tube_pose,
            hand_clearance_m=0.105,
            config=config,
        )

        self.assertEqual(len(upright.candidates), 2)
        self.assertEqual(len(horizontal.candidates), 2)

    def test_low_rolling_friction_tube_cannot_be_activated(self) -> None:
        unstable = replace(self.tube, rolling_friction=0.0)
        plan = build_shape_grasp_plan(
            unstable,
            self.tube_pose,
            hand_clearance_m=0.105,
        )

        self.assertFalse(plan.supported)
        self.assertFalse(plan.activation_eligible)
        self.assertEqual(plan.reason, "horizontal_tube_requires_guarded_support")

    def test_box_shape_ranking_is_identical_to_registered_ranker(self) -> None:
        farther = self._evaluation("farther", joint_distance_rad=0.8)
        nearer = self._evaluation("nearer", joint_distance_rad=0.2)
        evaluations = [farther, nearer]

        expected = rank_grasp_pose_evaluations(evaluations)
        actual = rank_shape_grasp_pose_evaluations(evaluations, shape="box")

        self.assertEqual(
            [row["candidate_id"] for row in actual],
            [row["candidate_id"] for row in expected],
        )

    def test_cylinder_ranking_prefers_low_roll_and_centred_contact_after_hard_gates(self) -> None:
        risky = self._evaluation(
            "risky",
            joint_distance_rad=0.1,
            rolling_risk_score=0.4,
            centre_of_mass_moment_arm_m=0.0,
        )
        offset = self._evaluation(
            "offset",
            joint_distance_rad=0.2,
            rolling_risk_score=0.0,
            centre_of_mass_moment_arm_m=0.04,
        )
        centred = self._evaluation(
            "centred",
            joint_distance_rad=1.0,
            rolling_risk_score=0.0,
            centre_of_mass_moment_arm_m=0.0,
        )

        ranked = rank_shape_grasp_pose_evaluations(
            [risky, offset, centred],
            shape="cylinder",
        )

        self.assertEqual(
            [row["candidate_id"] for row in ranked],
            ["centred", "offset", "risky"],
        )

    def test_cylinder_hard_feasibility_precedes_rolling_prior_and_rejections(self) -> None:
        infeasible = self._evaluation(
            "infeasible",
            rolling_risk_score=0.0,
            ik_position_error_m=0.010,
        )
        first = self._evaluation(
            "first",
            rolling_risk_score=0.1,
            centre_of_mass_moment_arm_m=0.0,
        )
        fallback = self._evaluation(
            "fallback",
            rolling_risk_score=0.2,
            centre_of_mass_moment_arm_m=0.0,
        )

        selected = select_shape_grasp_pose_evaluation(
            [infeasible, fallback, first],
            shape="cylinder",
            rejected_candidate_ids=frozenset({"first"}),
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["candidate_id"], "fallback")

    @staticmethod
    def _evaluation(candidate_id: str, **overrides):
        row = {
            "candidate_id": candidate_id,
            "seed_name": "current",
            "finite": True,
            "ik_position_error_m": 0.001,
            "ik_rotation_error_rad": 0.001,
            "fk_position_error_m": 0.001,
            "restore_max_abs_error": 0.0,
            "disallowed_collision_count": 0,
            "nonfinger_clearance_m": 0.01,
            "minimum_singular_value": 0.1,
            "wrist_variant": "canonical",
            "longitudinal_offset_m": 0.0,
            "vertical_offset_m": 0.0,
            "joint_distance_rad": 0.5,
            "rolling_risk_score": 0.0,
            "centre_of_mass_moment_arm_m": 0.0,
        }
        row.update(overrides)
        return row


if __name__ == "__main__":
    unittest.main()
