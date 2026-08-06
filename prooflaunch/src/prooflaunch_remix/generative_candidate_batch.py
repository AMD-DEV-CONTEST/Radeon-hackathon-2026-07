from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from .comfyui_production import (
    ComfyGenerationRequest,
    ComfyGenerationReceipt,
    ComfyUIProductionClient,
    ComfyWorkflowContract,
)
from .files import atomic_write_text


class CandidateBatchError(ValueError):
    """Raised when a generative candidate batch would weaken the effect protocol."""


@dataclass(frozen=True)
class CreativeRoute:
    route_id: str
    strategy_mechanism: str
    cultural_tension: str
    participation_mechanism: str
    proof_role: str
    channel_native_behavior: str
    expected_emotion: str
    falsifier: str
    workflow_values: Mapping[str, object]
    seeds: tuple[int, ...]

    def validate(self) -> None:
        for name in (
            "route_id",
            "strategy_mechanism",
            "cultural_tension",
            "participation_mechanism",
            "proof_role",
            "channel_native_behavior",
            "expected_emotion",
            "falsifier",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value.strip()) < 8:
                raise CandidateBatchError(f"{self.route_id or 'route'}: {name} is too shallow")
        if not self.workflow_values:
            raise CandidateBatchError(f"{self.route_id}: workflow_values are required")
        if not 2 <= len(self.seeds) <= 4 or len(set(self.seeds)) != len(self.seeds):
            raise CandidateBatchError(f"{self.route_id}: two to four unique seeds are required")
        if any(type(seed) is not int or not 0 <= seed < 2**63 for seed in self.seeds):
            raise CandidateBatchError(f"{self.route_id}: seed values are invalid")


@dataclass(frozen=True)
class CandidateBatchPlan:
    batch_id: str
    baseline_id: str
    baseline_content_sha256: str
    seed_binding_name: str
    base_workflow_values: Mapping[str, object]
    upload_paths: Mapping[str, str]
    rights_locator: str
    routes: tuple[CreativeRoute, ...]
    maximum_generations: int = 12

    def validate(self, contract: ComfyWorkflowContract) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.batch_id, self.baseline_id, self.seed_binding_name, self.rights_locator)
        ):
            raise CandidateBatchError("batch, baseline, seed binding, and rights are required")
        if len(self.baseline_content_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.baseline_content_sha256
        ):
            raise CandidateBatchError("baseline_content_sha256 is invalid")
        if not 3 <= len(self.routes) <= 6:
            raise CandidateBatchError("three to six distinct creative routes are required")
        for route in self.routes:
            route.validate()
        route_ids = [route.route_id for route in self.routes]
        mechanisms = [route.strategy_mechanism.casefold().strip() for route in self.routes]
        tensions = [route.cultural_tension.casefold().strip() for route in self.routes]
        if len(route_ids) != len(set(route_ids)):
            raise CandidateBatchError("creative route IDs must be unique")
        if len(mechanisms) != len(set(mechanisms)) or len(tensions) != len(set(tensions)):
            raise CandidateBatchError("routes must differ in mechanism and cultural tension")
        generation_count = sum(len(route.seeds) for route in self.routes)
        if generation_count > self.maximum_generations or not 6 <= generation_count <= 18:
            raise CandidateBatchError("candidate generation count is outside the bounded search budget")
        logical_names = {binding.logical_name for binding in contract.bindings}
        fixed_supplied = (
            set(self.base_workflow_values) | set(self.upload_paths) | {self.seed_binding_name}
        )
        for route in self.routes:
            supplied = fixed_supplied | set(route.workflow_values)
            unknown = supplied - logical_names
            missing = logical_names - supplied
            if unknown:
                raise CandidateBatchError(
                    f"{route.route_id}: undeclared workflow bindings: {sorted(unknown)}"
                )
            if missing:
                raise CandidateBatchError(
                    f"{route.route_id}: required workflow bindings missing: {sorted(missing)}"
                )


@dataclass(frozen=True)
class GeneratedCandidate:
    candidate_id: str
    route_id: str
    seed: int
    generation_receipt_path: str
    artifact_sha256s: tuple[str, ...]


