from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.lerobot_dataset_gate import audit_mantis_dataset_metadata
from mantis_rocm_bridge.training_preflight import (
    _check_training_contract,
    build_act_rocm_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "configs/act-rocm-baseline-v2.json"
CORRECTIVE = ROOT / "configs/act-rocm-corrective-multiseed6-v1.json"
CORRECTION = ROOT / "configs/act-trajectory-distribution-correction-v1.json"
INTERFACE = ROOT / "configs/mantis-lerobot-interface-v1.json"
TASK = ROOT / "configs/task-pack-v1.json"


class ActRocmCorrectiveContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.corrective = json.loads(CORRECTIVE.read_text(encoding="utf-8"))
        self.correction = json.loads(CORRECTION.read_text(encoding="utf-8"))
        self.interface = json.loads(INTERFACE.read_text(encoding="utf-8"))
        self.task = json.loads(TASK.read_text(encoding="utf-8"))

    def test_corrective_contract_is_accepted_by_training_preflight(self) -> None:
        _check_training_contract(self.corrective, self.interface, self.task)

    def test_optimizer_and_policy_invariants_match_baseline(self) -> None:
        scalar_fields = (
            "framework",
            "policy_type",
            "task_id",
            "robot_type",
            "upstream_revision",
            "policy_device_api",
            "seed",
            "steps",
            "batch_size",
            "num_workers",
            "save_freq",
            "eval_freq",
            "log_freq",
            "save_checkpoint",
            "wandb_enabled",
        )
        for field in scalar_fields:
            self.assertEqual(
                self.corrective[field],
                self.baseline[field],
                msg=f"frozen training field changed: {field}",
            )
        self.assertEqual(self.corrective["policy"], self.baseline["policy"])

    def test_dataset_identity_matches_single_correction(self) -> None:
        intervention = self.correction["single_intervention"]
        dataset = self.corrective["dataset"]
        self.assertEqual(dataset["episode_seeds"], intervention["corrected_episode_seeds"])
        self.assertEqual(dataset["episode_count"], intervention["corrected_episode_count"])
        self.assertEqual(dataset["frame_count"], intervention["corrected_frame_count"])
        self.assertEqual(dataset["episode_count"], 6)
        self.assertEqual(dataset["frame_count"], 7085)

    def test_cuda_representative_promotion_is_fail_closed(self) -> None:
        dependency = self.corrective["promotion_dependency"]
        self.assertEqual(
            dependency["gate"],
            "configs/act-corrective-representative-g3-v1.json",
        )
        self.assertEqual(
            dependency["required_terminal_status"],
            "COMPLETE_PROMOTABLE",
        )
        self.assertIn(
            "cuda_representative_complete_promotable",
            self.corrective["required_gates"],
        )

    def test_planned_execution_is_single_radeon_and_fresh(self) -> None:
        paths = self.corrective["planned_official_amd_paths"]
        self.assertTrue(paths["fresh_nonexistent_paths_required"])
        self.assertTrue(all(value.startswith("/workspace/") for key, value in paths.items() if key.endswith("_root")))
        self.assertEqual(self.corrective["official_cloud_lerobot_version"], "0.4.4")
        self.assertEqual(self.corrective["policy_device_api"], "cuda")
        self.assertIn("single-Radeon", self.corrective["claim_boundary"])

    def test_nonexecuting_preflight_builds_exact_corrective_argv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            dataset_root = base / "dataset"
            metadata_root = dataset_root / "meta"
            metadata_root.mkdir(parents=True)
            features = {
                "observation.state": {
                    "names": self.interface["state_names"],
                    "shape": [16],
                },
                "action": {
                    "names": self.interface["action_names"],
                    "shape": [16],
                },
            }
            features.update(
                {
                    key: {"shape": shape}
                    for key, shape in self.interface["camera_features"].items()
                }
            )
            (metadata_root / "info.json").write_text(
                json.dumps(
                    {
                        "robot_type": "mantis",
                        "fps": 30,
                        "total_episodes": 6,
                        "total_frames": 7085,
                        "features": features,
                    }
                ),
                encoding="utf-8",
            )
            (metadata_root / "stats.json").write_text(
                json.dumps(
                    {
                        feature: {
                            "mean": [0.0] * 16,
                            "std": [0.2] * 16,
                            "q01": [-1.0] * 16,
                            "q99": [1.0] * 16,
                        }
                        for feature in ("observation.state", "action")
                    }
                ),
                encoding="utf-8",
            )
            dataset_receipt = audit_mantis_dataset_metadata(
                dataset_root,
                INTERFACE,
            )
            dense_receipt = {
                "dense_demonstration_gate_pass": True,
                "task_id": "stack_bowls_three",
                "protocol": "competition_strict_v1",
                "info_sha256": dataset_receipt["info_sha256"],
                "stats_sha256": dataset_receipt["stats_sha256"],
            }
            scripted_g1_receipt = {
                "task_id": "stack_bowls_three",
                "protocol": "competition_strict_v1",
                "success": True,
                "g1_claim": True,
                "safety_failures": 0,
                "physics_divergence": False,
            }
            rocm_receipt = {
                "strict_rocm_pass": True,
                "torch": {
                    "hip_version": "7.2",
                    "cuda_api_available": True,
                    "device_count": 1,
                },
            }
            dataset_repo_id = self.corrective["dataset"]["repo_id"]
            receipt = build_act_rocm_preflight(
                dataset_root=dataset_root,
                dataset_repo_id=dataset_repo_id,
                output_dir=base / "fresh-output",
                training_contract_path=CORRECTIVE,
                interface_contract_path=INTERFACE,
                task_contract_path=TASK,
                dataset_receipt=dataset_receipt,
                dense_receipt=dense_receipt,
                scripted_g1_receipt=scripted_g1_receipt,
                rocm_receipt=rocm_receipt,
            )
            self.assertTrue(receipt["training_authorized"])
            self.assertEqual(
                receipt["training_id"],
                "mantis_stack_bowls_act_rocm_multiseed6_correction_v1",
            )
            self.assertIn(
                f"--dataset.repo_id={dataset_repo_id}",
                receipt["argv"],
            )
            self.assertIn(
                "--job_name=mantis_stack_bowls_act_rocm_multiseed6_correction_v1",
                receipt["argv"],
            )
            self.assertIn("--steps=60000", receipt["argv"])
            self.assertEqual(receipt["argv"].count("--policy.push_to_hub=false"), 1)


if __name__ == "__main__":
    unittest.main()
