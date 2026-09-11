from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_mobile_pi05_competition_v19_teacher_specialization",
    ROOT / "scripts" / "audit_mobile_pi05_competition_v19_teacher_specialization.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CompetitionV19TeacherSpecializationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prereg_path = (
            ROOT
            / "configs"
            / "mobile_pi05_competition_v19_teacher_specialization_preregistration.json"
        )
        cls.source_path = (
            ROOT / "configs" / "mobile_pi05_single_box_v14_v7_strict_smoke_3.json"
        )
        cls.deployment_path = (
            ROOT
            / "configs"
            / "mobile_pi05_competition_v18_deployment_progress_preregistration.json"
        )
        cls.prereg = json.loads(cls.prereg_path.read_text(encoding="utf-8"))
        cls.viable_prereg_path = (
            ROOT
            / "configs"
            / "mobile_pi05_competition_v19b_viable_teacher_subset_preregistration.json"
        )
        cls.viable_prereg = json.loads(
            cls.viable_prereg_path.read_text(encoding="utf-8")
        )
        cls.uniform_six_prereg_path = (
            ROOT
            / "configs"
            / "mobile_pi05_competition_v19c_uniform_six_preregistration.json"
        )
        cls.uniform_six_prereg = json.loads(
            cls.uniform_six_prereg_path.read_text(encoding="utf-8")
        )
        cls.mode_only_prereg_path = (
            ROOT
            / "configs"
            / "mobile_pi05_competition_v20_mode_only_preregistration.json"
        )
        cls.mode_only_prereg = json.loads(
            cls.mode_only_prereg_path.read_text(encoding="utf-8")
        )
        cls.source = json.loads(cls.source_path.read_text(encoding="utf-8"))
        cls.deployment = json.loads(cls.deployment_path.read_text(encoding="utf-8"))

    def test_frozen_preregistration_and_source_hashes_pass(self) -> None:
        result = MODULE.audit_preregistration(
            self.prereg,
            self.source,
            self.deployment,
            source_smoke_sha256=MODULE._sha256(self.source_path),
            deployment_preregistration_sha256=MODULE._sha256(self.deployment_path),
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["training_seed"], 11)
        self.assertEqual(result["inference_seeds"], [20260727, 20260728, 20260729])

    def test_generated_teacher_plan_preserves_cases_and_discloses_expert(self) -> None:
        generated = MODULE.build_teacher_collection_config(self.prereg, self.source)
        self.assertEqual(len(generated["episodes"]), 3)
        for source, teacher in zip(
            self.source["episodes"], generated["episodes"], strict=True
        ):
            self.assertEqual(teacher["seed"], 2026080206)
            self.assertEqual(teacher["size_m"], source["size_m"])
            self.assertEqual(teacher["offset_m"], source["offset_m"])
            self.assertEqual(
                teacher["teacher_for_evaluation_case_id"], source["episode_id"]
            )
            self.assertEqual(teacher["system_control_class"], "deterministic_expert_teacher")
            self.assertTrue(teacher["expert_reference_used"])
            self.assertFalse(teacher["pure_vla_eligible"])
            self.assertEqual(teacher["pure_vla_action_runs"], 0)
            self.assertFalse(teacher["dataset_admission_allowed"])

    def _passing_summary(self) -> tuple[dict, dict, str]:
        generated = MODULE.build_teacher_collection_config(self.prereg, self.source)
        results = []
        for episode in generated["episodes"]:
            results.append(
                {
                    "episode_id": episode["episode_id"],
                    "parameters": episode,
                    "return_code": 0,
                    "success": True,
                    "failure_stage": None,
                    "lift_success": True,
                    "transport_success": True,
                    "placed_before_release": True,
                    "released": True,
                    "place_force_safety_abort": False,
                    "release_force_safety_abort": False,
                    "safety_violation": False,
                    "frames": 120,
                    "dataset_saved": True,
                    "dataset_storage_format": "video",
                    "dataset_bytes": 1_000_000,
                    "recovery_label": {"verified_success": True},
                    "summary": f"/{episode['episode_id']}/summary.json",
                    "log": f"/{episode['episode_id']}/collector.log",
                    "media": {
                        "video_requested": True,
                        "video_saved": True,
                        "video_path": f"/{episode['episode_id']}.mp4",
                        "snapshot_requested": True,
                        "snapshot_saved": True,
                        "snapshot_path": f"/{episode['episode_id']}.png",
                    },
                }
            )
        config_sha = "a" * 64
        collector_sha = "b" * 64
        summary = {
            "collection_id": generated["collection_id"],
            "runtime_contract": {
                "config_sha256": config_sha,
                "collector_sha256": collector_sha,
                "policy_mode": "shadow",
            },
            "requested_episodes": 3,
            "completed_episodes": 3,
            "unattempted_episodes": 0,
            "successful_episodes": 3,
            "failed_episodes": 0,
            "status": "passed",
            "checkpoint_selection": None,
            "persistent_policy_service": False,
            "goal_verdict_required": False,
            "grasp_mode_verdict_required": False,
            "policy_visual_modality": "rgbd",
            "merged_dataset_root": "/dataset",
            "media_episode_ids": [item["episode_id"] for item in generated["episodes"]],
            "successful_episode_order": [
                item["episode_id"] for item in generated["episodes"]
            ],
            "merge_error": None,
            "results": results,
        }
        dataset_audit = {
            "status": "passed",
            "errors": [],
            "dataset_root": "/dataset",
            "episodes": 3,
            "fps": 30,
            "policy_modality": "rgbd",
            "privileged_state_in_policy": False,
            "storage_format": "video",
        }
        return summary, dataset_audit, config_sha

    def test_three_verified_expert_episodes_are_admitted_with_zero_vla_credit(self) -> None:
        generated = MODULE.build_teacher_collection_config(self.prereg, self.source)
        summary, dataset_audit, config_sha = self._passing_summary()
        result = MODULE.audit_collection(
            generated,
            summary,
            dataset_audit,
            collector_config_sha256=config_sha,
            collector_script_sha256="b" * 64,
        )
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["training_admission_allowed"])
        self.assertEqual(result["expert_reference_count"], 3)
        self.assertEqual(result["pure_vla_action_runs"], 0)
        self.assertEqual(result["pure_vla_success_credit"], 0)

    def test_partial_success_rejects_every_teacher_episode(self) -> None:
        generated = MODULE.build_teacher_collection_config(self.prereg, self.source)
        summary, dataset_audit, config_sha = self._passing_summary()
        summary["results"][1]["success"] = False
        summary["successful_episodes"] = 2
        summary["failed_episodes"] = 1
        result = MODULE.audit_collection(
            generated,
            summary,
            dataset_audit,
            collector_config_sha256=config_sha,
            collector_script_sha256="b" * 64,
        )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["training_admission_allowed"])
        self.assertEqual(result["accepted_episode_ids"], [])

    def _passing_viable_summary(self) -> tuple[dict, dict, str]:
        summary, dataset_audit, config_sha = self._passing_summary()
        failed = summary["results"][0]
        failed.update(
            {
                "return_code": 2,
                "success": False,
                "failure_stage": "scene_stability_failure",
                "lift_success": False,
                "transport_success": False,
                "placed_before_release": False,
                "released": False,
                "frames": 0,
                "dataset_saved": False,
                "dataset_bytes": 0,
                "recovery_label": {"verified_success": False},
            }
        )
        required = self.viable_prereg["viable_subset_admission"][
            "required_success_episode_ids"
        ]
        summary["successful_episodes"] = 2
        summary["failed_episodes"] = 1
        summary["successful_episode_order"] = required
        dataset_audit["episodes"] = 2
        return summary, dataset_audit, config_sha

    def test_viable_subset_admits_only_two_successes_with_zero_vla_credit(self) -> None:
        preflight = MODULE.audit_preregistration(
            self.viable_prereg,
            self.source,
            self.deployment,
            source_smoke_sha256=MODULE._sha256(self.source_path),
            deployment_preregistration_sha256=MODULE._sha256(self.deployment_path),
        )
        self.assertEqual(preflight["status"], "passed")
        generated = MODULE.build_teacher_collection_config(
            self.viable_prereg, self.source
        )
        summary, dataset_audit, config_sha = self._passing_viable_summary()
        result = MODULE.audit_collection(
            generated,
            summary,
            dataset_audit,
            collector_config_sha256=config_sha,
            collector_script_sha256="b" * 64,
            viable_subset_admission=self.viable_prereg["viable_subset_admission"],
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["accepted_episode_ids"], summary["successful_episode_order"])
        self.assertEqual(
            result["failure_telemetry_episode_ids"],
            [summary["results"][0]["episode_id"]],
        )
        self.assertEqual(result["expert_reference_count"], 2)
        self.assertEqual(result["pure_vla_action_runs"], 0)
        self.assertEqual(result["pure_vla_success_credit"], 0)

    def test_uniform_six_preregistration_preserves_frozen_contract(self) -> None:
        result = MODULE.audit_preregistration(
            self.uniform_six_prereg,
            self.source,
            self.deployment,
            source_smoke_sha256=MODULE._sha256(self.source_path),
            deployment_preregistration_sha256=MODULE._sha256(self.deployment_path),
        )
        self.assertEqual(result["status"], "passed")
        training = self.uniform_six_prereg["training_contract"]
        self.assertEqual(training["seed"], 11)
        self.assertEqual(training["samples_per_cell"], 6)
        self.assertEqual(
            training["sampling_policy"],
            "uniform_mode_stage_progress_without_replacement",
        )

    def test_mode_only_preregistration_freezes_action_progress_heads(self) -> None:
        result = MODULE.audit_preregistration(
            self.mode_only_prereg,
            self.source,
            self.deployment,
            source_smoke_sha256=MODULE._sha256(self.source_path),
            deployment_preregistration_sha256=MODULE._sha256(self.deployment_path),
        )
        self.assertEqual(result["status"], "passed")
        training = self.mode_only_prereg["training_contract"]
        self.assertEqual(training["calibration_scope"], "mode_only")
        self.assertEqual(
            training["trainable_components"],
            ["mode_head", "mode_head_state_residual"],
        )
        self.assertEqual(
            training["frozen_learned_components"],
            ["direct_action_head", "direct_action_state_residual"],
        )

    def test_viable_failure_telemetry_cannot_supply_bc_frames(self) -> None:
        generated = MODULE.build_teacher_collection_config(
            self.viable_prereg, self.source
        )
        summary, dataset_audit, config_sha = self._passing_viable_summary()
        summary["results"][0]["dataset_saved"] = True
        summary["results"][0]["frames"] = 1
        result = MODULE.audit_collection(
            generated,
            summary,
            dataset_audit,
            collector_config_sha256=config_sha,
            collector_script_sha256="b" * 64,
            viable_subset_admission=self.viable_prereg["viable_subset_admission"],
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            f"allowed_failure_no_dataset_mismatch:{summary['results'][0]['episode_id']}",
            result["errors"],
        )

    def test_any_vla_checkpoint_or_policy_mode_fails_attribution(self) -> None:
        generated = MODULE.build_teacher_collection_config(self.prereg, self.source)
        summary, dataset_audit, config_sha = self._passing_summary()
        summary["checkpoint_selection"] = {"checkpoint": "/vla"}
        summary["runtime_contract"]["policy_mode"] = "pi05_incremental"
        result = MODULE.audit_collection(
            generated,
            summary,
            dataset_audit,
            collector_config_sha256=config_sha,
            collector_script_sha256="b" * 64,
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("vla_checkpoint_was_supplied", result["errors"])
        self.assertIn("collector_not_in_expert_shadow_mode", result["errors"])


if __name__ == "__main__":
    unittest.main()
