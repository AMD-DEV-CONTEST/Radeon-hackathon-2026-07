from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import numpy as np
import torch
from PIL import Image
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from colorgraph.agent.creative_contracts import (
    CompiledCandidate,
    CritiqueDimension,
    CritiqueScore,
    FailureCase,
    GraphChange,
    NonEmptyString,
    NormalizedScore,
    PatchChange,
    ReflectionPatch,
    Sha256,
    StrategyOperation,
    StrategyScope,
    StrictFrozenModel,
    TimeSpan,
    VisualCritique,
    canonical_sha256,
)
from colorgraph.agent.creative_critic import PairwiseVisualCriticReport
from colorgraph.agent.creative_search import (
    CandidateAttemptStatus,
    DeterministicSearchHardGates,
    RenderedSearchSample,
    SearchCandidateInput,
    SearchCandidateRecord,
)
from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import (
    LEGACY_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    GradeNode,
    NodeType,
)
from colorgraph.grading.color import convert_color_space
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.looks import graph_digest
from colorgraph.grading.masks import GraphMaskResolver
from colorgraph.grading.precision import PREVIEW_PRECISION_BUDGET

REFLECTION_VERSION = "colorgraph.state-aware-creative-reflection/v2"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class ReflectionSource(StrEnum):
    CRITIC = "critic"
    USER = "user"


class PatchDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"


class ReflectionOutcomeStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED_HARD_GATE = "rejected_hard_gate"
    REJECTED_NO_PARETO_IMPROVEMENT = "rejected_no_pareto_improvement"
    REJECTED_REGRESSION = "rejected_regression"
    REJECTED_INTENT_DRIFT = "rejected_intent_drift"
    REJECTED_PAIRWISE = "rejected_pairwise"
    STOPPED_LOW_CONFIDENCE = "stopped_low_confidence"
    STOPPED_BUDGET = "stopped_budget"
    STOPPED_DUPLICATE = "stopped_duplicate"


class ReflectionParameterTarget(StrictFrozenModel):
    node_id: NonEmptyString
    parameter: NonEmptyString
    direction: PatchDirection
    expected_current_value: float
    absolute_delta: float = Field(gt=0)
    minimum_allowed_value: float
    maximum_allowed_value: float
    scope: StrategyScope

    @model_validator(mode="after")
    def validate_parameter_range(self) -> ReflectionParameterTarget:
        if self.minimum_allowed_value >= self.maximum_allowed_value:
            raise ValueError("reflection parameter bounds must be ordered")
        if not (
            self.minimum_allowed_value
            <= self.expected_current_value
            <= self.maximum_allowed_value
        ):
            raise ValueError("expected reflection value is outside its declared bounds")
        if self.absolute_delta > (
            self.maximum_allowed_value - self.minimum_allowed_value
        ):
            raise ValueError("reflection delta exceeds the full parameter domain")
        return self


class ReflectionDirective(StrictFrozenModel):
    schema_version: Literal["colorgraph.reflection-directive/v1"] = (
        "colorgraph.reflection-directive/v1"
    )
    directive_id: NonEmptyString
    source: ReflectionSource
    parent_candidate_id: NonEmptyString
    hypothesis: NonEmptyString
    target_dimensions: list[CritiqueDimension] = Field(min_length=1)
    evidence_ids: list[NonEmptyString] = Field(min_length=1)
    expected_improvement: NonEmptyString
    maximum_allowed_regression: NormalizedScore
    targets: list[ReflectionParameterTarget] = Field(min_length=1)
    confidence: NormalizedScore

    @model_validator(mode="after")
    def unique_targets(self) -> ReflectionDirective:
        dimensions = self.target_dimensions
        targets = [(item.node_id, item.parameter) for item in self.targets]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("reflection target dimensions must be unique")
        if len(targets) != len(set(targets)):
            raise ValueError("reflection parameter targets must be unique")
        return self


class ReflectionCompilePolicy(StrictFrozenModel):
    schema_version: Literal["colorgraph.reflection-compile-policy/v1"] = (
        "colorgraph.reflection-compile-policy/v1"
    )
    maximum_changed_parameters: int = Field(default=2, ge=1, le=4)
    maximum_parameter_domain_fraction: float = Field(default=0.25, gt=0, le=0.5)
    minimum_directive_confidence: NormalizedScore = 0.5


class CompiledReflectionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["colorgraph.compiled-reflection-candidate/v1"] = (
        "colorgraph.compiled-reflection-candidate/v1"
    )
    patch: ReflectionPatch
    directive_digest: Sha256
    parent_qc_digest: Sha256
    parent_rendered_digest: Sha256
    project_thesis_digest: Sha256
    contract: CompiledCandidate
    graph: GradeGraph
    undo_graph: GradeGraph
    locked_mask_digests: dict[NonEmptyString, Sha256]
    required_qc_checks: list[NonEmptyString] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bindings(self) -> CompiledReflectionCandidate:
        if self.patch.parent_candidate_id == self.contract.candidate_id:
            raise ValueError("a reflection candidate cannot be its own parent")
        if graph_digest(self.graph) != self.contract.compiled_graph_digest:
            raise ValueError("reflection graph digest does not match its contract")
        if graph_digest(self.undo_graph) != self.contract.undo_graph_digest:
            raise ValueError("reflection undo digest does not match its contract")
        if self.contract.source_graph_digest != self.contract.undo_graph_digest:
            raise ValueError("reflection source and undo digests must match")
        if self.patch.parent_candidate_id not in self.contract.candidate_id:
            parent_token = canonical_sha256(
                {"parent_candidate_id": self.patch.parent_candidate_id}
            )[:8]
            if parent_token not in self.contract.candidate_id:
                raise ValueError("reflection candidate ID is not bound to its parent")
        source_nodes = {item.id: item for item in self.undo_graph.nodes}
        refined_nodes = {item.id: item for item in self.graph.nodes}
        change_pairs = {
            (item.node_id, item.parameter): item for item in self.patch.changes
        }
        changed_node_ids = {node_id for node_id, _ in change_pairs}
        if set(source_nodes) != set(refined_nodes):
            raise ValueError("reflection changed the graph node inventory")
        if set(self.patch.locked_node_ids) != set(source_nodes) - changed_node_ids:
            raise ValueError("reflection locked-node inventory is incomplete")
        for node_id, source_node in source_nodes.items():
            refined_node = refined_nodes[node_id]
            expected_parameters = dict(source_node.parameters)
            for (changed_node_id, parameter), change in change_pairs.items():
                if changed_node_id != node_id:
                    continue
                if expected_parameters.get(parameter) != change.before_value:
                    raise ValueError("reflection patch before-value is stale")
                expected_parameters[parameter] = change.after_value
            expected_node = source_node.model_copy(
                update={"parameters": expected_parameters}
            )
            if refined_node != expected_node:
                raise ValueError(
                    "reflection changed an unnamed node field or parameter"
                )
        expected_masks = {
            item.id: canonical_sha256(item.model_dump(mode="json"))
            for item in self.undo_graph.masks
        }
        refined_masks = {
            item.id: canonical_sha256(item.model_dump(mode="json"))
            for item in self.graph.masks
        }
        if (
            self.locked_mask_digests != expected_masks
            or refined_masks != expected_masks
        ):
            raise ValueError("reflection changed a locked mask asset")
        return self


class ReflectionBudget(StrictFrozenModel):
    maximum_refinements: int = Field(default=1, ge=0, le=1)
    maximum_rendered_frames: int = Field(default=3, ge=1, le=3)
    maximum_model_calls: int = Field(default=2, ge=0, le=2)
    maximum_cost_usd: float = Field(default=1, ge=0)


class ReflectionPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["colorgraph.reflection-preparation/v2"] = (
        "colorgraph.reflection-preparation/v2"
    )
    run_id: NonEmptyString
    cache_key: Sha256
    cache_hit: bool
    compilation_digest: Sha256
    budget_digest: Sha256
    renderer_version: NonEmptyString
    renderer_input_digest: Sha256
    compilation: CompiledReflectionCandidate
    refined_record: SearchCandidateRecord
    rendered_frames: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def validate_preparation_bindings(self) -> ReflectionPreparation:
        if self.compilation_digest != canonical_sha256(self.compilation):
            raise ValueError("reflection preparation compilation digest is stale")
        if self.refined_record.cache_key != self.cache_key:
            raise ValueError("reflection preparation record has another cache key")
        if (
            self.refined_record.candidate_id
            != self.compilation.contract.candidate_id
        ):
            raise ValueError("reflection preparation record has another candidate")
        if self.rendered_frames != len(self.refined_record.samples):
            raise ValueError("reflection preparation rendered-frame count is stale")
        return self