@dataclass(frozen=True)
class CandidateBatchReceipt:
    batch_id: str
    workflow_id: str
    status: str
    candidate_count: int
    route_count: int
    candidates: tuple[GeneratedCandidate, ...]
    baseline_id: str
    baseline_content_sha256: str
    winner_selected: bool
    blind_review_completed: bool
    external_publish_executed: bool
    failure: str | None
    truth_boundary: str = (
        "Generated candidates are unreviewed alternatives. Batch completion is not a "
        "winner decision, 4A preference, publication, business lift, or Radeon proof."
    )
    schema: str = "ProofLaunchGenerativeCandidateBatchReceiptV1"


class GenerativeCandidateBatchCoordinator:
    """Run bounded concept diversity through ComfyUI without auto-selecting a winner."""

    def run(
        self,
        *,
        client: ComfyUIProductionClient,
        contract: ComfyWorkflowContract,
        workflow_api_path: str | Path,
        plan: CandidateBatchPlan,
        output_dir: str | Path,
    ) -> CandidateBatchReceipt:
        contract.validate()
        plan.validate(contract)
        root = Path(output_dir).resolve()
        if root.exists() and any(root.iterdir()):
            raise CandidateBatchError("candidate batch output directory must be empty")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        candidates: list[GeneratedCandidate] = []
        failure: str | None = None
        for route in plan.routes:
            for seed in route.seeds:
                values = dict(plan.base_workflow_values)
                values.update(route.workflow_values)
                values[plan.seed_binding_name] = seed
                generation_root = root / route.route_id / f"seed-{seed}"
                try:
                    receipt = client.execute(
                        contract,
                        workflow_api_path,
                        ComfyGenerationRequest(
                            request_id=f"{plan.batch_id}-{route.route_id}-{seed}",
                            values=values,
                            upload_paths=plan.upload_paths,
                            output_dir=str(generation_root),
                            rights_locator=plan.rights_locator,
                        ),
                    )
                    candidates.append(self._candidate(plan, route, seed, receipt, root))
                except Exception as error:
                    failure = f"{route.route_id}/seed-{seed}: {type(error).__name__}: {error}"
                    break
            if failure is not None:
                break

        status = "generated_unreviewed" if failure is None else "blocked_partial_generation"
        receipt = CandidateBatchReceipt(
            batch_id=plan.batch_id,
            workflow_id=contract.workflow_id,
            status=status,
            candidate_count=len(candidates),
            route_count=len({candidate.route_id for candidate in candidates}),
            candidates=tuple(candidates),
            baseline_id=plan.baseline_id,
            baseline_content_sha256=plan.baseline_content_sha256,
            winner_selected=False,
            blind_review_completed=False,
            external_publish_executed=False,
            failure=failure,
        )
        manifest_path = root / "candidate-batch-receipt.json"
        atomic_write_text(
            manifest_path,
            json.dumps(asdict(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        manifest_path.chmod(0o600)
        if failure is not None:
            raise CandidateBatchError(failure)
        return receipt

    @staticmethod
    def _candidate(
        plan: CandidateBatchPlan,
        route: CreativeRoute,
        seed: int,
        receipt: ComfyGenerationReceipt,
        root: Path,
    ) -> GeneratedCandidate:
        hashes = tuple(artifact.content_sha256 for artifact in receipt.artifacts)
        basis = json.dumps(
            {
                "batch_id": plan.batch_id,
                "route_id": route.route_id,
                "seed": seed,
                "artifact_sha256s": hashes,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        receipt_path = Path(receipt.output_root) / "comfy-generation-receipt.json"
        if not receipt_path.is_file():
            raise CandidateBatchError(
                f"{route.route_id}/seed-{seed}: generation receipt was not sealed"
            )
        try:
            relative_receipt_path = receipt_path.resolve().relative_to(root)
        except ValueError as error:
            raise CandidateBatchError(
                f"{route.route_id}/seed-{seed}: generation receipt escaped the batch root"
            ) from error
        return GeneratedCandidate(
            candidate_id=f"candidate-{hashlib.sha256(basis.encode()).hexdigest()[:24]}",
            route_id=route.route_id,
            seed=seed,
            generation_receipt_path=str(relative_receipt_path),
            artifact_sha256s=hashes,
        )
