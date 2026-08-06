from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v1.json"
CORRECTION_PATH = (
    ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v2.json"
)
SCRIPT_PATH = (
    ROOT
    / ".ops/wip/act-rocm-accuracy-parity-20260729"
    / "run_horizon_safe12_act_cuda_training_20260729_v2.sh"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HorizonSafe12TrainingV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(BASE_PATH.read_text(encoding="utf-8"))
        cls.correction = json.loads(
            CORRECTION_PATH.read_text(encoding="utf-8")
        )
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_v2_derives_from_exact_v1(self) -> None:
        self.assertEqual(
            self.correction["derives_from"]["sha256"],
            sha256(BASE_PATH),
        )
        predecessor = self.correction["predecessor_terminal_evidence"]
        self.assertEqual(
            predecessor["status"],
            "FAILED_PREFLIGHT_NO_TRAINING",
        )
        self.assertFalse(predecessor["training_process_started"])
        self.assertFalse(predecessor["output_root_created"])

    def test_only_declared_correction_is_package_manifest_cwd(self) -> None:
        correction = self.correction["single_correction"]
        self.assertEqual(
            correction["name"],
            "package_manifest_working_directory",
        )
        for key in (
            "training_behavior_changed",
            "dataset_changed",
            "hyperparameters_changed",
            "runtime_changed",
            "gpu_changed",
        ):
            self.assertFalse(correction[key], key)
        self.assertIn('cd "${INPUT_ROOT}"', self.script)
        self.assertIn(
            "sha256sum -c package.SHA256SUMS",
            self.script,
        )

    def test_fresh_v2_paths_and_frozen_training_identity(self) -> None:
        self.assertIn("20260729_v2", self.correction["input_root"])
        self.assertIn(
            "20260729_v2",
            self.correction["output"]["root"],
        )
        self.assertIn(
            "20260729-v2",
            self.correction["output"]["evidence_root"],
        )
        identity = self.correction["inherited_training_identity"]
        self.assertEqual(identity["dataset_episodes"], 12)
        self.assertEqual(identity["dataset_frames"], 14170)
        self.assertEqual(identity["physical_gpu_index"], 6)
        self.assertEqual(identity["steps"], 60000)
        self.assertEqual(identity["seed"], 20260723)
        self.assertEqual(identity["chunk_size"], 30)

    def test_script_uses_v2_paths_and_keeps_gpu_gate(self) -> None:
        for token in (
            "mantis_act_horizon_safe12_training_20260729_v2",
            "mantis_act_cuda_horizon_safe12_20260729_v2",
            "mantis-act-cuda-horizon-safe12-training-evidence-20260729-v2",
            "PHYSICAL_GPU=6",
            "exit 93",
            '"--steps=60000"',
            '"--batch_size=8"',
            '"--policy.push_to_hub=false"',
        ):
            self.assertIn(token, self.script)


if __name__ == "__main__":
    unittest.main()
