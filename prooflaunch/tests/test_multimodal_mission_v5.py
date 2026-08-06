from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.cross_media import (
    CrossMediaReleaseGate,
    DeliverableClaim,
)
from prooflaunch_remix.mission import (
    DeliverableKind,
    DeliverableSpec,
    DurableMissionExecutor,
    EvidenceObservation,
    MissionCheckpointStore,
    MissionError,
    MissionPlan,
    MissionStep,
    MultimodalMissionPlanner,
    StepStatus,
)
from prooflaunch_remix.multimodal_ingest import (
    IngestError,
    MediaArtifact,
    MediaKind,
    MediaSource,
    MultimodalIngestor,
    RightsStatus,
)
from prooflaunch_remix.multimodal_models import parse_grounded_understanding
from prooflaunch_remix.video_generation import IdentityLockedVideoComposer


class MultimodalIngestTests(unittest.TestCase):
    def ingest_bytes(
        self, root: Path, name: str, data: bytes, kind: MediaKind
    ) -> MediaArtifact:
        path = root / name
        path.write_bytes(data)
        return MultimodalIngestor().ingest(
            (
                MediaSource(
                    str(path),
                    "product",
                    rights=RightsStatus.OWNED,
                    declared_kind=kind,
                ),
            )
        )[0]

    def test_detects_png_by_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            item = self.ingest_bytes(
                Path(directory), "wrong.bin", b"\x89PNG\r\n\x1a\npayload", MediaKind.IMAGE
            )
            self.assertEqual(item.mime_type, "image/png")

    def test_detects_mp4_by_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            item = self.ingest_bytes(
                Path(directory), "clip.bin", b"\0\0\0\x18ftypisompayload", MediaKind.VIDEO
            )
            self.assertEqual(item.kind, MediaKind.VIDEO)

    def test_detects_wave_by_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            item = self.ingest_bytes(
                Path(directory), "voice.bin", b"RIFF\0\0\0\0WAVEpayload", MediaKind.AUDIO
            )
            self.assertEqual(item.mime_type, "audio/wav")

    def test_detects_pdf_by_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            item = self.ingest_bytes(
                Path(directory), "brief.bin", b"%PDF-1.7\npayload", MediaKind.PDF
            )
            self.assertEqual(item.kind, MediaKind.PDF)

    def test_detects_utf8_text_from_supported_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            item = self.ingest_bytes(
                Path(directory), "brief.md", "真实依据".encode(), MediaKind.TEXT
            )
            self.assertEqual(item.byte_size, 12)

    def test_declared_kind_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.mp4"
            path.write_bytes(b"%PDF-1.7\n")
            with self.assertRaises(IngestError):
                MultimodalIngestor().ingest(
                    (MediaSource(str(path), "brief", declared_kind=MediaKind.VIDEO),)
                )

    def test_duplicate_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one.png"
            second = root / "two.png"
            first.write_bytes(b"\x89PNG\r\n\x1a\nsame")
            second.write_bytes(first.read_bytes())
            with self.assertRaises(IngestError):
                MultimodalIngestor().ingest(
                    (
                        MediaSource(str(first), "product"),
                        MediaSource(str(second), "reference"),
                    )
                )

    def test_unknown_binary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.bin"
            path.write_bytes(b"\x00\x01\x02\x03")
            with self.assertRaises(IngestError):
                MultimodalIngestor().ingest((MediaSource(str(path), "unknown"),))

    def test_artifact_id_and_hash_are_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = b"%PDF-1.7\nstable"
            item = self.ingest_bytes(Path(directory), "brief.pdf", data, MediaKind.PDF)
            self.assertIn(hashlib.sha256(data).hexdigest()[:8], item.id)
            self.assertEqual(item.sha256, hashlib.sha256(data).hexdigest())