class ReflectionEvaluationPolicy(StrictFrozenModel):
    schema_version: Literal["colorgraph.reflection-evaluation-policy/v1"] = (
        "colorgraph.reflection-evaluation-policy/v1"
    )
    minimum_target_improvement: NormalizedScore = 0.02
    minimum_critic_confidence: NormalizedScore = 0.5
    maximum_technical_margin_regression: Literal[0] = 0


class ReflectionDimensionDelta(StrictFrozenModel):
    dimension: CritiqueDimension
    parent_score: NormalizedScore
    refined_score: NormalizedScore
    improvement: float = Field(ge=-1, le=1)
    targeted: bool


class ReflectionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["colorgraph.reflection-outcome/v1"] = (
        "colorgraph.reflection-outcome/v1"
    )
    status: ReflectionOutcomeStatus
    accepted: bool
    patch_id: NonEmptyString
    parent_candidate_id: NonEmptyString
    refined_candidate_id: NonEmptyString
    selected_candidate_id: NonEmptyString
    selected_graph_digest: Sha256
    rollback_graph_digest: Sha256
    pairwise_report_digest: Sha256 | None = None
    dimension_deltas: list[ReflectionDimensionDelta]
    stop_reasons: list[NonEmptyString]
    failure_case: FailureCase | None = None
    current_graph_unchanged: bool = True

    @model_validator(mode="after")
    def validate_outcome(self) -> ReflectionOutcome:
        if self.accepted != (self.status == ReflectionOutcomeStatus.ACCEPTED):
            raise ValueError("reflection accepted flag differs from its status")
        expected_selected = (
            self.refined_candidate_id if self.accepted else self.parent_candidate_id
        )
        if self.selected_candidate_id != expected_selected:
            raise ValueError("reflection outcome selected the wrong branch")
        if self.accepted and self.failure_case is not None:
            raise ValueError("an accepted reflection cannot generate a failure case")
        if not self.accepted and self.failure_case is None:
            raise ValueError("a rejected or stopped reflection requires a failure case")
        return self


class UserFeedbackAxis(StrEnum):
    EXPANSIVE = "expansive"
    RESTRAINED = "restrained"
    LONELY = "lonely"
    DREAMLIKE = "dreamlike"


class UserFeedbackBranch(StrictFrozenModel):
    schema_version: Literal["colorgraph.user-feedback-branch/v1"] = (
        "colorgraph.user-feedback-branch/v1"
    )
    branch_id: NonEmptyString
    parent_strategy_id: NonEmptyString
    parent_thesis_digest: Sha256
    raw_feedback: NonEmptyString
    axes: list[UserFeedbackAxis] = Field(min_length=1)
    target_dimensions: list[CritiqueDimension] = Field(min_length=1)
    requires_new_thesis_branch: bool
    reanalyze_project: Literal[False] = False


class FailureReuseTarget(StrEnum):
    GENERAL_FAILURE_CARD = "general_failure_card"
    REGRESSION_FIXTURE = "regression_fixture"


class FailureCaseReuseReview(StrictFrozenModel):
    schema_version: Literal["colorgraph.failure-case-reuse-review/v1"] = (
        "colorgraph.failure-case-reuse-review/v1"
    )
    source_failure_id: NonEmptyString
    source_failure_digest: Sha256
    reviewer_id: NonEmptyString
    reviewed_at: AwareDatetime
    human_review_completed: Literal[True]
    private_data_redacted: Literal[True]
    target: FailureReuseTarget
    version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$")
    sanitized_context_asset_id: NonEmptyString
    sanitized_operation_summary: NonEmptyString
    sanitized_actual_harm: NonEmptyString
    sanitized_responsible_node_roles: list[NonEmptyString] = Field(min_length=1)
    sanitized_repair_summary: NonEmptyString
    sanitized_evidence_ids: list[NonEmptyString] = Field(min_length=1)


class FailureCaseReuseArtifact(StrictFrozenModel):
    schema_version: Literal["colorgraph.failure-case-reuse-artifact/v1"] = (
        "colorgraph.failure-case-reuse-artifact/v1"
    )
    artifact_id: NonEmptyString
    source_failure_id: NonEmptyString
    source_failure_digest: Sha256
    target: FailureReuseTarget
    version: NonEmptyString
    reviewer_id: NonEmptyString
    reviewed_at: AwareDatetime
    sanitized_failure_case: FailureCase

    @model_validator(mode="after")
    def validate_reuse_gate(self) -> FailureCaseReuseArtifact:
        if (
            not self.sanitized_failure_case.reviewed_for_reuse
            or self.sanitized_failure_case.contains_private_data
        ):
            raise ValueError(
                "reusable failure artifacts must be reviewed and redacted"
            )
        return self


@dataclass(frozen=True, slots=True)
class ReflectionCompileResult:
    compilation: CompiledReflectionCandidate | None
    status: ReflectionOutcomeStatus | None
    detail: str | None
    patch_digest: str | None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str) -> str:
    label = _SAFE_COMPONENT.sub("-", value).strip("-")
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{label[:48] or 'item'}-{digest}"


