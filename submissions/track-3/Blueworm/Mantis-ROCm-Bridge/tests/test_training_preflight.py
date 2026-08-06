from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.lerobot_dataset_gate import audit_mantis_dataset_metadata
from mantis_rocm_bridge.training_preflight import (
    _check_training_contract,
    _scripted_g1_checks,
    build_act_rocm_preflight,
)


def canonical_scripted_g1_receipt(**overrides: object) -> dict[str, object]:
    """Build the canonical online G1 receipt emitted by the generator."""

    rows = [
        {
            "frame": frame,
            "policy_step": frame * 10,
            "consecutive_success_frames": frame,
            "strict": {
                "protocol_version": "competition_strict_v1",
                "frame_success": True,
                "checks": {
                    "lower_middle_xy": True,
                    "middle_upper_xy": True,
                    "absolute_heights": True,
                    "motion_stable": True,
                    "grippers_open": True,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                },
            },
        }
        for frame in range(1, 13)
    ]
    receipt: dict[str, object] = {
        "schema_version": 1,
        "generation_mode": "online",
        "task_id": "stack_bowls_three",
        "protocol_version": "competition_strict_v1",
        "transport_protocol": "contact_triggered_suction_scripted_g1_v1",
        "seed": 1,
        "scripted_g1_pass": True,
        "g1_claim": True,
        "episode_success_claim": True,
        "safety_failures": [],
        "strict_stability_rows": rows,
    }
    receipt.update(overrides)
    return receipt


ROOT = Path(__file__).resolve().parents[1]
INTERFACE = ROOT / "configs/mantis-lerobot-interface-v1.json"
TASK = ROOT / "configs/task-pack-v1.json"
TRAINING = ROOT / "configs/act-rocm-baseline-v2.json"
TRAINING_V1_LEGACY = ROOT / "configs/act-rocm-baseline-v1.json"
TRAINING_PERSISTENCE_V2 = (
    ROOT / "configs/act-rocm-corrective-multiseed6-v2.json"
)


