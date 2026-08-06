from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from prooflaunch_remix.comfyui_production import (
    ComfyGeneratedArtifact,
    ComfyGenerationReceipt,
    ComfyWorkflowContract,
    MediaKind,
    ModelRuntimeRef,
    WorkflowBinding,
)
from prooflaunch_remix.generative_candidate_batch import (
    CandidateBatchError,
    CandidateBatchPlan,
    CreativeRoute,
    GenerativeCandidateBatchCoordinator,
)


class _StubGenerationClient:
    def __init__(self, *, fail_on_call: int | None = None, seal_receipt: bool = True) -> None:
        self.fail_on_call = fail_on_call
        self.seal_receipt = seal_receipt
        self.requests = []

    def execute(self, contract, _workflow_api_path, request) -> ComfyGenerationReceipt:
        self.requests.append(request)
        if self.fail_on_call == len(self.requests):
            raise RuntimeError("synthetic GPU failure")
        root = Path(request.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        artifact_path = root / "artifact.png"
        payload = f"{request.request_id}:{request.values['seed']}".encode()
        artifact_path.write_bytes(payload)
        artifact_hash = hashlib.sha256(payload).hexdigest()
        receipt = ComfyGenerationReceipt(
            request_id=request.request_id,
            workflow_id=contract.workflow_id,
            prompt_id=f"prompt-{len(self.requests)}",
            workflow_api_sha256=contract.workflow_api_sha256,
            bound_request_sha256="9" * 64,
            artifacts=(
                ComfyGeneratedArtifact(
                    artifact_id=f"artifact-{len(self.requests)}",
                    relative_path="artifact.png",
                    media_type="image/png",
                    content_sha256=artifact_hash,
                    bytes=len(payload),
                    source_node_id="9",
                ),
            ),
            model_refs=contract.models,
            rights_locator=request.rights_locator,
            output_root=str(root.resolve()),
            elapsed_seconds=0.1,
        )
        if self.seal_receipt:
            (root / "comfy-generation-receipt.json").write_text(
                json.dumps({"request_id": request.request_id})
            )
        return receipt


class GenerativeCandidateBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workflow_path = self.root / "workflow-api.json"
        self.workflow_path.write_text("{}")
        self.contract = ComfyWorkflowContract(
            workflow_id="qwen-image-production-v1",
            media_kind=MediaKind.IMAGE,
            workflow_source_url="https://github.com/Comfy-Org/workflow_templates",
            workflow_revision="1" * 40,
            workflow_api_sha256=hashlib.sha256(
                self.workflow_path.read_bytes()
            ).hexdigest(),
            bindings=(
                WorkflowBinding("prompt", "1", "text"),
                WorkflowBinding("negative_prompt", "2", "text"),
                WorkflowBinding("seed", "3", "seed"),
                WorkflowBinding("width", "4", "width"),
                WorkflowBinding("height", "4", "height"),
            ),
            output_node_ids=("9",),
            models=(
                ModelRuntimeRef(
                    project="Qwen-Image",
                    repository_url="https://github.com/QwenLM/Qwen-Image",
                    source_revision="2" * 40,
                    model_id="Qwen/Qwen-Image-2.0",
                    model_revision="3" * 40,
                    source_license="Apache-2.0",
                    model_license="Apache-2.0",
                    license_locator="https://huggingface.co/Qwen/Qwen-Image-2.0/blob/main/LICENSE",
                    commercial_use_allowed=True,
                    weight_sha256="4" * 64,
                ),
            ),
            executable_admission=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def route(route_id: str, mechanism: str, tension: str, seeds=(11, 12)) -> CreativeRoute:
        return CreativeRoute(
            route_id=route_id,
            strategy_mechanism=mechanism,
            cultural_tension=tension,
            participation_mechanism=f"participate through {route_id}",
            proof_role=f"product proof for {route_id}",
            channel_native_behavior=f"native remix behavior for {route_id}",
            expected_emotion=f"earned confidence from {route_id}",
            falsifier=f"reject if audience ignores {route_id}",
            workflow_values={"prompt": f"cinematic campaign route {route_id}"},
            seeds=tuple(seeds),
        )

    def plan(self, **changes) -> CandidateBatchPlan:
        values = {
            "batch_id": "b2b-launch-candidate-batch",
            "baseline_id": "incumbent-production-baseline",
            "baseline_content_sha256": "a" * 64,
            "seed_binding_name": "seed",
            "base_workflow_values": {
                "negative_prompt": "generic stock advertising",
                "width": 1920,
                "height": 1080,
            },
            "upload_paths": {},
            "rights_locator": "project-owned://b2b-launch",
            "routes": (
                self.route("proof-theatre-route", "proof theatre mechanism", "trust deficit tension"),
                self.route("ritual-remix-route", "participation ritual mechanism", "passive audience tension"),
                self.route("status-reversal-route", "status reversal mechanism", "category sameness tension"),
            ),
            "maximum_generations": 12,
        }
        values.update(changes)
        return CandidateBatchPlan(**values)

    def test_runs_three_routes_two_seeds_without_claiming_a_winner(self) -> None:
        client = _StubGenerationClient()
        output = self.root / "batch"
        receipt = GenerativeCandidateBatchCoordinator().run(
            client=client,
            contract=self.contract,
            workflow_api_path=self.workflow_path,
            plan=self.plan(),
            output_dir=output,
        )
        self.assertEqual(receipt.status, "generated_unreviewed")
        self.assertEqual(receipt.candidate_count, 6)
        self.assertEqual(receipt.route_count, 3)
        self.assertFalse(receipt.winner_selected)
        self.assertFalse(receipt.blind_review_completed)
        self.assertFalse(receipt.external_publish_executed)
        self.assertEqual(len(client.requests), 6)
        self.assertTrue((output / "candidate-batch-receipt.json").is_file())
        self.assertEqual({request.values["seed"] for request in client.requests}, {11, 12})

    def test_duplicate_route_mechanism_is_rejected_before_generation(self) -> None:
        routes = list(self.plan().routes)
        routes[1] = replace(routes[1], strategy_mechanism=routes[0].strategy_mechanism)
        client = _StubGenerationClient()
        with self.assertRaisesRegex(CandidateBatchError, "differ in mechanism"):
            GenerativeCandidateBatchCoordinator().run(
                client=client,
                contract=self.contract,
                workflow_api_path=self.workflow_path,
                plan=self.plan(routes=tuple(routes)),
                output_dir=self.root / "duplicate",
            )
        self.assertEqual(client.requests, [])

    def test_too_few_seeds_is_rejected_before_generation(self) -> None:
        routes = tuple(replace(route, seeds=(11,)) for route in self.plan().routes)
        with self.assertRaisesRegex(CandidateBatchError, "two to four unique seeds"):
            self.plan(routes=routes).validate(self.contract)

    def test_each_route_must_cover_every_declared_binding(self) -> None:
        routes = list(self.plan().routes)
        routes[2] = replace(routes[2], workflow_values={"style": "cinematic"})
        with self.assertRaisesRegex(CandidateBatchError, "undeclared workflow bindings"):
            self.plan(routes=tuple(routes)).validate(self.contract)
        missing_contract = replace(
            self.contract,
            bindings=self.contract.bindings + (WorkflowBinding("steps", "5", "steps"),),
        )
        with self.assertRaisesRegex(CandidateBatchError, "required workflow bindings missing"):
            self.plan().validate(missing_contract)

    def test_first_generation_failure_stops_cost_and_seals_partial_receipt(self) -> None:
        client = _StubGenerationClient(fail_on_call=3)
        output = self.root / "partial"
        with self.assertRaisesRegex(CandidateBatchError, "synthetic GPU failure"):
            GenerativeCandidateBatchCoordinator().run(
                client=client,
                contract=self.contract,
                workflow_api_path=self.workflow_path,
                plan=self.plan(),
                output_dir=output,
            )
        self.assertEqual(len(client.requests), 3)
        partial = json.loads((output / "candidate-batch-receipt.json").read_text())
        self.assertEqual(partial["status"], "blocked_partial_generation")
        self.assertEqual(partial["candidate_count"], 2)
        self.assertFalse(partial["winner_selected"])

    def test_missing_child_receipt_fails_closed_and_seals_batch_failure(self) -> None:
        client = _StubGenerationClient(seal_receipt=False)
        output = self.root / "unsealed"
        with self.assertRaisesRegex(CandidateBatchError, "was not sealed"):
            GenerativeCandidateBatchCoordinator().run(
                client=client,
                contract=self.contract,
                workflow_api_path=self.workflow_path,
                plan=self.plan(),
                output_dir=output,
            )
        failure = json.loads((output / "candidate-batch-receipt.json").read_text())
        self.assertEqual(failure["status"], "blocked_partial_generation")
        self.assertEqual(failure["candidate_count"], 0)

    def test_nonempty_batch_output_is_rejected(self) -> None:
        output = self.root / "nonempty"
        output.mkdir()
        (output / "existing.txt").write_text("do not overwrite")
        with self.assertRaisesRegex(CandidateBatchError, "must be empty"):
            GenerativeCandidateBatchCoordinator().run(
                client=_StubGenerationClient(),
                contract=self.contract,
                workflow_api_path=self.workflow_path,
                plan=self.plan(),
                output_dir=output,
            )


if __name__ == "__main__":
    unittest.main()
