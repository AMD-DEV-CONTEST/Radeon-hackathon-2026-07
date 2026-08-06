from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = json.loads((ROOT / "VERSION_LOCK.json").read_text())
        cls.probe = load_module("probe_inference", ROOT / "src" / "probe_inference.py")
        cls.summary = load_module("summarize_results", ROOT / "src" / "summarize_results.py")
        cls.calibration = load_module(
            "calibrate_amd_shell", ROOT / "src" / "calibrate_amd_shell.py"
        )

    def test_opensplat_camera_conversion(self) -> None:
        import tempfile

        if not hasattr(self.calibration.np, "asarray"):
            self.skipTest("NumPy runtime is installed only in the AMD evaluation venv")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cameras.json"
            source.write_text(
                json.dumps(
                    [
                        {
                            "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            "position": [1, 2, 3],
                            "height": 1080,
                            "fy": 837.0,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            cameras, payload = self.calibration.load_opensplat_cameras(source)
            self.assertEqual(cameras.shape, (1, 4, 4))
            self.assertEqual(cameras[0, :3, 3].tolist(), [1.0, 2.0, 3.0])
            self.assertEqual(payload["frames"], 1)
            self.assertGreater(payload["fovy_degrees_median"], 1.0)

    def test_provider_neutral_inference_contract(self) -> None:
        contract = self.lock["inference_protocol"]
        self.assertEqual(contract["protocol_version"], 2)
        self.assertEqual(contract["action_dim"], 16)
        self.assertEqual(contract["action_horizon"], 10)
        self.assertEqual(contract["state_dim"], 16)
        self.assertEqual(contract["camera_names"], ["head", "left_wrist", "right_wrist"])

    def test_formal_benchmark_is_32_distinct_seeds(self) -> None:
        benchmark = self.lock["benchmark"]
        self.assertEqual(benchmark["formal_episodes"], 32)
        self.assertEqual(benchmark["seed0"], 0)
        self.assertTrue(benchmark["strict_visual_shell"])

    def test_visual_shell_lock_requires_live_calibration_receipt(self) -> None:
        visual_shell = self.lock["visual_shell"]
        self.assertEqual(visual_shell["calibration_source_camera_index"], 296)
        self.assertEqual(visual_shell["calibration_receipt"], "calibration-receipt.json")
        self.assertEqual(len(visual_shell["calibration_receipt_sha256"]), 64)

    def test_probe_png_is_valid_rgb(self) -> None:
        payload = self.probe.png_rgb(12, 9, (1, 2, 3))
        self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(payload[12:16], b"IHDR")
        width, height = struct.unpack(">II", payload[16:24])
        self.assertEqual((width, height), (12, 9))

    def test_probe_enforces_v2_identity_and_timing(self) -> None:
        source = (ROOT / "src" / "probe_inference.py").read_text()
        self.assertIn('"provider"', source)
        self.assertIn('"model_id"', source)
        self.assertIn('"model_revision"', source)
        self.assertIn("request_id", source)
        self.assertIn("server_total_before_final_serialize", source)

    def test_summary_preserves_failures(self) -> None:
        results = {
            "status": "benchmark_complete",
            "task": "DishwasherUnloadCutleryLong",
            "n_episodes": 3,
            "successes": 1,
            "success_rate": 1 / 3,
            "policy_requests": 7,
            "policy_latency_ms": {"p50": 210.0},
            "visual_shell": {"strict": True, "runtime_passed": True},
            "episodes": [
                {"success": True, "failure_reason": None},
                {"success": False, "failure_reason": "policy_timeout"},
                {"success": False, "failure_reason": "max_steps_without_success"},
            ],
        }
        summary = self.summary.summarize(results, 3)
        self.assertEqual(summary["status"], "evaluation_complete")
        self.assertEqual(summary["failure_categories"]["policy_timeout"], 1)
        self.assertFalse(summary["gates"]["human_visual_review"])

        reviewed = self.summary.summarize(results, 3, "passed")
        self.assertTrue(reviewed["gates"]["human_visual_review"])
        self.assertEqual(reviewed["human_visual_review_status"], "passed")

    def test_schema_v2_requires_full_recording_gate(self) -> None:
        results = {
            "schema_version": 2,
            "status": "benchmark_complete",
            "task": "DishwasherUnloadCutleryLong",
            "n_episodes": 1,
            "successes": 0,
            "success_rate": 0.0,
            "policy_requests": 1,
            "policy_latency_ms": {"p50": 210.0},
            "visual_shell": {"strict": True, "runtime_passed": True},
            "episodes": [{"success": False, "failure_reason": "max_steps_without_success"}],
        }
        missing = self.summary.summarize(results, 1)
        self.assertEqual(missing["status"], "evaluation_failed")
        self.assertFalse(missing["gates"]["full_evaluation_recording"])

        results["recording"] = {
            "mode": "full",
            "episodes_terminal": 1,
            "episodes_interrupted": 0,
        }
        validation = {"status": "recording_valid", "expected_episodes": 1}
        complete = self.summary.summarize(
            results, 1, recording_validation=validation
        )
        self.assertEqual(complete["status"], "evaluation_complete")
        self.assertTrue(complete["gates"]["full_evaluation_recording"])

    def test_incomplete_episode_count_fails(self) -> None:
        results = {
            "status": "benchmark_complete",
            "n_episodes": 32,
            "policy_requests": 1,
            "policy_latency_ms": {"p50": 1.0},
            "visual_shell": {"strict": True, "runtime_passed": True},
            "episodes": [{}],
        }
        summary = self.summary.summarize(results, 32)
        self.assertEqual(summary["status"], "evaluation_failed")

    def test_evaluator_accepts_any_v2_provider_identity(self) -> None:
        evaluator = (ROOT / "src" / "eval_bigym_3dgs.py").read_text()
        self.assertIn('identity.get("provider")', evaluator)
        self.assertIn('identity.get("model_id")', evaluator)
        self.assertIn('identity.get("model_revision")', evaluator)
        self.assertIn('identity.get("adapter_source_sha256")', evaluator)

    def test_evaluator_can_reuse_verified_prebuilt_hip_gsplat(self) -> None:
        evaluator = (ROOT / "src" / "eval_bigym_3dgs.py").read_text()
        self.assertIn("GSPLAT_PREBUILT_DIR", evaluator)
        self.assertIn("_import_module_from_library", evaluator)
        self.assertIn("CameraModelType", evaluator)

    def test_evaluator_records_full_trajectory_and_supports_custom_counts(self) -> None:
        evaluator = (ROOT / "src" / "eval_bigym_3dgs.py").read_text()
        runner = (ROOT / "bin" / "run_eval.sh").read_text()
        validator = (ROOT / "src" / "validate_recording.py").read_text()
        self.assertIn("EpisodeRecorder", evaluator)
        self.assertIn('"action16_model"', evaluator)
        self.assertIn('"action_clipped"', evaluator)
        self.assertIn('"record_type": "transition"', evaluator)
        self.assertIn("--restart-interrupted", evaluator)
        self.assertIn("custom)", runner)
        self.assertIn("N_EPISODES must be a positive integer", runner)
        self.assertIn("validate_recording.py", runner)
        self.assertLess(
            runner.index("validate_recording.py"),
            runner.index("summarize_results.py"),
        )
        self.assertIn("--recording-validation", runner)
        self.assertIn("REQUIRED_TRANSITION_FIELDS", validator)
        self.assertIn("INFERENCE_BASE_URL", runner)
        self.assertIn("INFERENCE_PROVIDER", runner)


if __name__ == "__main__":
    unittest.main()