def _storage_signature(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if resolved.is_file():
        return {
            "kind": "file",
            "path": str(resolved),
            "size": resolved.stat().st_size,
            "sha256": _sha256_file(resolved),
        }
    if resolved.is_dir():
        files = [
            item
            for item in sorted(resolved.rglob("*"))
            if item.is_file()
        ]
        return {
            "kind": "directory",
            "path": str(resolved),
            "files": [
                {
                    "relative_path": item.relative_to(resolved).as_posix(),
                    "size": item.stat().st_size,
                    "sha256": _sha256_file(item),
                }
                for item in files
            ],
        }
    return {"kind": "missing", "path": str(resolved)}


def _mask_storage_signatures(graph: GradeGraph) -> list[dict[str, object]]:
    signatures: list[dict[str, object]] = []
    for asset in sorted(graph.masks, key=lambda item: item.id):
        storage = asset.metadata.get("storage")
        preferred = (
            storage.get("preferred_decode")
            if isinstance(storage, dict)
            else None
        )
        storage_value = (
            asset.metadata.get("video_path")
            if preferred == "video_ffmpeg"
            else asset.path
        )
        signatures.append(
            {
                "asset_id": asset.id,
                "declared_asset_digest": canonical_sha256(
                    asset.model_dump(mode="json")
                ),
                "actual_storage": _storage_signature(Path(str(storage_value))),
            }
        )
    return signatures


def _validate_sample_assets(
    samples: Sequence[RenderedSearchSample],
    *,
    candidate_root: Path | None = None,
) -> bool:
    root = candidate_root.resolve() if candidate_root is not None else None
    for sample in samples:
        paths = (
            (Path(sample.source_path).resolve(), sample.source_sha256),
            (Path(sample.current_path).resolve(), sample.current_sha256),
            (Path(sample.candidate_path).resolve(), sample.candidate_sha256),
        )
        if root is not None and not paths[2][0].is_relative_to(root):
            return False
        if any(
            not path.is_file() or _sha256_file(path) != digest
            for path, digest in paths
        ):
            return False
        try:
            with Image.open(paths[2][0]) as image:
                image.load()
                if image.size != (sample.width, sample.height):
                    return False
        except OSError:
            return False
    return True


def _renderer_input_digest(
    *,
    renderer: ReflectionFrameRenderer,
    parent_record: SearchCandidateRecord,
    graph: GradeGraph,
) -> str:
    if not _validate_sample_assets(parent_record.samples):
        raise ValueError("reflection parent evidence assets are stale")
    provider = getattr(renderer, "input_digest", None)
    provider_digest: str | None = None
    if callable(provider):
        provider_digest = provider(parent_record=parent_record, graph=graph)
        if not isinstance(provider_digest, str) or not _SHA256.fullmatch(
            provider_digest
        ):
            raise ValueError("reflection renderer input digest must be SHA-256")
    return canonical_sha256(
        {
            "renderer_version": renderer.renderer_version,
            "renderer_input_digest": provider_digest,
            "parent_samples": [
                {
                    "frame_index": item.frame_index,
                    "time_seconds": item.time_seconds,
                    "source": _storage_signature(Path(item.source_path)),
                    "current": _storage_signature(Path(item.current_path)),
                    "candidate": _storage_signature(Path(item.candidate_path)),
                }
                for item in parent_record.samples
            ],
            "mask_storage": _mask_storage_signatures(graph),
        }
    )


def _parent_rendered_digest(record: SearchCandidateRecord) -> str:
    return canonical_sha256(
        {
            "candidate_frames": [
                {
                    "frame_index": item.frame_index,
                    "time_seconds": item.time_seconds,
                    "sha256": item.candidate_sha256,
                }
                for item in record.samples
            ]
        }
    )


def _load_parent_contract(record: SearchCandidateRecord) -> CompiledCandidate:
    path = Path(record.contract_path)
    if not path.is_file():
        raise ValueError("parent compiled contract is missing")
    contract = CompiledCandidate.model_validate_json(
        path.read_text(encoding="utf-8"),
        strict=True,
    )
    if (
        contract.candidate_id != record.candidate_id
        or contract.compiled_graph_digest != record.compiled_graph_digest
    ):
        raise ValueError("parent candidate record is stale relative to its contract")
    return contract


def _load_parent_graph(record: SearchCandidateRecord) -> GradeGraph:
    path = Path(record.graph_path)
    if not path.is_file():
        raise ValueError("parent compiled graph is missing")
    graph = GradeGraph.model_validate_json(
        path.read_text(encoding="utf-8"),
    )
    if graph_digest(graph) != record.compiled_graph_digest:
        raise ValueError("parent candidate record is stale relative to its graph")
    return graph


def _mask_digests(graph: GradeGraph) -> dict[str, str]:
    return {
        item.id: canonical_sha256(item.model_dump(mode="json"))
        for item in graph.masks
    }


def compile_reflection_directive(
    *,
    parent_record: SearchCandidateRecord,
    directive: ReflectionDirective,
    project_thesis_digest: str,
    evaluated_at: datetime,
    budget: ReflectionBudget | None = None,
    policy: ReflectionCompilePolicy | None = None,
    prior_patch_digests: Sequence[str] = (),
) -> ReflectionCompileResult:
    budget = budget or ReflectionBudget()
    policy = policy or ReflectionCompilePolicy()
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("reflection compile time must be timezone-aware")
    if len(project_thesis_digest) != 64:
        raise ValueError("project thesis digest must be a SHA-256 value")
    if (
        budget.maximum_refinements == 0
        or parent_record.is_refinement
    ):
        return ReflectionCompileResult(
            compilation=None,
            status=ReflectionOutcomeStatus.STOPPED_BUDGET,
            detail="The first-version reflection budget permits at most one refinement.",
            patch_digest=None,
        )
    if directive.confidence < policy.minimum_directive_confidence:
        return ReflectionCompileResult(
            compilation=None,
            status=ReflectionOutcomeStatus.STOPPED_LOW_CONFIDENCE,
            detail="The reflection directive confidence is below policy.",
            patch_digest=None,
        )
    if directive.parent_candidate_id != parent_record.candidate_id:
        raise ValueError("reflection directive belongs to another parent candidate")
    if (
        parent_record.status != CandidateAttemptStatus.HARD_PASS
        or parent_record.qc is None
        or not parent_record.qc.hard_passed
    ):
        raise ValueError("reflection can only refine a deterministic QC survivor")
    if len(directive.targets) > policy.maximum_changed_parameters:
        raise ValueError("reflection directive exceeds the minimal-change parameter budget")

    parent_contract = _load_parent_contract(parent_record)
    parent_graph = _load_parent_graph(parent_record)
    node_by_id = {item.id: item for item in parent_graph.nodes}
    target_pairs = {(item.node_id, item.parameter) for item in directive.targets}
    changes: list[PatchChange] = []
    graph_changes: list[GraphChange] = []
    updated_nodes = []
    for node in parent_graph.nodes:
        targets = [
            item for item in directive.targets if item.node_id == node.id
        ]
        if not targets:
            updated_nodes.append(node.model_copy(deep=True))
            continue
        if node.type in {
            NodeType.INPUT_TRANSFORM,
            NodeType.OUTPUT_TRANSFORM,
        }:
            raise ValueError("reflection cannot modify color-management nodes")
        if not str(node.metadata.get("source", "")).startswith(
            "colorgraph.deterministic-strategy-compiler/"
        ):
            raise ValueError("reflection may modify only creative compiler-owned nodes")
        parameters = dict(node.parameters)
        for target in targets:
            if target.node_id not in node_by_id:
                raise ValueError(f"reflection target node is unknown: {target.node_id}")
            if target.parameter not in parameters:
                raise ValueError(
                    f"reflection target parameter is unknown: {target.parameter}"
                )
            current = parameters[target.parameter]
            if isinstance(current, bool) or not isinstance(current, (int, float)):
                raise ValueError("reflection can only patch numeric renderer parameters")
            if abs(float(current) - target.expected_current_value) > 1e-12:
                raise ValueError("reflection directive is stale for its target value")
            domain = target.maximum_allowed_value - target.minimum_allowed_value
            if (
                target.absolute_delta
                > domain * policy.maximum_parameter_domain_fraction + 1e-12
            ):
                raise ValueError("reflection change exceeds the minimal domain fraction")
            if (
                target.scope.project_id != parent_graph.project_id
                or target.scope.project_id != node.temporal_scope.project_id
            ):
                raise ValueError("reflection scope is outside the parent project")
            if (
                target.scope.scene_id != node.temporal_scope.scene_id
                or target.scope.shot_id != node.temporal_scope.shot_id
            ):
                raise ValueError(
                    "reflection temporal scope is outside the creative node scope"
                )
            node_time_range = node.temporal_scope.time_range
            target_time_range = target.scope.time_range
            if (
                (node_time_range is None) != (target_time_range is None)
                or (
                    node_time_range is not None
                    and target_time_range is not None
                    and (
                        node_time_range.start_seconds
                        != target_time_range.start_seconds
                        or node_time_range.end_seconds
                        != target_time_range.end_seconds
                    )
                )
            ):
                raise ValueError(
                    "reflection time range is outside the creative node scope"
                )
            if target.scope.mask_target != node.spatial_scope.target:
                raise ValueError(
                    "reflection mask target differs from the creative node scope"
                )
            sign = 1 if target.direction == PatchDirection.INCREASE else -1
            after = float(current) + sign * target.absolute_delta
            if not (
                target.minimum_allowed_value
                <= after
                <= target.maximum_allowed_value
            ):
                raise ValueError("reflection change exceeds declared parameter bounds")
            parameters[target.parameter] = after
            changes.append(
                PatchChange(
                    node_id=node.id,
                    parameter=target.parameter,
                    before_value=float(current),
                    after_value=after,
                    scope=target.scope,
                )
            )
            graph_changes.append(
                GraphChange(
                    action_id=str(
                        node.metadata.get(
                            "strategy_action_id",
                            f"reflection:{node.id}",
                        )
                    ),
                    node_id=node.id,
                    operation="update",
                    parameter=target.parameter,
                    before_value=float(current),
                    after_value=after,
                )
            )
        updated_nodes.append(node.model_copy(update={"parameters": parameters}))
    if {(item.node_id, item.parameter) for item in changes} != target_pairs:
        unknown = target_pairs - {
            (item.node_id, item.parameter) for item in changes
        }
        raise ValueError(f"reflection references unknown target pairs: {sorted(unknown)}")

    locked_nodes = sorted(set(node_by_id) - {item.node_id for item in changes})
    patch_seed = canonical_sha256(
        {
            "parent_candidate_id": parent_record.candidate_id,
            "parent_graph_digest": parent_record.compiled_graph_digest,
            "directive": directive.model_dump(mode="json"),
            "changes": [item.model_dump(mode="json") for item in changes],
            "project_thesis_digest": project_thesis_digest,
        }
    )
    patch = ReflectionPatch(
        patch_id=f"reflection:{patch_seed[:24]}",
        parent_candidate_id=parent_record.candidate_id,
        hypothesis=directive.hypothesis,
        target_dimensions=directive.target_dimensions,
        maximum_allowed_regression=directive.maximum_allowed_regression,
        changes=changes,
        locked_node_ids=locked_nodes,
        expected_improvement=directive.expected_improvement,
    )
    patch_digest = canonical_sha256(patch)
    if patch_digest in set(prior_patch_digests):
        return ReflectionCompileResult(
            compilation=None,
            status=ReflectionOutcomeStatus.STOPPED_DUPLICATE,
            detail="The same reflection patch was already attempted.",
            patch_digest=patch_digest,
        )

    graph_payload = parent_graph.model_dump(mode="python")
    graph_payload["nodes"] = [
        item.model_dump(mode="python") for item in updated_nodes
    ]
    graph_payload["updated_at"] = evaluated_at
    metadata = dict(parent_graph.metadata)
    reflection_history = list(metadata.get("creative_reflections", []))
    reflection_history.append(
        {
            "version": REFLECTION_VERSION,
            "patch_id": patch.patch_id,
            "parent_candidate_id": parent_record.candidate_id,
            "directive_digest": canonical_sha256(directive),
            "project_thesis_digest": project_thesis_digest,
            "evaluated_at": evaluated_at.isoformat(),
        }
    )
    metadata["creative_reflections"] = reflection_history
    graph_payload["metadata"] = metadata
    refined_graph = GradeGraph.model_validate(graph_payload)
    parent_token = canonical_sha256(
        {"parent_candidate_id": parent_record.candidate_id}
    )[:8]
    refined_digest = graph_digest(refined_graph)
    refined_id = (
        f"candidate:reflection:{parent_token}:"
        f"{canonical_sha256({'patch': patch_digest, 'graph': refined_digest})[:20]}"
    )
    contract = CompiledCandidate(
        candidate_id=refined_id,
        strategy_id=parent_contract.strategy_id,
        source_graph_digest=parent_record.compiled_graph_digest,
        compiled_graph_digest=refined_digest,
        undo_graph_digest=parent_record.compiled_graph_digest,
        graph_changes=graph_changes,
        operation_card_versions={
            **parent_contract.operation_card_versions,
            "reflection-policy": policy.schema_version,
        },
        compiler_version=REFLECTION_VERSION,
        validation_passed=True,
    )
    compilation = CompiledReflectionCandidate(
        patch=patch,
        directive_digest=canonical_sha256(directive),
        parent_qc_digest=canonical_sha256(parent_record.qc),
        parent_rendered_digest=_parent_rendered_digest(parent_record),
        project_thesis_digest=project_thesis_digest,
        contract=contract,
        graph=refined_graph,
        undo_graph=parent_graph,
        locked_mask_digests=_mask_digests(parent_graph),
        required_qc_checks=parent_record.qc.required_check_ids,
    )
    return ReflectionCompileResult(
        compilation=compilation,
        status=None,
        detail=None,
        patch_digest=patch_digest,
    )


class ReflectionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run_dir(self, run_id: str) -> Path:
        return self.root / _safe_component(run_id)

    def cache_dir(self, run_id: str, cache_key: str) -> Path:
        if not _SHA256.fullmatch(cache_key):
            raise ValueError("reflection cache key must be a SHA-256 value")
        directory = (self.run_dir(run_id) / cache_key).resolve()
        if not directory.is_relative_to(self.root):
            raise ValueError("reflection cache directory escaped its store")
        return directory

    @staticmethod
    def _write_immutable(path: Path, content: str) -> None:
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"immutable reflection asset differs: {path.name}")
            return
        _atomic_write(path, content)

    def persist_compilation(
        self,
        run_id: str,
        cache_key: str,
        compilation: CompiledReflectionCandidate,
    ) -> tuple[str, str, str, str]:
        directory = self.cache_dir(run_id, cache_key)
        graph_path = directory / "refined-graph.json"
        rollback_path = directory / "rollback-graph.json"
        contract_path = directory / "compiled-contract.json"
        patch_path = directory / "reflection-patch.json"
        self._write_immutable(
            graph_path,
            compilation.graph.model_dump_json(indent=2),
        )
        self._write_immutable(
            rollback_path,
            compilation.undo_graph.model_dump_json(indent=2),
        )
        self._write_immutable(
            contract_path,
            compilation.contract.model_dump_json(indent=2),
        )
        self._write_immutable(
            patch_path,
            compilation.patch.model_dump_json(indent=2),
        )
        return tuple(
            str(path.resolve())
            for path in (graph_path, rollback_path, contract_path, patch_path)
        )

    def preparation_path(self, run_id: str, cache_key: str) -> Path:
        return self.cache_dir(run_id, cache_key) / "preparation.json"

    def load_preparation(
        self,
        run_id: str,
        cache_key: str,
        *,
        expected_compilation: CompiledReflectionCandidate,
        expected_budget_digest: str,
        expected_renderer_version: str,
        expected_renderer_input_digest: str,
        parent_record: SearchCandidateRecord,
    ) -> ReflectionPreparation | None:
        path = self.preparation_path(run_id, cache_key)
        if not path.is_file():
            return None
        try:
            result = ReflectionPreparation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        expected_compilation_digest = canonical_sha256(expected_compilation)
        if (
            result.run_id != run_id
            or result.cache_key != cache_key
            or result.compilation_digest != expected_compilation_digest
            or result.compilation != expected_compilation
            or result.budget_digest != expected_budget_digest
            or result.renderer_version != expected_renderer_version
            or result.renderer_input_digest != expected_renderer_input_digest
        ):
            return None
        directory = self.cache_dir(run_id, cache_key).resolve()
        graph_path = (directory / "refined-graph.json").resolve()
        rollback_path = (directory / "rollback-graph.json").resolve()
        contract_path = (directory / "compiled-contract.json").resolve()
        patch_path = (directory / "reflection-patch.json").resolve()
        record = result.refined_record
        if (
            Path(record.graph_path).resolve() != graph_path
            or Path(record.undo_graph_path).resolve() != rollback_path
            or Path(record.contract_path).resolve() != contract_path
            or any(
                not item.is_file()
                for item in (
                    graph_path,
                    rollback_path,
                    contract_path,
                    patch_path,
                )
            )
        ):
            return None
        try:
            graph = GradeGraph.model_validate_json(
                graph_path.read_text(encoding="utf-8")
            )
            rollback = GradeGraph.model_validate_json(
                rollback_path.read_text(encoding="utf-8")
            )
            contract = CompiledCandidate.model_validate_json(
                contract_path.read_text(encoding="utf-8"),
                strict=True,
            )
            patch = ReflectionPatch.model_validate_json(
                patch_path.read_text(encoding="utf-8"),
                strict=True,
            )
        except (OSError, ValueError):
            return None
        if (
            graph != expected_compilation.graph
            or rollback != expected_compilation.undo_graph
            or contract != expected_compilation.contract
            or patch != expected_compilation.patch
            or record.compiled_graph_digest != graph_digest(graph)
            or not _validate_sample_assets(
                record.samples,
                candidate_root=directory / "rendered",
            )
            or len(record.samples) != len(parent_record.samples)
        ):
            return None
        for refined, parent in zip(
            record.samples,
            parent_record.samples,
            strict=True,
        ):
            if (
                refined.frame_index != parent.frame_index
                or refined.time_seconds != parent.time_seconds
                or Path(refined.source_path).resolve()
                != Path(parent.source_path).resolve()
                or refined.source_sha256 != parent.source_sha256
                or Path(refined.current_path).resolve()
                != Path(parent.candidate_path).resolve()
                or refined.current_sha256 != parent.candidate_sha256
            ):
                return None
        proxy = SimpleNamespace(
            compiled=SimpleNamespace(graph=expected_compilation.graph)
        )
        try:
            qc = DeterministicSearchHardGates().evaluate(
                candidate=cast(SearchCandidateInput, proxy),
                samples=record.samples,
                required_check_ids=expected_compilation.required_qc_checks,
            )
        except (OSError, ValueError):
            return None
        expected_status = (
            CandidateAttemptStatus.HARD_PASS
            if qc.hard_passed
            else CandidateAttemptStatus.HARD_FAIL
        )
        if record.qc != qc or record.status != expected_status:
            return None
        return result.model_copy(update={"cache_hit": True})

    def save_preparation(self, preparation: ReflectionPreparation) -> Path:
        path = self.preparation_path(
            preparation.run_id,
            preparation.cache_key,
        )
        _atomic_write(path, preparation.model_dump_json(indent=2))
        return path

    def save_outcome(
        self,
        run_id: str,
        cache_key: str,
        outcome: ReflectionOutcome,
    ) -> Path:
        path = self.cache_dir(run_id, cache_key) / "outcome.json"
        self._write_immutable(path, outcome.model_dump_json(indent=2))
        return path


