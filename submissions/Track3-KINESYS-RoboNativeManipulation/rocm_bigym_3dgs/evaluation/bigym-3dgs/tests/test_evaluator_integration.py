from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def runtime_available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy as np
    except Exception:
        return False
    return hasattr(np, "zeros") and hasattr(np, "ndarray")


@unittest.skipUnless(runtime_available(), "NumPy and OpenCV are not installed")
class EvaluatorIntegrationTests(unittest.TestCase):
    def test_one_successful_episode_writes_a_valid_full_recording(self) -> None:
        import numpy as np

        spec = importlib.util.spec_from_file_location(
            "eval_bigym_3dgs_integration", SRC / "eval_bigym_3dgs.py"
        )
        assert spec and spec.loader
        evaluator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evaluator)

        dim_utils = types.ModuleType("dim_utils")
        dim_utils.drop_z = lambda action, _task: action
        dim_utils.pad_to_16 = lambda state, _task: np.asarray(state, dtype=np.float32)

        class FakeShell:
            def __init__(self, rendered_frames: int):
                self.rendered_frames = rendered_frames

            def status(self):
                return {
                    "enabled": True,
                    "rendered_frames": self.rendered_frames,
                    "last_error": None,
                }

        class FakeEnv:
            shell_frames = 9

            def __init__(self):
                self.action_mode = types.SimpleNamespace(_mojo=object())
                self.action_space = types.SimpleNamespace(
                    low=np.full(16, -1.0, dtype=np.float32),
                    high=np.full(16, 1.0, dtype=np.float32),
                )
                self.robot = object()
                self._visual_shell = FakeShell(self.shell_frames)
                self.steps = 0

            @staticmethod
            def observation(value: int):
                return {
                    "rgb_head": np.full((3, 480, 848), value, dtype=np.uint8),
                    "rgb_left_wrist": np.full((3, 480, 640), value, dtype=np.uint8),
                    "rgb_right_wrist": np.full((3, 480, 640), value, dtype=np.uint8),
                }

            def reset(self, seed: int):
                self.steps = 0
                return self.observation(seed), {"reset_seed": seed}

            def step(self, _action):
                self.steps += 1
                success = self.steps == 2
                return (
                    self.observation(20 + self.steps),
                    1.0 if success else 0.0,
                    False,
                    False,
                    {"task_success": success},
                )

            def close(self):
                return None

        env_utils = types.ModuleType("env_utils")
        env_utils.build_env = lambda *_args, **_kwargs: FakeEnv()
        env_utils.get_state = lambda *_args, **_kwargs: np.zeros(16, dtype=np.float32)

        tasks = types.ModuleType("tasks")
        tasks.FREQ = 20
        tasks.TASKS = {
            "DishwasherUnloadCutleryLong": {
                "prompt": "Unload cutlery from dishwasher to drawer task."
            }
        }
        tasks.get_maxstep = lambda _task: 2
        tasks.resolve_task = lambda task: task
        tasks.task_to_snake = lambda _task: "dishwasher_unload_cutlery_long"

        replacements = {
            "dim_utils": dim_utils,
            "env_utils": env_utils,
            "tasks": tasks,
        }
        previous_modules = {name: sys.modules.get(name) for name in replacements}
        sys.modules.update(replacements)
        original_argv = sys.argv
        try:
            evaluator.install_prebuilt_gsplat_backend = lambda: None
            evaluator.policy_health = lambda _base_url: {
                "status": "ok",
                "backend": "external-test",
                "adapter": "fixture-http-v2",
                "protocol_version": 2,
                "policy_identity": {
                    "provider": "fixture-provider",
                    "model_id": "fixture/model",
                    "model_revision": "fixture-model",
                    "adapter_source_sha256": "b" * 64,
                },
            }
            evaluator.request_chunk = lambda *_args, **_kwargs: (
                np.zeros((10, 16), dtype=np.float32),
                {
                    "request_id": "fixture-request",
                    "started_at_utc": "2026-08-05T00:00:00+00:00",
                    "image_encode_ms": 1.0,
                    "http_round_trip_ms": 2.0,
                    "server_timing_ms": {
                        "image_decode": 0.25,
                        "policy_infer": 1.5,
                        "total_before_serialize": 1.8,
                        "serialization_first_pass": 0.1,
                        "server_total_before_final_serialize": 1.9,
                    },
                },
            )
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                bigym_root = root / "bigym"
                (bigym_root / "d" / "replay_generation").mkdir(parents=True)
                (bigym_root / "d" / "eval").mkdir(parents=True)
                profile = root / "profile.json"
                profile.write_text(json.dumps({"fixture": True}), encoding="utf-8")
                output = root / "results"
                sys.argv = [
                    "eval_bigym_3dgs.py",
                    "--bigym-root",
                    str(bigym_root),
                    "--base-url",
                    "http://127.0.0.1:7891",
                    "--visual-shell-profile",
                    str(profile),
                    "--output-dir",
                    str(output),
                    "--n-episodes",
                    "1",
                    "--run-id",
                    "fixture-full-v2",
                ]
                evaluator.main()

                from validate_recording import validate_task_dir

                task_dir = output / "dishwasher_unload_cutlery_long"
                results = json.loads((task_dir / "results.json").read_text())
                self.assertEqual(results["status"], "benchmark_complete")
                self.assertEqual(results["successes"], 1)
                self.assertEqual(results["recording"]["episodes_terminal"], 1)
                self.assertEqual(results["recording"]["camera_frame_steps"], 3)
                validation = validate_task_dir(task_dir, 1)
                self.assertEqual(validation["status"], "recording_valid")
                self.assertEqual(validation["transitions"], 2)

                # Simulate a crash after terminal manifest finalize but before the
                # authoritative top-level checkpoint. Resume must overwrite the
                # stale interrupted entry from the manifest instead of getting stuck.
                results["status"] = "benchmark_incomplete"
                results["episodes"][0] = {
                    "episode_index": 0,
                    "seed": 0,
                    "success": False,
                    "recording_status": "interrupted",
                }
                results["recording"]["episodes_terminal"] = 0
                results["recording"]["episodes_interrupted"] = 1
                (task_dir / "results.json").write_text(json.dumps(results))
                FakeEnv.shell_frames = 0
                sys.argv.extend(["--resume", "--restart-interrupted"])
                evaluator.main()
                recovered = json.loads((task_dir / "results.json").read_text())
                self.assertEqual(recovered["status"], "benchmark_complete")
                self.assertEqual(recovered["episodes"][0]["recording_status"], "complete")
                self.assertEqual(recovered["recording"]["episodes_terminal"], 1)
                self.assertEqual(
                    recovered["visual_shell"]["status"]["rendered_frames"], 9
                )
                self.assertTrue(recovered["visual_shell"]["runtime_passed"])
                self.assertEqual(validate_task_dir(task_dir, 1)["status"], "recording_valid")
        finally:
            sys.argv = original_argv
            for name, previous in previous_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
