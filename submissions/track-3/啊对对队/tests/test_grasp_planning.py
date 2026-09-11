from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.grasp_planning import (
    box_requires_geometry_aware_grasp_planning,
    effective_rejected_candidate_ids,
    generate_box_grasp_pose_candidates,
    generate_box_oblique_grasp_pose_candidates,
    generate_box_side_grasp_pose_candidates,
    grasp_evaluation_is_feasible,
    interpolate_joint_segment,
    rank_grasp_pose_evaluations,
    rejected_candidates_after_retry,
    select_grasp_pose_evaluation,
)
from parcel_sorter.randomization import DomainRandomizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GraspPoseCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
        self.sample = replace(
            randomizer.sample_profile("large_narrow_carton", 7_000_000),
            dimensions_m=(0.35, 0.07, 0.16),
            position_xy=(0.60, 0.10),
            yaw_rad=0.0,
        )
        self.parcel_pose = (0.60, 0.10, 0.08, 1.0, 0.0, 0.0, 0.0)

    def test_generates_unique_longitudinal_height_and_wrist_variants(self) -> None:
        candidates = generate_box_grasp_pose_candidates(
            self.sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
        )

        self.assertEqual(len(candidates), 24)
        self.assertEqual(len({candidate.candidate_id for candidate in candidates}), 24)
        self.assertEqual({candidate.wrist_variant for candidate in candidates}, {"canonical", "symmetric_pi"})

    def test_offsets_preserve_edge_and_side_overlap_constraints(self) -> None:
        candidates = generate_box_grasp_pose_candidates(
            self.sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
        )

        self.assertLessEqual(max(abs(item.longitudinal_offset_m) for item in candidates), 0.05)
        self.assertLessEqual(max(item.vertical_offset_m for item in candidates), 0.055)
        self.assertGreaterEqual(
            self.sample.dimensions_m[0] / 2
            - max(abs(item.longitudinal_offset_m) for item in candidates),
            0.06,
        )
        self.assertGreaterEqual(
            self.sample.dimensions_m[2] / 2
            - max(item.vertical_offset_m for item in candidates),
            0.02,
        )

    def test_longitudinal_offset_rotates_with_parcel_yaw(self) -> None:
        sample = replace(self.sample, yaw_rad=math.pi / 2)
        parcel_pose = (
            self.parcel_pose[0],
            self.parcel_pose[1],
            self.parcel_pose[2],
            math.cos(math.pi / 4),
            0.0,
            0.0,
            math.sin(math.pi / 4),
        )
        candidates = generate_box_grasp_pose_candidates(
            sample,
            parcel_pose,
            hand_clearance_m=0.105,
        )
        positive = next(
            item
            for item in candidates
            if item.wrist_variant == "canonical"
            and math.isclose(item.longitudinal_offset_m, 0.05)
            and math.isclose(item.vertical_offset_m, 0.0)
        )

        self.assertAlmostEqual(positive.target_position[0], parcel_pose[0])
        self.assertAlmostEqual(positive.target_position[1], parcel_pose[1] + 0.05)

    def test_wrist_quaternions_are_normalized_and_distinct(self) -> None:
        candidates = generate_box_grasp_pose_candidates(
            self.sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
        )
        quaternions = {
            item.wrist_variant: item.target_quaternion
            for item in candidates
            if math.isclose(item.longitudinal_offset_m, 0.0)
            and math.isclose(item.vertical_offset_m, 0.0)
        }

        self.assertNotEqual(quaternions["canonical"], quaternions["symmetric_pi"])
        for quaternion in quaternions.values():
            self.assertAlmostEqual(math.sqrt(sum(value * value for value in quaternion)), 1.0)

    def test_symmetric_wrist_generation_can_be_disabled_for_ablation(self) -> None:
        candidates = generate_box_grasp_pose_candidates(
            self.sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
            include_symmetric_wrist=False,
        )

        self.assertEqual(len(candidates), 12)
        self.assertEqual({item.wrist_variant for item in candidates}, {"canonical"})

    def test_top_down_candidates_preserve_explicit_approach_metadata(self) -> None:
        candidates = generate_box_grasp_pose_candidates(
            self.sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
        )

        self.assertEqual({item.approach_variant for item in candidates}, {"top_down"})
        self.assertEqual(
            {item.approach_direction for item in candidates},
            {(0.0, 0.0, -1.0)},
        )

    def test_side_candidates_keep_palm_outside_and_approach_from_both_ends(self) -> None:
        candidates = generate_box_side_grasp_pose_candidates(
            self.sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
        )

        self.assertEqual(len(candidates), 8)
        self.assertEqual(
            {item.wrist_variant for item in candidates},
            {"positive_long", "negative_long"},
        )
        half_length_m = self.sample.dimensions_m[0] / 2
        for candidate in candidates:
            side_sign = 1.0 if candidate.target_position[0] > self.parcel_pose[0] else -1.0
            palm_offset_m = side_sign * (
                candidate.target_position[0] - self.parcel_pose[0]
            )
            self.assertGreaterEqual(palm_offset_m, half_length_m + 0.065 - 1e-12)
            self.assertAlmostEqual(
                math.sqrt(
                    sum(value * value for value in candidate.target_quaternion)
                ),
                1.0,
            )
            w, x, y, z = candidate.target_quaternion
            local_z_world = (
                2 * (x * z + w * y),
                2 * (y * z - w * x),
                1 - 2 * (x * x + y * y),
            )
            for actual, expected in zip(
                local_z_world,
                candidate.approach_direction,
                strict=True,
            ):
                self.assertAlmostEqual(actual, expected)

    def test_side_candidates_rotate_with_box_yaw(self) -> None:
        parcel_pose = (
            self.parcel_pose[0],
            self.parcel_pose[1],
            self.parcel_pose[2],
            math.cos(math.pi / 4),
            0.0,
            0.0,
            math.sin(math.pi / 4),
        )
        candidates = generate_box_side_grasp_pose_candidates(
            self.sample,
            parcel_pose,
            hand_clearance_m=0.105,
        )

        positive = next(
            item
            for item in candidates
            if item.wrist_variant == "positive_long"
            and math.isclose(item.vertical_offset_m, 0.0)
        )
        self.assertAlmostEqual(positive.target_position[0], parcel_pose[0])
        self.assertGreater(positive.target_position[1], parcel_pose[1])
        for actual, expected in zip(
            positive.approach_direction,
            (0.0, -1.0, 0.0),
            strict=True,
        ):
            self.assertAlmostEqual(actual, expected)

    def test_side_candidates_reject_boxes_without_contact_edge_margin(self) -> None:
        sample = replace(self.sample, dimensions_m=(0.06, 0.07, 0.08))

        candidates = generate_box_side_grasp_pose_candidates(
            sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
        )

        self.assertEqual(candidates, ())

    def test_oblique_candidates_tilt_palm_while_preserving_centred_contact(self) -> None:
        candidates = generate_box_oblique_grasp_pose_candidates(
            self.sample,
            self.parcel_pose,
            hand_clearance_m=0.105,
        )

        self.assertEqual(len(candidates), 8)
        self.assertEqual(
            {item.approach_variant for item in candidates},
            {"oblique_top_down"},
        )
        self.assertEqual(
            {
                round(math.degrees(math.acos(-item.approach_direction[2])))
                for item in candidates
            },
            {30, 45},
        )
        for candidate in candidates:
            self.assertAlmostEqual(candidate.longitudinal_offset_m, 0.0)
            self.assertLess(candidate.approach_direction[2], 0.0)
            self.assertAlmostEqual(
                math.sqrt(
                    sum(value * value for value in candidate.approach_direction)
                ),
                1.0,
            )
            w, x, y, z = candidate.target_quaternion
            local_z_world = (
                2 * (x * z + w * y),
                2 * (y * z - w * x),
                1 - 2 * (x * x + y * y),
            )
            for actual, expected in zip(
                local_z_world,
                candidate.approach_direction,
                strict=True,
            ):
                self.assertAlmostEqual(actual, expected)

    def test_planning_scope_is_derived_from_palm_clearance_and_side_overlap(self) -> None:
        below = replace(self.sample, dimensions_m=(0.30, 0.07, 0.1249))
        at_boundary = replace(self.sample, dimensions_m=(0.30, 0.07, 0.1250))

        self.assertFalse(
            box_requires_geometry_aware_grasp_planning(
                below,
                hand_clearance_m=0.105,
            )
        )
        self.assertTrue(
            box_requires_geometry_aware_grasp_planning(
                at_boundary,
                hand_clearance_m=0.105,
            )
        )

    def test_joint_segment_interpolation_bounds_every_arm_increment(self) -> None:
        start = (0.0,) * 9
        goal = (0.10, -0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.04, 0.04)

        segment = interpolate_joint_segment(
            start,
            goal,
            max_joint_delta_rad=0.025,
        )

        self.assertEqual(len(segment), 4)
        self.assertEqual(segment[-1], goal)
        previous = start
        for waypoint in segment:
            self.assertLessEqual(
                max(abs(a - b) for a, b in zip(previous[:7], waypoint[:7], strict=True)),
                0.025 + 1e-12,
            )
            previous = waypoint


