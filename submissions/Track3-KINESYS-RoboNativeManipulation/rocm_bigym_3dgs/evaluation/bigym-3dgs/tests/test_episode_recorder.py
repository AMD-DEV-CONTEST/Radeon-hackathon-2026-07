from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load_recorder_module():
    path = ROOT / "src" / "episode_recorder.py"
    spec = importlib.util.spec_from_file_location("episode_recorder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECORDER = load_recorder_module()


def opencv_available() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:
        return False
    return True


def numpy_available() -> bool:
    return hasattr(np, "asarray") and hasattr(np, "ndarray")


class EpisodeRecorderTests(unittest.TestCase):
    def test_json_safe_handles_numpy_nonfinite_bytes_paths_and_cycles(self) -> None:
        cyclic: list[object] = []
        cyclic.append(cyclic)
        source = {
            "nan": math.nan,
            "positive_infinity": float("inf"),
            "bytes": b"abc",
            "path": Path("episode/steps.jsonl"),
            "set": {3, 1, 2},
            "cycle": cyclic,
        }
        if numpy_available():
            source["array"] = np.asarray([[1, 2], [3, 4]], dtype=np.int16)
            source["scalar"] = np.float32(1.25)
        payload = RECORDER.json_safe(source)
        if numpy_available():
            self.assertEqual(payload["array"], [[1, 2], [3, 4]])
            self.assertAlmostEqual(payload["scalar"], 1.25)
        self.assertEqual(payload["nan"], "NaN")
        self.assertEqual(payload["positive_infinity"], "Infinity")
        self.assertEqual(payload["bytes"]["base64"], "YWJj")
        self.assertEqual(payload["path"], "episode/steps.jsonl")
        self.assertEqual(payload["set"], [1, 2, 3])
        self.assertEqual(payload["cycle"][0]["__type__"], "cycle")
        json.dumps(payload, allow_nan=False)

    def test_append_only_steps_and_atomic_failed_manifest_without_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = RECORDER.EpisodeRecorder(
                directory,
                episode_index=7,
                seed=107,
                fps=20,
                fsync=False,
            )
            first = recorder.append_step(
                {
                    "state": list(range(16)),
                    "action": [0.0] * 16,
                    "reward": 0.0,
                    "success": False,
                    "terminated": False,
                    "truncated": False,
                    "inference_latency_ms": 210.5,
                    "info": {"contacts": [2, 4]},
                }
            )
            self.assertEqual(first["episode_index"], 7)
            self.assertEqual(first["seed"], 107)
            self.assertEqual(first["step_index"], 0)
            self.assertFalse(first["camera_frames_recorded"])

            manifest = recorder.finalize(
                success=False,
                failure_reason="policy_timeout",
                failure_detail="request exceeded deadline",
                result={"final_reward": 0.0},
            )
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["steps"]["count"], 1)
            self.assertEqual(len(manifest["steps"]["sha256"]), 64)
            self.assertTrue(all(value["final"] is None for value in manifest["videos"].values()))

            episode_dir = Path(directory) / "episodes" / "episode-000007"
            lines = (episode_dir / "steps.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            stored = json.loads(lines[0])
            self.assertEqual(stored["state"], list(range(16)))
            self.assertEqual(stored["info"]["contacts"], [2, 4])
            self.assertFalse(list(episode_dir.glob(".manifest.json.*.tmp")))

            report = RECORDER.inspect_episode(directory, 7, seed=107)
            self.assertEqual(report["state"], "failed")
            with self.assertRaises(RECORDER.EpisodeAlreadyComplete):
                RECORDER.EpisodeRecorder(
                    directory, 7, 107, 20, resume=True, fsync=False
                )

    def test_graceful_interrupt_repairs_partial_jsonl_tail_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = RECORDER.EpisodeRecorder(
                directory, 2, 42, 20, fsync=False
            )
            first.append_step({"reward": 0.0, "success": False})
            interrupted = first.interrupt("planned restart")
            self.assertEqual(interrupted["status"], "interrupted")

            steps_path = first.episode_dir / "steps.jsonl"
            with steps_path.open("ab") as stream:
                stream.write(b'{"partial":true')
            report = RECORDER.inspect_episode(directory, 2, seed=42)
            self.assertEqual(report["state"], "resumable")
            self.assertGreater(report["steps"]["partial_tail_bytes"], 0)

            resumed = RECORDER.EpisodeRecorder(
                directory, 2, 42, 20, resume=True, fsync=False
            )
            self.assertEqual(resumed.next_step_index, 1)
            resumed.append_step({"reward": 1.0, "success": True})
            manifest = resumed.finalize(success=True, result={"reward": 1.0})
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["steps"]["count"], 2)
            self.assertEqual(manifest["session_count"], 2)
            self.assertEqual(
                manifest["recovery"][-1]["action"],
                "truncate_partial_jsonl_tail",
            )
            rows = [json.loads(line) for line in steps_path.read_text().splitlines()]
            self.assertEqual([row["step_index"] for row in rows], [0, 1])

    @unittest.skipUnless(numpy_available(), "NumPy is not installed")
    def test_camera_set_and_frame_shape_are_validated_before_opening_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = RECORDER.EpisodeRecorder(
                directory, 0, 0, 20, fsync=False
            )
            frame = np.zeros((8, 8, 3), dtype=np.uint8)
            with self.assertRaisesRegex(ValueError, "exactly"):
                recorder.append_step({"reward": 0}, {"head": frame})
            with self.assertRaisesRegex(ValueError, "uint8"):
                recorder.append_step(
                    {"reward": 0},
                    {
                        "head": frame.astype(np.float32),
                        "left_wrist": frame,
                        "right_wrist": frame,
                    },
                )
            recorder.interrupt()

    @unittest.skipUnless(
        numpy_available() and opencv_available(),
        "NumPy and OpenCV are not installed",
    )
    def test_three_camera_videos_are_merged_hashed_and_frame_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = RECORDER.EpisodeRecorder(
                directory, 1, 11, 20, fsync=False
            )
            frames0 = {
                "head": np.full((32, 48, 3), 20, dtype=np.uint8),
                "left_wrist": np.full((3, 24, 32), 60, dtype=np.uint8),
                "right_wrist": np.full((24, 32, 3), 100, dtype=np.uint8),
            }
            first.append_step(
                {
                    "state": np.zeros(16, dtype=np.float32),
                    "action": np.ones(16, dtype=np.float32),
                    "reward": 0.0,
                    "success": False,
                    "timestamp_s": 0.0,
                    "inference_latency_ms": 12.5,
                },
                frames0,
            )
            first.interrupt("rotate process")
            self.assertEqual(
                RECORDER.inspect_episode(directory, 1, seed=11)["state"],
                "resumable",
            )

            resumed = RECORDER.EpisodeRecorder(
                directory, 1, 11, 20, resume=True, fsync=False
            )
            frames1 = {
                camera: np.full_like(frame, 180) for camera, frame in frames0.items()
            }
            resumed.append_step(
                {
                    "state": np.ones(16, dtype=np.float32),
                    "action": np.zeros(16, dtype=np.float32),
                    "reward": 1.0,
                    "success": True,
                    "timestamp_s": 0.05,
                    "inference_latency_ms": None,
                },
                frames1,
            )
            manifest = resumed.finalize(success=True, result={"final_reward": 1})
            self.assertEqual(manifest["steps"]["camera_frame_steps"], 2)
            for camera in RECORDER.DEFAULT_CAMERA_NAMES:
                metadata = manifest["videos"][camera]["final"]
                self.assertTrue(metadata["passed"])
                self.assertEqual(metadata["decoded_frames"], 2)
                self.assertEqual(len(metadata["sha256"]), 64)
                self.assertTrue((resumed.episode_dir / metadata["path"]).is_file())
                self.assertTrue(
                    all(
                        segment["retained"] is False
                        for segment in manifest["videos"][camera]["segments"]
                    )
                )
            self.assertEqual(
                RECORDER.inspect_episode(directory, 1, seed=11)["state"],
                "complete",
            )

    @unittest.skipUnless(
        numpy_available() and opencv_available(),
        "NumPy and OpenCV are not installed",
    )
    def test_partial_camera_write_requires_seed_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = RECORDER.EpisodeRecorder(
                directory, 3, 13, 20, fsync=False
            )
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            original_write = recorder._writers["right_wrist"].write

            def fail_write(_frame, _camera):
                raise OSError("fixture camera write failure")

            recorder._writers["right_wrist"].write = fail_write
            with self.assertRaisesRegex(OSError, "fixture camera write failure"):
                recorder.append_step(
                    {"record_type": "reset"},
                    {camera: frame for camera in RECORDER.DEFAULT_CAMERA_NAMES},
                )
            recorder._writers["right_wrist"].write = original_write
            recorder.interrupt("restart after partial camera write")
            report = RECORDER.inspect_episode(directory, 3, seed=13)
            self.assertEqual(report["state"], "restart_required")
            self.assertTrue(
                any("camera/step frame mismatch" in error for error in report["errors"])
            )


if __name__ == "__main__":
    unittest.main()
