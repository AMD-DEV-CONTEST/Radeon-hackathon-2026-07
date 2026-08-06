from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Mapping

from .comfyui_production import (
    ComfyGenerationRequest,
    ComfyGenerationReceipt,
    ComfyUIProductionClient,
    ComfyWorkflowContract,
    MediaKind,
)
from .files import atomic_write_text


_HEX = frozenset("0123456789abcdef")


class ProgressiveProductionError(ValueError):
    """Raised when a progressive multimodal production cannot be admitted."""


def _sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise ProgressiveProductionError(f"{field_name} must be a lowercase SHA-256")


def _required(value: str, field_name: str, *, minimum: int = 1) -> None:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ProgressiveProductionError(f"{field_name} is required")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _parse_timestamp(value: str, field_name: str) -> None:
    _required(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProgressiveProductionError(f"{field_name} is invalid") from error
    if parsed.tzinfo is None:
        raise ProgressiveProductionError(f"{field_name} must include a timezone")


@dataclass(frozen=True)
class FinalistSelectionReceipt:
    batch_id: str
    reviewer_id: str
    reviewed_at: str
    selected_candidate_id: str
    selected_artifact_sha256: str
    blind_packet_path: str
    blind_packet_sha256: str
    review_method: str
    candidate_role_revealed_before_decision: bool
    independence_attested: bool
    conflict_of_interest_disclosed: bool
    directly_publishable: bool
    major_rework_required: bool
    rationale: str
    schema: str = "ProofLaunchFinalistSelectionReceiptV1"

    def validate(self) -> None:
        for field_name in ("batch_id", "reviewer_id", "selected_candidate_id"):
            _required(getattr(self, field_name), field_name, minimum=8)
        _parse_timestamp(self.reviewed_at, "reviewed_at")
        _sha256(self.selected_artifact_sha256, "selected_artifact_sha256")
        _sha256(self.blind_packet_sha256, "blind_packet_sha256")
        _required(self.blind_packet_path, "blind_packet_path")
        if self.review_method != "independent_human_blind_review":
            raise ProgressiveProductionError("finalist selection must use human blind review")
        if self.candidate_role_revealed_before_decision:
            raise ProgressiveProductionError("finalist decision was deblinded too early")
        if not self.independence_attested or self.conflict_of_interest_disclosed:
            raise ProgressiveProductionError("finalist reviewer is not independent")
        if not self.directly_publishable or self.major_rework_required:
            raise ProgressiveProductionError("selected visual did not clear the craft gate")
        _required(self.rationale, "rationale", minimum=32)

    @classmethod
    def load(cls, path: str | Path) -> "FinalistSelectionReceipt":
        source = Path(path).resolve()
        if not source.is_file():
            raise ProgressiveProductionError("finalist selection receipt is missing")
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ProgressiveProductionError("finalist selection receipt is invalid JSON") from error
        if not isinstance(payload, dict) or payload.get("schema") != cls.schema:
            raise ProgressiveProductionError("finalist selection receipt schema is unsupported")
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(payload) != expected:
            raise ProgressiveProductionError("finalist selection receipt fields do not match")
        receipt = cls(**payload)
        receipt.validate()
        return receipt


class ProductionStageRole(str, Enum):
    HERO_VIDEO = "hero_video"
    MUSIC = "music"
    SPEECH = "speech"


_EXPECTED_MEDIA = {
    ProductionStageRole.HERO_VIDEO: MediaKind.VIDEO,
    ProductionStageRole.MUSIC: MediaKind.AUDIO,
    ProductionStageRole.SPEECH: MediaKind.AUDIO,
}


@dataclass(frozen=True)
class MultimodalStageSpec:
    stage_id: str
    role: ProductionStageRole
    contract: ComfyWorkflowContract
    workflow_api_path: str
    prompt_binding_name: str
    creative_prompt: str
    workflow_values: Mapping[str, object]
    selected_visual_binding_name: str | None
    identity_lock: tuple[str, ...]
    negative_constraints: tuple[str, ...]

    def validate(self, campaign_genome_sha256: str) -> None:
        _required(self.stage_id, "stage_id", minimum=8)
        if not isinstance(self.role, ProductionStageRole):
            raise ProgressiveProductionError("stage role is invalid")
        self.contract.validate()
        if not self.contract.executable_admission:
            raise ProgressiveProductionError(f"{self.stage_id}: workflow is not executable")
        if self.contract.media_kind != _EXPECTED_MEDIA[self.role]:
            raise ProgressiveProductionError(f"{self.stage_id}: media kind does not match role")
        source = Path(self.workflow_api_path).resolve()
        if not source.is_file() or _file_sha256(source) != self.contract.workflow_api_sha256:
            raise ProgressiveProductionError(f"{self.stage_id}: workflow API hash does not match")
        logical_names = {binding.logical_name for binding in self.contract.bindings}
        if self.prompt_binding_name not in logical_names:
            raise ProgressiveProductionError(f"{self.stage_id}: prompt binding is undeclared")
        if self.workflow_values.get(self.prompt_binding_name) != self.creative_prompt:
            raise ProgressiveProductionError(f"{self.stage_id}: creative prompt is not bound")
        _required(self.creative_prompt, "creative_prompt", minimum=80)
        if len(self.identity_lock) < 3 or len(self.negative_constraints) < 3:
            raise ProgressiveProductionError(
                f"{self.stage_id}: identity and negative-control contracts are too shallow"
            )
        if not any(campaign_genome_sha256 in item for item in self.identity_lock):
            raise ProgressiveProductionError(
                f"{self.stage_id}: campaign genome is absent from identity lock"
            )
        if self.role == ProductionStageRole.HERO_VIDEO:
            if self.selected_visual_binding_name not in logical_names:
                raise ProgressiveProductionError(
                    f"{self.stage_id}: hero video must bind the selected visual"
                )
        elif self.selected_visual_binding_name is not None:
            raise ProgressiveProductionError(
                f"{self.stage_id}: only the hero video may receive the selected visual"
            )
        supplied = set(self.workflow_values)
        if self.selected_visual_binding_name is not None:
            supplied.add(self.selected_visual_binding_name)
        unknown = supplied - logical_names
        missing = logical_names - supplied
        if unknown or missing:
            raise ProgressiveProductionError(
                f"{self.stage_id}: workflow binding mismatch; unknown={sorted(unknown)}, "
                f"missing={sorted(missing)}"
            )


@dataclass(frozen=True)
class ProgressiveMultimodalPlan:
    campaign_id: str
    source_production_pack_path: str
    source_production_pack_sha256: str
    campaign_genome_sha256: str
    candidate_batch_root: str
    finalist_selection_path: str
    rights_locator: str
    stages: tuple[MultimodalStageSpec, ...]

    def validate(self) -> None:
        _required(self.campaign_id, "campaign_id", minimum=8)
        _required(self.rights_locator, "rights_locator", minimum=8)
        _sha256(self.source_production_pack_sha256, "source_production_pack_sha256")
        _sha256(self.campaign_genome_sha256, "campaign_genome_sha256")
        production_pack = Path(self.source_production_pack_path).resolve()
        if not production_pack.is_file() or _file_sha256(production_pack) != self.source_production_pack_sha256:
            raise ProgressiveProductionError("source production pack is missing or drifted")
        roles = [stage.role for stage in self.stages]
        if set(roles) != set(ProductionStageRole) or len(roles) != len(set(roles)):
            raise ProgressiveProductionError("plan requires one hero video, music, and speech stage")
        if roles != [
            ProductionStageRole.HERO_VIDEO,
            ProductionStageRole.MUSIC,
            ProductionStageRole.SPEECH,
        ]:
            raise ProgressiveProductionError("production stages must run video, music, then speech")
        if len({stage.stage_id for stage in self.stages}) != len(self.stages):
            raise ProgressiveProductionError("production stage IDs must be unique")
        for stage in self.stages:
            stage.validate(self.campaign_genome_sha256)


@dataclass(frozen=True)
class ProducedStage:
    stage_id: str
    role: str
    generation_receipt_path: str
    artifact_sha256s: tuple[str, ...]


@dataclass(frozen=True)
class ProgressiveMultimodalReceipt:
    campaign_id: str
    status: str
    source_production_pack_sha256: str
    campaign_genome_sha256: str
    candidate_batch_sha256: str
    finalist_selection_sha256: str
    selected_candidate_id: str
    selected_visual_sha256: str
    completed_stage_count: int
    stages: tuple[ProducedStage, ...]
    failure: str | None
    master_mux_performed: bool
    human_effect_review_completed: bool
    external_publish_executed: bool
    four_a_effect_proven: bool
    truth_boundary: str = (
        "The receipt binds a human-selected visual to independently generated video, music, "
        "and speech assets. It does not prove a finished master, 4A preference, publication, "
        "business lift, causal revenue, or Radeon execution."
    )
    schema: str = "ProofLaunchProgressiveMultimodalReceiptV1"


class ProgressiveMultimodalCoordinator:
    """Promote a blind-selected visual into video/audio workflows without re-rendering media."""

    def run(
        self,
        *,
        client: ComfyUIProductionClient,
        plan: ProgressiveMultimodalPlan,
        output_dir: str | Path,
    ) -> ProgressiveMultimodalReceipt:
        plan.validate()
        root = Path(output_dir).resolve()
        if root.exists() and any(root.iterdir()):
            raise ProgressiveProductionError("multimodal output directory must be empty")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        batch_path = Path(plan.candidate_batch_root).resolve() / "candidate-batch-receipt.json"
        if not batch_path.is_file():
            raise ProgressiveProductionError("candidate batch receipt is missing")
        batch_sha = _file_sha256(batch_path)
        batch = self._load_batch(batch_path)
        selection_path = Path(plan.finalist_selection_path).resolve()
        selection = FinalistSelectionReceipt.load(selection_path)
        self._verify_blind_packet(selection_path, selection)
        selection_sha = _file_sha256(selection_path)
        selected_visual = self._resolve_selected_visual(
            batch_path.parent, batch, selection
        )
        stages: list[ProducedStage] = []
        failure: str | None = None
        for spec in plan.stages:
            stage_root = root / spec.stage_id
            uploads = {}
            if spec.selected_visual_binding_name is not None:
                uploads[spec.selected_visual_binding_name] = str(selected_visual)
            try:
                receipt = client.execute(
                    spec.contract,
                    spec.workflow_api_path,
                    ComfyGenerationRequest(
                        request_id=f"{plan.campaign_id}-{spec.stage_id}",
                        values=spec.workflow_values,
                        upload_paths=uploads,
                        output_dir=str(stage_root),
                        rights_locator=plan.rights_locator,
                    ),
                )
                child_receipt = Path(receipt.output_root) / "comfy-generation-receipt.json"
                if not child_receipt.is_file():
                    raise ProgressiveProductionError(
                        f"{spec.stage_id}: generation receipt was not sealed"
                    )
                relative_receipt = child_receipt.resolve().relative_to(root)
                stages.append(
                    ProducedStage(
                        stage_id=spec.stage_id,
                        role=spec.role.value,
                        generation_receipt_path=str(relative_receipt),
                        artifact_sha256s=tuple(
                            artifact.content_sha256 for artifact in receipt.artifacts
                        ),
                    )
                )
            except Exception as error:
                failure = f"{spec.stage_id}: {type(error).__name__}: {error}"
                break
        receipt = ProgressiveMultimodalReceipt(
            campaign_id=plan.campaign_id,
            status="generated_unreviewed" if failure is None else "blocked_partial_production",
            source_production_pack_sha256=plan.source_production_pack_sha256,
            campaign_genome_sha256=plan.campaign_genome_sha256,
            candidate_batch_sha256=batch_sha,
            finalist_selection_sha256=selection_sha,
            selected_candidate_id=selection.selected_candidate_id,
            selected_visual_sha256=selection.selected_artifact_sha256,
            completed_stage_count=len(stages),
            stages=tuple(stages),
            failure=failure,
            master_mux_performed=False,
            human_effect_review_completed=False,
            external_publish_executed=False,
            four_a_effect_proven=False,
        )
        receipt_path = root / "progressive-multimodal-receipt.json"
        atomic_write_text(
            receipt_path,
            json.dumps(asdict(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        receipt_path.chmod(0o600)
        if failure is not None:
            raise ProgressiveProductionError(failure)
        return receipt

    @staticmethod
    def _verify_blind_packet(
        selection_path: Path,
        selection: FinalistSelectionReceipt,
    ) -> None:
        selection_root = selection_path.parent.resolve()
        try:
            packet_path = (selection_root / selection.blind_packet_path).resolve()
            packet_path.relative_to(selection_root)
        except ValueError as error:
            raise ProgressiveProductionError("blind packet escaped the selection root") from error
        if not packet_path.is_file() or _file_sha256(packet_path) != selection.blind_packet_sha256:
            raise ProgressiveProductionError("blind packet is missing or drifted")

    @staticmethod
    def _load_batch(path: Path) -> dict[str, object]:
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ProgressiveProductionError("candidate batch receipt is invalid JSON") from error
        if not isinstance(batch, dict) or batch.get("schema") != "ProofLaunchGenerativeCandidateBatchReceiptV1":
            raise ProgressiveProductionError("candidate batch receipt schema is unsupported")
        if batch.get("status") != "generated_unreviewed" or batch.get("failure") is not None:
            raise ProgressiveProductionError("candidate batch did not complete cleanly")
        if batch.get("winner_selected") is not False or batch.get("blind_review_completed") is not False:
            raise ProgressiveProductionError("candidate batch truth boundary was altered")
        if not isinstance(batch.get("candidates"), list) or not batch["candidates"]:
            raise ProgressiveProductionError("candidate batch contains no candidates")
        return batch

    @staticmethod
    def _resolve_selected_visual(
        batch_root: Path,
        batch: Mapping[str, object],
        selection: FinalistSelectionReceipt,
    ) -> Path:
        if selection.batch_id != batch.get("batch_id"):
            raise ProgressiveProductionError("selection batch ID does not match")
        matches = [
            row
            for row in batch["candidates"]
            if isinstance(row, dict) and row.get("candidate_id") == selection.selected_candidate_id
        ]
        if len(matches) != 1:
            raise ProgressiveProductionError("selected candidate is absent or duplicated")
        candidate = matches[0]
        hashes = candidate.get("artifact_sha256s")
        if not isinstance(hashes, list) or hashes.count(selection.selected_artifact_sha256) != 1:
            raise ProgressiveProductionError("selected artifact is not uniquely bound to candidate")
        receipt_value = candidate.get("generation_receipt_path")
        if not isinstance(receipt_value, str):
            raise ProgressiveProductionError("candidate generation receipt path is invalid")
        try:
            child_receipt = (batch_root / receipt_value).resolve()
            child_receipt.relative_to(batch_root)
        except ValueError as error:
            raise ProgressiveProductionError("candidate receipt escaped the batch root") from error
        if not child_receipt.is_file():
            raise ProgressiveProductionError("candidate generation receipt is missing")
        try:
            payload = json.loads(child_receipt.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ProgressiveProductionError("candidate generation receipt is invalid") from error
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
        artifact_rows = [
            row
            for row in artifacts or []
            if isinstance(row, dict) and row.get("content_sha256") == selection.selected_artifact_sha256
        ]
        if len(artifact_rows) != 1 or not isinstance(artifact_rows[0].get("relative_path"), str):
            raise ProgressiveProductionError("selected artifact path is not sealed")
        artifact_path = (child_receipt.parent / artifact_rows[0]["relative_path"]).resolve()
        try:
            artifact_path.relative_to(child_receipt.parent)
        except ValueError as error:
            raise ProgressiveProductionError("selected artifact escaped its generation root") from error
        if not artifact_path.is_file() or _file_sha256(artifact_path) != selection.selected_artifact_sha256:
            raise ProgressiveProductionError("selected artifact is missing or drifted")
        return artifact_path
