import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_competition_mvp_delivery.py"
SPEC = importlib.util.spec_from_file_location("competition_delivery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VERIFY_SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_competition_mvp_delivery.py"
VERIFY_SPEC = importlib.util.spec_from_file_location("competition_delivery_verify", VERIFY_SCRIPT)
assert VERIFY_SPEC is not None and VERIFY_SPEC.loader is not None
VERIFY_MODULE = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY_MODULE)


class CompetitionMVPDeliveryTests(unittest.TestCase):
    def _campaign(self, video_paths: list[Path] | None = None) -> dict:
        video_paths = video_paths or [Path(f"episode-{index}.mp4") for index in range(3)]
        return {
            "status": "passed",
            "successes": 2,
            "trials": 3,
            "success_rate": 2 / 3,
            "wilson_95": [0.2, 0.94],
            "pure_vla_complete_success_count": 2,
            "vla_qualified_run_count": 3,
            "vla_actuated_run_count": 3,
            "single_radeon_rocm_run_count": 3,
            "expert_fallback_count": 0,
            "force_violation_count": 0,
            "runs": [
                {
                    "episode_id": f"episode-{index}",
                    "success": index < 2,
                    "pure_vla_complete_success": index < 2,
                    "vla_qualified": True,
                    "expert_reference_used": False,
                    "media": {
                        "video_requested": True,
                        "video_saved": True,
                        "video_path": str(video_paths[index]),
                    },
                }
                for index in range(3)
            ],
        }

    def test_two_of_three_pure_vla_passes_competition_gate(self) -> None:
        result = MODULE._campaign_gate(self._campaign(), min_successes=2)
        self.assertTrue(result["passed"])
        self.assertEqual(result["pure_vla_complete_successes"], 2)
        self.assertEqual(result["trials"], 3)

    def test_expert_reference_fails_competition_gate(self) -> None:
        campaign = self._campaign()
        campaign["runs"][1]["expert_reference_used"] = True
        result = MODULE._campaign_gate(campaign, min_successes=2)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["zero_expert_reference"])

    def test_one_of_three_fails_competition_gate(self) -> None:
        campaign = self._campaign()
        campaign["pure_vla_complete_success_count"] = 1
        result = MODULE._campaign_gate(campaign, min_successes=2)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["minimum_pure_vla_successes"])

    def test_competition_threshold_cannot_be_lowered(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 2 and 3"):
            MODULE._campaign_gate(self._campaign(), min_successes=1)

    @staticmethod
    def _video_probe(fingerprint: str = "fingerprint-a") -> dict:
        return {
            "codec": "h264",
            "width": 640,
            "height": 480,
            "duration_seconds": 4.0,
            "minimum_decoded_frames_verified": 2,
            "content_fingerprint_protocol": "decoded-gray-32x18-5-quantized-v1",
            "content_fingerprint": fingerprint,
            "content_sample_frame_count": 12,
            "content_sample_frame_indices": [0, 3, 6, 8, 11],
            "content_sample_frame_sha256": [fingerprint] * 5,
        }

    @staticmethod
    def _write_visual_video(path: Path, *, rgb: tuple[int, int, int], title: str) -> None:
        import av
        import numpy as np

        with av.open(str(path), "w") as container:
            container.metadata["title"] = title
            stream = container.add_stream("mpeg4", rate=5)
            stream.width = 32
            stream.height = 24
            stream.pix_fmt = "yuv420p"
            for index in range(8):
                image = np.full((24, 32, 3), rgb, dtype=np.uint8)
                image[:, index * 4 : index * 4 + 4, :] = 255 - image[:, index * 4 : index * 4 + 4, :]
                frame = av.VideoFrame.from_ndarray(image, format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)

    def test_three_playable_rollout_videos_are_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            posttrain = Path(directory) / "posttrain"
            output = Path(directory) / "delivery"
            posttrain.mkdir()
            output.mkdir()
            videos = [posttrain / f"episode-{index}.mp4" for index in range(3)]
            for index, video in enumerate(videos):
                video.write_bytes(bytes([index]) * 2048)
            with mock.patch.object(
                MODULE,
                "_probe_video",
                side_effect=[
                    self._video_probe("fingerprint-a"),
                    self._video_probe("fingerprint-b"),
                    self._video_probe("fingerprint-c"),
                ],
            ):
                records = MODULE._package_demo_videos(
                    self._campaign(videos), posttrain=posttrain, output=output
                )
            self.assertEqual(len(records), 3)
            self.assertEqual(
                sorted(path.name for path in (output / "demo-videos").glob("*.mp4")),
                ["01-episode-0.mp4", "02-episode-1.mp4", "03-episode-2.mp4"],
            )
            self.assertTrue(
                all(record["probe"]["minimum_decoded_frames_verified"] == 2 for record in records)
            )

    def test_missing_rollout_video_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            posttrain = Path(directory) / "posttrain"
            output = Path(directory) / "delivery"
            posttrain.mkdir()
            output.mkdir()
            videos = [posttrain / f"episode-{index}.mp4" for index in range(3)]
            for index, video in enumerate(videos[:2]):
                video.write_bytes(bytes([index]) * 2048)
            with self.assertRaisesRegex(ValueError, "required demo MP4 is missing"):
                MODULE._package_demo_videos(
                    self._campaign(videos), posttrain=posttrain, output=output
                )

    def test_relative_rollout_video_paths_are_bound_to_posttrain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            posttrain = Path(directory) / "posttrain"
            output = Path(directory) / "delivery"
            posttrain.mkdir()
            output.mkdir()
            videos = [posttrain / f"episode-{index}.mp4" for index in range(3)]
            for index, video in enumerate(videos):
                video.write_bytes(bytes([index]) * 2048)
            campaign = self._campaign([Path(video.name) for video in videos])
            with mock.patch.object(
                MODULE,
                "_probe_video",
                side_effect=[
                    self._video_probe("fingerprint-a"),
                    self._video_probe("fingerprint-b"),
                    self._video_probe("fingerprint-c"),
                ],
            ):
                records = MODULE._package_demo_videos(
                    campaign, posttrain=posttrain, output=output
                )
            self.assertEqual(len(records), 3)

    def test_duplicate_rollout_video_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            posttrain = Path(directory) / "posttrain"
            output = Path(directory) / "delivery"
            posttrain.mkdir()
            output.mkdir()
            first = posttrain / "episode-0.mp4"
            second = posttrain / "episode-2.mp4"
            first.write_bytes(b"0" * 2048)
            second.write_bytes(b"0" * 2048)
            with self.assertRaisesRegex(ValueError, "duplicate demo video source"):
                MODULE._package_demo_videos(
                    self._campaign([first, first, second]),
                    posttrain=posttrain,
                    output=output,
                )

    def test_duplicate_rollout_video_content_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            posttrain = Path(directory) / "posttrain"
            output = Path(directory) / "delivery"
            posttrain.mkdir()
            output.mkdir()
            videos = [posttrain / f"episode-{index}.mp4" for index in range(3)]
            for video in videos:
                video.write_bytes(b"0" * 2048)
            with self.assertRaisesRegex(ValueError, "duplicate demo video content"):
                MODULE._package_demo_videos(
                    self._campaign(videos), posttrain=posttrain, output=output
                )

    def test_duplicate_decoded_video_content_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            posttrain = Path(directory) / "posttrain"
            output = Path(directory) / "delivery"
            posttrain.mkdir()
            output.mkdir()
            videos = [posttrain / f"episode-{index}.mp4" for index in range(3)]
            for index, video in enumerate(videos):
                video.write_bytes(bytes([index]) * 2048)
            with mock.patch.object(
                MODULE,
                "_probe_video",
                side_effect=[
                    self._video_probe("same-visual-content"),
                    self._video_probe("same-visual-content"),
                    self._video_probe("different-visual-content"),
                ],
            ):
                with self.assertRaisesRegex(ValueError, "duplicate demo video visual content"):
                    MODULE._package_demo_videos(
                        self._campaign(videos), posttrain=posttrain, output=output
                    )

    def test_content_fingerprint_rejects_same_frames_with_different_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            posttrain = Path(directory) / "posttrain"
            output = Path(directory) / "delivery"
            posttrain.mkdir()
            output.mkdir()
            videos = [posttrain / f"episode-{index}.mp4" for index in range(3)]
            self._write_visual_video(videos[0], rgb=(25, 90, 190), title="rollout-one")
            self._write_visual_video(videos[1], rgb=(25, 90, 190), title="rollout-two")
            self._write_visual_video(videos[2], rgb=(190, 90, 25), title="rollout-three")
            self.assertNotEqual(MODULE._sha256(videos[0]), MODULE._sha256(videos[1]))
            first = MODULE._probe_video(videos[0])
            second = MODULE._probe_video(videos[1])
            third = MODULE._probe_video(videos[2])
            self.assertEqual(first["content_fingerprint"], second["content_fingerprint"])
            self.assertNotEqual(first["content_fingerprint"], third["content_fingerprint"])
            self.assertEqual(
                first["content_fingerprint"],
                VERIFY_MODULE._probe_video(videos[0])["content_fingerprint"],
            )
            with self.assertRaisesRegex(ValueError, "duplicate demo video visual content"):
                MODULE._package_demo_videos(
                    self._campaign(videos), posttrain=posttrain, output=output
                )

    def test_delivery_verifier_rejects_missing_per_run_attribution(self) -> None:
        campaign = self._campaign()
        for run in campaign["runs"]:
            run.update(
                {
                    "system_control_class": "pure_vla",
                    "task_action_correction_count": 0,
                    "task_routing_authorities": ["vla_policy"],
                    "policy_authority_consistent": True,
                    "policy": {
                        "expert_fallback_count": 0,
                        "expert_reference_used": False,
                        "emergency_stop_count": 0,
                    },
                    "runtime": {
                        "gpu_count": 1,
                        "cuda": None,
                        "rocm": "6.4",
                        "gpu_name": "AMD Radeon",
                    },
                }
            )
        checks = VERIFY_MODULE._campaign_gate(campaign)
        self.assertTrue(all(checks.values()))
        del campaign["runs"][0]["policy"]["expert_reference_used"]
        checks = VERIFY_MODULE._campaign_gate(campaign)
        self.assertFalse(checks["all_runs_pure_vla_attributed"])


if __name__ == "__main__":
    unittest.main()