class MissionPlannerTests(unittest.TestCase):
    @staticmethod
    def artifact(kind: MediaKind, item_id: str = "MED-001") -> MediaArtifact:
        return MediaArtifact(
            id=item_id,
            path="/tmp/input",
            role="product",
            kind=kind,
            mime_type="application/octet-stream",
            sha256="a" * 64,
            byte_size=1,
            rights=RightsStatus.OWNED,
        )

    def test_image_mission_routes_qwen_gemma_sdxl_and_siglip(self) -> None:
        plan = MultimodalMissionPlanner().build(
            mission_id="image",
            artifacts=(self.artifact(MediaKind.IMAGE),),
            deliverables=(
                DeliverableSpec(DeliverableKind.SOCIAL_IMAGE, "9:16"),
            ),
            available_vram_gb=24,
        )
        roles = [phase.role for phase in plan.model_phases]
        self.assertEqual(
            roles,
            [
                "vision_language_audit",
                "affect_critic",
                "image_generation",
                "image_text_scoring",
            ],
        )
        self.assertTrue(all(phase.unload_after for phase in plan.model_phases))

    def test_video_input_and_output_routes_qwen_whisper_and_ltx(self) -> None:
        plan = MultimodalMissionPlanner().build(
            mission_id="video",
            artifacts=(self.artifact(MediaKind.VIDEO),),
            deliverables=(
                DeliverableSpec(DeliverableKind.SHORT_VIDEO, "9:16", 8),
            ),
            available_vram_gb=24,
        )
        roles = {phase.role for phase in plan.model_phases}
        self.assertTrue(
            {
                "vision_language_audit",
                "audio_transcription",
                "affect_critic",
                "video_generation",
                "image_text_scoring",
            }.issubset(roles)
        )

    def test_video_duration_is_bounded(self) -> None:
        with self.assertRaises(MissionError):
            DeliverableSpec(DeliverableKind.SHORT_VIDEO, "9:16", 60)

    def test_non_video_cannot_have_duration(self) -> None:
        with self.assertRaises(MissionError):
            DeliverableSpec(DeliverableKind.SOCIAL_IMAGE, "1:1", 5)

    def test_plan_terminates_at_human_release_boundary(self) -> None:
        plan = MultimodalMissionPlanner().build(
            mission_id="approval",
            artifacts=(self.artifact(MediaKind.IMAGE),),
            deliverables=(DeliverableSpec(DeliverableKind.CAPTION_SET, "n/a"),),
            available_vram_gb=24,
        )
        self.assertEqual(plan.steps[-1].kind, "human_release")
        self.assertTrue(plan.steps[-1].human_approval_required)

    def test_plan_hash_is_deterministic(self) -> None:
        planner = MultimodalMissionPlanner()
        arguments = dict(
            mission_id="stable",
            artifacts=(self.artifact(MediaKind.IMAGE),),
            deliverables=(DeliverableSpec(DeliverableKind.CAPTION_SET, "n/a"),),
            available_vram_gb=24,
        )
        self.assertEqual(
            planner.build(**arguments).graph_hash,
            planner.build(**arguments).graph_hash,
        )

    def test_forward_dependency_is_rejected(self) -> None:
        with self.assertRaises(MissionError):
            MissionPlan(
                mission_id="bad",
                input_ids=("MED",),
                deliverables=(DeliverableSpec(DeliverableKind.CAPTION_SET, "n/a"),),
                steps=(
                    MissionStep("S01", "ingest", ("S02",)),
                    MissionStep("S02", "human_release", ("S01",)),
                ),
                model_phases=(),
            )

    def test_repair_budget_above_two_is_rejected(self) -> None:
        with self.assertRaises(MissionError):
            MissionPlan(
                mission_id="bad-budget",
                input_ids=("MED",),
                deliverables=(DeliverableSpec(DeliverableKind.CAPTION_SET, "n/a"),),
                steps=(MissionStep("S01", "human_release", ()),),
                model_phases=(),
                max_repairs=3,
            )


class GroundingAndReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.artifact = MissionPlannerTests.artifact(MediaKind.IMAGE)
        self.observation = EvidenceObservation(
            id="OBS-001",
            source_artifact_id=self.artifact.id,
            claim="Battery life is up to 18 hours.",
            locator="bbox:0.1,0.2,0.4,0.6",
            confidence=0.91,
            model_ref="Qwen/Qwen3-VL-2B-Instruct",
        )

    def test_parser_accepts_fenced_grounded_json(self) -> None:
        result = parse_grounded_understanding(
            "```json\n"
            + json.dumps(
                {
                    "summary": "Product evidence",
                    "observations": [
                        {
                            "claim": "Blue enclosure",
                            "source_id": self.artifact.id,
                            "locator": "bbox:1,2,3,4",
                            "confidence": 0.8,
                        }
                    ],
                }
            )
            + "\n```",
            allowed_source_ids={self.artifact.id},
            model_ref="local-qwen",
        )
        self.assertEqual(result.observations[0].source_artifact_id, self.artifact.id)

    def test_parser_rejects_unknown_source_id(self) -> None:
        payload = json.dumps(
            {
                "summary": "bad",
                "observations": [
                    {
                        "claim": "invented",
                        "source_id": "MED-999",
                        "locator": "frame:3",
                        "confidence": 0.5,
                    }
                ],
            }
        )
        with self.assertRaises(MissionError):
            parse_grounded_understanding(
                payload,
                allowed_source_ids={self.artifact.id},
                model_ref="local-qwen",
            )

    def test_observation_rejects_empty_locator(self) -> None:
        with self.assertRaises(MissionError):
            EvidenceObservation(
                "OBS", self.artifact.id, "claim", "", 0.5, "model"
            )

    def test_release_gate_passes_grounded_owned_claim(self) -> None:
        findings = CrossMediaReleaseGate().audit(
            artifacts=(self.artifact,),
            observations=(self.observation,),
            claims=(
                DeliverableClaim(
                    "DEL-001",
                    self.observation.claim,
                    (self.observation.id,),
                ),
            ),
        )
        self.assertEqual(findings, ())

    def test_release_gate_blocks_unknown_rights(self) -> None:
        unsafe = MediaArtifact(
            **{
                **self.artifact.__dict__,
                "rights": RightsStatus.UNKNOWN,
            }
        )
        findings = CrossMediaReleaseGate().audit(
            artifacts=(unsafe,),
            observations=(self.observation,),
            claims=(),
        )
        self.assertTrue(any(item.category == "rights" for item in findings))

    def test_release_gate_blocks_missing_observation(self) -> None:
        findings = CrossMediaReleaseGate().audit(
            artifacts=(self.artifact,),
            observations=(self.observation,),
            claims=(DeliverableClaim("DEL-001", "claim", ("OBS-404",)),),
        )
        self.assertTrue(any(item.category == "ungrounded_claim" for item in findings))
        self.assertTrue(all(item.blocking for item in findings))


