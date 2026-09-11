from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.cylinder_grasp_planning import (
    assess_cylinder_grasp_capability,
    cylinder_candidate_prior_key,
    cylinder_geometry,
    plan_cylinder_grasp_candidates,
    point_to_capsule_signed_distance,
)
from parcel_sorter.randomization import DomainRandomizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _local_axis(quaternion: tuple[float, float, float, float], index: int) -> tuple[float, float, float]:
    w, x, y, z = quaternion
    columns = (
        (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)),
        (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)),
        (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)),
    )
    return columns[index]


class CylinderGraspPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        self.config = config
        randomizer = DomainRandomizer(
            config.randomization,
            config.seed,
            config.parcel_profiles,
        )
        self.upright = replace(
            randomizer.sample_profile("upright_canister", 8_100_001),
            dimensions_m=(0.060, 0.060, 0.140),
            position_xy=(0.58, -0.06),
            yaw_rad=0.0,
        )
        self.horizontal = replace(
            randomizer.sample_profile("mailing_tube", 8_100_002),
            dimensions_m=(0.240, 0.050, 0.050),
            position_xy=(0.60, 0.08),
            yaw_rad=0.0,
            rolling_friction=0.005,
        )
        self.upright_pose = (0.58, -0.06, 0.070, 1.0, 0.0, 0.0, 0.0)
        self.horizontal_pose = (
            0.60,
            0.08,
            0.025,
            math.cos(math.pi / 4),
            0.0,
            math.sin(math.pi / 4),
            0.0,
        )

    def test_reads_upright_and_horizontal_axis_from_actual_pose(self) -> None:
        upright = cylinder_geometry(self.upright, self.upright_pose)
        horizontal = cylinder_geometry(self.horizontal, self.horizontal_pose)

        self.assertEqual(upright.axis_world, (0.0, 0.0, 1.0))
        self.assertAlmostEqual(horizontal.axis_world[0], 1.0)
        self.assertAlmostEqual(horizontal.axis_world[1], 0.0)
        self.assertAlmostEqual(horizontal.axis_world[2], 0.0)
        self.assertAlmostEqual(horizontal.axial_length_m, 0.240)
        self.assertAlmostEqual(horizontal.diameter_m, 0.050)

    def test_rejects_malformed_radial_dimensions(self) -> None:
        malformed = replace(self.horizontal, dimensions_m=(0.24, 0.05, 0.06))

        with self.assertRaisesRegex(ValueError, "radial dimensions"):
            cylinder_geometry(malformed, self.horizontal_pose)

    def test_capability_accepts_catalog_tube_with_measured_margin(self) -> None:
        capability = assess_cylinder_grasp_capability(
            self.horizontal,
            self.horizontal_pose,
            jaw_aperture_m=0.080,
        )

        self.assertTrue(capability.supported)
        self.assertEqual(capability.reason, "supported")
        self.assertAlmostEqual(capability.aperture_margin_m, 0.030)
        self.assertAlmostEqual(capability.rolling_risk_index, 0.2)

    def test_capability_rejects_large_and_low_rolling_friction_tubes(self) -> None:
        oversized = replace(
            self.horizontal,
            dimensions_m=(0.24, 0.080, 0.080),
        )
        unstable = replace(self.horizontal, rolling_friction=0.0)

        aperture = assess_cylinder_grasp_capability(
            oversized,
            self.horizontal_pose,
            jaw_aperture_m=0.080,
        )
        rolling = assess_cylinder_grasp_capability(
            unstable,
            self.horizontal_pose,
            jaw_aperture_m=0.080,
        )

        self.assertFalse(aperture.supported)
        self.assertEqual(aperture.reason, "jaw_aperture_margin_below_limit")
        self.assertFalse(rolling.supported)
        self.assertEqual(rolling.reason, "horizontal_tube_requires_guarded_support")

    def test_declared_cradle_boundary_never_generates_parallel_jaw_candidates(self) -> None:
        boundary = replace(
            self.horizontal,
            handling_class="cradle_required",
            dimensions_m=(0.50, 0.10, 0.10),
        )

        plan = plan_cylinder_grasp_candidates(
            boundary,
            self.horizontal_pose,
            hand_clearance_m=0.105,
            jaw_aperture_m=0.080,
        )

        self.assertFalse(plan.capability.supported)
        self.assertEqual(
            plan.capability.reason,
            "unsupported_handling_class:cradle_required",
        )
        self.assertEqual(plan.candidates, ())

    def test_upright_candidates_cover_radial_yaw_height_and_symmetric_wrist(self) -> None:
        plan = plan_cylinder_grasp_candidates(
            self.upright,
            self.upright_pose,
            hand_clearance_m=0.113,
            jaw_aperture_m=0.080,
        )

        self.assertTrue(plan.capability.supported)
        self.assertEqual(len(plan.candidates), 16)
        self.assertEqual(len({item.candidate_id for item in plan.candidates}), 16)
        self.assertEqual(
            {item.wrist_variant for item in plan.candidates},
            {"canonical", "symmetric_pi"},
        )
        self.assertEqual(
            {round(item.vertical_offset_m, 3) for item in plan.candidates},
            {0.0, 0.02},
        )
        for candidate in plan.candidates:
            self.assertEqual(candidate.approach_direction, (0.0, 0.0, -1.0))
            self.assertAlmostEqual(sum(value * value for value in candidate.target_quaternion), 1.0)

    def test_horizontal_candidates_align_fingers_to_axis_and_close_across_diameter(self) -> None:
        plan = plan_cylinder_grasp_candidates(
            self.horizontal,
            self.horizontal_pose,
            hand_clearance_m=0.105,
            jaw_aperture_m=0.080,
        )

        self.assertTrue(plan.capability.supported)
        self.assertEqual(len(plan.candidates), 18)
        self.assertEqual(len({item.candidate_id for item in plan.candidates}), 18)
        self.assertEqual(
            {round(item.longitudinal_offset_m, 3) for item in plan.candidates},
            {-0.05, 0.0, 0.05},
        )
        axis = plan.capability.geometry.axis_world
        for candidate in plan.candidates:
            local_x = _local_axis(candidate.target_quaternion, 0)
            local_z = _local_axis(candidate.target_quaternion, 2)
            self.assertAlmostEqual(abs(sum(a * b for a, b in zip(local_x, axis, strict=True))), 1.0)
            self.assertAlmostEqual(sum(a * b for a, b in zip(local_z, axis, strict=True)), 0.0)
            for actual, expected in zip(local_z, candidate.approach_direction, strict=True):
                self.assertAlmostEqual(actual, expected)

    def test_short_tube_collapses_duplicate_axial_offsets(self) -> None:
        short = replace(self.horizontal, dimensions_m=(0.10, 0.05, 0.05))

        plan = plan_cylinder_grasp_candidates(
            short,
            self.horizontal_pose,
            hand_clearance_m=0.105,
            jaw_aperture_m=0.080,
        )

        self.assertEqual(len(plan.candidates), 6)
        self.assertEqual({item.longitudinal_offset_m for item in plan.candidates}, {0.0})

    def test_prior_prefers_top_down_centred_canonical_tube_candidate(self) -> None:
        plan = plan_cylinder_grasp_candidates(
            self.horizontal,
            self.horizontal_pose,
            hand_clearance_m=0.105,
            jaw_aperture_m=0.080,
        )

        selected = min(plan.candidates, key=cylinder_candidate_prior_key)

        self.assertAlmostEqual(selected.radial_approach_angle_rad, 0.0)
        self.assertAlmostEqual(selected.longitudinal_offset_m, 0.0)
        self.assertEqual(selected.wrist_variant, "canonical")

    def test_capsule_distance_is_negative_inside_zero_on_side_and_positive_outside(self) -> None:
        kwargs = {
            "centre": (0.0, 0.0, 0.0),
            "axis": (1.0, 0.0, 0.0),
            "half_segment_length_m": 0.10,
            "radius_m": 0.025,
        }

        inside = point_to_capsule_signed_distance((0.0, 0.0, 0.0), **kwargs)
        surface = point_to_capsule_signed_distance((0.0, 0.025, 0.0), **kwargs)
        beyond_end = point_to_capsule_signed_distance((0.15, 0.0, 0.0), **kwargs)

        self.assertAlmostEqual(inside, -0.025)
        self.assertAlmostEqual(surface, 0.0)
        self.assertAlmostEqual(beyond_end, 0.025)


if __name__ == "__main__":
    unittest.main()