class LocalReflectionFrameRenderer:
    renderer_version = "colorgraph.local-reflection-frame-renderer/v2"

    def __init__(self, *, backend: ComputeBackend) -> None:
        self.backend = backend

    def input_digest(
        self,
        *,
        parent_record: SearchCandidateRecord,
        graph: GradeGraph,
    ) -> str:
        del parent_record, graph
        return canonical_sha256(
            {
                "renderer_version": self.renderer_version,
                "backend": {
                    "runtime": self.backend.info.runtime,
                    "name": self.backend.info.name,
                    "torch_version": self.backend.info.torch_version,
                },
            }
        )

    def render(
        self,
        *,
        parent_record: SearchCandidateRecord,
        graph: GradeGraph,
        output_dir: Path,
    ) -> list[RenderedSearchSample]:
        output_dir.mkdir(parents=True, exist_ok=True)
        engine = GradeRenderEngine(self.backend)
        resolver = GraphMaskResolver(graph)
        rendered: list[RenderedSearchSample] = []
        try:
            for sample in parent_record.samples:
                candidate_path = (
                    output_dir
                    / f"refined-{sample.frame_index:08d}.png"
                )
                masks = (
                    resolver.load_batch([sample.frame_index])
                    if resolver.assets
                    else None
                )
                with Image.open(sample.source_path) as source_image:
                    source_array = (
                        np.asarray(
                            source_image.convert("RGB"),
                            dtype=np.float32,
                        )
                        / 255
                    )
                source_tensor = (
                    torch.from_numpy(source_array)
                    .permute(2, 0, 1)
                    .unsqueeze(0)
                )
                raw_output, _ = engine.render_output_batch(
                    source_tensor,
                    graph,
                    timestamps=[sample.time_seconds],
                    masks=masks,
                    mixed_precision=(
                        PREVIEW_PRECISION_BUDGET.mixed_precision_allowed
                    ),
                    clamp_output=False,
                )
                finite = torch.isfinite(raw_output)
                invalid = int(
                    raw_output.numel() - torch.count_nonzero(finite).item()
                )
                outside = float(
                    torch.count_nonzero(
                        finite & ((raw_output < 0) | (raw_output > 1))
                    ).item()
                    / raw_output.numel()
                )
                display_output = torch.nan_to_num(
                    raw_output,
                    nan=0,
                    posinf=1,
                    neginf=0,
                ).clamp(0, 1)
                if graph.renderer_version != LEGACY_RENDERER_VERSION:
                    output_node = next(
                        node
                        for node in graph.ordered_nodes()
                        if node.type == NodeType.OUTPUT_TRANSFORM
                    )
                    destination_log_profile = output_node.parameters.get(
                        "destination_log_profile"
                    )
                    display_output = convert_color_space(
                        display_output,
                        graph.output_color_space,
                        ColorSpace.SRGB,
                        source_log_profile=(
                            destination_log_profile
                            if isinstance(destination_log_profile, str)
                            else None
                        ),
                    ).clamp(0, 1)
                output_array = (
                    display_output[0]
                    .permute(1, 2, 0)
                    .mul(255)
                    .round()
                    .byte()
                    .cpu()
                    .numpy()
                )
                Image.fromarray(output_array, mode="RGB").save(candidate_path)
                height, width = output_array.shape[:2]
                rendered.append(
                    RenderedSearchSample(
                        frame_index=sample.frame_index,
                        time_seconds=sample.time_seconds,
                        source_path=sample.source_path,
                        source_sha256=sample.source_sha256,
                        current_path=sample.candidate_path,
                        current_sha256=sample.candidate_sha256,
                        candidate_path=str(candidate_path.resolve()),
                        candidate_sha256=_sha256_file(candidate_path),
                        width=width,
                        height=height,
                        unclamped_finite_invalid=invalid,
                        unclamped_output_outside_ratio=outside,
                    )
                )
        finally:
            resolver.close()
        return rendered


