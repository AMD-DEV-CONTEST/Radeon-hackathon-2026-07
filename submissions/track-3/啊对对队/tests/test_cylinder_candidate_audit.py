from __future__ import annotations

import math
from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.cylinder_candidate_audit import (
    audit_cylinder_candidate_population,
    initial_cylinder_pose,
)
from parcel_sorter.randomization import DomainRandomizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CylinderCandidateAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        self.protocol = {
            "metadata": {"protocol_id": "test-cylinder-audit"},
            "population": {
                "profile_ids": ["upright_canister", "mailing_tube"],
                "episodes_per_profile": 2,
                "expected_samples": 4,
                "episode_starts": {
                    "upright_canister": 10_100_000,
                    "mailing_tube": 10_200_000,
                },
            },
            "planner": {
                "hand_clearance_m": 0.113,
                "jaw_aperture_m": 0.080,
                "min_aperture_margin_m": 0.001,
                "min_horizontal_rolling_friction": 0.001,
                "max_parallel_jaw_length_m": 0.320,
                "max_axis_tilt_deg": 20.0,
                "include_symmetric_wrist": True,
                "upright_radial_yaw_count": 4,
                "max_upright_vertical_offset_m": 0.020,
                "min_upright_side_overlap_m": 0.020,
                "max_horizontal_axial_offset_m": 0.050,
                "min_horizontal_end_margin_m": 0.060,
                "horizontal_radial_angles_deg": [0.0, -20.0, 20.0],
            },
            "gates": {
                "min_candidates_per_sample": 8,
                "max_quaternion_norm_error": 1e-12,
                "max_axis_alignment_error": 1e-12,
            },
        }

    def test_initial_horizontal_pose_rotates_local_axis_to_sample_yaw(self) -> None:
        randomizer = DomainRandomizer(
            self.config.randomization,
            self.config.seed,
            self.config.parcel_profiles,
        )
        sample = randomizer.sample_profile("mailing_tube", 10_200_000)
        pose = initial_cylinder_pose(sample)
        w, x, y, z = pose[3:]
        axis = (
            2 * (x * z + w * y),
            2 * (y * z - w * x),
            1 - 2 * (x * x + y * y),
        )

        self.assertAlmostEqual(axis[0], math.cos(sample.yaw_rad))
        self.assertAlmostEqual(axis[1], math.sin(sample.yaw_rad))
        self.assertAlmostEqual(axis[2], 0.0)
        self.assertAlmostEqual(pose[2], sample.dimensions_m[1] / 2)

    def test_audit_is_outcome_free_complete_and_deterministic(self) -> None:
        first = audit_cylinder_candidate_population(self.config, self.protocol)
        second = audit_cylinder_candidate_population(self.config, self.protocol)

        self.assertEqual(first["status"], "candidate_population_valid")
        self.assertEqual(first["errors"], [])
        self.assertEqual(first["observed_samples"], 4)
        self.assertEqual(first["population_sha256"], second["population_sha256"])
        self.assertEqual(first["selection_contract"]["outcome_fields_read"], [])
        self.assertFalse(first["selection_contract"]["scene_constructed"])
        self.assertFalse(first["selection_contract"]["physics_stepped"])

    def test_profile_summaries_preserve_shape_specific_candidate_counts(self) -> None:
        result = audit_cylinder_candidate_population(self.config, self.protocol)
        upright = result["profile_summaries"]["upright_canister"]
        horizontal = result["profile_summaries"]["mailing_tube"]

        self.assertEqual(upright["supported_count"], 2)
        self.assertEqual(upright["candidate_count_min"], 16)
        self.assertEqual(upright["candidate_count_max"], 16)
        self.assertEqual(horizontal["supported_count"], 2)
        self.assertEqual(horizontal["candidate_count_min"], 18)
        self.assertEqual(horizontal["candidate_count_max"], 18)
        self.assertLess(horizontal["max_axis_alignment_error"], 1e-12)
        self.assertLess(horizontal["max_approach_axis_dot"], 1e-12)

    def test_population_contract_failure_is_reported(self) -> None:
        self.protocol["population"]["expected_samples"] = 5

        result = audit_cylinder_candidate_population(self.config, self.protocol)

        self.assertEqual(result["status"], "candidate_population_invalid")
        self.assertIn("population_size_contract", result["errors"])
        self.assertIn("observed_sample_count", result["errors"])


if __name__ == "__main__":
    unittest.main()
