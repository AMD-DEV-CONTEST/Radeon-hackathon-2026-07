from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from mantis_rocm_bridge.act_closedloop_g3 import validate_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/act-horizon-safe12-representative-g3-v1.json"
SCRIPT_PATH = (
    ROOT
    / ".ops/wip/act-rocm-accuracy-parity-20260729"
    / "run_g3_horizon_safe12_representative_20260730_v1.sh"
)
CHECKPOINT_MANIFEST_PATH = (
    ROOT
    / ".ops/wip/act-rocm-accuracy-parity-20260729"
    / "checkpoint_060000_horizon_safe12_v4.SHA256SUMS"
)
TRAINING_MANIFEST_PATH = (
    ROOT
    / ".ops/wip/act-rocm-accuracy-parity-20260729"
    / "training_final_evidence_horizon_safe12_v4.SHA256SUMS"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HorizonSafe12RepresentativeG3V1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_frozen_g3_contract_validates(self) -> None:
        validate_config(self.config)
        self.assertEqual(
            self.config["work_package_id"],
            "WP-ACT-ROCM-ACCURACY-PARITY-006-R3",
        )
        self.assertEqual(
            self.config["training_contract"],
            "configs/act-rocm-baseline-v2.json",
        )
        self.assertEqual(
            self.config["candidate_training_contract"],
            "configs/act-mantis-recovery-horizon-safe12-training-v4.json",
        )

    def test_exact_candidate_and_checkpoint_identity(self) -> None:
        profile = self.config["development_representative_profile"]
        self.assertEqual(profile["ordered_seeds"], [101, 107, 108])
        self.assertEqual(profile["physical_gpu_index"], 6)
        self.assertEqual(
            profile["checkpoint_manifest_sha256"],
            sha256(CHECKPOINT_MANIFEST_PATH),
        )
        self.assertEqual(
            self.config["training_evidence_manifest_sha256"],
            sha256(TRAINING_MANIFEST_PATH),
        )
        self.assertEqual(
            self.config["training_id"],
            "mantis_stack_bowls_act_cuda_horizon_safe12_20260729_v4",
        )

    def test_checkpoint_manifest_is_complete(self) -> None:
        rows = [
            line
            for line in CHECKPOINT_MANIFEST_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]
        self.assertEqual(len(rows), 11)
        self.assertTrue(
            any("./pretrained_model/model.safetensors" in row for row in rows)
        )
        self.assertTrue(
            any(
                "./training_state/optimizer_state.safetensors" in row
                for row in rows
            )
        )
        self.assertTrue(
            any("./training_state/training_step.json" in row for row in rows)
        )

    def test_exact_script_preflight_stops_before_batch(self) -> None:
        self.assertIn("mode=${1:-run}", self.script)
        self.assertIn(
            "PREFLIGHT_COMPLETE_NO_EVALUATION",
            self.script,
        )
        self.assertLess(
            self.script.index("PREFLIGHT_COMPLETE_NO_EVALUATION"),
            self.script.index('mkdir -p "$batch"'),
        )
        self.assertIn(
            "mantis-g3-horizon-safe12-representative-preflight-20260730-v1",
            self.script,
        )

    def test_script_pins_gpu_checkpoint_training_and_sources(self) -> None:
        for token in (
            "physical_gpu=6",
            'CUDA_VISIBLE_DEVICES="$physical_gpu"',
            "b0fa632813739494323146ee0d51c9e23ed23f2c17226f8319a571e706f468d6",
            "5fd0dd3f626078df5bbe675b300bdbb862da1fb0e0a465c5052d410c43da2928",
            "fe9ffa1a22ce41408968a3cc13cabdd2185c6e29e29e184ec759b05c2ce8f76e",
            "aa351ddc6b4e698554fd4569a0e65fa4b87e048ee22e79a188a5a0eb7a31513f",
            "seeds=(101 107 108)",
            "-p no:quadrants",
        ):
            self.assertIn(token, self.script)

    def test_no_assistance_or_external_publish_added(self) -> None:
        self.assertNotIn("scripted_planner", self.script)
        self.assertNotIn("trajectory_replay", self.script)
        self.assertNotIn("git push", self.script)
        self.assertNotIn("huggingface-cli", self.script)


if __name__ == "__main__":
    unittest.main()
