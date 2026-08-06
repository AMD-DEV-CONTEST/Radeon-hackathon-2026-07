from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from prooflaunch_remix.comfyui_production import (
    ComfyGeneratedArtifact,
    ComfyGenerationReceipt,
    ComfyWorkflowContract,
    MediaKind,
    ModelRuntimeRef,
    WorkflowBinding,
)
from prooflaunch_remix.progressive_multimodal_production import (
    FinalistSelectionReceipt,
    MultimodalStageSpec,
    ProductionStageRole,
    ProgressiveMultimodalCoordinator,
    ProgressiveMultimodalPlan,
    ProgressiveProductionError,
)


class _StubClient:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.requests = []

    def execute(self, contract, _workflow_path, request) -> ComfyGenerationReceipt:
        self.requests.append(request)
        if self.fail_on_call == len(self.requests):
            raise RuntimeError("synthetic stage failure")
        root = Path(request.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        extension = ".mp4" if contract.media_kind == MediaKind.VIDEO else ".wav"
        artifact_path = root / f"asset{extension}"
        content = f"{request.request_id}:{len(self.requests)}".encode()
        artifact_path.write_bytes(content)
        artifact = ComfyGeneratedArtifact(
            artifact_id=f"stage-artifact-{len(self.requests)}",
            relative_path=artifact_path.name,
            media_type="video/mp4" if extension == ".mp4" else "audio/wav",
            content_sha256=hashlib.sha256(content).hexdigest(),
            bytes=len(content),
            source_node_id="9",
        )
        receipt = ComfyGenerationReceipt(
            request_id=request.request_id,
            workflow_id=contract.workflow_id,
            prompt_id=f"prompt-{len(self.requests)}",
            workflow_api_sha256=contract.workflow_api_sha256,
            bound_request_sha256="8" * 64,
            artifacts=(artifact,),
            model_refs=contract.models,
            rights_locator=request.rights_locator,
            output_root=str(root.resolve()),
            elapsed_seconds=0.1,
        )
        (root / "comfy-generation-receipt.json").write_text(
            json.dumps({"request_id": receipt.request_id, "artifacts": [asdict(artifact)]})
        )
        return receipt


class ProgressiveMultimodalProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.genome = "6" * 64
        self.pack_path = self.root / "production-pack.json"
        self.pack_path.write_text('{"pack":"evidence-bound"}')
        self.pack_sha = hashlib.sha256(self.pack_path.read_bytes()).hexdigest()
        self.batch_root = self.root / "candidate-batch"
        child_root = self.batch_root / "route-one" / "seed-11"
        child_root.mkdir(parents=True)
        self.selected_path = child_root / "keyframe.png"
        self.selected_path.write_bytes(b"selected-keyframe")
        self.selected_sha = hashlib.sha256(self.selected_path.read_bytes()).hexdigest()
        child_receipt = child_root / "comfy-generation-receipt.json"
        child_receipt.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {
                            "relative_path": "keyframe.png",
                            "content_sha256": self.selected_sha,
                        }
                    ]
                }
            )
        )
        self.candidate_id = "candidate-1234567890abcdef12345678"
        self.batch_id = "campaign-visual-exploration"
        (self.batch_root / "candidate-batch-receipt.json").write_text(
            json.dumps(
                {
                    "schema": "ProofLaunchGenerativeCandidateBatchReceiptV1",
                    "batch_id": self.batch_id,
                    "status": "generated_unreviewed",
                    "failure": None,
                    "winner_selected": False,
                    "blind_review_completed": False,
                    "candidates": [
                        {
                            "candidate_id": self.candidate_id,
                            "route_id": "route-one",
                            "seed": 11,
                            "generation_receipt_path": str(
                                child_receipt.relative_to(self.batch_root)
                            ),
                            "artifact_sha256s": [self.selected_sha],
                        }
                    ],
                }
            )
        )
        self.selection_path = self.root / "finalist-selection.json"
        self.blind_packet_path = self.root / "blind-pairs.jsonl"
        self.blind_packet_path.write_text(
            json.dumps({"left_blind_id": "left-01", "right_blind_id": "right-01"})
            + "\n"
        )
        self.selection = FinalistSelectionReceipt(
            batch_id=self.batch_id,
            reviewer_id="independent-creative-director-01",
            reviewed_at="2026-08-01T15:00:00Z",
            selected_candidate_id=self.candidate_id,
            selected_artifact_sha256=self.selected_sha,
            blind_packet_path=self.blind_packet_path.name,
            blind_packet_sha256=hashlib.sha256(self.blind_packet_path.read_bytes()).hexdigest(),
            review_method="independent_human_blind_review",
            candidate_role_revealed_before_decision=False,
            independence_attested=True,
            conflict_of_interest_disclosed=False,
            directly_publishable=True,
            major_rework_required=False,
            rationale=(
                "The selected frame has the strongest category break, legible proof hierarchy, "
                "and a production-ready visual system."
            ),
        )
        self.selection_path.write_text(json.dumps(asdict(self.selection)))
        self.workflow_paths = {}
        for role in ProductionStageRole:
            path = self.root / f"{role.value}-workflow.json"
            path.write_text("{}")
            self.workflow_paths[role] = path

    def tearDown(self) -> None:
        self.temp.cleanup()

    def contract(self, role: ProductionStageRole) -> ComfyWorkflowContract:
        media = MediaKind.VIDEO if role == ProductionStageRole.HERO_VIDEO else MediaKind.AUDIO
        bindings = [WorkflowBinding("prompt", "1", "text"), WorkflowBinding("seed", "2", "seed")]
        if role == ProductionStageRole.HERO_VIDEO:
            bindings.append(WorkflowBinding("reference_image", "3", "image"))
        path = self.workflow_paths[role]
        return ComfyWorkflowContract(
            workflow_id=f"{role.value}-production-v1",
            media_kind=media,
            workflow_source_url="https://github.com/Comfy-Org/workflow_templates",
            workflow_revision="1" * 40,
            workflow_api_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            bindings=tuple(bindings),
            output_node_ids=("9",),
            models=(
                ModelRuntimeRef(
                    project=f"model-{role.value}",
                    repository_url="https://github.com/example/model",
                    source_revision="2" * 40,
                    model_id=f"model/{role.value}",
                    model_revision="3" * 40,
                    source_license="Apache-2.0",
                    model_license="Apache-2.0",
                    license_locator="https://example.com/license",
                    commercial_use_allowed=True,
                    weight_sha256="4" * 64,
                ),
            ),
            executable_admission=True,
        )

    def stage(self, role: ProductionStageRole) -> MultimodalStageSpec:
        prompt = (
            f"Create the {role.value} for a premium proof-led campaign: preserve the selected "
            "visual language, build a distinctive narrative arc, and avoid generic stock-advertising codes."
        )
        values = {"prompt": prompt, "seed": 42}
        return MultimodalStageSpec(
            stage_id=f"stage-{role.value}",
            role=role,
            contract=self.contract(role),
            workflow_api_path=str(self.workflow_paths[role]),
            prompt_binding_name="prompt",
            creative_prompt=prompt,
            workflow_values=values,
            selected_visual_binding_name=(
                "reference_image" if role == ProductionStageRole.HERO_VIDEO else None
            ),
            identity_lock=(
                f"campaign-genome-sha256:{self.genome}",
                "preserve the approved visual identity and product geometry",
                "preserve the evidence hierarchy and campaign color logic",
            ),
            negative_constraints=(
                "reject generic stock-advertising composition",
                "reject identity drift or invented product interfaces",
                "reject synthetic testimonials and unsupported claims",
            ),
        )

    def plan(self, **changes) -> ProgressiveMultimodalPlan:
        values = {
            "campaign_id": "campaign-prooflaunch-aug3",
            "source_production_pack_path": str(self.pack_path),
            "source_production_pack_sha256": self.pack_sha,
            "campaign_genome_sha256": self.genome,
            "candidate_batch_root": str(self.batch_root),
            "finalist_selection_path": str(self.selection_path),
            "rights_locator": "project-owned://campaign-prooflaunch-aug3",
            "stages": tuple(self.stage(role) for role in ProductionStageRole),
        }
        values.update(changes)
        return ProgressiveMultimodalPlan(**values)

    def test_runs_selected_visual_through_video_music_and_speech(self) -> None:
        client = _StubClient()
        output = self.root / "multimodal"
        receipt = ProgressiveMultimodalCoordinator().run(
            client=client,
            plan=self.plan(),
            output_dir=output,
        )
        self.assertEqual(receipt.status, "generated_unreviewed")
        self.assertEqual(receipt.completed_stage_count, 3)
        self.assertEqual([row.role for row in receipt.stages], [role.value for role in ProductionStageRole])
        self.assertEqual(
            Path(client.requests[0].upload_paths["reference_image"]),
            self.selected_path.resolve(),
        )
        self.assertEqual(client.requests[1].upload_paths, {})
        self.assertFalse(receipt.master_mux_performed)
        self.assertFalse(receipt.human_effect_review_completed)
        self.assertFalse(receipt.four_a_effect_proven)
        self.assertTrue((output / "progressive-multimodal-receipt.json").is_file())

    def test_stage_failure_stops_remaining_gpu_work_and_seals_partial_receipt(self) -> None:
        client = _StubClient(fail_on_call=2)
        output = self.root / "partial"
        with self.assertRaisesRegex(ProgressiveProductionError, "synthetic stage failure"):
            ProgressiveMultimodalCoordinator().run(
                client=client,
                plan=self.plan(),
                output_dir=output,
            )
        self.assertEqual(len(client.requests), 2)
        partial = json.loads((output / "progressive-multimodal-receipt.json").read_text())
        self.assertEqual(partial["status"], "blocked_partial_production")
        self.assertEqual(partial["completed_stage_count"], 1)

    def test_deblinded_or_nonpublishable_selection_is_rejected(self) -> None:
        invalid = replace(
            self.selection,
            candidate_role_revealed_before_decision=True,
            directly_publishable=False,
        )
        self.selection_path.write_text(json.dumps(asdict(invalid)))
        client = _StubClient()
        with self.assertRaises(ProgressiveProductionError):
            ProgressiveMultimodalCoordinator().run(
                client=client,
                plan=self.plan(),
                output_dir=self.root / "invalid-selection",
            )
        self.assertEqual(client.requests, [])

    def test_selected_visual_content_drift_is_rejected(self) -> None:
        self.selected_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ProgressiveProductionError, "missing or drifted"):
            ProgressiveMultimodalCoordinator().run(
                client=_StubClient(),
                plan=self.plan(),
                output_dir=self.root / "drifted",
            )

    def test_blind_packet_drift_is_rejected_before_gpu_work(self) -> None:
        self.blind_packet_path.write_text("tampered\n")
        client = _StubClient()
        with self.assertRaisesRegex(ProgressiveProductionError, "blind packet is missing or drifted"):
            ProgressiveMultimodalCoordinator().run(
                client=client,
                plan=self.plan(),
                output_dir=self.root / "blind-packet-drift",
            )
        self.assertEqual(client.requests, [])

    def test_campaign_genome_must_be_bound_to_every_stage(self) -> None:
        stages = list(self.plan().stages)
        stages[1] = replace(stages[1], identity_lock=("brand lock one", "brand lock two", "brand lock three"))
        with self.assertRaisesRegex(ProgressiveProductionError, "campaign genome is absent"):
            self.plan(stages=tuple(stages)).validate()

    def test_plan_requires_video_music_speech_in_cost_order(self) -> None:
        stages = self.plan().stages
        with self.assertRaisesRegex(ProgressiveProductionError, "must run video, music, then speech"):
            self.plan(stages=(stages[1], stages[0], stages[2])).validate()


if __name__ == "__main__":
    unittest.main()