class ReflectionFrameRenderer:
    renderer_version: str

    def render(
        self,
        *,
        parent_record: SearchCandidateRecord,
        graph: GradeGraph,
        output_dir: Path,
    ) -> list[RenderedSearchSample]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ReflectionPreparationResult:
    preparation: ReflectionPreparation | None
    status: ReflectionOutcomeStatus | None
    detail: str | None
    patch_digest: str | None


class ReflectionRunner:
    def __init__(
        self,
        *,
        renderer: ReflectionFrameRenderer,
        store: ReflectionStore,
    ) -> None:
        self.renderer = renderer
        self.store = store

    def prepare(
        self,
        *,
        run_id: str,
        parent_record: SearchCandidateRecord,
        directive: ReflectionDirective,
        project_thesis_digest: str,
        evaluated_at: datetime,
        budget: ReflectionBudget | None = None,
        compile_policy: ReflectionCompilePolicy | None = None,
        prior_patch_digests: Sequence[str] = (),
    ) -> ReflectionPreparationResult:
        budget = budget or ReflectionBudget()
        compile_result = compile_reflection_directive(
            parent_record=parent_record,
            directive=directive,
            project_thesis_digest=project_thesis_digest,
            evaluated_at=evaluated_at,
            budget=budget,
            policy=compile_policy,
            prior_patch_digests=prior_patch_digests,
        )
        if compile_result.compilation is None:
            return ReflectionPreparationResult(
                preparation=None,
                status=compile_result.status,
                detail=compile_result.detail,
                patch_digest=compile_result.patch_digest,
            )
        compilation = compile_result.compilation
        if len(parent_record.samples) > budget.maximum_rendered_frames:
            return ReflectionPreparationResult(
                preparation=None,
                status=ReflectionOutcomeStatus.STOPPED_BUDGET,
                detail="Reflection frame count exceeds the frozen render budget.",
                patch_digest=compile_result.patch_digest,
            )
        if budget.maximum_model_calls < 2:
            return ReflectionPreparationResult(
                preparation=None,
                status=ReflectionOutcomeStatus.STOPPED_BUDGET,
                detail=(
                    "Blind pairwise reflection validation requires two "
                    "position-swapped model calls."
                ),
                patch_digest=compile_result.patch_digest,
            )
        renderer_input_digest = _renderer_input_digest(
            renderer=self.renderer,
            parent_record=parent_record,
            graph=compilation.graph,
        )
        compilation_digest = canonical_sha256(compilation)
        budget_digest = canonical_sha256(budget)
        cache_key = canonical_sha256(
            {
                "version": REFLECTION_VERSION,
                "compilation_digest": compilation_digest,
                "budget_digest": budget_digest,
                "renderer_version": self.renderer.renderer_version,
                "renderer_input_digest": renderer_input_digest,
            }
        )
        cached = self.store.load_preparation(
            run_id,
            cache_key,
            expected_compilation=compilation,
            expected_budget_digest=budget_digest,
            expected_renderer_version=self.renderer.renderer_version,
            expected_renderer_input_digest=renderer_input_digest,
            parent_record=parent_record,
        )
        if cached is not None:
            return ReflectionPreparationResult(
                preparation=cached,
                status=None,
                detail=None,
                patch_digest=compile_result.patch_digest,
            )
        graph_path, rollback_path, contract_path, _ = (
            self.store.persist_compilation(
                run_id,
                cache_key,
                compilation,
            )
        )
        try:
            samples = self.renderer.render(
                parent_record=parent_record,
                graph=compilation.graph,
                output_dir=self.store.cache_dir(run_id, cache_key) / "rendered",
            )
            if len(samples) != len(parent_record.samples):
                raise ValueError(
                    "reflection renderer did not return every parent evidence frame"
                )
            rendered_root = self.store.cache_dir(
                run_id,
                cache_key,
            ) / "rendered"
            if not _validate_sample_assets(
                samples,
                candidate_root=rendered_root,
            ):
                raise ValueError("reflection renderer returned stale or escaped assets")
            for refined, parent in zip(
                samples,
                parent_record.samples,
                strict=True,
            ):
                if (
                    refined.frame_index != parent.frame_index
                    or refined.time_seconds != parent.time_seconds
                    or Path(refined.source_path).resolve()
                    != Path(parent.source_path).resolve()
                    or refined.source_sha256 != parent.source_sha256
                    or Path(refined.current_path).resolve()
                    != Path(parent.candidate_path).resolve()
                    or refined.current_sha256 != parent.candidate_sha256
                ):
                    raise ValueError(
                        "reflection renderer changed the frozen evidence pairing"
                    )
            proxy = SimpleNamespace(
                compiled=SimpleNamespace(graph=compilation.graph)
            )
            qc = DeterministicSearchHardGates().evaluate(
                candidate=cast(SearchCandidateInput, proxy),
                samples=samples,
                required_check_ids=compilation.required_qc_checks,
            )
            status = (
                CandidateAttemptStatus.HARD_PASS
                if qc.hard_passed
                else CandidateAttemptStatus.HARD_FAIL
            )
            failure_detail = None
        except Exception as exc:
            samples = []
            qc = None
            status = CandidateAttemptStatus.RENDER_FAILED
            failure_detail = f"{type(exc).__name__}: {exc}"
        record = SearchCandidateRecord(
            candidate_id=compilation.contract.candidate_id,
            parent_candidate_id=parent_record.candidate_id,
            scene_id=parent_record.scene_id,
            brief_id=parent_record.brief_id,
            direction=parent_record.direction,
            strategy_id=parent_record.strategy_id,
            compiled_graph_digest=compilation.contract.compiled_graph_digest,
            cache_key=cache_key,
            cache_hit=False,
            status=status,
            samples=samples,
            qc=qc,
            failure_detail=failure_detail,
            graph_path=graph_path,
            undo_graph_path=rollback_path,
            contract_path=contract_path,
            is_refinement=True,
        )
        preparation = ReflectionPreparation(
            run_id=run_id,
            cache_key=cache_key,
            cache_hit=False,
            compilation_digest=compilation_digest,
            budget_digest=budget_digest,
            renderer_version=self.renderer.renderer_version,
            renderer_input_digest=renderer_input_digest,
            compilation=compilation,
            refined_record=record,
            rendered_frames=len(samples),
        )
        self.store.save_preparation(preparation)
        return ReflectionPreparationResult(
            preparation=preparation,
            status=None,
            detail=None,
            patch_digest=compile_result.patch_digest,
        )


