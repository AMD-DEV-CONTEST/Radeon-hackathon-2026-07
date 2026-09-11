import unittest
from pathlib import Path

from parcel_sorter.mobile_pi05_validation import (
    GRASP_MODES,
    build_pi05_validation_design,
    summarize_pi05_frozen_validation,
    summarize_pi05_long_run,
    validate_pi05_validation_design,
)


ROOT = Path(__file__).resolve().parents[1]


def _pure_run(episode: dict, *, success: bool = True) -> dict:
    mode = episode["grasp_mode"]
    return {
        "episode_id": episode["episode_id"],
        "success": success,
        "pure_vla_complete_success": success,
        "policy_authority": "absolute_vla_action_candidate",
        "system_control_class": "pure_vla",
        "task_action_correction_count": 0,
        "expert_reference_used": False,
        "suction": {"max_contact_force_n": 10.0},
        "policy": {
            "mode": "pi05_absolute",
            "policy_authority": "absolute_vla_action_candidate",
            "system_control_class": "pure_vla",
            "task_action_correction_count": 0,
            "absolute_full_authority": True,
            "expert_reference_used": False,
            "expert_fallback_count": 0,
            "emergency_stop_count": 0,
            "applied_physics_steps": 20,
            "selected_grasp_mode": mode,
            "executed_grasp_mode": mode,
            "grasp_mode_match": True,
            "policy_runtime_session_id": "persistent-session-1",
        },
    }


class MobilePI05ValidationDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validation, cls.long_run = build_pi05_validation_design(
            ROOT / "configs/catalog_v2.toml"
        )

    def test_design_is_balanced_and_repeated_measure_count_is_honest(self) -> None:
        validate_pi05_validation_design(self.validation, self.long_run)
        self.assertEqual(len(self.validation["episodes"]), 60)
        self.assertEqual(len(self.long_run["episodes"]), 120)
        self.assertEqual(self.long_run["independent_physical_contexts"], 60)
        for mode in GRASP_MODES:
            self.assertEqual(
                sum(item["grasp_mode"] == mode for item in self.validation["episodes"]),
                20,
            )

    def test_design_is_deterministic_and_fingerprinted(self) -> None:
        other_validation, other_long_run = build_pi05_validation_design(
            ROOT / "configs/catalog_v2.toml"
        )
        self.assertEqual(self.validation, other_validation)
        self.assertEqual(self.long_run, other_long_run)

    def test_development_design_uses_a_disjoint_parameter_grid(self) -> None:
        development, _ = build_pi05_validation_design(
            ROOT / "configs/catalog_v2.toml",
            seed=20260711,
            blocks=10,
            context_prefix="pd30",
            validation_collection_id="development",
            long_run_collection_id="development-repeat",
            validation_split="development_validation_do_not_train",
        )
        self.assertEqual(len(development["episodes"]), 30)
        final_physics = {
            (
                item["profile"],
                tuple(item["size_m"]),
                item["mass_kg"],
                item["friction"],
                tuple(item["offset_m"]),
                item["yaw_rad"],
            )
            for item in self.validation["episodes"]
        }
        development_physics = {
            (
                item["profile"],
                tuple(item["size_m"]),
                item["mass_kg"],
                item["friction"],
                tuple(item["offset_m"]),
                item["yaw_rad"],
            )
            for item in development["episodes"]
        }
        self.assertFalse(final_physics & development_physics)

    def test_frozen_gate_accepts_45_of_60_with_13_per_mode(self) -> None:
        successes_left = {mode: 15 for mode in GRASP_MODES}
        runs = []
        for episode in self.validation["episodes"]:
            mode = episode["grasp_mode"]
            success = successes_left[mode] > 0
            successes_left[mode] -= int(success)
            runs.append(_pure_run(episode, success=success))
        result = summarize_pi05_frozen_validation(
            self.validation,
            {"runs": runs},
            telemetry={
                "sample_count": 3,
                "energy_wh": 6.0,
                "sampling_error_count": 0,
            },
        )
        self.assertEqual(result["pure_vla_complete_success"]["successes"], 45)
        self.assertTrue(result["gate_checks"]["per_mode_success"])
        self.assertEqual(result["status"], "passed")

    def test_hybrid_success_receives_no_credit(self) -> None:
        runs = [_pure_run(item) for item in self.validation["episodes"]]
        runs[0]["policy"]["mode"] = "pi05_residual"
        runs[0]["policy_authority"] = "hybrid_expert_reference_plus_vla_residual"
        runs[0]["expert_reference_used"] = True
        result = summarize_pi05_frozen_validation(
            self.validation,
            {"runs": runs},
            telemetry={
                "sample_count": 3,
                "energy_wh": 6.0,
                "sampling_error_count": 0,
            },
        )
        self.assertEqual(result["pure_vla_complete_success"]["successes"], 59)
        self.assertFalse(result["gate_checks"]["all_runs_pure_vla"])
        self.assertEqual(result["status"], "failed")

    def test_missing_radeon_telemetry_blocks_formal_validation(self) -> None:
        runs = [_pure_run(item) for item in self.validation["episodes"]]
        result = summarize_pi05_frozen_validation(self.validation, {"runs": runs})
        self.assertFalse(result["gate_checks"]["rocm_telemetry_complete"])
        self.assertEqual(result["status"], "failed")

    def test_long_run_reports_60_independent_not_120(self) -> None:
        runs = [_pure_run(item) for item in self.long_run["episodes"]]
        telemetry = {
            "energy_wh": 12.0,
            "vram_growth_percentage_points": 1.0,
        }
        result = summarize_pi05_long_run(
            self.long_run, {"runs": runs}, telemetry=telemetry
        )
        self.assertEqual(result["independent_physical_contexts"], 60)
        self.assertEqual(result["descriptive_repeated_rollouts"], 120)
        self.assertTrue(result["persistent_policy_runtime_evidence"])
        self.assertAlmostEqual(result["telemetry"]["wh_per_attempt"], 0.1)


if __name__ == "__main__":
    unittest.main()
