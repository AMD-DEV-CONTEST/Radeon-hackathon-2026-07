from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v1.json"
V2_PATH = ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v2.json"
V3_PATH = ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v3.json"
SCRIPT_PATH = (
    ROOT
    / ".ops/wip/act-rocm-accuracy-parity-20260729"
    / "run_horizon_safe12_act_cuda_training_20260729_v3.sh"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HorizonSafe12TrainingV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v3 = json.loads(V3_PATH.read_text(encoding="utf-8"))
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_v3_derivation_is_exact(self) -> None:
        self.assertEqual(
            self.v3["derives_from"]["sha256"],
            sha256(V2_PATH),
        )
        self.assertEqual(
            self.v3["base_training_contract"]["sha256"],
            sha256(BASE_PATH),
        )

    def test_v2_failed_before_training(self) -> None:
        predecessor = self.v3["predecessor_terminal_evidence"]
        self.assertEqual(
            predecessor["status"],
            "FAILED_PREFLIGHT_NO_TRAINING",
        )
        self.assertFalse(predecessor["training_process_started"])
        self.assertFalse(predecessor["output_root_created"])

    def test_only_unsupported_uuid_introspection_is_removed(self) -> None:
        correction = self.v3["single_correction"]
        self.assertEqual(
            correction["name"],
            "remove_unsupported_torch_device_uuid_introspection",
        )
        for key in (
            "training_behavior_changed",
            "dataset_changed",
            "hyperparameters_changed",
            "runtime_changed",
            "gpu_changed",
        ):
            self.assertFalse(correction[key], key)
        self.assertNotIn(
            "torch.cuda.get_device_properties(0).uuid",
            self.script,
        )
        self.assertIn(
            'printf \'%s\\n\' "${selected_gpu_uuid}"',
            self.script,
        )
        self.assertIn(
            'grep -Fq "${selected_gpu_uuid}"',
            self.script,
        )

    def test_v3_keeps_frozen_training_and_fresh_paths(self) -> None:
        identity = self.v3["inherited_training_identity"]
        self.assertEqual(identity["dataset_episodes"], 12)
        self.assertEqual(identity["dataset_frames"], 14170)
        self.assertEqual(identity["physical_gpu_index"], 6)
        self.assertEqual(identity["steps"], 60000)
        self.assertEqual(identity["seed"], 20260723)
        for token in (
            "mantis_act_horizon_safe12_training_20260729_v3",
            "mantis_act_cuda_horizon_safe12_20260729_v3",
            "mantis-act-cuda-horizon-safe12-training-evidence-20260729-v3",
            '"--steps=60000"',
            '"--batch_size=8"',
            '"--policy.push_to_hub=false"',
        ):
            self.assertIn(token, self.script)


if __name__ == "__main__":
    unittest.main()