def build_critic_reflection_directive(
    *,
    parent_record: SearchCandidateRecord,
    critique: VisualCritique,
    target_dimensions: Sequence[CritiqueDimension],
    targets: Sequence[ReflectionParameterTarget],
    hypothesis: str,
    expected_improvement: str,
    maximum_allowed_regression: float,
) -> ReflectionDirective:
    if critique.candidate_id != parent_record.candidate_id:
        raise ValueError("Critic evidence belongs to another reflection parent")
    if not target_dimensions:
        raise ValueError("Critic reflection requires at least one target dimension")
    scores = {item.dimension: item for item in critique.scores}
    unknown = set(target_dimensions) - set(scores)
    if unknown:
        raise ValueError(f"Critic reflection dimensions are missing: {sorted(unknown)}")
    evidence_ids = sorted(
        {
            evidence_id
            for dimension in target_dimensions
            for evidence_id in scores[dimension].counterevidence_ids
        }
    )
    confidence = min(scores[item].confidence for item in target_dimensions)
    seed = canonical_sha256(
        {
            "parent_candidate_id": parent_record.candidate_id,
            "critique_digest": canonical_sha256(critique),
            "target_dimensions": [item.value for item in target_dimensions],
            "targets": [item.model_dump(mode="json") for item in targets],
            "hypothesis": hypothesis,
            "expected_improvement": expected_improvement,
        }
    )
    return ReflectionDirective(
        directive_id=f"directive:critic:{seed[:24]}",
        source=ReflectionSource.CRITIC,
        parent_candidate_id=parent_record.candidate_id,
        hypothesis=hypothesis,
        target_dimensions=list(target_dimensions),
        evidence_ids=evidence_ids,
        expected_improvement=expected_improvement,
        maximum_allowed_regression=maximum_allowed_regression,
        targets=list(targets),
        confidence=confidence,
    )


_TOWARD_NEUTRAL_DIMENSIONS = {
    CritiqueDimension.NATURALNESS,
    CritiqueDimension.OVERGRADING_RISK,
    CritiqueDimension.CONTEXT_CONSISTENCY,
}
_DIMENSION_PARAMETER_PREFERENCES: dict[
    CritiqueDimension,
    tuple[str, ...],
] = {
    CritiqueDimension.CONCEPT_ALIGNMENT: (
        "contrast",
        "saturation",
        "highlights",
        "shadows",
        "exposure",
        "temperature",
        "tint",
    ),
    CritiqueDimension.SCENE_SUPPORT: (
        "exposure",
        "contrast",
        "highlights",
        "shadows",
        "saturation",
        "temperature",
        "tint",
    ),
    CritiqueDimension.VISUAL_HIERARCHY: (
        "contrast",
        "highlights",
        "shadows",
        "exposure",
        "saturation",
    ),
    CritiqueDimension.EXPRESSIVE_STRENGTH: (
        "contrast",
        "saturation",
        "temperature",
        "tint",
        "highlights",
        "shadows",
        "exposure",
    ),
    CritiqueDimension.NATURALNESS: (
        "saturation",
        "contrast",
        "temperature",
        "tint",
        "highlights",
        "shadows",
        "exposure",
    ),
    CritiqueDimension.DISTINCTIVENESS: (
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
        "exposure",
    ),
    CritiqueDimension.OVERGRADING_RISK: (
        "saturation",
        "contrast",
        "highlights",
        "shadows",
        "temperature",
        "tint",
        "exposure",
    ),
    CritiqueDimension.CONTEXT_CONSISTENCY: (
        "temperature",
        "tint",
        "exposure",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
    ),
}


def plan_critic_reflection_directive(
    *,
    parent_record: SearchCandidateRecord,
    critique: VisualCritique,
    maximum_allowed_regression: float = 0.05,
) -> ReflectionDirective:
    """Compile the weakest evidenced Critic dimension into one bounded target.

    This planner is intentionally deterministic. It can only move one numeric
    parameter on a compiler-owned node, uses the immutable operation-card
    domain, and moves naturalness/overgrading/continuity concerns toward the
    neutral value. It does not decide whether the resulting child is accepted;
    the normal render, hard-QC, swapped pairwise, and Pareto gates still apply.
    """

    _validate_critique_binding(parent_record, critique)
    parent_graph = _load_parent_graph(parent_record)
    from colorgraph.agent.operation_catalog import (  # avoid import cycle
        build_project_operation_registry,
        operation_card_id,
    )

    registry = build_project_operation_registry(parent_graph)
    score_candidates = [
        score
        for score in critique.scores
        if score.counterevidence_ids and score.confidence >= 0.5
    ]
    if not score_candidates:
        raise ValueError(
            "Critic reflection requires confident, cited counterevidence"
        )

    def quality(score: CritiqueScore) -> float:
        return (
            1 - score.score
            if score.dimension == CritiqueDimension.OVERGRADING_RISK
            else score.score
        )

    score_candidates.sort(
        key=lambda score: (
            quality(score),
            -score.confidence,
            score.dimension.value,
        )
    )
    compiler_nodes = [
        node
        for node in parent_graph.nodes
        if str(node.metadata.get("source", "")).startswith(
            "colorgraph.deterministic-strategy-compiler/"
        )
        and node.metadata.get("strategy_id") == parent_record.strategy_id
    ]
    if not compiler_nodes:
        raise ValueError(
            "Critic reflection parent has no matching compiler-owned node"
        )

    for score in score_candidates:
        preferences = _DIMENSION_PARAMETER_PREFERENCES[score.dimension]
        parameter_candidates: list[
            tuple[int, str, str, float, float, float, GradeNode]
        ] = []
        for node in compiler_nodes:
            for parameter, raw_value in node.parameters.items():
                card = registry.get(
                    str(node.metadata.get("operation_card_id", ""))
                )
                if card is None:
                    try:
                        operation = StrategyOperation(
                            str(node.metadata.get("strategy_operation", ""))
                        )
                        inferred_card_id = operation_card_id(
                            operation,
                            parameter,
                            mask_target=(
                                node.spatial_scope.target
                                if operation
                                in {
                                    StrategyOperation.MASKED_GRADE,
                                    StrategyOperation.COMPOSITE_MASK,
                                }
                                else None
                            ),
                        )
                    except ValueError:
                        continue
                    card = registry.get(inferred_card_id)
                if card is None:
                    continue
                specs_by_renderer_parameter = {
                    card.parameter_mapping.get(spec.name, spec.name): spec
                    for spec in card.parameters
                }
                spec = specs_by_renderer_parameter.get(parameter)
                if (
                    spec is None
                    or isinstance(raw_value, bool)
                    or not isinstance(raw_value, (int, float))
                ):
                    continue
                preference = (
                    preferences.index(parameter)
                    if parameter in preferences
                    else len(preferences)
                )
                parameter_candidates.append(
                    (
                        preference,
                        node.id,
                        parameter,
                        float(raw_value),
                        spec.minimum,
                        spec.maximum,
                        node,
                    )
                )
        parameter_candidates.sort(key=lambda item: item[:3])
        for (
            _,
            node_id,
            parameter,
            current,
            minimum,
            maximum,
            raw_node,
        ) in parameter_candidates:
            node = raw_node
            domain = maximum - minimum
            if domain <= 0:
                continue
            neutral = 0.0 if minimum <= 0 <= maximum else (minimum + maximum) / 2
            toward_neutral = score.dimension in _TOWARD_NEUTRAL_DIMENSIONS
            if toward_neutral and math.isclose(current, neutral, abs_tol=1e-12):
                continue
            if toward_neutral:
                direction = (
                    PatchDirection.DECREASE
                    if current > neutral
                    else PatchDirection.INCREASE
                )
            elif current < neutral:
                direction = PatchDirection.DECREASE
            else:
                direction = PatchDirection.INCREASE
            available = (
                maximum - current
                if direction == PatchDirection.INCREASE
                else current - minimum
            )
            if available <= 1e-12 and not toward_neutral:
                direction = (
                    PatchDirection.DECREASE
                    if direction == PatchDirection.INCREASE
                    else PatchDirection.INCREASE
                )
                available = (
                    maximum - current
                    if direction == PatchDirection.INCREASE
                    else current - minimum
                )
            absolute_delta = min(domain * 0.025, available)
            if absolute_delta <= 1e-12:
                continue
            scope = StrategyScope(
                project_id=parent_graph.project_id,
                scene_id=node.temporal_scope.scene_id,
                shot_id=node.temporal_scope.shot_id,
                time_range=(
                    TimeSpan(
                        start_seconds=(
                            node.temporal_scope.time_range.start_seconds
                        ),
                        end_seconds=node.temporal_scope.time_range.end_seconds,
                    )
                    if node.temporal_scope.time_range is not None
                    else None
                ),
                mask_target=node.spatial_scope.target,
            )
            return build_critic_reflection_directive(
                parent_record=parent_record,
                critique=critique,
                target_dimensions=[score.dimension],
                targets=[
                    ReflectionParameterTarget(
                        node_id=node_id,
                        parameter=parameter,
                        direction=direction,
                        expected_current_value=current,
                        absolute_delta=absolute_delta,
                        minimum_allowed_value=minimum,
                        maximum_allowed_value=maximum,
                        scope=scope,
                    )
                ],
                hypothesis=(
                    f"A single bounded {parameter} change may improve "
                    f"{score.dimension.value} while every other node remains locked."
                ),
                expected_improvement=(
                    f"Improve cited {score.dimension.value} evidence without "
                    "reducing deterministic technical margin or untargeted dimensions."
                ),
                maximum_allowed_regression=maximum_allowed_regression,
            )
    raise ValueError(
        "Critic reflection found no safe non-neutral compiler parameter target"
    )