class GraspPoseRankingTests(unittest.TestCase):
    @staticmethod
    def evaluation(candidate_id: str, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "candidate_id": candidate_id,
            "seed_name": "current",
            "wrist_variant": "canonical",
            "longitudinal_offset_m": 0.0,
            "vertical_offset_m": 0.02,
            "finite": True,
            "ik_position_error_m": 0.001,
            "ik_rotation_error_rad": 0.01,
            "fk_position_error_m": 0.001,
            "restore_max_abs_error": 0.0,
            "disallowed_collision_count": 0,
            "nonfinger_clearance_m": 0.010,
            "minimum_singular_value": 0.10,
            "joint_distance_rad": 1.0,
        }
        row.update(overrides)
        return row

    def test_subthreshold_ik_noise_does_not_outrank_clearance_and_manipulability(self) -> None:
        lower_ik_error = self.evaluation(
            "low-error",
            ik_position_error_m=1e-6,
            nonfinger_clearance_m=0.002,
            minimum_singular_value=0.02,
        )
        safer_pose = self.evaluation(
            "safer",
            ik_position_error_m=0.004,
            nonfinger_clearance_m=0.020,
            minimum_singular_value=0.20,
        )

        ranked = rank_grasp_pose_evaluations((lower_ik_error, safer_pose))

        self.assertEqual(ranked[0]["candidate_id"], "safer")

    def test_collision_filter_rejects_nonfinger_collision(self) -> None:
        colliding = self.evaluation("colliding", disallowed_collision_count=1)

        self.assertFalse(grasp_evaluation_is_feasible(colliding))
        self.assertTrue(
            grasp_evaluation_is_feasible(
                colliding,
                collision_filter_enabled=False,
            )
        )

    def test_selection_skips_candidate_rejected_by_a_dynamic_waypoint(self) -> None:
        preferred = self.evaluation("preferred", nonfinger_clearance_m=0.020)
        fallback = self.evaluation("fallback", nonfinger_clearance_m=0.010)

        selected = select_grasp_pose_evaluation(
            (preferred, fallback),
            rejected_candidate_ids=frozenset({"preferred"}),
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["candidate_id"], "fallback")

    def test_retry_blacklist_accumulates_failed_candidates_when_enabled(self) -> None:
        first = self.evaluation("first")
        second = self.evaluation("second")

        rejected = rejected_candidates_after_retry(
            set(),
            first,
            retry_changed=True,
            blacklist_failed_candidate_enabled=True,
        )
        rejected = rejected_candidates_after_retry(
            rejected,
            second,
            retry_changed=True,
            blacklist_failed_candidate_enabled=True,
        )

        self.assertEqual(rejected, {"first", "second"})

    def test_retry_blacklist_preserves_historical_default(self) -> None:
        selected = self.evaluation("failed")

        unchanged = rejected_candidates_after_retry(
            {"waypoint-rejected"},
            selected,
            retry_changed=False,
            blacklist_failed_candidate_enabled=True,
        )
        default_retry = rejected_candidates_after_retry(
            {"waypoint-rejected"},
            selected,
            retry_changed=True,
            blacklist_failed_candidate_enabled=False,
        )

        self.assertEqual(unchanged, {"waypoint-rejected"})
        self.assertEqual(default_retry, set())

    def test_diagnostic_allowlist_adds_to_runtime_rejections(self) -> None:
        effective = effective_rejected_candidate_ids(
            ("a", "b", "c"),
            {"c"},
            frozenset({"b"}),
        )

        self.assertEqual(effective, frozenset({"a", "c"}))
        self.assertEqual(
            effective_rejected_candidate_ids(("a", "b"), {"a"}),
            frozenset({"a"}),
        )

    def test_centered_lower_side_contact_outranks_shorter_joint_path(self) -> None:
        off_center = self.evaluation(
            "off-center",
            longitudinal_offset_m=0.05,
            vertical_offset_m=0.04,
            joint_distance_rad=0.4,
        )
        centered = self.evaluation(
            "centered",
            longitudinal_offset_m=0.0,
            vertical_offset_m=0.02,
            joint_distance_rad=0.8,
        )

        ranked = rank_grasp_pose_evaluations((off_center, centered))

        self.assertEqual(ranked[0]["candidate_id"], "centered")


if __name__ == "__main__":
    unittest.main()