class DurableMissionExecutorTests(unittest.TestCase):
    def build_plan(self) -> MissionPlan:
        return MultimodalMissionPlanner().build(
            mission_id="resume",
            artifacts=(MissionPlannerTests.artifact(MediaKind.IMAGE),),
            deliverables=(DeliverableSpec(DeliverableKind.CAPTION_SET, "n/a"),),
            available_vram_gb=24,
        )

    @staticmethod
    def handlers() -> dict:
        kinds = {
            "ingest",
            "understand",
            "ground_evidence",
            "plan_creative",
            "create_deliverables",
            "cross_media_audit",
            "bounded_repair",
            "human_release",
        }
        return {
            kind: (lambda step, outputs: {"step": step.id, "seen": len(outputs)})
            for kind in kinds
        }

    def test_executor_stops_at_human_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MissionCheckpointStore(Path(directory) / "checkpoint.json")
            checkpoint = DurableMissionExecutor(store).run(
                self.build_plan(), self.handlers()
            )
            self.assertEqual(checkpoint.statuses["S08"], StepStatus.BLOCKED)
            self.assertEqual(checkpoint.attempts["S08"], 0)

    def test_executor_resumes_without_repeating_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MissionCheckpointStore(Path(directory) / "checkpoint.json")
            executor = DurableMissionExecutor(store)
            first = executor.run(self.build_plan(), self.handlers())
            attempts = dict(first.attempts)
            second = executor.run(
                self.build_plan(), self.handlers(), human_approved=True
            )
            self.assertEqual(second.statuses["S08"], StepStatus.SUCCEEDED)
            self.assertEqual(second.attempts["S01"], attempts["S01"])

    def test_handler_exception_is_fail_closed_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MissionCheckpointStore(Path(directory) / "checkpoint.json")
            handlers = self.handlers()

            def fail(step, outputs):
                del step, outputs
                raise RuntimeError("adapter offline")

            handlers["understand"] = fail
            checkpoint = DurableMissionExecutor(store).run(
                self.build_plan(), handlers
            )
            self.assertEqual(checkpoint.statuses["S02"], StepStatus.FAILED)
            self.assertEqual(
                checkpoint.outputs["S02"]["error_type"], "RuntimeError"
            )

    def test_changed_graph_cannot_resume_old_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MissionCheckpointStore(Path(directory) / "checkpoint.json")
            executor = DurableMissionExecutor(store)
            executor.run(self.build_plan(), self.handlers())
            changed = MultimodalMissionPlanner().build(
                mission_id="resume",
                artifacts=(MissionPlannerTests.artifact(MediaKind.IMAGE),),
                deliverables=(
                    DeliverableSpec(DeliverableKind.SOCIAL_IMAGE, "1:1"),
                ),
                available_vram_gb=24,
            )
            with self.assertRaises(MissionError):
                executor.run(changed, self.handlers())

    def test_trace_is_hash_chained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MissionCheckpointStore(Path(directory) / "checkpoint.json")
            checkpoint = DurableMissionExecutor(store).run(
                self.build_plan(), self.handlers()
            )
            previous = "0" * 64
            for event in checkpoint.trace:
                self.assertEqual(event["previous_hash"], previous)
                copy = {key: value for key, value in event.items() if key != "event_hash"}
                expected = hashlib.sha256(
                    json.dumps(
                        copy, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                self.assertEqual(event["event_hash"], expected)
                previous = event["event_hash"]


class VideoIdentityLockTests(unittest.TestCase):
    def test_exact_product_pixels_survive_every_frame(self) -> None:
        from PIL import Image

        backgrounds = (
            Image.new("RGB", (100, 200), (20, 30, 40)),
            Image.new("RGB", (100, 200), (80, 90, 100)),
        )
        product = Image.new("RGBA", (20, 30), (240, 20, 40, 255))
        frames, report = IdentityLockedVideoComposer().compose(
            generated_frames=backgrounds,
            product_layer=product,
            normalized_box=(0.2, 0.3, 0.6, 0.6),
        )
        self.assertTrue(report.passed)
        self.assertEqual(len(set(report.frame_product_hashes)), 1)
        self.assertEqual(len(frames), 2)

    def test_transparent_product_layer_uses_only_opaque_identity_pixels(self) -> None:
        from PIL import Image, ImageDraw

        product = Image.new("RGBA", (20, 30), (0, 0, 0, 0))
        ImageDraw.Draw(product).rectangle((4, 5, 15, 25), fill=(20, 80, 220, 255))
        _, report = IdentityLockedVideoComposer().compose(
            generated_frames=(
                Image.new("RGB", (100, 100), "black"),
                Image.new("RGB", (100, 100), "white"),
            ),
            product_layer=product,
            normalized_box=(0.2, 0.2, 0.6, 0.8),
        )
        self.assertTrue(report.passed)

    def test_empty_video_fails_closed(self) -> None:
        from PIL import Image

        with self.assertRaises(MissionError):
            IdentityLockedVideoComposer().compose(
                generated_frames=(),
                product_layer=Image.new("RGBA", (10, 10)),
                normalized_box=(0.1, 0.1, 0.5, 0.5),
            )

    def test_inconsistent_frame_sizes_fail_closed(self) -> None:
        from PIL import Image

        with self.assertRaises(MissionError):
            IdentityLockedVideoComposer().compose(
                generated_frames=(
                    Image.new("RGB", (100, 100)),
                    Image.new("RGB", (120, 100)),
                ),
                product_layer=Image.new("RGBA", (10, 10)),
                normalized_box=(0.1, 0.1, 0.5, 0.5),
            )

    def test_product_box_must_be_inside_canvas(self) -> None:
        from PIL import Image

        with self.assertRaises(MissionError):
            IdentityLockedVideoComposer().compose(
                generated_frames=(Image.new("RGB", (100, 100)),),
                product_layer=Image.new("RGBA", (10, 10)),
                normalized_box=(-0.1, 0.1, 0.5, 0.5),
            )


if __name__ == "__main__":
    unittest.main()
