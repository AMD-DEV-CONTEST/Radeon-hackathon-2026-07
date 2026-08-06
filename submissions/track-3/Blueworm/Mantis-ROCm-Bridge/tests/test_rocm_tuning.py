from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.rocm_tuning import (
    evaluate_benchmark_receipt,
    latency_summary,
    strict_rocm_device_receipt,
    validate_tuning_plan,
    write_json_exclusive,
)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools/benchmark_rocm_act_shapes.py"


def _plan() -> dict:
    return {
        "schema_version": 1,
        "kind": "rocm_act_shape_tuning_plan",
        "robot_id": "fixture",
        "task_id": "test",
        "workload": "ACT-shaped synthetic forward and backward compute",
        "morphology": {
            "arm_count": 1,
            "dof_per_arm": [6],
            "policy_state_dimension": 8,
            "policy_action_dimension": 6,
            "camera_count": 1,
            "act_chunk_size": 20,
        },
        "benchmark_model": {
            "family": "transformer_encoder_action_head",
            "d_model": 32,
            "nhead": 4,
            "encoder_layers": 1,
            "sequence_length": 8,
            "batch_size": 2,
        },
        "protocol": {
            "seed": 1,
            "warmup_iterations": 1,
            "measured_iterations": 2,
            "same_device_comparison_required": True,
            "raw_latency_samples_required": True,
        },
        "profiles": [
            {
                "profile_id": "fp32-baseline",
                "precision": "float32",
                "role": "baseline",
            },
            {
                "profile_id": "bf16-candidate",
                "precision": "bfloat16",
                "role": "candidate",
            },
            {
                "profile_id": "fp16-candidate",
                "precision": "float16",
                "role": "candidate",
            },
        ],
        "admission_thresholds": {
            "cosine_similarity_minimum": 0.999,
            "maximum_absolute_error": 0.05,
            "minimum_inference_or_training_speedup_fraction": 0.05,
            "finite_outputs_required": True,
        },
        "maximum_promotion_state": "ROCM_TUNING_MEASURED",
        "amd_deployable": False,
        "claim_boundary": "test",
    }


def _measurement(
    profile_id: str,
    inference: list[float],
    training: list[float],
    *,
    cosine: float = 1.0,
    error: float = 0.0,
    finite: bool = True,
) -> dict:
    return {
        "profile_id": profile_id,
        "precision": "float32" if "fp32" in profile_id else "bfloat16",
        "status": "measured",
        "output_finite": finite,
        "max_abs_error": error,
        "cosine_similarity": cosine,
        "inference": {
            "latency_ms_samples": inference,
            "peak_memory_bytes": 10,
        },
        "training": {
            "latency_ms_samples": training,
            "peak_memory_bytes": 20,
        },
    }


def _receipt(execution_mode: str = "rocm") -> dict:
    strict = execution_mode == "rocm"
    return {
        "schema_version": 1,
        "kind": "rocm_act_shape_benchmark_receipt",
        "execution_mode": execution_mode,
        "device": {
            "strict_rocm": strict,
            "torch_device": "cuda:0" if strict else "cpu",
            "torch_version": "2.test",
            "hip_version": "7.test" if strict else None,
            "device_count": 1 if strict else 0,
            "device_name": "AMD Radeon Graphics" if strict else "CPU",
        },
        "profiles": [
            _measurement("fp32-baseline", [10.0, 10.0], [20.0, 20.0]),
            _measurement(
                "bf16-candidate",
                [8.0, 8.0],
                [18.0, 18.0],
                cosine=0.9999,
                error=0.01,
            ),
            {
                "profile_id": "fp16-candidate",
                "precision": "float16",
                "status": "unsupported",
                "reason": "fixture unsupported",
            },
        ],
    }


class RocmTuningTests(unittest.TestCase):
    def test_latency_summary_uses_linear_interpolation(self) -> None:
        summary = latency_summary([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(summary["p50_ms"], 2.5)
        self.assertAlmostEqual(summary["p95_ms"], 3.85)
        self.assertAlmostEqual(summary["p99_ms"], 3.97)

    def test_latency_summary_rejects_nonpositive_and_nonfinite(self) -> None:
        for samples in ([], [0.0], [float("nan")]):
            with self.subTest(samples=samples):
                with self.assertRaises(ContractError):
                    latency_summary(samples)

    def test_plan_validation_is_fail_closed(self) -> None:
        plan = _plan()
        self.assertEqual(
            validate_tuning_plan(plan)["maximum_promotion_state"],
            "ROCM_TUNING_MEASURED",
        )
        broken = copy.deepcopy(plan)
        broken["amd_deployable"] = True
        with self.assertRaises(ContractError):
            validate_tuning_plan(broken)

    def test_strict_rocm_identity_requires_hip_and_amd_name(self) -> None:
        device = _receipt()["device"]
        self.assertTrue(strict_rocm_device_receipt(device))
        for key, value in (
            ("hip_version", None),
            ("device_count", 2),
            ("device_name", "NVIDIA GPU"),
        ):
            broken = dict(device)
            broken[key] = value
            self.assertFalse(strict_rocm_device_receipt(broken))

    def test_same_device_candidate_can_pass_microbenchmark_only(self) -> None:
        decision = evaluate_benchmark_receipt(_plan(), _receipt())
        self.assertEqual(decision["current_state"], "ROCM_TUNING_MEASURED")
        self.assertEqual(decision["promoted_candidate_id"], "bf16-candidate")
        self.assertTrue(decision["microbenchmark_promotable"])
        self.assertFalse(decision["act_quality_promoted"])
        self.assertFalse(decision["amd_deployable"])

    def test_candidate_fails_when_accuracy_threshold_is_missed(self) -> None:
        receipt = _receipt()
        receipt["profiles"][1]["cosine_similarity"] = 0.95
        decision = evaluate_benchmark_receipt(_plan(), receipt)
        self.assertIsNone(decision["promoted_candidate_id"])
        self.assertFalse(decision["candidate_decisions"][0]["cosine_pass"])

    def test_cpu_test_only_never_becomes_rocm_measured(self) -> None:
        decision = evaluate_benchmark_receipt(
            _plan(), _receipt(execution_mode="cpu_test_only")
        )
        self.assertEqual(decision["current_state"], "CPU_TEST_ONLY")
        self.assertFalse(decision["strict_rocm_device"])
        self.assertFalse(decision["amd_deployable"])

    def test_profile_set_must_match_plan_exactly(self) -> None:
        receipt = _receipt()
        receipt["profiles"].pop()
        with self.assertRaises(ContractError):
            evaluate_benchmark_receipt(_plan(), receipt)

    def test_exclusive_writer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            write_json_exclusive(path, {"status": "first"})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_json_exclusive(path, {"status": "second"})
            self.assertEqual(path.read_bytes(), before)

    def test_cli_refuses_existing_output_before_importing_torch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(_plan(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = root / "receipt.json"
            output.write_text('{"preserve": true}\n', encoding="utf-8")
            before = output.read_bytes()
            process = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    str(plan_path),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 2)
            self.assertIn("refusing to overwrite", process.stderr)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
