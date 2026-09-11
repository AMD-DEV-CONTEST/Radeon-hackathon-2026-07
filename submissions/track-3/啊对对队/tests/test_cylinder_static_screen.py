from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.cylinder_static_screen import (
    screen_cylinder_environment,
    screen_episode_keys,
    summarize_static_screen,
)
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.cylinder_candidate_audit import initial_cylinder_pose
from scripts.run_cylinder_static_screen import _sample_matches_source
from scripts.run_cylinder_static_screen import _load_toml, _validate_protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Expert:
    @staticmethod
    def grasp_hand_clearance_m() -> float:
        return 0.105


class _State:
    parcel_pose = (
        0.60,
        0.08,
        0.025,
        0.7071067811865476,
        0.0,
        0.7071067811865476,
        0.0,
    )


class _FakeEnvironment:
    def __init__(self, config, sample) -> None:
        self.config = config
        self.sample = sample
        self.expert = _Expert()

    @staticmethod
    def state() -> _State:
        return _State()

    @staticmethod
    def _grasp_planning_seeds():
        return (("current", (0.0,) * 9), ("reset", (0.1,) * 9))

    @staticmethod
    def _evaluate_grasp_pose_candidate(candidate, seed_name, seed_qpos):
        del seed_qpos
        feasible = (
            candidate.wrist_variant == "canonical"
            and candidate.longitudinal_offset_m == 0.0
        )
        return {
            **candidate.__dict__,
            "seed_name": seed_name,
            "finite": True,
            "feasible": feasible,
            "ik_position_error_m": 0.001 if feasible else 0.010,
            "ik_rotation_error_rad": 0.001,
            "fk_position_error_m": 0.001,
            "joint_distance_rad": 0.5,
            "minimum_singular_value": 0.1,
            "nonfinger_clearance_m": 0.02,
            "collision_count": 0,
            "disallowed_collision_count": 0,
            "restore_max_abs_error": 0.0,
            "compute_ms": 0.1,
        }


class CylinderStaticScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        randomizer = DomainRandomizer(
            self.config.randomization,
            self.config.seed,
            self.config.parcel_profiles,
        )
        self.sample = replace(
            randomizer.sample_profile("mailing_tube", 10_200_000),
            dimensions_m=(0.24, 0.05, 0.05),
            yaw_rad=0.0,
        )
        self.protocol = {
            "population": {
                "profile_ids": ["upright_canister", "mailing_tube"],
                "episode_offsets": [0, 5],
                "episode_starts": {
                    "upright_canister": 10_100_000,
                    "mailing_tube": 10_200_000,
                },
                "expected_samples": 4,
            },
            "execution": {
                "backend": "rocm",
                "require_single_visible_device": True,
                "require_hip": True,
                "defer_initialization_settle": True,
                "expected_physics_steps": 0,
            },
            "planner": {
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
                "min_feasible_sample_fraction_per_profile": 0.75,
                "max_restore_error": 1e-7,
                "max_screen_compute_p95_ms": 5000.0,
            },
        }

    def test_episode_selection_is_complete_deterministic_and_interleak_free(self) -> None:
        keys = screen_episode_keys(self.protocol)

        self.assertEqual(
            keys,
            (
                ("upright_canister", 10_100_000),
                ("upright_canister", 10_100_005),
                ("mailing_tube", 10_200_000),
                ("mailing_tube", 10_200_005),
            ),
        )

    def test_environment_screen_counts_unique_feasible_candidates(self) -> None:
        result = screen_cylinder_environment(
            _FakeEnvironment(self.config, self.sample),
            self.protocol,
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["candidate_count"], 18)
        self.assertEqual(result["evaluation_count"], 36)
        self.assertEqual(result["feasible_candidate_count"], 3)
        self.assertEqual(result["feasible_evaluation_count"], 6)
        self.assertTrue(result["all_evaluations_finite"])
        self.assertFalse(result["contract"]["physics_stepped"])
        self.assertFalse(result["contract"]["task_outcome_read"])

    def test_summary_applies_profile_fraction_and_latency_gates(self) -> None:
        rows = []
        for profile_id, episode in screen_episode_keys(self.protocol):
            rows.append(
                {
                    "status": "complete",
                    "profile_id": profile_id,
                    "episode": episode,
                    "feasible_candidate_count": 2,
                    "all_evaluations_finite": True,
                    "maximum_restore_error": 0.0,
                    "screen_compute_ms": 12.0,
                    "scene_build_ms": 100.0,
                    "device": {
                        "backend": "rocm",
                        "torch_version": "test",
                        "torch_hip_version": "7.2",
                        "visible_device_count": 1,
                        "device_name": "AMD Radeon Graphics",
                        "gcn_arch_name": "gfx1100",
                        "total_memory_bytes": 1,
                    },
                }
            )

        passed = summarize_static_screen(rows, self.protocol)
        rows[-1]["feasible_candidate_count"] = 0
        rows[-2]["feasible_candidate_count"] = 0
        failed = summarize_static_screen(rows, self.protocol)

        self.assertEqual(passed["status"], "screen_pass")
        self.assertEqual(passed["errors"], [])
        self.assertEqual(failed["status"], "screen_fail")
        self.assertIn("profile_feasible_fraction:mailing_tube", failed["errors"])

    def test_summary_rejects_restore_error_and_incomplete_population(self) -> None:
        profile_id, episode = screen_episode_keys(self.protocol)[0]
        result = summarize_static_screen(
            (
                {
                    "status": "complete",
                    "profile_id": profile_id,
                    "episode": episode,
                    "feasible_candidate_count": 1,
                    "all_evaluations_finite": True,
                    "maximum_restore_error": 1e-5,
                    "screen_compute_ms": 1.0,
                    "scene_build_ms": 1.0,
                    "device": {
                        "backend": "rocm",
                        "torch_version": "test",
                        "torch_hip_version": "7.2",
                        "visible_device_count": 1,
                        "device_name": "AMD Radeon Graphics",
                        "gcn_arch_name": "gfx1100",
                        "total_memory_bytes": 1,
                    },
                },
            ),
            self.protocol,
        )

        self.assertEqual(result["status"], "screen_fail")
        self.assertIn("sample_population_incomplete", result["errors"])
        self.assertIn("state_restore_error", result["errors"])

    def test_summary_rejects_non_rocm_or_multiple_device_evidence(self) -> None:
        rows = []
        for profile_id, episode in screen_episode_keys(self.protocol):
            rows.append(
                {
                    "status": "complete",
                    "profile_id": profile_id,
                    "episode": episode,
                    "feasible_candidate_count": 1,
                    "all_evaluations_finite": True,
                    "maximum_restore_error": 0.0,
                    "screen_compute_ms": 1.0,
                    "scene_build_ms": 1.0,
                    "device": {
                        "backend": "rocm",
                        "torch_version": "test",
                        "torch_hip_version": "7.2",
                        "visible_device_count": 1,
                        "device_name": "AMD Radeon Graphics",
                        "gcn_arch_name": "gfx1100",
                        "total_memory_bytes": 1,
                    },
                }
            )
        rows[0]["device"] = {
            **rows[0]["device"],
            "backend": "cpu",
            "torch_hip_version": "",
            "visible_device_count": 2,
        }

        result = summarize_static_screen(rows, self.protocol)

        self.assertEqual(result["status"], "screen_fail")
        self.assertIn("device_metadata_mismatch", result["errors"])
        self.assertIn("execution_backend_mismatch", result["errors"])
        self.assertIn("hip_metadata_missing", result["errors"])
        self.assertIn("visible_device_count", result["errors"])

    def test_runner_binds_geometry_affecting_sample_projection(self) -> None:
        source_row = {
            "profile_id": self.sample.profile_id,
            "episode": self.sample.episode_index,
            "orientation_mode": self.sample.orientation_mode,
            "dimensions_m": list(self.sample.dimensions_m),
            "mass_kg": self.sample.mass_kg,
            "friction": self.sample.friction,
            "rolling_friction": self.sample.rolling_friction,
            "position_xy": list(self.sample.position_xy),
            "yaw_rad": self.sample.yaw_rad,
            "pose": list(initial_cylinder_pose(self.sample)),
        }

        self.assertTrue(_sample_matches_source(self.sample, source_row))
        source_row["yaw_rad"] += 1e-4
        self.assertFalse(_sample_matches_source(self.sample, source_row))

    def test_runner_rejects_source_pose_or_dimensions_drift(self) -> None:
        source_row = {
            "profile_id": self.sample.profile_id,
            "episode": self.sample.episode_index,
            "orientation_mode": self.sample.orientation_mode,
            "dimensions_m": list(self.sample.dimensions_m),
            "mass_kg": self.sample.mass_kg,
            "friction": self.sample.friction,
            "rolling_friction": self.sample.rolling_friction,
            "position_xy": list(self.sample.position_xy),
            "yaw_rad": self.sample.yaw_rad,
            "pose": list(initial_cylinder_pose(self.sample)),
        }

        source_row["pose"][2] += 1e-4
        self.assertFalse(_sample_matches_source(self.sample, source_row))
        source_row["pose"] = list(initial_cylinder_pose(self.sample))
        source_row["dimensions_m"][0] += 1e-4
        self.assertFalse(_sample_matches_source(self.sample, source_row))

    def test_active_runner_protocol_binds_source_audit_implementation(self) -> None:
        path = PROJECT_ROOT / "configs" / "cylinder_static_screen_v1.toml"
        protocol = _load_toml(path)

        self.assertEqual(_validate_protocol(path, protocol), [])
        protocol["implementation"]["source_audit_module_sha256"] = "0" * 64
        errors = _validate_protocol(path, protocol)

        self.assertIn("source_audit_module_hash_mismatch", errors)
        self.assertIn("source_implementation:audit_module", errors)

    def test_v2_protocol_is_disjoint_and_reduces_candidate_population(self) -> None:
        v1 = _load_toml(PROJECT_ROOT / "configs" / "cylinder_static_screen_v1.toml")
        v2_path = PROJECT_ROOT / "configs" / "cylinder_static_screen_v2.toml"
        v2 = _load_toml(v2_path)

        self.assertEqual(_validate_protocol(v2_path, v2), [])
        self.assertTrue(set(screen_episode_keys(v1)).isdisjoint(screen_episode_keys(v2)))
        self.assertEqual(v2["planner"]["upright_radial_yaw_count"], 1)
        self.assertEqual(v2["planner"]["horizontal_radial_angles_deg"], [0.0])
        self.assertEqual(v2["planner"]["max_upright_vertical_offset_m"], 0.040)


if __name__ == "__main__":
    unittest.main()