class ActRocmPreflightTests(unittest.TestCase):
    def make_dataset(self, root: Path) -> dict[str, object]:
        contract = json.loads(INTERFACE.read_text(encoding="utf-8"))
        features = {
            "observation.state": {"names": contract["state_names"], "shape": [16]},
            "action": {"names": contract["action_names"], "shape": [16]},
        }
        features.update(
            {key: {"shape": shape} for key, shape in contract["camera_features"].items()}
        )
        info = {
            "robot_type": "mantis",
            "fps": 30,
            "total_episodes": 12,
            "total_frames": 1200,
            "features": features,
        }
        stats = {
            feature: {
                "mean": [0.0] * 16,
                "std": [0.2] * 16,
                "q01": [-1.0] * 16,
                "q99": [1.0] * 16,
            }
            for feature in ("observation.state", "action")
        }
        (root / "meta").mkdir(parents=True)
        (root / "meta/info.json").write_text(json.dumps(info), encoding="utf-8")
        (root / "meta/stats.json").write_text(json.dumps(stats), encoding="utf-8")
        return audit_mantis_dataset_metadata(root, INTERFACE)

    def rocm_receipt(self) -> dict[str, object]:
        return {
            "strict_rocm_pass": True,
            "torch": {
                "hip_version": "6.4",
                "cuda_api_available": True,
                "device_count": 1,
            },
        }

    def test_all_required_receipts_authorize_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            dataset = self.make_dataset(root)
            dense = {
                "dense_demonstration_gate_pass": True,
                "task_id": "stack_bowls_three",
                "protocol": "competition_strict_v1",
                "info_sha256": dataset["info_sha256"],
                "stats_sha256": dataset["stats_sha256"],
            }
            scripted = {
                "task_id": "stack_bowls_three",
                "protocol": "competition_strict_v1",
                "success": True,
                "g1_claim": True,
                "safety_failures": 0,
                "physics_divergence": False,
            }
            receipt = build_act_rocm_preflight(
                dataset_root=root,
                dataset_repo_id="local/mantis_stack_bowls",
                output_dir=Path(directory) / "act-output",
                training_contract_path=TRAINING,
                interface_contract_path=INTERFACE,
                task_contract_path=TASK,
                dataset_receipt=dataset,
                rocm_receipt=self.rocm_receipt(),
                dense_receipt=dense,
                scripted_g1_receipt=scripted,
            )
            self.assertTrue(receipt["command_contract_ready"])
            self.assertTrue(receipt["training_authorized"])
            self.assertIn("--policy.device=cuda", receipt["argv"])
            self.assertIn("--policy.chunk_size=30", receipt["argv"])
            self.assertEqual(receipt["argv"].count("--policy.push_to_hub=false"), 1)

    def test_canonical_generator_receipt_authorizes_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            dataset = self.make_dataset(root)
            dense = {
                "dense_demonstration_gate_pass": True,
                "task_id": "stack_bowls_three",
                "protocol": "competition_strict_v1",
                "info_sha256": dataset["info_sha256"],
                "stats_sha256": dataset["stats_sha256"],
            }
            receipt = build_act_rocm_preflight(
                dataset_root=root,
                dataset_repo_id="local/mantis_stack_bowls",
                output_dir=Path(directory) / "act-output",
                training_contract_path=TRAINING,
                interface_contract_path=INTERFACE,
                task_contract_path=TASK,
                dataset_receipt=dataset,
                rocm_receipt=self.rocm_receipt(),
                dense_receipt=dense,
                scripted_g1_receipt=canonical_scripted_g1_receipt(),
            )
            self.assertTrue(receipt["command_contract_ready"])
            self.assertTrue(receipt["training_authorized"])
            checks = receipt["checks"]
            self.assertTrue(checks["scripted_g1_success"])
            self.assertTrue(checks["scripted_g1_contract_match"])
            self.assertTrue(checks["scripted_g1_safety_pass"])

    def test_missing_dense_and_g1_receipts_prevent_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            dataset = self.make_dataset(root)
            receipt = build_act_rocm_preflight(
                dataset_root=root,
                dataset_repo_id="local/mantis_stack_bowls",
                output_dir=Path(directory) / "act-output",
                training_contract_path=TRAINING,
                interface_contract_path=INTERFACE,
                task_contract_path=TASK,
                dataset_receipt=dataset,
                rocm_receipt=self.rocm_receipt(),
            )
            self.assertTrue(receipt["command_contract_ready"])
            self.assertFalse(receipt["training_authorized"])
            self.assertFalse(receipt["checks"]["dense_demonstration_gate_pass"])
            self.assertFalse(receipt["checks"]["scripted_g1_success"])

    def test_persistence_contract_blocks_old_paths_and_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            dataset = self.make_dataset(root)
            dense = {
                "dense_demonstration_gate_pass": True,
                "task_id": "stack_bowls_three",
                "protocol": "competition_strict_v1",
                "info_sha256": dataset["info_sha256"],
                "stats_sha256": dataset["stats_sha256"],
            }
            receipt = build_act_rocm_preflight(
                dataset_root=root,
                dataset_repo_id=(
                    "local/mantis_stack_bowls_multiseed6_gripper_v2_20260727_v1"
                ),
                output_dir=Path(directory) / "act-output",
                training_contract_path=TRAINING_PERSISTENCE_V2,
                interface_contract_path=INTERFACE,
                task_contract_path=TASK,
                dataset_receipt=dataset,
                rocm_receipt=self.rocm_receipt(),
                dense_receipt=dense,
                scripted_g1_receipt=canonical_scripted_g1_receipt(),
            )
            self.assertFalse(receipt["training_authorized"])
            self.assertFalse(receipt["checks"]["dataset_under_persistence_root"])
            self.assertFalse(receipt["checks"]["output_under_persistence_root"])
            self.assertFalse(
                receipt["checks"]["training_contract_execution_authorized"]
            )


class PushToHubFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.interface = json.loads(INTERFACE.read_text(encoding="utf-8"))
        self.task = json.loads(TASK.read_text(encoding="utf-8"))
        self.training = json.loads(TRAINING.read_text(encoding="utf-8"))

    def check(self, training: dict[str, object]) -> None:
        _check_training_contract(training, self.interface, self.task)

    def test_v2_contract_with_push_to_hub_false_is_accepted(self) -> None:
        self.assertIs(self.training["policy"]["push_to_hub"], False)
        self.check(self.training)

    def test_legacy_v1_contract_omitting_push_to_hub_is_rejected(self) -> None:
        legacy = json.loads(TRAINING_V1_LEGACY.read_text(encoding="utf-8"))
        self.assertNotIn("push_to_hub", legacy["policy"])
        with self.assertRaises(ContractError):
            self.check(legacy)

    def test_missing_push_to_hub_is_rejected(self) -> None:
        training = json.loads(json.dumps(self.training))
        del training["policy"]["push_to_hub"]
        with self.assertRaises(ContractError):
            self.check(training)

    def test_non_false_push_to_hub_is_rejected(self) -> None:
        for bad in (True, 1, "false"):
            training = json.loads(json.dumps(self.training))
            training["policy"]["push_to_hub"] = bad
            with self.assertRaises(ContractError, msg=f"push_to_hub={bad!r}"):
                self.check(training)


