from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image

from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_image_mastering import PixelBox
from prooflaunch_remix.v10_video_mastering import (
    MASTER_FRAME_COUNT,
    FrameChunkPlan,
    FrameRepairRequest,
    PronunciationLexicon,
    ShotGraph,
    TemporalRewardDimension,
    UHD_LANDSCAPE,
    UHD_PORTRAIT,
    UHD_SQUARE,
    VAETilePlan,
    VideoComputePolicy,
    VideoMasterSpec,
    av_alignment_score,
    cross_media_claim_pass,
    exact_product_identity,
    safe_zone_pass,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evidence/v10/video-mastering-fixture"


class VideoPolicyTests(unittest.TestCase):
    def test_single_card_cannot_retrain_a_10b_or_larger_teacher(self) -> None:
        denied = VideoComputePolicy(1, 10.0, "finetune", "pinned", "a" * 64, True)
        reused = VideoComputePolicy(1, 10.0, "reuse_distilled_checkpoint", "pinned", "a" * 64, False)
        self.assertFalse(denied.admitted)
        self.assertTrue(reused.admitted)

    def test_shot_graph_rejects_cycles(self) -> None:
        ShotGraph(("hook", "proof", "action"), (("hook", "proof"), ("proof", "action")))
        with self.assertRaisesRegex(V10ContractError, "acyclic"):
            ShotGraph(("a", "b"), (("a", "b"), ("b", "a")))

    def test_chunk_overlap_and_vae_tiles_cover_the_full_master(self) -> None:
        windows = FrameChunkPlan(MASTER_FRAME_COUNT, 48, 8).windows()
        self.assertEqual(windows[0], (0, 48))
        self.assertEqual(windows[-1][1], MASTER_FRAME_COUNT)
        self.assertTrue(all(right[0] < left[1] for left, right in zip(windows, windows[1:])))
        tiles = VAETilePlan(UHD_LANDSCAPE, 1024, 128).tiles()
        self.assertTrue(any(tile.right == UHD_LANDSCAPE[0] for tile in tiles))
        self.assertTrue(any(tile.bottom == UHD_LANDSCAPE[1] for tile in tiles))

    def test_frame_fallback_is_local_and_cannot_touch_identity(self) -> None:
        product = PixelBox(2700, 700, 3500, 1500)
        admitted = FrameRepairRequest(96, PixelBox(500, 1500, 700, 1700), PixelBox(450, 1450, 800, 1800), (product,))
        identity_edit = FrameRepairRequest(96, PixelBox(2800, 900, 2900, 1000), PixelBox(2750, 850, 2950, 1050), (product,))
        global_edit = FrameRepairRequest(96, PixelBox(1, 1, 3800, 2100), PixelBox(1, 1, 3839, 2159), (product,))
        self.assertTrue(admitted.admitted)
        self.assertFalse(identity_edit.admitted)
        self.assertFalse(global_edit.admitted)

    def test_master_spec_is_exactly_three_4k_variants_eight_seconds_24fps(self) -> None:
        spec = VideoMasterSpec()
        self.assertEqual(spec.variants, (UHD_LANDSCAPE, UHD_PORTRAIT, UHD_SQUARE))
        self.assertEqual(spec.duration_seconds * spec.fps, 192)
        self.assertEqual((spec.audio_integrated_lufs, spec.audio_true_peak_dbtp), (-16.0, -1.0))

    def test_pronunciation_safe_zone_av_and_claim_checks_fail_closed(self) -> None:
        lexicon = PronunciationLexicon({"ProofLaunch": "P R UW F L AO N CH"})
        self.assertTrue(lexicon.validate_tokens({"ProofLaunch": "P R UW F L AO N CH"}))
        self.assertFalse(lexicon.validate_tokens({"ProofLaunch": "wrong"}))
        safe = PixelBox(100, 100, 1000, 1000)
        self.assertTrue(safe_zone_pass((PixelBox(200, 200, 300, 300),), safe))
        self.assertFalse(safe_zone_pass((PixelBox(50, 50, 300, 300),), safe))
        from prooflaunch_remix.v10_video_mastering import TimedEvent
        self.assertEqual(av_alignment_score((TimedEvent("a", 1.0),), (TimedEvent("a", 1.04),)), 1.0)
        self.assertFalse(cross_media_claim_pass({"c": "invented"}, {"c": "approved"}))


class VideoFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads((FIXTURE / "report.json").read_text(encoding="utf-8"))

    def test_fixture_is_hash_bound_4k_boundary_evidence_not_an_encoded_video(self) -> None:
        self.assertEqual(self.report["fixture_origin"], "project_owned_mechanical_frames_not_model_generated_not_encoded_video")
        self.assertIsNone(self.report["encoded_video"])
        for name, metadata in self.report["files"].items():
            path = FIXTURE / name
            self.assertEqual(sha256_file(path), metadata["sha256"])
            with Image.open(path) as frame:
                self.assertEqual(frame.size, UHD_LANDSCAPE)

    def test_three_roles_storyboard_dag_keyframes_and_constraints_are_bound(self) -> None:
        self.assertEqual(self.report["roles"], ["director", "identity_guardian", "av_quality_editor"])
        shots = self.report["storyboard"]["shots"]
        self.assertEqual([(item["start_frame"], item["end_frame"]) for item in shots], [(0, 47), (48, 143), (144, 191)])
        self.assertEqual(self.report["shot_graph"]["edges"], [["hook", "proof"], ["proof", "action"]])
        self.assertTrue(all(len(item["first_keyframe_sha256"]) == 64 and len(item["last_keyframe_sha256"]) == 64 for item in shots))
        self.assertEqual(len(self.report["constraints"]["product_boxes"]), 6)
        self.assertEqual(len(self.report["constraints"]["logo_boxes"]), 6)

    def test_temporal_reward_has_five_located_hard_dimensions(self) -> None:
        rewards = self.report["temporal_reward"]
        self.assertEqual(set(rewards), {item.value for item in TemporalRewardDimension})
        self.assertTrue(all(item["locator"] and item["value"] == 1.0 for item in rewards.values()))
        self.assertTrue(self.report["temporal_reward_pass"])

    def test_observed_frames_pass_identity_flicker_motion_av_safe_zone_and_claim_gates(self) -> None:
        product = Image.open(ROOT / "evidence/v10/image-mastering-fixture/product-source.png").convert("RGBA")
        for frame_index, values in self.report["constraints"]["product_boxes"].items():
            box = PixelBox(*values)
            frame = Image.open(FIXTURE / f"frame-{int(frame_index):03d}-3840x2160.png")
            self.assertEqual(exact_product_identity(frame, product, box), 1.0)
        self.assertTrue(all(value == 1.0 for value in self.report["product_identity"].values()))
        self.assertGreaterEqual(self.report["flicker_score"], 0.99)
        self.assertEqual(self.report["motion_continuity_score"], 1.0)
        self.assertEqual(self.report["av_alignment_score"], 1.0)
        self.assertTrue(self.report["safe_zone_pass"])
        self.assertTrue(self.report["cross_media_claim_pass"])
        self.assertFalse(any(self.report["model_execution"].values()))


if __name__ == "__main__":
    unittest.main()
