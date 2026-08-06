from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from episode_recorder import EpisodeRecorder  # noqa: E402
from validate_recording import finite_numbers, validate_task_dir  # noqa: E402


class RecordingValidatorTests(unittest.TestCase):
    def test_reset_failure_without_frames_is_a_complete_diagnostic_episode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory)
            recorder = EpisodeRecorder(task_dir, 0, 7, 20, fsync=False)
            policy_health = {"status": "ok", "policy_identity": {"revision": "fixture"}}
            code_revisions = {"evaluation_repository": "fixture", "bigym": "fixture"}
            configuration_sha256 = "a" * 64
            provenance = {
                "run_id": "fixture-run",
                "configuration_sha256": configuration_sha256,
                "task": "DishwasherUnloadCutleryLong",
                "policy_health": policy_health,
                "code_revisions": code_revisions,
            }
            episode_result = {
                "episode_index": 0,
                "seed": 7,
                "success": False,
                "steps_executed": 0,
                "max_steps": 1203,
                "failure_reason": "environment_reset_error",
                "failure_detail": "fixture reset failed",
                "request_count": 0,
                "request_attempts": 0,
                "request_latency_ms": [],
                "request_attempt_latency_ms": [],
                "request_records": [],
                "provenance": provenance,
            }
            manifest = recorder.finalize(
                success=False,
                failure_reason="environment_reset_error",
                failure_detail="fixture reset failed",
                result=episode_result,
            )
            top_episode = dict(episode_result)
            top_episode.update(
                {
                    "recording_status": "failed",
                    "recording_manifest": "episodes/episode-000000/manifest.json",
                    "step_records": 0,
                    "camera_frame_steps": 0,
                    "videos": {
                        camera: manifest["videos"][camera]["final"]
                        for camera in manifest["camera_names"]
                    },
                }
            )
            (task_dir / "results.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "status": "benchmark_complete",
                        "run_id": "fixture-run",
                        "task": "DishwasherUnloadCutleryLong",
                        "n_episodes": 1,
                        "episodes_completed": 1,
                        "seed0": 7,
                        "successes": 0,
                        "success_rate": 0.0,
                        "policy_requests": 0,
                        "policy_request_attempts": 0,
                        "policy_attempts_with_http_latency": 0,
                        "policy_latency_ms": {
                            "mean": None,
                            "p50": None,
                            "p95": None,
                            "maximum": None,
                        },
                        "policy_attempt_latency_ms": {
                            "mean": None,
                            "p50": None,
                            "p95": None,
                            "maximum": None,
                        },
                        "recording": {
                            "mode": "full",
                            "episodes_terminal": 1,
                            "episodes_interrupted": 0,
                            "step_records": 0,
                            "camera_frame_steps": 0,
                        },
                        "configuration": {"fps": 20.0},
                        "configuration_sha256": configuration_sha256,
                        "code_revisions": code_revisions,
                        "policy_health": policy_health,
                        "observation_contract": {
                            "cameras": {
                                "head": [3, 480, 848],
                                "left_wrist": [3, 480, 640],
                                "right_wrist": [3, 480, 640],
                            }
                        },
                        "episodes": [top_episode],
                    }
                ),
                encoding="utf-8",
            )
            report = validate_task_dir(task_dir, 1)
            self.assertEqual(report["status"], "recording_valid")
            self.assertEqual(report["episodes_passed"], 1)

            contradictory = json.loads((task_dir / "results.json").read_text())
            contradictory["episodes"][0]["seed"] = 999
            contradictory["episodes"][0]["success"] = True
            contradictory["successes"] = 1
            (task_dir / "results.json").write_text(json.dumps(contradictory))
            rejected = validate_task_dir(task_dir, 1)
            self.assertEqual(rejected["status"], "recording_invalid")
            self.assertTrue(rejected["top_level_errors"])

    def test_tagged_nonfinite_numbers_are_rejected(self) -> None:
        self.assertTrue(finite_numbers({"value": 1.25}))
        self.assertFalse(finite_numbers({"value": "NaN"}))
        self.assertFalse(finite_numbers({"value": "Infinity"}))


if __name__ == "__main__":
    unittest.main()