def interpret_user_feedback(
    *,
    feedback: str,
    parent_strategy_id: str,
    parent_thesis_digest: str,
) -> UserFeedbackBranch:
    normalized = feedback.strip().casefold()
    if not normalized:
        raise ValueError("user feedback must not be empty")
    patterns: tuple[tuple[UserFeedbackAxis, tuple[str, ...]], ...] = (
        (
            UserFeedbackAxis.EXPANSIVE,
            ("更壮阔", "壮阔", "majestic", "more expansive", "more epic"),
        ),
        (
            UserFeedbackAxis.RESTRAINED,
            ("更克制", "克制", "restrained", "subtler", "more subtle"),
        ),
        (
            UserFeedbackAxis.LONELY,
            ("更孤寂", "孤寂", "lonely", "more solitary", "more isolated"),
        ),
        (
            UserFeedbackAxis.DREAMLIKE,
            ("更梦幻", "梦幻", "dreamlike", "more ethereal", "more surreal"),
        ),
    )
    axes = [
        axis
        for axis, phrases in patterns
        if any(phrase in normalized for phrase in phrases)
    ]
    if not axes:
        raise ValueError(
            "feedback is not one of the bounded first-version creative axes"
        )
    dimensions_by_axis = {
        UserFeedbackAxis.EXPANSIVE: (
            CritiqueDimension.EXPRESSIVE_STRENGTH,
            CritiqueDimension.VISUAL_HIERARCHY,
        ),
        UserFeedbackAxis.RESTRAINED: (
            CritiqueDimension.NATURALNESS,
            CritiqueDimension.OVERGRADING_RISK,
        ),
        UserFeedbackAxis.LONELY: (
            CritiqueDimension.CONCEPT_ALIGNMENT,
            CritiqueDimension.SCENE_SUPPORT,
        ),
        UserFeedbackAxis.DREAMLIKE: (
            CritiqueDimension.DISTINCTIVENESS,
            CritiqueDimension.CONCEPT_ALIGNMENT,
        ),
    }
    dimensions: list[CritiqueDimension] = []
    for axis in axes:
        for dimension in dimensions_by_axis[axis]:
            if dimension not in dimensions:
                dimensions.append(dimension)
    new_thesis_phrases = (
        "rewrite thesis",
        "new thesis",
        "reinterpret the film",
        "改写命题",
        "重新命题",
        "重新诠释全片",
    )
    requires_branch = any(
        phrase in normalized for phrase in new_thesis_phrases
    )
    branch_seed = canonical_sha256(
        {
            "parent_strategy_id": parent_strategy_id,
            "parent_thesis_digest": parent_thesis_digest,
            "feedback": feedback.strip(),
            "axes": [item.value for item in axes],
            "requires_new_thesis_branch": requires_branch,
        }
    )
    return UserFeedbackBranch(
        branch_id=f"feedback-branch:{branch_seed[:24]}",
        parent_strategy_id=parent_strategy_id,
        parent_thesis_digest=parent_thesis_digest,
        raw_feedback=feedback.strip(),
        axes=axes,
        target_dimensions=dimensions,
        requires_new_thesis_branch=requires_branch,
    )


def build_user_reflection_directive(
    *,
    branch: UserFeedbackBranch,
    parent_record: SearchCandidateRecord,
    targets: Sequence[ReflectionParameterTarget],
    maximum_allowed_regression: float,
) -> ReflectionDirective:
    if branch.parent_strategy_id != parent_record.strategy_id:
        raise ValueError("user feedback branch belongs to another strategy")
    if branch.requires_new_thesis_branch:
        raise ValueError(
            "thesis-rewrite feedback must create a new explicit branch, not a patch"
        )
    return ReflectionDirective(
        directive_id=f"directive:user:{branch.branch_id.split(':')[-1]}",
        source=ReflectionSource.USER,
        parent_candidate_id=parent_record.candidate_id,
        hypothesis=(
            "A bounded update to the existing strategy should better express "
            + ", ".join(item.value for item in branch.axes)
            + "."
        ),
        target_dimensions=branch.target_dimensions,
        evidence_ids=[f"feedback:{branch.branch_id}"],
        expected_improvement=(
            "Improve only the declared feedback dimensions without reanalyzing "
            "the project or rewriting its thesis."
        ),
        maximum_allowed_regression=maximum_allowed_regression,
        targets=list(targets),
        confidence=1,
    )


def promote_failure_case_for_reuse(
    *,
    failure_case: FailureCase,
    review: FailureCaseReuseReview,
) -> FailureCaseReuseArtifact:
    source_digest = canonical_sha256(failure_case)
    if (
        review.source_failure_id != failure_case.failure_id
        or review.source_failure_digest != source_digest
    ):
        raise ValueError("failure reuse review belongs to another source case")
    seed = canonical_sha256(
        {
            "source_failure_digest": source_digest,
            "review": review.model_dump(mode="json"),
        }
    )
    sanitized = FailureCase(
        failure_id=f"failure:reusable:{seed[:24]}",
        context_asset_id=review.sanitized_context_asset_id,
        operation_summary=review.sanitized_operation_summary,
        actual_harm=review.sanitized_actual_harm,
        responsible_node_ids=review.sanitized_responsible_node_roles,
        repair_summary=review.sanitized_repair_summary,
        evidence_ids=review.sanitized_evidence_ids,
        reviewed_for_reuse=True,
        contains_private_data=False,
    )
    return FailureCaseReuseArtifact(
        artifact_id=f"failure-artifact:{seed[:24]}",
        source_failure_id=failure_case.failure_id,
        source_failure_digest=source_digest,
        target=review.target,
        version=review.version,
        reviewer_id=review.reviewer_id,
        reviewed_at=review.reviewed_at,
        sanitized_failure_case=sanitized,
    )


def _critique_map(
    report: PairwiseVisualCriticReport,
) -> dict[str, VisualCritique]:
    return {item.candidate_id: item for item in report.critiques}


def _validate_critique_binding(
    record: SearchCandidateRecord,
    critique: VisualCritique,
) -> None:
    if critique.candidate_id != record.candidate_id:
        raise ValueError("reflection critique references another candidate")
    if record.qc is None:
        raise ValueError("reflection critique candidate has no QC evidence")
    if critique.technical_integrity_sha256 != canonical_sha256(record.qc):
        raise ValueError("reflection critique QC digest is stale")
    if critique.rendered_sha256 != _parent_rendered_digest(record):
        raise ValueError("reflection critique rendered digest is stale")


def _dimension_deltas(
    *,
    parent: VisualCritique,
    refined: VisualCritique,
    targeted: set[CritiqueDimension],
) -> list[ReflectionDimensionDelta]:
    parent_scores = {item.dimension: item.score for item in parent.scores}
    refined_scores = {item.dimension: item.score for item in refined.scores}
    return [
        ReflectionDimensionDelta(
            dimension=dimension,
            parent_score=parent_scores[dimension],
            refined_score=refined_scores[dimension],
            improvement=(
                parent_scores[dimension] - refined_scores[dimension]
                if dimension == CritiqueDimension.OVERGRADING_RISK
                else refined_scores[dimension] - parent_scores[dimension]
            ),
            targeted=dimension in targeted,
        )
        for dimension in CritiqueDimension
    ]


