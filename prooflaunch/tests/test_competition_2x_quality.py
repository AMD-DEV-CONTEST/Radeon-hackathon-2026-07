from __future__ import annotations

import unittest

from PIL import Image

from prooflaunch_remix.media_quality import (
    AudioVideoAlignmentGate,
    EncodedVideoIdentityGate,
    SemanticEvent,
)
from prooflaunch_remix.mission import (
    DeliverableKind,
    DeliverableSpec,
    MultimodalMissionPlanner,
)
from prooflaunch_remix.multimodal_ingest import (
    MediaArtifact,
    MediaKind,
    RightsStatus,
)
from prooflaunch_remix.multimodal_models import (
    GroundedDetection,
    summarize_temporal_masks,
)
from prooflaunch_remix.quality_contract import (
    QualityTier,
    contract_for,
    wilson_lower_bound,
)


class Competition2XContractTests(unittest.TestCase):
    @staticmethod
    def passing_evidence() -> dict:
        return {
            "schema": "ProofLaunchCompetition2XCompiledEvidenceV2",
            "product_count": 30,
            "aspect_ratio_count": 3,
            "seeds_per_product": 5,
            "video_case_count": 30,
            "human_raters": 5,
            "repair_budget_max": 2,
            "unsupported_claim_count": 0,
            "locator_coverage": 1.0,
            "image_identity_pass_rate": 1.0,
            "preencode_video_identity_pass_rate": 1.0,
            "encoded_video_identity_pass_rate": 0.96,
            "audio_video_alignment_pass_rate": 0.96,
            "cross_media_pass_rate": 0.97,
            "completion_rate": 0.96,
            "crash_rate": 0.01,
            "seed_diversity_group_pass_rate": 0.96,
            "baseline_completion_rate_gap": 0.01,
            "publish_preferred_count": 100,
            "publish_comparison_count": 150,
        }

    def test_complete_measured_contract_passes(self) -> None:
        report = contract_for(QualityTier.COMPETITION_2X).evaluate(
            self.passing_evidence()
        )
        self.assertTrue(report.passed)
        self.assertGreater(
            report.derived_metrics["publish_preference_lower_95"], 0.50
        )

    def test_missing_metric_fails_closed(self) -> None:
        evidence = self.passing_evidence()
        del evidence["encoded_video_identity_pass_rate"]
        report = contract_for(QualityTier.COMPETITION_2X).evaluate(evidence)
        self.assertFalse(report.passed)
        encoded = next(
            item
            for item in report.metrics
            if item.key == "encoded_video_identity_pass_rate"
        )
        self.assertIsNone(encoded.actual)

    def test_reported_confidence_cannot_replace_raw_comparison_counts(self) -> None:
        evidence = self.passing_evidence()
        del evidence["publish_preferred_count"]
        del evidence["publish_comparison_count"]
        evidence.update(
            {
                "human_rating_count": 999,
                "publish_preference_rate": 1.0,
                "publish_preference_lower_95": 1.0,
            }
        )
        report = contract_for(QualityTier.COMPETITION_2X).evaluate(evidence)
        self.assertFalse(report.passed)
        self.assertNotIn("publish_preference_lower_95", report.derived_metrics)

    def test_wilson_interval_rejects_invalid_counts(self) -> None:
        with self.assertRaises(Exception):
            wilson_lower_bound(2, 1)

    def test_uncompiled_aggregate_is_rejected(self) -> None:
        evidence = self.passing_evidence()
        del evidence["schema"]
        report = contract_for(QualityTier.COMPETITION_2X).evaluate(evidence)
        self.assertFalse(report.passed)
        self.assertTrue(all(item.actual is None for item in report.metrics))


class Competition2XRoutingTests(unittest.TestCase):
    @staticmethod
    def artifact(kind: MediaKind) -> MediaArtifact:
        return MediaArtifact(
            id="MED-2X",
            path="/tmp/input",
            role="product",
            kind=kind,
            mime_type="video/mp4",
            sha256="a" * 64,
            byte_size=1,
            rights=RightsStatus.OWNED,
        )

    def test_2x_video_plan_adds_grounding_tracking_and_audio_semantics(self) -> None:
        plan = MultimodalMissionPlanner().build(
            mission_id="competition-2x",
            artifacts=(self.artifact(MediaKind.VIDEO),),
            deliverables=(
                DeliverableSpec(DeliverableKind.SHORT_VIDEO, "9:16", 8),
            ),
            available_vram_gb=24,
            quality_tier=QualityTier.COMPETITION_2X,
        )
        roles = {phase.role for phase in plan.model_phases}
        self.assertTrue(
            {
                "open_set_detection",
                "temporal_segmentation",
                "audio_text_scoring",
            }.issubset(roles)
        )
        self.assertEqual(plan.quality_tier, QualityTier.COMPETITION_2X)
        self.assertEqual(
            plan.serializable()["quality_contract"]["tier"], "competition_2x"
        )
        self.assertTrue(all(phase.unload_after for phase in plan.model_phases))

    def test_standard_plan_does_not_enable_candidate_models(self) -> None:
        plan = MultimodalMissionPlanner().build(
            mission_id="standard",
            artifacts=(self.artifact(MediaKind.VIDEO),),
            deliverables=(
                DeliverableSpec(DeliverableKind.SHORT_VIDEO, "9:16", 8),
            ),
            available_vram_gb=24,
        )
        roles = {phase.role for phase in plan.model_phases}
        self.assertNotIn("open_set_detection", roles)
        self.assertNotIn("temporal_segmentation", roles)


