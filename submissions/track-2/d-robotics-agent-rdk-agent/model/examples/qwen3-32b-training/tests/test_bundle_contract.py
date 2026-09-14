from __future__ import annotations

import sys
import unittest
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent.parent
DATA = BUNDLE.parent / "data-gen/data/releases/rdk-sft-v1-20260803/agentic"
sys.path.insert(0, str(BUNDLE / "scripts"))

import verify_bundle  # noqa: E402


class BundleContractTest(unittest.TestCase):
    def test_remote_snapshot_is_byte_identical(self) -> None:
        report = verify_bundle.verify_remote_snapshot(BUNDLE)
        self.assertEqual(report["files"], 41)

    def test_model_weights_are_intentionally_absent(self) -> None:
        metadata = verify_bundle.verify_model_metadata(BUNDLE)
        payload = verify_bundle.verify_no_payload(BUNDLE)
        self.assertEqual(metadata["weight_shards"], "OMITTED_EXPECTED")
        self.assertEqual(payload["model_payload"], "OMITTED_EXPECTED")

    def test_formal_data_matches_frozen_hashes(self) -> None:
        report = verify_bundle.verify_data(DATA)
        self.assertEqual(report["unique_tasks"], 1175)

    def test_plan_contract(self) -> None:
        report = verify_bundle.verify_plan_contract(BUNDLE)
        self.assertEqual(report["optimizer_steps"], 119)
        self.assertEqual(report["train_micro_windows"], 948)

    def test_phase2_completed(self) -> None:
        gate_report = verify_bundle.verify_preflight_gate_evidence(BUNDLE)
        report = verify_bundle.verify_execution_evidence(BUNDLE)
        self.assertEqual(gate_report["status"], "PASS")
        self.assertEqual(report["formal_training_execution"], "PASS")
        self.assertEqual(report["completed_optimizer_step"], 119)

    def test_trainer_does_not_reference_test_split(self) -> None:
        source = (
            BUNDLE / "configs/qwen3_32b_agentic_formal_trainer_v2_cachebounded.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("test.jsonl", source)
        self.assertNotIn('"test"', source)


if __name__ == "__main__":
    unittest.main()