def _failure_case(
    *,
    preparation: ReflectionPreparation,
    status: ReflectionOutcomeStatus,
    reasons: Sequence[str],
    report: PairwiseVisualCriticReport | None,
) -> FailureCase:
    compilation = preparation.compilation
    evidence_ids = {
        f"patch:{compilation.patch.patch_id}",
        f"parent-qc:{compilation.parent_qc_digest[:24]}",
    }
    if report is not None:
        evidence_ids.add(f"critic-report:{canonical_sha256(report)[:24]}")
        for critique in report.critiques:
            for score in critique.scores:
                evidence_ids.update(score.evidence_ids)
                evidence_ids.update(score.counterevidence_ids)
    record = preparation.refined_record
    if record.qc is not None:
        evidence_ids.update(
            f"qc:{record.candidate_id}:{item.check_id}"
            for item in record.qc.checks
        )
    seed = canonical_sha256(
        {
            "patch_id": compilation.patch.patch_id,
            "status": status,
            "reasons": list(reasons),
            "evidence_ids": sorted(evidence_ids),
        }
    )
    return FailureCase(
        failure_id=f"failure:reflection:{seed[:24]}",
        candidate_id=record.candidate_id,
        patch_id=compilation.patch.patch_id,
        context_asset_id=(
            "context:project:"
            f"{canonical_sha256({'project_id': compilation.graph.project_id})[:16]}:"
            f"rendered:{compilation.parent_rendered_digest[:24]}"
        ),
        operation_summary=(
            "Attempted bounded creative reflection on "
            + ", ".join(
                sorted(
                    {
                        f"{item.node_id}.{item.parameter}"
                        for item in compilation.patch.changes
                    }
                )
            )
        ),
        actual_harm="; ".join(reasons),
        responsible_node_ids=sorted(
            {item.node_id for item in compilation.patch.changes}
        ),
        repair_summary="Rolled back to the immutable parent candidate graph.",
        evidence_ids=sorted(evidence_ids),
        reviewed_for_reuse=False,
        contains_private_data=True,
    )


def finalize_reflection(
    *,
    parent_record: SearchCandidateRecord,
    preparation: ReflectionPreparation,
    pairwise_report: PairwiseVisualCriticReport,
    policy: ReflectionEvaluationPolicy | None = None,
    store: ReflectionStore | None = None,
) -> ReflectionOutcome:
    policy = policy or ReflectionEvaluationPolicy()
    compilation = preparation.compilation
    refined_record = preparation.refined_record
    if not _validate_sample_assets(parent_record.samples):
        raise ValueError("reflection parent evidence assets changed before finalize")
    if refined_record.status != CandidateAttemptStatus.RENDER_FAILED:
        if (
            not _validate_sample_assets(refined_record.samples)
            or len(refined_record.samples) != len(parent_record.samples)
        ):
            raise ValueError(
                "reflection refined evidence assets changed before finalize"
            )
        for refined, parent in zip(
            refined_record.samples,
            parent_record.samples,
            strict=True,
        ):
            if (
                refined.frame_index != parent.frame_index
                or refined.time_seconds != parent.time_seconds
                or Path(refined.source_path).resolve()
                != Path(parent.source_path).resolve()
                or refined.source_sha256 != parent.source_sha256
                or Path(refined.current_path).resolve()
                != Path(parent.candidate_path).resolve()
                or refined.current_sha256 != parent.candidate_sha256
            ):
                raise ValueError(
                    "reflection evidence pairing changed before finalize"
                )
    if compilation.patch.parent_candidate_id != parent_record.candidate_id:
        raise ValueError("reflection preparation belongs to another parent")
    if refined_record.parent_candidate_id != parent_record.candidate_id:
        raise ValueError("refined record is not a child of the parent candidate")
    if compilation.parent_qc_digest != canonical_sha256(parent_record.qc):
        raise ValueError("reflection parent QC changed after compilation")
    if compilation.parent_rendered_digest != _parent_rendered_digest(parent_record):
        raise ValueError("reflection parent render changed after compilation")
    if graph_digest(compilation.undo_graph) != parent_record.compiled_graph_digest:
        raise ValueError("reflection rollback graph is stale")
    if _mask_digests(compilation.graph) != compilation.locked_mask_digests:
        raise ValueError("reflection modified a locked mask asset")

    critiques = _critique_map(pairwise_report)
    expected_candidates = {
        parent_record.candidate_id,
        refined_record.candidate_id,
    }
    report_valid = (
        set(critiques) == expected_candidates
        and pairwise_report.position_swap_consistent
        and all(item.valid for item in pairwise_report.output_audits)
    )
    reasons: list[str] = []
    status: ReflectionOutcomeStatus
    deltas: list[ReflectionDimensionDelta] = []
    if (
        refined_record.status != CandidateAttemptStatus.HARD_PASS
        or refined_record.qc is None
        or not refined_record.qc.hard_passed
    ):
        status = ReflectionOutcomeStatus.REJECTED_HARD_GATE
        if refined_record.qc is not None:
            reasons.extend(
                f"hard_gate:{item.check_id}"
                for item in refined_record.qc.checks
                if not item.passed
            )
        else:
            reasons.append(
                refined_record.failure_detail or "refined render or QC failed"
            )
    elif not report_valid:
        status = ReflectionOutcomeStatus.REJECTED_PAIRWISE
        reasons.append(
            "blind pairwise report is missing, invalid, or position inconsistent"
        )
    else:
        parent_critique = critiques[parent_record.candidate_id]
        refined_critique = critiques[refined_record.candidate_id]
        _validate_critique_binding(parent_record, parent_critique)
        _validate_critique_binding(refined_record, refined_critique)
        targeted = set(compilation.patch.target_dimensions)
        deltas = _dimension_deltas(
            parent=parent_critique,
            refined=refined_critique,
            targeted=targeted,
        )
        refined_scores = {
            item.dimension: item for item in refined_critique.scores
        }
        target_confidence = min(
            refined_scores[item].confidence for item in targeted
        )
        parent_margin = parent_record.qc.technical_margin
        refined_margin = refined_record.qc.technical_margin
        intent_dimensions = {
            CritiqueDimension.CONCEPT_ALIGNMENT,
            CritiqueDimension.SCENE_SUPPORT,
        } - targeted
        intent_regressions = [
            item
            for item in deltas
            if item.dimension in intent_dimensions
            and item.improvement
            < -compilation.patch.maximum_allowed_regression
        ]
        other_regressions = [
            item
            for item in deltas
            if not item.targeted
            and item.improvement
            < -compilation.patch.maximum_allowed_regression
        ]
        target_deltas = [item.improvement for item in deltas if item.targeted]
        if target_confidence < policy.minimum_critic_confidence:
            status = ReflectionOutcomeStatus.STOPPED_LOW_CONFIDENCE
            reasons.append(
                f"target confidence {target_confidence:.6f} is below "
                f"{policy.minimum_critic_confidence:.6f}"
            )
        elif (
            refined_margin
            < parent_margin - policy.maximum_technical_margin_regression
        ):
            status = ReflectionOutcomeStatus.REJECTED_HARD_GATE
            reasons.append(
                "deterministic technical margin regressed from "
                f"{parent_margin:.6f} to {refined_margin:.6f}"
            )
        elif intent_regressions:
            status = ReflectionOutcomeStatus.REJECTED_INTENT_DRIFT
            reasons.extend(
                f"intent_drift:{item.dimension.value}:{item.improvement:.6f}"
                for item in intent_regressions
            )
        elif other_regressions:
            status = ReflectionOutcomeStatus.REJECTED_REGRESSION
            reasons.extend(
                f"regression:{item.dimension.value}:{item.improvement:.6f}"
                for item in other_regressions
            )
        elif (
            not target_deltas
            or any(value < -1e-12 for value in target_deltas)
            or max(target_deltas) < policy.minimum_target_improvement
        ):
            status = ReflectionOutcomeStatus.REJECTED_NO_PARETO_IMPROVEMENT
            reasons.append(
                "the patch produced no Pareto improvement in its target dimensions"
            )
        elif (
            pairwise_report.preferred_candidate_id
            != refined_record.candidate_id
        ):
            status = ReflectionOutcomeStatus.REJECTED_PAIRWISE
            reasons.append(
                "blind pairwise comparison did not prefer the refined candidate"
            )
        else:
            status = ReflectionOutcomeStatus.ACCEPTED

    accepted = status == ReflectionOutcomeStatus.ACCEPTED
    if accepted:
        selected_id = refined_record.candidate_id
        selected_digest = compilation.contract.compiled_graph_digest
        failure = None
    else:
        selected_id = parent_record.candidate_id
        selected_digest = parent_record.compiled_graph_digest
        failure = _failure_case(
            preparation=preparation,
            status=status,
            reasons=reasons,
            report=pairwise_report,
        )
    outcome = ReflectionOutcome(
        status=status,
        accepted=accepted,
        patch_id=compilation.patch.patch_id,
        parent_candidate_id=parent_record.candidate_id,
        refined_candidate_id=refined_record.candidate_id,
        selected_candidate_id=selected_id,
        selected_graph_digest=selected_digest,
        rollback_graph_digest=graph_digest(compilation.undo_graph),
        pairwise_report_digest=canonical_sha256(pairwise_report),
        dimension_deltas=deltas,
        stop_reasons=reasons,
        failure_case=failure,
        current_graph_unchanged=True,
    )
    if store is not None:
        store.save_outcome(
            preparation.run_id,
            preparation.cache_key,
            outcome,
        )
    return outcome