class ScriptedG1CanonicalSchemaTests(unittest.TestCase):
    """Focused dual-schema checks for ``_scripted_g1_checks``."""

    def setUp(self) -> None:
        self.task = json.loads(TASK.read_text(encoding="utf-8"))

    def checks(self, receipt: dict[str, object] | None) -> dict[str, bool]:
        return _scripted_g1_checks(receipt, self.task)

    def test_canonical_online_receipt_passes_all_three(self) -> None:
        checks = self.checks(canonical_scripted_g1_receipt())
        self.assertTrue(checks["scripted_g1_success"])
        self.assertTrue(checks["scripted_g1_contract_match"])
        self.assertTrue(checks["scripted_g1_safety_pass"])

    def test_legacy_normalized_receipt_still_passes(self) -> None:
        checks = self.checks(
            {
                "task_id": "stack_bowls_three",
                "protocol": "competition_strict_v1",
                "success": True,
                "g1_claim": True,
                "safety_failures": 0,
                "physics_divergence": False,
            }
        )
        self.assertTrue(checks["scripted_g1_success"])
        self.assertTrue(checks["scripted_g1_contract_match"])
        self.assertTrue(checks["scripted_g1_safety_pass"])

    def test_replay_mode_is_rejected(self) -> None:
        receipt = canonical_scripted_g1_receipt(
            generation_mode="replay",
            scripted_g1_pass=False,
            g1_claim=False,
            episode_success_claim=False,
        )
        checks = self.checks(receipt)
        self.assertFalse(checks["scripted_g1_success"])
        self.assertTrue(checks["scripted_g1_contract_match"])
        self.assertTrue(checks["scripted_g1_safety_pass"])

    def test_missing_episode_success_claim_is_rejected(self) -> None:
        checks = self.checks(
            canonical_scripted_g1_receipt(episode_success_claim=False)
        )
        self.assertFalse(checks["scripted_g1_success"])

    def test_short_stability_evidence_is_rejected(self) -> None:
        receipt = canonical_scripted_g1_receipt()
        receipt["strict_stability_rows"] = receipt["strict_stability_rows"][:11]
        self.assertFalse(self.checks(receipt)["scripted_g1_success"])

    def test_false_physics_check_is_rejected(self) -> None:
        receipt = canonical_scripted_g1_receipt()
        receipt["strict_stability_rows"][-1]["strict"]["checks"][
            "no_physics_divergence"
        ] = False
        self.assertFalse(self.checks(receipt)["scripted_g1_success"])

    def test_false_safety_check_is_rejected(self) -> None:
        receipt = canonical_scripted_g1_receipt()
        receipt["strict_stability_rows"][-1]["strict"]["checks"][
            "no_safety_failure"
        ] = False
        self.assertFalse(self.checks(receipt)["scripted_g1_success"])

    def test_short_final_consecutive_count_is_rejected(self) -> None:
        receipt = canonical_scripted_g1_receipt()
        receipt["strict_stability_rows"][-1]["consecutive_success_frames"] = 11
        self.assertFalse(self.checks(receipt)["scripted_g1_success"])

    def test_nonempty_safety_list_is_rejected(self) -> None:
        receipt = canonical_scripted_g1_receipt(
            safety_failures=[{"kind": "robot_table_contact"}]
        )
        checks = self.checks(receipt)
        self.assertFalse(checks["scripted_g1_safety_pass"])
        self.assertTrue(checks["scripted_g1_success"])

    def test_legacy_zero_does_not_satisfy_canonical_safety(self) -> None:
        checks = self.checks(canonical_scripted_g1_receipt(safety_failures=0))
        self.assertFalse(checks["scripted_g1_safety_pass"])

    def test_wrong_protocol_is_rejected(self) -> None:
        receipt = canonical_scripted_g1_receipt(
            protocol_version="legacy_source_v1"
        )
        checks = self.checks(receipt)
        self.assertFalse(checks["scripted_g1_contract_match"])
        self.assertTrue(checks["scripted_g1_success"])

    def test_canonical_protocol_key_is_also_accepted(self) -> None:
        receipt = canonical_scripted_g1_receipt()
        del receipt["protocol_version"]
        receipt["protocol"] = "competition_strict_v1"
        self.assertTrue(self.checks(receipt)["scripted_g1_contract_match"])


if __name__ == "__main__":
    unittest.main()