class EncodedIdentityTests(unittest.TestCase):
    @staticmethod
    def frames(
        *,
        count: int = 10,
        color: tuple[int, int, int] = (200, 20, 30),
    ) -> tuple[Image.Image, ...]:
        frames = []
        for _ in range(count):
            frame = Image.new("RGB", (100, 100), (5, 5, 5))
            frame.paste(Image.new("RGB", (20, 20), color), (20, 20))
            frames.append(frame)
        return tuple(frames)

    @staticmethod
    def product() -> Image.Image:
        return Image.new("RGBA", (20, 20), (200, 20, 30, 255))

    def test_small_codec_noise_passes(self) -> None:
        noisy = self.frames(color=(205, 18, 33))
        report = EncodedVideoIdentityGate(
            decoder=lambda _: noisy,
            codec_tolerance=0.04,
        ).audit(
            video_path="unused.mp4",
            product_layer=self.product(),
            normalized_box=(0.2, 0.2, 0.4, 0.4),
            expected_frame_count=10,
        )
        self.assertTrue(report.passed)
        self.assertLess(report.p95_normalized_mae, 0.04)

    def test_product_tamper_fails_after_decode(self) -> None:
        tampered = self.frames(color=(20, 180, 210))
        report = EncodedVideoIdentityGate(
            decoder=lambda _: tampered,
            codec_tolerance=0.04,
        ).audit(
            video_path="unused.mp4",
            product_layer=self.product(),
            normalized_box=(0.2, 0.2, 0.4, 0.4),
            expected_frame_count=10,
        )
        self.assertFalse(report.passed)

    def test_missing_decoded_frames_fails_coverage(self) -> None:
        report = EncodedVideoIdentityGate(
            decoder=lambda _: self.frames(count=9),
        ).audit(
            video_path="unused.mp4",
            product_layer=self.product(),
            normalized_box=(0.2, 0.2, 0.4, 0.4),
            expected_frame_count=10,
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.frame_coverage, 0.9)


class AudioVideoAlignmentTests(unittest.TestCase):
    @staticmethod
    def event(label: str, start: float, end: float, locator: str) -> SemanticEvent:
        return SemanticEvent(label, start, end, 0.9, locator)

    def test_aligned_events_and_duration_pass(self) -> None:
        report = AudioVideoAlignmentGate().audit(
            audio_events=(
                self.event("logo reveal", 1.0, 1.4, "audio:1.0-1.4"),
                self.event("product click", 3.0, 3.2, "audio:3.0-3.2"),
            ),
            video_events=(
                self.event("logo reveal", 1.1, 1.5, "frame:31"),
                self.event("product click", 3.1, 3.3, "frame:76"),
            ),
            audio_duration_seconds=5.0,
            video_duration_seconds=5.1,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.event_coverage, 1.0)

    def test_semantic_miss_fails_coverage(self) -> None:
        report = AudioVideoAlignmentGate().audit(
            audio_events=(
                self.event("logo reveal", 1.0, 1.2, "audio:1"),
                self.event("product click", 3.0, 3.2, "audio:3"),
            ),
            video_events=(
                self.event("logo reveal", 1.0, 1.2, "frame:24"),
                self.event("unrelated", 3.0, 3.2, "frame:72"),
            ),
            audio_duration_seconds=5.0,
            video_duration_seconds=5.0,
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.event_coverage, 0.5)

    def test_large_timing_drift_fails(self) -> None:
        report = AudioVideoAlignmentGate().audit(
            audio_events=(self.event("impact", 1.0, 1.1, "audio:1"),),
            video_events=(self.event("impact", 2.0, 2.1, "frame:48"),),
            audio_duration_seconds=4.0,
            video_duration_seconds=4.0,
        )
        self.assertFalse(report.passed)
        self.assertGreater(report.p95_midpoint_delta_seconds or 0, 0.5)


class ModelAdapterContractTests(unittest.TestCase):
    def test_grounded_detection_converts_to_located_observation(self) -> None:
        detection = GroundedDetection(
            label="Aster Arc product",
            score=0.91,
            box_xyxy=(10.0, 20.0, 80.0, 90.0),
            source_artifact_id="MED-001",
            model_ref="IDEA-Research/grounding-dino-tiny",
        )
        observation = detection.to_observation(1)
        self.assertEqual(observation.source_artifact_id, "MED-001")
        self.assertTrue(observation.locator.startswith("bbox_xyxy:"))

    def test_temporal_summary_requires_95_percent_nonempty_masks(self) -> None:
        ratios = [(index, 0.2) for index in range(19)] + [(19, 0.0)]
        report = summarize_temporal_masks(
            source_artifact_id="VID-001",
            model_ref="facebook/sam2.1-hiera-small",
            frame_count=20,
            frame_mask_area_ratios=ratios,
        )
        self.assertTrue(report.passed)
        failed = summarize_temporal_masks(
            source_artifact_id="VID-001",
            model_ref="facebook/sam2.1-hiera-small",
            frame_count=20,
            frame_mask_area_ratios=ratios[:-2],
        )
        self.assertFalse(failed.passed)


if __name__ == "__main__":
    unittest.main()
