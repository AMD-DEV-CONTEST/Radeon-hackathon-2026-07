from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1_PATH = ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v1.json"
V3_PATH = ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v3.json"
V4_PATH = ROOT / "configs/act-mantis-recovery-horizon-safe12-training-v4.json"
SCRIPT_PATH = (
    ROOT
    / ".ops/wip/act-rocm-accuracy-parity-20260729"
    / "run_horizon_safe12_act_cuda_training_20260729_v4.sh"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HorizonSafe12TrainingV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v4 = json.loads(V4_PATH.read_text(encoding="utf-8"))
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_v4_derivation_is_exact(self) -> None:
        self.assertEqual(
            self.v4["derives_from"]["sha256"],
            sha256(V3_PATH),
        )
        self.assertEqual(
            self.v4["base_training_contract"]["sha256"],
            sha256(V1_PATH),
        )

    def test_v3_failed_before_training(self) -> None:
        predecessor = self.v4["predecessor_terminal_evidence"]
        self.assertEqual(
            predecessor["status"],
            "FAILED_PREFLIGHT_NO_TRAINING",
        )
        self.assertFalse(predecessor["training_process_started"])
        self.assertFalse(predecessor["output_root_created"])

    def test_awk_selector_avoids_reserved_name(self) -> None:
        self.assertIn(
            '-v target_gpu="${PHYSICAL_GPU}"',
            self.script,
        )
        self.assertNotIn('-v index="${PHYSICAL_GPU}"', self.script)
        self.assertIn(
            "$1 == target_gpu {print $2}",
            self.script,
        )

    def test_exact_script_verify_only_stops_before_train(self) -> None:
        self.assertIn('MODE=${1:-run}', self.script)
        self.assertIn(
            'if [[ "${MODE}" == "verify-only" ]]',
            self.script,
        )
        marker = "PREFLIGHT_COMPLETE_NO_TRAINING"
        self.assertIn(marker, self.script)
        self.assertLess(
            self.script.index(marker),
            self.script.index("command=("),
        )
        self.assertIn(
            "mantis-act-cuda-horizon-safe12-training-preflight-20260729-v4",
            self.script,
        )

    def test_v4_keeps_frozen_training_and_fresh_paths(self) -> None:
        identity = self.v4["inherited_training_identity"]
        self.assertEqual(identity["dataset_episodes"], 12)
        self.assertEqual(identity["dataset_frames"], 14170)
        self.assertEqual(identity["physical_gpu_index"], 6)
        self.assertEqual(identity["steps"], 60000)
        self.assertEqual(identity["seed"], 20260723)
        for token in (
            "mantis_act_horizon_safe12_training_20260729_v4",
            "mantis_act_cuda_horizon_safe12_20260729_v4",
            "mantis-act-cuda-horizon-safe12-training-evidence-20260729-v4",
            '"--steps=60000"',
            '"--batch_size=8"',
            '"--policy.push_to_hub=false"',
        ):
            self.assertIn(token, self.script)


if __name__ == "__main__":
    unittest.main()
