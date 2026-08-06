from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from colorgraph.agent.creative_compiler import (
    MANDATORY_COMPILER_QC_CHECKS,
    CompilationPolicy,
    CompiledGraphCandidate,
    compile_color_strategy,
)
from colorgraph.agent.creative_contracts import (
    AdjustmentDirection,
    AllowedCreativeDeviation,
    BaselineRelationship,
    ColorLanguageCue,
    ColorProperty,
    ColorStrategy,
    ContextBudget,
    ContrastCharacter,
    CreativeBrief,
    CreativeDirection,
    EvidenceKind,
    PaletteCharacter,
    ProjectContextPack,
    ProjectVisualThesis,
    ProtectedAttribute,
    SceneNarrativeRole,
    StrategyAction,
    StrategyOperation,
    StrategyParameter,
    StrategyScope,
    StrictFrozenModel,
    VisualHierarchyItem,
    canonical_sha256,
)
from colorgraph.agent.creative_corpus import CreativeCorpusAuditReport
from colorgraph.agent.creative_critic import (
    BlindCriticRequestContext,
    CreativeModelIdentity,
    CriticCalibrationGate,
    PairwiseVisualCriticReport,
    VisualCriticValidationError,
    build_blind_pairwise_critic_requests,
    run_blind_pairwise_critic,
)
from colorgraph.agent.creative_director import (
    ClosedBookDirectorResult,
    CreativeDirectorValidationError,
    audit_closed_book_thesis,
    build_closed_book_director_request,
    run_closed_book_director,
)
from colorgraph.agent.creative_evidence import (
    ProjectEvidenceBuildResult,
    build_project_evidence_pack,
)
from colorgraph.agent.creative_provider import (
    CreativeProviderRuntime,
    CreativeRole,
    FallbackDecision,
    ProviderImage,
    provider_runtime_configuration_digest,
)
from colorgraph.agent.creative_reflection import (
    LocalReflectionFrameRenderer,
    ReflectionBudget,
    ReflectionOutcome,
    ReflectionRunner,
    ReflectionStore,
    finalize_reflection,
    plan_critic_reflection_directive,
)
from colorgraph.agent.creative_retrieval import (
    CreativeKnowledgeIndex,
    RetrievalFilterContext,
    retrieve_creative_possibilities,
)
from colorgraph.agent.creative_search import (
    BudgetedCandidateSearchRunner,
    CandidateAttemptStatus,
    CandidateSearchBudget,
    CandidateSearchResult,
    CandidateSearchState,
    CandidateSearchStatus,
    CandidateSearchStore,
    DeterministicSearchHardGates,
    LocalCandidateFrameRenderer,
    SearchCandidateInput,
    SearchCandidateRecord,
)
from colorgraph.agent.creative_strategy import (
    ColorGraphCapabilityCatalog,
    ColorStrategistResult,
    ColorStrategyValidationError,
    audit_color_strategy_set,
    build_color_strategist_request,
    run_color_strategist,
)
from colorgraph.agent.creative_ui import (
    AgentApplicationManifest,
    AgentRunUISnapshot,
    AgentUIBudgetSnapshot,
    AgentUICritiqueDimension,
    AgentUIDirectionSnapshot,
    AgentUIEvidenceSnapshot,
    AgentUIProviderSnapshot,
    AgentUIRunStatus,
    AgentUISceneSnapshot,
    AgentUISelectionSnapshot,
    AgentUIStage,
    AgentUIStore,
    CandidateApplicationAsset,
    seal_snapshot,
)
from colorgraph.agent.operation_catalog import (
    build_project_operation_registry,
    build_renderer_capability_catalog,
    operation_card_id,
)
from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import GradeGraph
from colorgraph.grading.looks import graph_digest

OFFLINE_CREATIVE_PIPELINE_VERSION = "colorgraph.offline-creative-pipeline/v1"

_DIRECTION_TITLES = {
    CreativeDirection.FAITHFUL: "Source-faithful study",
    CreativeDirection.AMPLIFIED: "Evidence-led amplification",
    CreativeDirection.COUNTERPOINT: "Restrained counterpoint",
}
_DIRECTION_INTERPRETATIONS = {
    CreativeDirection.FAITHFUL: (
        "Preserve the source relationship and let the observed hierarchy remain primary."
    ),
    CreativeDirection.AMPLIFIED: (
        "Strengthen the most legible visual relationship while retaining measured detail."
    ),
    CreativeDirection.COUNTERPOINT: (
        "Test a quieter opposing relationship that keeps the source evidence recognizable."
    ),
}
_DIRECTION_EMOTIONS = {
    CreativeDirection.FAITHFUL: "observational restraint",
    CreativeDirection.AMPLIFIED: "controlled emphasis",
    CreativeDirection.COUNTERPOINT: "quiet tension",
}
_DIRECTION_HIERARCHY_TARGETS = {
    CreativeDirection.FAITHFUL: "source-relationship",
    CreativeDirection.AMPLIFIED: "primary-hierarchy",
    CreativeDirection.COUNTERPOINT: "negative-space",
}
_DIRECTION_CUES = {
    CreativeDirection.FAITHFUL: (
        "color_separation",
        ColorProperty.COLOR_SEPARATION,
        AdjustmentDirection.PRESERVE,
        0.0,
        0.2,
    ),
    CreativeDirection.AMPLIFIED: (
        "contrast",
        ColorProperty.CONTRAST,
        AdjustmentDirection.INCREASE,
        0.3,
        0.45,
    ),
    CreativeDirection.COUNTERPOINT: (
        "saturation",
        ColorProperty.SATURATION,
        AdjustmentDirection.DECREASE,
        0.4,
        0.55,
    ),
}
_STRATEGY_PARAMETERS = {
    CreativeDirection.FAITHFUL: (
        StrategyOperation.TONE,
        "contrast",
        ColorProperty.CONTRAST,
        AdjustmentDirection.PRESERVE,
        -0.08,
        0.0,
        0.08,
    ),
    CreativeDirection.AMPLIFIED: (
        StrategyOperation.TONE,
        "contrast",
        ColorProperty.CONTRAST,
        AdjustmentDirection.INCREASE,
        0.30,
        0.36,
        0.45,
    ),
    CreativeDirection.COUNTERPOINT: (
        StrategyOperation.LOOK,
        "saturation",
        ColorProperty.SATURATION,
        AdjustmentDirection.DECREASE,
        -0.55,
        -0.45,
        -0.40,
    ),
}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _safe_component(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    digest = canonical_sha256({"value": value})[:12]
    return f"{label[:48] or 'run'}-{digest}"


class OfflineCreativeRunRequest(StrictFrozenModel):
    schema_version: Literal["colorgraph.offline-creative-run-request/v1"] = (
        "colorgraph.offline-creative-run-request/v1"
    )
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    user_intent: str | None = Field(default=None, max_length=4_096)
    created_at: AwareDatetime
    provider_shadow_enabled: bool = False
    reflection_shadow_enabled: bool = False
    provider_configuration_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    cloud_upload_consent: bool = False
    critic_calibration_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    knowledge_corpus_id: str | None = None
    knowledge_corpus_version: str | None = None
    knowledge_corpus_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    context_budget: ContextBudget
    search_budget: CandidateSearchBudget
    maximum_pipeline_wall_seconds: float = Field(default=600, gt=0)

    @model_validator(mode="after")
    def validate_pipeline_budget(self) -> OfflineCreativeRunRequest:
        if (
            self.search_budget.maximum_wall_seconds
            > self.maximum_pipeline_wall_seconds
        ):
            raise ValueError(
                "candidate-search wall budget cannot exceed the pipeline wall budget"
            )
        corpus_identity = (
            self.knowledge_corpus_id,
            self.knowledge_corpus_version,
            self.knowledge_corpus_sha256,
        )
        if any(item is not None for item in corpus_identity) and not all(
            item is not None for item in corpus_identity
        ):
            raise ValueError(
                "knowledge corpus id, version, and digest must be configured together"
            )
        if self.provider_shadow_enabled:
            if self.provider_configuration_sha256 is None:
                raise ValueError(
                    "provider Shadow runs require an immutable configuration digest"
                )
        elif (
            self.provider_configuration_sha256 is not None
            or self.cloud_upload_consent
            or self.critic_calibration_sha256 is not None
        ):
            raise ValueError(
                "provider configuration, cloud consent, and Critic calibration "
                "cannot be set when provider Shadow is disabled"
            )
        if self.reflection_shadow_enabled:
            if not self.provider_shadow_enabled:
                raise ValueError(
                    "Reflection Shadow requires the provider pipeline"
                )
            if self.search_budget.maximum_refinements != 1:
                raise ValueError(
                    "Reflection Shadow requires exactly one frozen refinement"
                )
            if self.search_budget.maximum_model_calls < 2:
                raise ValueError(
                    "Reflection Shadow requires two position-swapped validation calls"
                )
        return self


@dataclass(frozen=True, slots=True)
class OfflineCreativePipelineResult:
    snapshot: AgentRunUISnapshot
    search: CandidateSearchResult | None
    cancelled: bool


@dataclass(frozen=True, slots=True)
class _PipelineReflectionResult:
    stage_status: str
    stage_executed: bool
    completed: bool
    parent_record: SearchCandidateRecord | None
    refined_record: SearchCandidateRecord | None
    selected_record: SearchCandidateRecord | None
    outcome: ReflectionOutcome | None


def _scene_evidence(
    context: ProjectContextPack,
    scene_id: str,
) -> tuple[list[str], list[str], bool]:
    scoped = [
        item
        for item in context.evidence
        if item.scene_id in {None, scene_id}
    ]
    scene_specific = [item for item in scoped if item.scene_id == scene_id]
    visual = [
        item
        for item in scene_specific
        if item.kind in {EvidenceKind.FRAME, EvidenceKind.CONTACT_SHEET}
    ]
    support = visual[:1] or scene_specific[:1] or scoped[:1]
    counter = [
        item
        for item in scene_specific
        if item.evidence_id not in {value.evidence_id for value in support}
    ][:1]
    if not counter:
        counter = support
    return (
        [item.evidence_id for item in support],
        [item.evidence_id for item in counter],
        bool(visual) and len(scene_specific) >= 2,
    )


def build_offline_visual_thesis(
    *,
    context: ProjectContextPack,
    graph: GradeGraph,
    user_intent: str | None = None,
) -> ProjectVisualThesis:
    """Build a conservative, evidence-bound fallback without claiming model creativity."""

    if set(context.allowed_scene_ids) != {scene.id for scene in graph.scenes}:
        raise ValueError("offline Director graph and evidence scene scopes differ")
    briefs: list[CreativeBrief] = []
    roles: list[SceneNarrativeRole] = []
    deviations: list[AllowedCreativeDeviation] = []
    project_support: list[str] = []
    project_counter: list[str] = []
    for scene in graph.scenes:
        support, counter, sufficient = _scene_evidence(context, scene.id)
        project_support.extend(support)
        project_counter.extend(counter)
        roles.append(
            SceneNarrativeRole(
                scene_id=scene.id,
                shot_ids=list(scene.shot_ids),
                narrative_role=(
                    f"Observed movement {scene.index + 1} in the project sequence."
                ),
                relationship_to_project_thesis=(
                    "Maintain a shared restrained language while preserving this "
                    "scene's measured visual hierarchy."
                ),
                evidence_ids=support,
            )
        )
        deviations.append(
            AllowedCreativeDeviation(
                scene_id=scene.id,
                property=ColorProperty.COLOR_SEPARATION,
                maximum_normalized_strength=0.35,
                rationale=(
                    "A bounded departure is allowed only when the cited scene "
                    "evidence remains legible."
                ),
                evidence_ids=support,
            )
        )
        for direction in CreativeDirection:
            target, property_name, adjustment, minimum, maximum = (
                _DIRECTION_CUES[direction]
            )
            briefs.append(
                CreativeBrief(
                    brief_id=f"brief:{scene.id}:{direction.value}",
                    scene_id=scene.id,
                    direction=direction,
                    interpretation=_DIRECTION_INTERPRETATIONS[direction],
                    evidence_for=support,
                    evidence_against=counter,
                    emotional_target=_DIRECTION_EMOTIONS[direction],
                    visual_hierarchy=[
                        VisualHierarchyItem(
                            target=_DIRECTION_HIERARCHY_TARGETS[direction],
                            priority=1,
                            rationale=(
                                "The cited scene evidence defines this direction's "
                                "primary visual relationship."
                            ),
                            evidence_ids=support,
                        )
                    ],
                    possible_color_language=[
                        ColorLanguageCue(
                            target=target,
                            property=property_name,
                            direction=adjustment,
                            minimum_strength=minimum,
                            maximum_strength=maximum,
                            rationale=(
                                "Keep the interpretation bounded by support and "
                                "counterevidence."
                            ),
                        )
                    ],
                    cliche_risks=[
                        "Avoid a generic landscape treatment that ignores context."
                    ],
                    confidence=0.62 if sufficient else 0.45,
                    uncertainties=(
                        []
                        if sufficient
                        else [
                            "needs_user_intent because scene evidence is insufficient"
                        ]
                    ),
                    failure_conditions=[
                        "The source hierarchy becomes less legible or continuity breaks."
                    ],
                )
            )
    project_interpretation = (
        "Use a restrained project language grounded in display evidence, physical "
        "measurements, motion, and available audio observations."
    )
    if user_intent:
        project_interpretation += (
            " A user intent is present as an explicit constraint, without being "
            "treated as measured fact."
        )
    thesis = ProjectVisualThesis(
        thesis_id=f"thesis:{context.graph_digest[:20]}",
        project_interpretation=project_interpretation,
        palette_character=PaletteCharacter.SOURCE_FAITHFUL,
        contrast_character=ContrastCharacter.NATURAL,
        shared_protections=[
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.STRUCTURE,
            ProtectedAttribute.NATURAL_SATURATION,
            ProtectedAttribute.PROJECT_CONTINUITY,
        ],
        evidence_for=list(dict.fromkeys(project_support)),
        evidence_against=list(dict.fromkeys(project_counter)),
        confidence=0.58,
        uncertainties=[
            "Offline fallback does not claim an expert aesthetic judgment."
        ],
        briefs=briefs,
        scene_roles=roles,
        allowed_deviations=deviations,
    )
    audit = audit_closed_book_thesis(
        thesis,
        context=context,
        user_intent=user_intent,
    )
    if not audit.valid:
        raise ValueError(
            "offline Director failed closed-book audit: "
            + ", ".join(item.code.value for item in audit.violations)
        )
    return thesis


def build_offline_color_strategies(
    *,
    thesis: ProjectVisualThesis,
    context: ProjectContextPack,
    baseline_asset_id: str,
    baseline_asset_sha256: str,
    retrieval_asset_sha256: str,
    catalog: ColorGraphCapabilityCatalog,
) -> list[ColorStrategy]:
    strategies: list[ColorStrategy] = []
    role_by_scene = {item.scene_id: item for item in thesis.scene_roles}
    thesis_digest = canonical_sha256(thesis)
    for brief in thesis.briefs:
        (
            operation,
            parameter_name,
            property_name,
            adjustment,
            minimum,
            nominal,
            maximum,
        ) = _STRATEGY_PARAMETERS[brief.direction]
        evidence_ids = list(
            dict.fromkeys([*brief.evidence_for, *brief.evidence_against])
        )
        strategies.append(
            ColorStrategy(
                strategy_id=f"strategy:{brief.scene_id}:{brief.direction.value}",
                brief_id=brief.brief_id,
                technical_baseline_asset_id=baseline_asset_id,
                technical_baseline_sha256=baseline_asset_sha256,
                common_language=(
                    "Preserve measured detail and project continuity while testing "
                    "one bounded visual relationship."
                ),
                actions=[
                    StrategyAction(
                        action_id=(
                            f"action:{brief.scene_id}:{brief.direction.value}:"
                            f"{parameter_name}"
                        ),
                        operation=operation,
                        scope=StrategyScope(
                            project_id=catalog.project_id,
                            scene_id=brief.scene_id,
                        ),
                        parameters=[
                            StrategyParameter(
                                name=parameter_name,
                                unit="normalized",
                                minimum=minimum,
                                nominal=nominal,
                                maximum=maximum,
                            )
                        ],
                        serves_brief_id=brief.brief_id,
                        evidence_ids=evidence_ids,
                        protected_attributes=list(thesis.shared_protections),
                        rationale=(
                            "The bounded action serves the cited hierarchy while "
                            "retaining the immutable technical baseline."
                        ),
                        capability_id=operation_card_id(
                            operation,
                            parameter_name,
                        ),
                        intended_property=property_name,
                        direction=adjustment,
                        baseline_relationship=BaselineRelationship.PRESERVE,
                    )
                ],
                alternatives_not_selected=[
                    "A broader treatment was not selected because it would weaken "
                    "the evidence boundary."
                ],
                continuity_constraints=list(thesis.shared_protections),
                failure_conditions=list(brief.failure_conditions),
                project_thesis_sha256=thesis_digest,
                retrieval_bundle_sha256=retrieval_asset_sha256,
                selected_possibility_card_ids=[],
                scene_role=role_by_scene[brief.scene_id].narrative_role,
                tonal_structure=[
                    "Retain measured highlight and structural separation."
                ],
                color_relationships=[
                    "Keep the source relationship legible while testing this direction."
                ],
                visual_hierarchy=[
                    item.target for item in brief.visual_hierarchy
                ],
                local_region_intents=[],
            )
        )
    return strategies


class OfflineCreativePipelineRunner:
    """Project-scoped offline Shadow runner with resumable real-frame search."""

    def __init__(
        self,
        *,
        project_root: Path,
        source: Path,
        graph: GradeGraph,
        backend: ComputeBackend,
        request: OfflineCreativeRunRequest,
        ui_store: AgentUIStore | None = None,
        search_store: CandidateSearchStore | None = None,
        renderer: LocalCandidateFrameRenderer | None = None,
        knowledge_index: CreativeKnowledgeIndex | None = None,
        knowledge_corpus_audit: CreativeCorpusAuditReport | None = None,
        provider_runtime: CreativeProviderRuntime | None = None,
        critic_calibration_gate: CriticCalibrationGate | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.source = source.resolve()
        self.graph = graph
        self.backend = backend
        self.request = request
        self.ui_store = ui_store or AgentUIStore(self.project_root)
        self.search_store = search_store or CandidateSearchStore(
            self.ui_store.root / "search"
        )
        self.renderer = renderer or LocalCandidateFrameRenderer(
            source=self.source,
            backend=backend,
            maximum_width=request.context_budget.maximum_image_edge,
        )
        self.knowledge_index = knowledge_index
        self.knowledge_corpus_audit = knowledge_corpus_audit
        self.provider_runtime = provider_runtime
        self.critic_calibration_gate = critic_calibration_gate
        self._provider_loop: asyncio.AbstractEventLoop | None = None
        self._director_identity: CreativeModelIdentity | None = None
        self._director_provider_used = False
        self._strategist_provider_successes = 0
        self._critic_reports: list[PairwiseVisualCriticReport] = []
        self._expected_critic_pairs = 0
        self._critic_notes: dict[
            str,
            list[AgentUICritiqueDimension],
        ] = {}
        self.started = time.perf_counter()
        self._last_stage = AgentUIStage.ANALYZING
        self._evidence: ProjectEvidenceBuildResult | None = None
        self._thesis: ProjectVisualThesis | None = None
        self._strategies: list[ColorStrategy] = []
        self._records: list[SearchCandidateRecord] = []
        if request.project_id != graph.project_id:
            raise ValueError("offline run request belongs to another graph")
        if self.project_root.name != graph.project_id:
            raise ValueError("offline run graph belongs to another project root")
        if not self.source.is_file():
            raise FileNotFoundError(self.source)
        request_has_corpus = request.knowledge_corpus_sha256 is not None
        runtime_has_corpus = (
            knowledge_index is not None or knowledge_corpus_audit is not None
        )
        if request_has_corpus != runtime_has_corpus:
            raise ValueError(
                "knowledge corpus runtime must exactly match the immutable run request"
            )
        if request_has_corpus:
            if knowledge_index is None or knowledge_corpus_audit is None:
                raise ValueError("configured knowledge corpus is incomplete")
            if not knowledge_corpus_audit.passed:
                raise ValueError("configured knowledge corpus did not pass its audit")
            if (
                knowledge_corpus_audit.corpus_id != request.knowledge_corpus_id
                or knowledge_corpus_audit.corpus_version
                != request.knowledge_corpus_version
                or knowledge_corpus_audit.corpus_sha256
                != request.knowledge_corpus_sha256
            ):
                raise ValueError(
                    "knowledge corpus identity does not match the immutable run request"
                )
        if request.provider_shadow_enabled != (provider_runtime is not None):
            raise ValueError(
                "provider runtime must exactly match the immutable run request"
            )
        if provider_runtime is not None:
            runtime_digest = provider_runtime_configuration_digest(provider_runtime)
            if runtime_digest != request.provider_configuration_sha256:
                raise ValueError(
                    "provider runtime configuration differs from the immutable run request"
                )
        if request.critic_calibration_sha256 is None:
            if critic_calibration_gate is not None:
                raise ValueError(
                    "Critic calibration gate is not bound to the run request"
                )
        elif (
            critic_calibration_gate is None
            or canonical_sha256(critic_calibration_gate)
            != request.critic_calibration_sha256
        ):
            raise ValueError(
                "Critic calibration gate differs from the immutable run request"
            )

    @property
    def run_root(self) -> Path:
        return (
            self.ui_store.root
            / "runs"
            / _safe_component(self.request.run_id)
        )

    @property
    def request_path(self) -> Path:
        return self.run_root / "run-request.json"

    def persist_request(self) -> Path:
        content = self.request.model_dump_json(indent=2)
        if self.request_path.is_file():
            if self.request_path.read_text(encoding="utf-8") != content:
                raise ValueError("refusing to replace an immutable Agent run request")
            return self.request_path
        _atomic_write(self.request_path, content)
        return self.request_path

    @classmethod
    def load_request(
        cls,
        project_root: Path,
        run_id: str,
    ) -> OfflineCreativeRunRequest:
        path = (
            project_root.resolve()
            / "creative-agent"
            / "runs"
            / _safe_component(run_id)
            / "run-request.json"
        )
        return OfflineCreativeRunRequest.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def _elapsed(self) -> float:
        return max(0.0, time.perf_counter() - self.started)

    def _await_provider[ResultT](self, awaitable: object) -> ResultT:
        if self.provider_runtime is None:
            raise RuntimeError("provider runtime is not configured")
        if self._provider_loop is None:
            self._provider_loop = asyncio.new_event_loop()
        return self._provider_loop.run_until_complete(awaitable)  # type: ignore[arg-type]

    @staticmethod
    def _fallback_payload(fallback: FallbackDecision) -> dict[str, object]:
        return {
            "status": "fallback",
            "route": fallback.route,
            "reason": fallback.reason.value,
            "detail": fallback.detail,
            "request_digest": fallback.request_digest,
        }

    def _provider_images(
        self,
        evidence: ProjectEvidenceBuildResult,
        *,
        role: CreativeRole,
        scene_id: str | None = None,
    ) -> tuple[ProviderImage, ...]:
        if self.provider_runtime is None:
            return ()
        provider = self.provider_runtime.providers[role]
        if not provider.capabilities.image_input:
            return ()
        evidence_by_id = {
            item.evidence_id: item for item in evidence.context_pack.evidence
        }
        model_input_ids = set(
            evidence.evidence_bundle.model_input_evidence_ids
        )
        images: list[ProviderImage] = []
        for artifact in evidence.evidence_bundle.artifacts:
            context_evidence = evidence_by_id.get(artifact.evidence_id)
            if (
                artifact.evidence_id not in model_input_ids
                or context_evidence is None
                or (
                    scene_id is not None
                    and context_evidence.scene_id not in {None, scene_id}
                )
            ):
                continue
            path = (evidence.artifact_root / artifact.relative_path).resolve()
            if not path.is_relative_to(evidence.artifact_root.resolve()):
                raise ValueError("provider evidence path escapes its artifact root")
            suffix = path.suffix.casefold()
            media_type = (
                "image/jpeg"
                if suffix in {".jpg", ".jpeg"}
                else "image/webp"
                if suffix == ".webp"
                else "image/png"
            )
            images.append(
                ProviderImage(
                    asset_id=artifact.evidence_id,
                    sha256=artifact.sha256,
                    media_type=media_type,
                    content=path.read_bytes(),
                    detail="low",
                )
            )
            if len(images) >= provider.capabilities.maximum_images:
                break
        return tuple(images)

    def _cancel_requested(self) -> bool:
        snapshot = self.ui_store.load_snapshot()
        return bool(
            snapshot is not None
            and snapshot.run_id == self.request.run_id
            and snapshot.cancellation_requested
        )

    def _budget_snapshot(
        self,
        state: CandidateSearchState | None = None,
    ) -> AgentUIBudgetSnapshot:
        usage = state.usage if state is not None else None
        provider_usage = (
            self.provider_runtime.budget_usage
            if self.provider_runtime is not None
            else None
        )
        return AgentUIBudgetSnapshot(
            model_calls_used=(
                self.provider_runtime.provider_attempts
                if self.provider_runtime is not None
                else usage.model_calls
                if usage is not None
                else 0
            ),
            model_calls_limit=(
                self.provider_runtime.budget.maximum_provider_attempts
                if self.provider_runtime is not None
                else self.request.search_budget.maximum_model_calls
            ),
            rendered_frames_used=(
                usage.rendered_frames if usage is not None else 0
            ),
            rendered_frames_limit=(
                self.request.search_budget.maximum_rendered_frames
            ),
            cost_usd_used=(
                provider_usage.estimated_cost_usd
                if provider_usage is not None
                else usage.cost_usd
                if usage is not None
                else 0
            ),
            cost_usd_limit=(
                self.provider_runtime.budget.maximum_cost_usd
                if self.provider_runtime is not None
                else self.request.search_budget.maximum_cost_usd
            ),
            elapsed_seconds=min(
                self._elapsed(),
                self.request.maximum_pipeline_wall_seconds,
            ),
            wall_seconds_limit=self.request.maximum_pipeline_wall_seconds,
            refinements_used=usage.refinements if usage is not None else 0,
            refinements_limit=self.request.search_budget.maximum_refinements,
        )

    def _provider_snapshot(self) -> AgentUIProviderSnapshot:
        if self.provider_runtime is not None:
            provider = self.provider_runtime.providers[CreativeRole.DIRECTOR]
            cloud = provider.boundary.value != "local"
            return AgentUIProviderSnapshot(
                provider_id=provider.provider_id,
                model_id=provider.model_id,
                model_revision=provider.model_revision,
                boundary=(
                    "local"
                    if not cloud
                    else (
                        "openai_compatible"
                        if provider.boundary.value == "openai_compatible"
                        else "cloud"
                    )
                ),
                network_enabled=self.provider_runtime.policy.network_enabled,
                cloud_upload_required=cloud,
                cloud_upload_consented=(
                    self.request.cloud_upload_consent if cloud else False
                ),
            )
        return AgentUIProviderSnapshot(
            provider_id="offline-rules",
            model_id="local-evidence-strategy-fallback",
            model_revision=OFFLINE_CREATIVE_PIPELINE_VERSION,
            boundary="local",
            network_enabled=False,
            cloud_upload_required=False,
            cloud_upload_consented=False,
        )

    def _public_copy(self, source: Path, relative_path: Path) -> str:
        destination = self.ui_store.root / "public" / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            if hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256(
                source.read_bytes()
            ).digest():
                raise ValueError("immutable public Agent asset differs")
        else:
            shutil.copyfile(source, destination)
        return (
            f"/api/projects/{self.request.project_id}/creative-agent/assets/"
            f"{relative_path.as_posix()}"
        )

    def _evidence_thumbnail_urls(self) -> dict[str, str]:
        if self._evidence is None:
            return {}
        result: dict[str, str] = {}
        for artifact in self._evidence.evidence_bundle.artifacts:
            source = self._evidence.artifact_root / artifact.relative_path
            if not source.is_file():
                continue
            suffix = source.suffix.casefold() or ".jpg"
            relative = (
                Path(_safe_component(self.request.run_id))
                / "evidence"
                / f"{canonical_sha256({'id': artifact.evidence_id})[:20]}{suffix}"
            )
            result[artifact.evidence_id] = self._public_copy(source, relative)
        return result

    def _candidate_thumbnail_urls(
        self,
        records: list[SearchCandidateRecord],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for record in records:
            urls: list[str] = []
            for index, sample in enumerate(record.samples):
                source = Path(sample.candidate_path)
                relative = (
                    Path(_safe_component(self.request.run_id))
                    / "candidates"
                    / canonical_sha256({"candidate": record.candidate_id})[:20]
                    / f"{index:03d}{source.suffix.casefold() or '.png'}"
                )
                urls.append(self._public_copy(source, relative))
            result[record.candidate_id] = urls
        return result

    def _scene_snapshots(
        self,
        *,
        records: list[SearchCandidateRecord],
        preferred_candidate_id: str | None,
        runner_up_candidate_id: str | None,
    ) -> list[AgentUISceneSnapshot]:
        if self._thesis is None or self._evidence is None:
            return []
        record_by_brief = {item.brief_id: item for item in records}
        strategy_by_brief = {item.brief_id: item for item in self._strategies}
        role_by_scene = {
            item.scene_id: item for item in self._thesis.scene_roles
        }
        evidence_urls = self._evidence_thumbnail_urls()
        candidate_urls = self._candidate_thumbnail_urls(records)
        scenes: list[AgentUISceneSnapshot] = []
        for scene in self.graph.scenes:
            briefs = [
                item
                for item in self._thesis.briefs
                if item.scene_id == scene.id
            ]
            referenced_support = {
                value
                for brief in briefs
                for value in brief.evidence_for
            }
            referenced_counter = {
                value
                for brief in briefs
                for value in brief.evidence_against
            }
            evidence = [
                AgentUIEvidenceSnapshot(
                    evidence_id=item.evidence_id,
                    label=item.summary,
                    role=(
                        "support"
                        if item.evidence_id in referenced_support
                        else (
                            "counterevidence"
                            if item.evidence_id in referenced_counter
                            else "source"
                        )
                    ),
                    scene_id=item.scene_id,
                    shot_id=item.shot_id,
                    frame_index=item.frame_index,
                    thumbnail_url=evidence_urls.get(item.evidence_id),
                )
                for item in self._evidence.context_pack.evidence
                if item.scene_id in {None, scene.id}
            ]
            directions: list[AgentUIDirectionSnapshot] = []
            for brief in sorted(
                briefs,
                key=lambda item: list(CreativeDirection).index(item.direction),
            ):
                record = record_by_brief.get(brief.brief_id)
                strategy = strategy_by_brief.get(brief.brief_id)
                candidate_id = record.candidate_id if record is not None else None
                directions.append(
                    AgentUIDirectionSnapshot(
                        brief_id=brief.brief_id,
                        direction=brief.direction,
                        title=_DIRECTION_TITLES[brief.direction],
                        interpretation=brief.interpretation,
                        emotional_target=brief.emotional_target,
                        support_evidence_ids=brief.evidence_for,
                        counterevidence_ids=brief.evidence_against,
                        protections=[
                            item.value
                            for item in (
                                strategy.continuity_constraints
                                if strategy is not None
                                else self._thesis.shared_protections
                            )
                        ],
                        intentional_exceptions=(
                            [
                                f"{item.exception_id}: {item.reason}"
                                for item in strategy.intentional_exceptions
                            ]
                            if strategy is not None
                            else []
                        ),
                        failure_conditions=brief.failure_conditions,
                        candidate_id=candidate_id,
                        candidate_thumbnail_urls=(
                            candidate_urls.get(candidate_id, [])
                            if candidate_id is not None
                            else []
                        ),
                        qc_status=(
                            "pending"
                            if record is None
                            else (
                                "pass"
                                if record.status
                                == CandidateAttemptStatus.HARD_PASS
                                else "fail"
                            )
                        ),
                        critique=(
                            self._critic_notes.get(candidate_id, [])
                            if candidate_id is not None
                            else []
                        ),
                        is_pareto=False,
                        is_preferred=(
                            candidate_id is not None
                            and candidate_id == preferred_candidate_id
                        ),
                        is_runner_up=(
                            candidate_id is not None
                            and candidate_id == runner_up_candidate_id
                        ),
                        application_scopes=(
                            [item.scope for item in strategy.actions]
                            if record is not None and strategy is not None
                            else []
                        ),
                        refinement=None,
                    )
                )
            role = role_by_scene[scene.id]
            scenes.append(
                AgentUISceneSnapshot(
                    scene_id=scene.id,
                    scene_label=scene.label,
                    narrative_role=role.narrative_role,
                    continuity_notes=[
                        (
                            "Provider Shadow outputs preserve deterministic "
                            "compiler and QC boundaries."
                            if self.provider_runtime is not None
                            else (
                                "Offline fallback preserves shared project "
                                "protections."
                            )
                        ),
                        (
                            "Blind Critic evidence is shown for human review."
                            if self._critic_reports
                            else (
                                "Visual Critic and Reflection remain explicitly "
                                "skipped or unavailable."
                            )
                        ),
                    ],
                    evidence=evidence,
                    directions=directions,
                )
            )
        return scenes

    def _save_snapshot(
        self,
        *,
        status: AgentUIRunStatus,
        stage: AgentUIStage,
        progress: int,
        message: str,
        records: list[SearchCandidateRecord] | None = None,
        state: CandidateSearchState | None = None,
        preferred_candidate_id: str | None = None,
        runner_up_candidate_id: str | None = None,
        selection_status: str = "not-selected",
        gate_trace: list[str] | None = None,
        skipped_stages: list[AgentUIStage] | None = None,
        last_error: str | None = None,
        clear_control_requests: bool = False,
    ) -> AgentRunUISnapshot:
        self._last_stage = stage
        resolved_records = records if records is not None else self._records
        for _ in range(4):
            existing = self.ui_store.load_snapshot()
            revision = 0 if existing is None else existing.snapshot_revision + 1
            cancellation_requested = bool(
                existing is not None
                and existing.run_id == self.request.run_id
                and existing.cancellation_requested
                and not clear_control_requests
            )
            resume_requested = bool(
                existing is not None
                and existing.run_id == self.request.run_id
                and existing.resume_requested
                and not clear_control_requests
            )
            snapshot = seal_snapshot(
                project_id=self.request.project_id,
                run_id=self.request.run_id,
                snapshot_revision=revision,
                status=status,
                stage=stage,
                progress=progress,
                message=message,
                updated_at=datetime.now(UTC),
                shadow_mode=True,
                current_graph_digest=graph_digest(self.graph),
                current_graph_unchanged=True,
                offline_available=True,
                project_visual_thesis=(
                    self._thesis.project_interpretation
                    if self._thesis is not None
                    else None
                ),
                palette_character=(
                    self._thesis.palette_character.value
                    if self._thesis is not None
                    else None
                ),
                contrast_character=(
                    self._thesis.contrast_character.value
                    if self._thesis is not None
                    else None
                ),
                provider=self._provider_snapshot(),
                budget=self._budget_snapshot(state),
                scenes=self._scene_snapshots(
                    records=resolved_records,
                    preferred_candidate_id=preferred_candidate_id,
                    runner_up_candidate_id=runner_up_candidate_id,
                ),
                selection=AgentUISelectionSnapshot(
                    status=selection_status,
                    preferred_candidate_id=preferred_candidate_id,
                    runner_up_candidate_id=runner_up_candidate_id,
                    pareto_candidate_ids=[],
                    gate_trace=gate_trace or [],
                    automatic_selection_allowed=False,
                    requires_user_confirmation=True,
                ),
                skipped_stages=skipped_stages or [],
                cancellation_requested=cancellation_requested,
                resume_requested=resume_requested,
                last_error=last_error,
            )
            try:
                self.ui_store.save_snapshot(snapshot)
                return snapshot
            except ValueError as exc:
                if "revision must be" not in str(exc):
                    raise
        raise RuntimeError("Agent UI snapshot revision changed repeatedly")

    def initialize(self) -> AgentRunUISnapshot:
        self.persist_request()
        provider = self._provider_snapshot()
        return self._save_snapshot(
            status=AgentUIRunStatus.RUNNING,
            stage=AgentUIStage.ANALYZING,
            progress=2,
            message=(
                (
                    "Building an on-device evidence pack. Representative frames "
                    "will be sent only to the explicitly configured Shadow provider "
                    "under this run's recorded consent."
                )
                if provider.cloud_upload_required
                else (
                    "Building an on-device evidence pack; no media leaves this computer."
                )
            ),
            selection_status=(
                "provider-shadow-analysis-started"
                if self.provider_runtime is not None
                else "offline-analysis-started"
            ),
            clear_control_requests=True,
        )

    def _cancel(
        self,
        *,
        stage: AgentUIStage,
        progress: int,
        state: CandidateSearchState | None = None,
    ) -> OfflineCreativePipelineResult:
        snapshot = self._save_snapshot(
            status=AgentUIRunStatus.CANCELLED,
            stage=stage,
            progress=progress,
            message=(
                "Offline Shadow run stopped at a safe boundary; persisted "
                "candidate state can be resumed."
            ),
            state=state,
            selection_status="cancelled-at-safe-boundary",
            skipped_stages=[
                AgentUIStage.CRITICIZING,
                AgentUIStage.REFINING,
            ],
            clear_control_requests=True,
        )
        return OfflineCreativePipelineResult(
            snapshot=snapshot,
            search=(
                CandidateSearchResult(state=state)
                if state is not None
                else None
            ),
            cancelled=True,
        )

    def _write_run_artifact(self, name: str, value: object) -> Path:
        path = self.run_root / name
        payload = (
            value.model_dump(mode="json")
            if isinstance(value, BaseModel)
            else value
        )
        _atomic_write(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        )
        return path

    def _run_reflection_shadow(
        self,
        *,
        survivors: list[SearchCandidateRecord],
        briefs_by_id: dict[str, CreativeBrief],
        strategy_by_brief: dict[str, ColorStrategy],
        search_state: CandidateSearchState,
    ) -> _PipelineReflectionResult:
        if not self.request.reflection_shadow_enabled:
            return _PipelineReflectionResult(
                stage_status="skipped-shadow-v1",
                stage_executed=False,
                completed=False,
                parent_record=None,
                refined_record=None,
                selected_record=None,
                outcome=None,
            )

        payload: dict[str, object] = {
            "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
            "requested": True,
            "current_graph_unchanged": True,
            "automatic_selection_allowed": False,
            "requires_user_confirmation": True,
            "release_effect": "none_shadow_only",
            "critic_calibration_sha256": (
                canonical_sha256(self.critic_calibration_gate)
                if self.critic_calibration_gate is not None
                else None
            ),
        }

        def finish(
            *,
            stage_status: str,
            stage_executed: bool,
            completed: bool,
            parent_record: SearchCandidateRecord | None = None,
            refined_record: SearchCandidateRecord | None = None,
            selected_record: SearchCandidateRecord | None = None,
            outcome: ReflectionOutcome | None = None,
            detail: str | None = None,
        ) -> _PipelineReflectionResult:
            payload.update(
                {
                    "stage_status": stage_status,
                    "stage_executed": stage_executed,
                    "completed": completed,
                    "parent_candidate_id": (
                        parent_record.candidate_id
                        if parent_record is not None
                        else None
                    ),
                    "refined_candidate_id": (
                        refined_record.candidate_id
                        if refined_record is not None
                        else None
                    ),
                    "selected_candidate_id": (
                        selected_record.candidate_id
                        if selected_record is not None
                        else None
                    ),
                    "outcome": (
                        outcome.model_dump(mode="json")
                        if outcome is not None
                        else None
                    ),
                    "detail": detail,
                }
            )
            self._write_run_artifact("reflection-results.json", payload)
            return _PipelineReflectionResult(
                stage_status=stage_status,
                stage_executed=stage_executed,
                completed=completed,
                parent_record=parent_record,
                refined_record=refined_record,
                selected_record=selected_record,
                outcome=outcome,
            )

        if (
            self.provider_runtime is None
            or self._director_identity is None
        ):
            return finish(
                stage_status="blocked-provider-runtime",
                stage_executed=False,
                completed=False,
                detail=(
                    "Reflection Shadow requires the bound provider and Director "
                    "identity."
                ),
            )
        eligible_reports = [
            report
            for report in self._critic_reports
            if report.position_swap_consistent
            and all(item.valid for item in report.output_audits)
            and report.preferred_candidate_id is not None
        ]
        if not eligible_reports:
            return finish(
                stage_status="blocked-critic-position-or-evidence-gate",
                stage_executed=False,
                completed=False,
                detail=(
                    "No blind Critic pair passed the position-swap and structured "
                    "evidence gates. Calibration is not required to create a "
                    "manual-review Shadow candidate, but remains mandatory for "
                    "automatic selection."
                ),
            )
        records_by_id = {item.candidate_id: item for item in survivors}
        report = next(
            (
                item
                for item in sorted(
                    eligible_reports,
                    key=lambda value: value.pair_id,
                )
                if item.preferred_candidate_id in records_by_id
            ),
            None,
        )
        if report is None or report.preferred_candidate_id is None:
            return finish(
                stage_status="blocked-critic-candidate-binding",
                stage_executed=False,
                completed=False,
                detail="The calibrated Critic preference is not a hard-QC survivor.",
            )
        parent_record = records_by_id[report.preferred_candidate_id]
        critique = next(
            (
                item
                for item in report.critiques
                if item.candidate_id == parent_record.candidate_id
            ),
            None,
        )
        if critique is None:
            return finish(
                stage_status="failed-closed-missing-critique",
                stage_executed=True,
                completed=False,
                parent_record=parent_record,
                selected_record=parent_record,
                detail="The calibrated Critic report omitted its preferred candidate.",
            )

        self._save_snapshot(
            status=AgentUIRunStatus.RUNNING,
            stage=AgentUIStage.REFINING,
            progress=94,
            message=(
                "Planning one content-bound minimal Reflection, then rerendering "
                "and validating it with hard QC and a fresh swapped blind pair."
            ),
            records=self._records,
            state=search_state,
            preferred_candidate_id=parent_record.candidate_id,
            runner_up_candidate_id=next(
                item.candidate_id
                for item in survivors
                if item.candidate_id != parent_record.candidate_id
            ),
            selection_status="provider-reflection-shadow",
        )
        try:
            directive = plan_critic_reflection_directive(
                parent_record=parent_record,
                critique=critique,
            )
        except (OSError, ValueError) as exc:
            return finish(
                stage_status="failed-closed-planning",
                stage_executed=True,
                completed=False,
                parent_record=parent_record,
                selected_record=parent_record,
                detail=f"{type(exc).__name__}: {exc}",
            )
        payload["directive"] = directive.model_dump(mode="json")
        reflection_run_id = (
            "r:"
            + canonical_sha256(
                {
                    "project_id": self.request.project_id,
                    "run_id": self.request.run_id,
                }
            )[:12]
        )
        payload["reflection_run_id"] = reflection_run_id
        reflection_store = ReflectionStore(
            self.project_root / ".reflection"
        )
        reflection_runner = ReflectionRunner(
            renderer=LocalReflectionFrameRenderer(backend=self.backend),
            store=reflection_store,
        )
        assert self._thesis is not None
        preparation_result = reflection_runner.prepare(
            run_id=reflection_run_id,
            parent_record=parent_record,
            directive=directive,
            project_thesis_digest=canonical_sha256(self._thesis),
            evaluated_at=self.request.created_at,
            budget=ReflectionBudget(
                maximum_refinements=1,
                maximum_rendered_frames=3,
                maximum_model_calls=2,
                maximum_cost_usd=self.request.search_budget.maximum_cost_usd,
            ),
        )
        if preparation_result.preparation is None:
            payload["preparation_status"] = (
                preparation_result.status.value
                if preparation_result.status is not None
                else "unknown"
            )
            payload["patch_digest"] = preparation_result.patch_digest
            return finish(
                stage_status=(
                    "stopped-"
                    + (
                        preparation_result.status.value
                        if preparation_result.status is not None
                        else "unknown"
                    )
                ),
                stage_executed=True,
                completed=False,
                parent_record=parent_record,
                selected_record=parent_record,
                detail=preparation_result.detail,
            )
        preparation = preparation_result.preparation
        refined_record = preparation.refined_record
        payload["preparation"] = preparation.model_dump(mode="json")
        brief = briefs_by_id[parent_record.brief_id]
        strategy = strategy_by_brief[parent_record.brief_id]
        requests = build_blind_pairwise_critic_requests(
            pair_id=(
                f"{self.request.run_id}:{parent_record.scene_id}:reflection"
            ),
            left_record=parent_record,
            left_brief=brief,
            left_exceptions=strategy.intentional_exceptions,
            right_record=refined_record,
            right_brief=brief,
            right_exceptions=strategy.intentional_exceptions,
            randomization_seed=canonical_sha256(
                {
                    "run_id": self.request.run_id,
                    "parent_candidate_id": parent_record.candidate_id,
                    "refined_candidate_id": refined_record.candidate_id,
                    "stage": "reflection-validation",
                }
            ),
            cloud_upload_consent=self.request.cloud_upload_consent,
        )
        try:
            pairwise = self._await_provider(
                run_blind_pairwise_critic(
                    self.provider_runtime,
                    requests=requests,
                    director_identity=self._director_identity,
                    calibration_gate=self.critic_calibration_gate,
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return finish(
                stage_status="failed-closed-pairwise-validation",
                stage_executed=True,
                completed=False,
                parent_record=parent_record,
                refined_record=refined_record,
                selected_record=parent_record,
                detail=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(pairwise, PairwiseVisualCriticReport):
            return finish(
                stage_status="failed-closed-pairwise-fallback",
                stage_executed=True,
                completed=False,
                parent_record=parent_record,
                refined_record=refined_record,
                selected_record=parent_record,
                detail=(
                    pairwise.detail
                    if isinstance(pairwise, FallbackDecision)
                    else "Reflection Critic returned an unknown result."
                ),
            )
        payload["pairwise_report"] = pairwise.model_dump(mode="json")
        try:
            outcome = finalize_reflection(
                parent_record=parent_record,
                preparation=preparation,
                pairwise_report=pairwise,
                store=reflection_store,
            )
        except (OSError, ValueError) as exc:
            return finish(
                stage_status="failed-closed-finalization",
                stage_executed=True,
                completed=False,
                parent_record=parent_record,
                refined_record=refined_record,
                selected_record=parent_record,
                detail=f"{type(exc).__name__}: {exc}",
            )
        selected_record = (
            refined_record if outcome.accepted else parent_record
        )
        for item in pairwise.critiques:
            self._critic_notes[item.candidate_id] = [
                AgentUICritiqueDimension(
                    dimension=score.dimension,
                    score=score.score,
                    confidence=score.confidence,
                    concise_reason=score.concise_reason,
                )
                for score in item.scores
            ]
        return finish(
            stage_status=f"completed-{outcome.status.value}",
            stage_executed=True,
            completed=True,
            parent_record=parent_record,
            refined_record=refined_record,
            selected_record=selected_record,
            outcome=outcome,
        )

    def _run(self) -> OfflineCreativePipelineResult:
        self.persist_request()
        self._save_snapshot(
            status=AgentUIRunStatus.RUNNING,
            stage=AgentUIStage.ANALYZING,
            progress=5,
            message=(
                "Extracting real representative frames and deterministic "
                "physical evidence on-device."
            ),
            selection_status="analyzing-evidence",
            clear_control_requests=True,
        )
        evidence = build_project_evidence_pack(
            source=self.source,
            graph=self.graph,
            output_root=self.run_root / "evidence",
            backend=self.backend,
            budget=self.request.context_budget,
            created_at=self.request.created_at,
        )
        self._evidence = evidence
        self._write_run_artifact(
            "evidence-summary.json",
            {
                "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
                "context_digest": canonical_sha256(evidence.context_pack),
                "bundle_digest": evidence.evidence_bundle_digest,
                "baseline_asset_id": evidence.technical_baseline.asset_id,
                "baseline_asset_sha256": evidence.technical_baseline.sha256,
            },
        )
        if self._cancel_requested():
            return self._cancel(stage=AgentUIStage.ANALYZING, progress=22)

        self._save_snapshot(
            status=AgentUIRunStatus.RUNNING,
            stage=AgentUIStage.INTERPRETING,
            progress=25,
            message=(
                (
                    "Running the closed-book Creative Director against the signed "
                    "evidence pack; recipes and retrieval remain hidden."
                )
                if self.provider_runtime is not None
                else "Building three conservative evidence-bound directions per scene."
            ),
            selection_status=(
                "provider-closed-book-shadow"
                if self.provider_runtime is not None
                else "offline-closed-book-fallback"
            ),
        )
        offline_thesis = build_offline_visual_thesis(
            context=evidence.context_pack,
            graph=self.graph,
            user_intent=self.request.user_intent,
        )
        thesis = offline_thesis
        director_provider_result: dict[str, object] = {
            "status": "not-configured",
        }
        if self.provider_runtime is not None:
            director_request = build_closed_book_director_request(
                context=evidence.context_pack,
                context_asset_digest=canonical_sha256(evidence.context_pack),
                images=self._provider_images(
                    evidence,
                    role=CreativeRole.DIRECTOR,
                ),
                user_intent=self.request.user_intent,
                user_intent_digest=(
                    hashlib.sha256(
                        self.request.user_intent.encode("utf-8")
                    ).hexdigest()
                    if self.request.user_intent is not None
                    else None
                ),
                cloud_upload_consent=self.request.cloud_upload_consent,
            )
            try:
                director_outcome = self._await_provider(
                    run_closed_book_director(
                        self.provider_runtime,
                        request=director_request,
                        context=evidence.context_pack,
                        user_intent=self.request.user_intent,
                    )
                )
            except CreativeDirectorValidationError as exc:
                director_provider_result = {
                    "status": "audit-rejected",
                    "detail": str(exc),
                    "director_audit": exc.audit.model_dump(mode="json"),
                }
            else:
                if isinstance(director_outcome, FallbackDecision):
                    director_provider_result = self._fallback_payload(
                        director_outcome
                    )
                elif isinstance(director_outcome, ClosedBookDirectorResult):
                    thesis = director_outcome.thesis
                    self._director_provider_used = True
                    audit = director_outcome.provider_audit
                    self._director_identity = CreativeModelIdentity(
                        provider_id=audit.provider_id,
                        model_id=audit.model_id,
                        model_revision=audit.model_revision,
                        prompt_version=audit.prompt_version,
                    )
                    director_provider_result = {
                        "status": "completed",
                        "provider_audit": audit.model_dump(mode="json"),
                        "director_audit": (
                            director_outcome.director_audit.model_dump(mode="json")
                        ),
                    }
                else:
                    raise TypeError("creative Director returned an unknown result")
        if self._director_identity is None:
            self._director_identity = CreativeModelIdentity(
                provider_id="offline-rules",
                model_id="local-evidence-director-fallback",
                model_revision=OFFLINE_CREATIVE_PIPELINE_VERSION,
                prompt_version="offline-closed-book-fallback/v1",
            )
        self._write_run_artifact(
            "director-provider-result.json",
            director_provider_result,
        )
        self._thesis = thesis
        director_audit = audit_closed_book_thesis(
            thesis,
            context=evidence.context_pack,
            user_intent=self.request.user_intent,
        )
        self._write_run_artifact("project-visual-thesis.json", thesis)
        self._write_run_artifact("director-audit.json", director_audit)
        if self._cancel_requested():
            return self._cancel(stage=AgentUIStage.INTERPRETING, progress=34)

        has_knowledge_corpus = self.knowledge_index is not None
        self._save_snapshot(
            status=AgentUIRunStatus.RUNNING,
            stage=AgentUIStage.RETRIEVING,
            progress=36,
            message=(
                (
                    "Retrieving from the content-bound, rights-audited creative corpus."
                )
                if has_knowledge_corpus
                else (
                    "No licensed production corpus is configured; recording an "
                    "explicit empty/OOD retrieval bundle."
                )
            ),
            selection_status=(
                "authorized-corpus-retrieval"
                if has_knowledge_corpus
                else "offline-empty-retrieval"
            ),
        )
        index = self.knowledge_index or CreativeKnowledgeIndex(
            "offline-empty-index/v1"
        )
        if self.knowledge_corpus_audit is not None:
            self._write_run_artifact(
                "knowledge-corpus-audit.json",
                self.knowledge_corpus_audit,
            )
        catalog = build_renderer_capability_catalog(self.graph)
        allowed_rights = sorted(
            {
                card.provenance.rights
                for card in index.possibility_cards_for_retrieval()
            }
        ) or ["internal-authorized"]
        retrieval_result = retrieve_creative_possibilities(
            thesis=thesis,
            thesis_asset_id=f"thesis:{canonical_sha256(thesis)[:20]}",
            thesis_sha256=canonical_sha256(thesis),
            context=evidence.context_pack,
            index=index,
            filters=RetrievalFilterContext(
                media_type="video",
                color_domain=self.graph.working_color_space.value,
                scope="scene",
                available_capabilities=[
                    item.capability_id for item in catalog.capabilities
                ],
                allowed_rights=allowed_rights,
                required_protections=list(thesis.shared_protections),
            ),
        )
        retrieval = retrieval_result.bundle
        retrieval_sha = canonical_sha256(retrieval)
        self._write_run_artifact("retrieval-bundle.json", retrieval)
        self._write_run_artifact("retrieval-audit.json", retrieval_result.audit)
        if self._cancel_requested():
            return self._cancel(stage=AgentUIStage.RETRIEVING, progress=43)

        self._save_snapshot(
            status=AgentUIRunStatus.RUNNING,
            stage=AgentUIStage.COMPILING,
            progress=45,
            message=(
                "Compiling typed strategies through the versioned renderer "
                "operation catalog."
            ),
            selection_status="deterministic-compilation",
        )
        offline_strategies = build_offline_color_strategies(
            thesis=thesis,
            context=evidence.context_pack,
            baseline_asset_id=evidence.technical_baseline.asset_id,
            baseline_asset_sha256=evidence.technical_baseline.sha256,
            retrieval_asset_sha256=retrieval_sha,
            catalog=catalog,
        )
        strategies = offline_strategies
        strategist_provider_results: list[dict[str, object]] = []
        if self.provider_runtime is not None:
            fallback_by_brief = {
                item.brief_id: item for item in offline_strategies
            }
            strategist_requests = [
                (
                    brief,
                    build_color_strategist_request(
                        brief=brief,
                        thesis=thesis,
                        thesis_asset_sha256=canonical_sha256(thesis),
                        retrieval=retrieval,
                        retrieval_asset_sha256=retrieval_sha,
                        context=evidence.context_pack,
                        context_asset_sha256=canonical_sha256(
                            evidence.context_pack
                        ),
                        baseline=evidence.technical_baseline.payload,
                        baseline_asset_id=evidence.technical_baseline.asset_id,
                        baseline_asset_sha256=(
                            evidence.technical_baseline.sha256
                        ),
                        catalog=catalog,
                        catalog_asset_sha256=canonical_sha256(catalog),
                        images=self._provider_images(
                            evidence,
                            role=CreativeRole.STRATEGIST,
                            scene_id=brief.scene_id,
                        ),
                        cloud_upload_consent=(
                            self.request.cloud_upload_consent
                        ),
                    ),
                )
                for brief in thesis.briefs
            ]

            async def run_strategists() -> list[object]:
                return list(
                    await asyncio.gather(
                        *(
                            run_color_strategist(
                                self.provider_runtime,
                                request=request,
                                brief=brief,
                                thesis=thesis,
                                retrieval=retrieval,
                                retrieval_asset_sha256=retrieval_sha,
                                context=evidence.context_pack,
                                baseline=evidence.technical_baseline.payload,
                                baseline_asset_id=(
                                    evidence.technical_baseline.asset_id
                                ),
                                baseline_asset_sha256=(
                                    evidence.technical_baseline.sha256
                                ),
                                catalog=catalog,
                            )
                            for brief, request in strategist_requests
                        ),
                        return_exceptions=True,
                    )
                )

            outcomes = self._await_provider(run_strategists())
            strategies = []
            for (brief, _), outcome in zip(
                strategist_requests,
                outcomes,
                strict=True,
            ):
                if isinstance(outcome, ColorStrategistResult):
                    strategies.append(outcome.strategy)
                    self._strategist_provider_successes += 1
                    strategist_provider_results.append(
                        {
                            "brief_id": brief.brief_id,
                            "status": "completed",
                            "provider_audit": (
                                outcome.provider_audit.model_dump(mode="json")
                            ),
                            "strategy_audit": (
                                outcome.strategy_audit.model_dump(mode="json")
                            ),
                        }
                    )
                else:
                    strategies.append(fallback_by_brief[brief.brief_id])
                    if isinstance(outcome, FallbackDecision):
                        payload = self._fallback_payload(outcome)
                    elif isinstance(outcome, ColorStrategyValidationError):
                        payload = {
                            "status": "audit-rejected",
                            "detail": str(outcome),
                            "strategy_audit": outcome.audit.model_dump(
                                mode="json"
                            ),
                        }
                    elif isinstance(outcome, BaseException):
                        payload = {
                            "status": "failed-closed-to-local-fallback",
                            "error_type": type(outcome).__name__,
                            "detail": str(outcome),
                        }
                    else:
                        raise TypeError(
                            "creative Strategist returned an unknown result"
                        )
                    strategist_provider_results.append(
                        {
                            "brief_id": brief.brief_id,
                            **payload,
                        }
                    )
        self._write_run_artifact(
            "strategist-provider-results.json",
            {
                "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
                "provider_successes": self._strategist_provider_successes,
                "brief_count": len(thesis.briefs),
                "items": strategist_provider_results,
            },
        )
        strategy_audit = audit_color_strategy_set(
            strategies,
            briefs=thesis.briefs,
            thesis=thesis,
            retrieval=retrieval,
            retrieval_asset_sha256=retrieval_sha,
            context=evidence.context_pack,
            baseline=evidence.technical_baseline.payload,
            baseline_asset_id=evidence.technical_baseline.asset_id,
            baseline_asset_sha256=evidence.technical_baseline.sha256,
            catalog=catalog,
        )
        if not strategy_audit.valid:
            raise ValueError(
                "offline strategies failed audit: "
                + ", ".join(
                    item.code.value for item in strategy_audit.violations
                )
            )
        self._strategies = strategies
        self._write_run_artifact("color-strategies.json", {
            "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
            "strategies": [
                item.model_dump(mode="json") for item in strategies
            ],
        })
        self._write_run_artifact("strategy-audit.json", strategy_audit)
        registry = build_project_operation_registry(self.graph)
        inputs: list[SearchCandidateInput] = []
        compilation_audits: list[dict[str, object]] = []
        briefs_by_id = {item.brief_id: item for item in thesis.briefs}
        for strategy in strategies:
            compilation = compile_color_strategy(
                strategy,
                source_graph=self.graph,
                expected_source_graph_digest=graph_digest(self.graph),
                technical_baseline=evidence.technical_baseline.payload,
                baseline_asset_id=evidence.technical_baseline.asset_id,
                baseline_asset_sha256=evidence.technical_baseline.sha256,
                registry=registry,
                policy=CompilationPolicy(
                    maximum_variants=0,
                    variation_fraction=0.25,
                    non_waivable_qc_checks=sorted(
                        MANDATORY_COMPILER_QC_CHECKS
                    ),
                ),
            )
            candidate: CompiledGraphCandidate = compilation.candidates[0]
            inputs.append(
                SearchCandidateInput(
                    brief=briefs_by_id[strategy.brief_id],
                    strategy=strategy,
                    compiled=candidate,
                )
            )
            compilation_audits.append(
                {
                    "strategy_id": strategy.strategy_id,
                    "candidate_id": candidate.contract.candidate_id,
                    "audit": compilation.audit.model_dump(mode="json"),
                }
            )
        self._write_run_artifact(
            "compilation-audits.json",
            {
                "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
                "items": compilation_audits,
            },
        )
        if self._cancel_requested():
            return self._cancel(stage=AgentUIStage.COMPILING, progress=54)

        self._save_snapshot(
            status=AgentUIRunStatus.RUNNING,
            stage=AgentUIStage.RENDERING,
            progress=55,
            message=(
                "Rendering real source frames through the same ColorGraph engine "
                "and running non-waivable hard QC."
            ),
            selection_status="rendering-real-candidates",
        )
        search_runner = BudgetedCandidateSearchRunner(
            renderer=self.renderer,
            qc_evaluator=DeterministicSearchHardGates(),
            store=self.search_store,
        )
        total = len(inputs)

        def progress_callback(state: CandidateSearchState) -> None:
            self._records = list(state.candidates)
            completed = len(state.candidates)
            progress = min(88, 55 + round(33 * completed / max(1, total)))
            self._save_snapshot(
                status=AgentUIRunStatus.RUNNING,
                stage=AgentUIStage.RENDERING,
                progress=progress,
                message=(
                    f"Rendered and checked {completed}/{total} real "
                    "scene-direction candidates."
                ),
                records=self._records,
                state=state,
                selection_status="rendering-real-candidates",
            )

        search = search_runner.run(
            run_id=self.request.run_id,
            context=evidence.context_pack,
            current_graph=self.graph,
            candidates=inputs,
            budget=self.request.search_budget,
            cancel_check=self._cancel_requested,
            progress_callback=progress_callback,
        )
        self._records = list(search.state.candidates)
        if search.state.status == CandidateSearchStatus.CANCELLED:
            return self._cancel(
                stage=AgentUIStage.RENDERING,
                progress=min(
                    88,
                    55
                    + round(
                        33
                        * len(search.state.candidates)
                        / max(1, total)
                    ),
                ),
                state=search.state,
            )
        if search.state.status != CandidateSearchStatus.COMPLETE:
            raise RuntimeError(
                "offline candidate search stopped before completion: "
                f"{search.state.status.value}"
            )
        survivors = list(search.survivors)
        if len(survivors) < 2:
            raise RuntimeError(
                "offline candidate search produced fewer than two hard-QC survivors"
            )
        critic_provider_results: list[dict[str, object]] = []
        strategy_by_brief = {
            item.brief_id: item for item in self._strategies
        }
        if self.provider_runtime is not None:
            self._save_snapshot(
                status=AgentUIRunStatus.RUNNING,
                stage=AgentUIStage.CRITICIZING,
                progress=90,
                message=(
                    "Running blind A/B and forced position-swap Visual Critic "
                    "probes; deterministic QC remains immutable."
                ),
                records=self._records,
                state=search.state,
                selection_status="provider-critic-shadow",
                skipped_stages=[AgentUIStage.REFINING],
            )
            records_by_scene: dict[str, list[SearchCandidateRecord]] = {}
            for record in survivors:
                brief = briefs_by_id[record.brief_id]
                records_by_scene.setdefault(brief.scene_id, []).append(record)
            critic_jobs: list[
                tuple[
                    str,
                    tuple[
                        BlindCriticRequestContext,
                        BlindCriticRequestContext,
                    ],
                ]
            ] = []
            for scene_id, scene_records in sorted(records_by_scene.items()):
                if len(scene_records) < 2:
                    continue
                left, right = scene_records[:2]
                left_strategy = strategy_by_brief[left.brief_id]
                right_strategy = strategy_by_brief[right.brief_id]
                requests = build_blind_pairwise_critic_requests(
                    pair_id=f"{self.request.run_id}:{scene_id}",
                    left_record=left,
                    left_brief=briefs_by_id[left.brief_id],
                    left_exceptions=left_strategy.intentional_exceptions,
                    right_record=right,
                    right_brief=briefs_by_id[right.brief_id],
                    right_exceptions=right_strategy.intentional_exceptions,
                    randomization_seed=canonical_sha256(
                        {
                            "run_id": self.request.run_id,
                            "scene_id": scene_id,
                            "candidate_ids": [
                                left.candidate_id,
                                right.candidate_id,
                            ],
                        }
                    ),
                    cloud_upload_consent=self.request.cloud_upload_consent,
                )
                critic_jobs.append((scene_id, requests))
            self._expected_critic_pairs = len(critic_jobs)

            async def run_critics() -> list[object]:
                assert self._director_identity is not None
                return list(
                    await asyncio.gather(
                        *(
                            run_blind_pairwise_critic(
                                self.provider_runtime,
                                requests=requests,
                                director_identity=self._director_identity,
                                calibration_gate=self.critic_calibration_gate,
                            )
                            for _, requests in critic_jobs
                        ),
                        return_exceptions=True,
                    )
                )

            critic_outcomes = (
                self._await_provider(run_critics()) if critic_jobs else []
            )
            for (scene_id, _), outcome in zip(
                critic_jobs,
                critic_outcomes,
                strict=True,
            ):
                if isinstance(outcome, PairwiseVisualCriticReport):
                    self._critic_reports.append(outcome)
                    for critique in outcome.critiques:
                        self._critic_notes[critique.candidate_id] = [
                            AgentUICritiqueDimension(
                                dimension=score.dimension,
                                score=score.score,
                                confidence=score.confidence,
                                concise_reason=score.concise_reason,
                            )
                            for score in critique.scores
                        ]
                    critic_provider_results.append(
                        {
                            "scene_id": scene_id,
                            "status": "completed",
                            "report": outcome.model_dump(mode="json"),
                        }
                    )
                elif isinstance(outcome, FallbackDecision):
                    critic_provider_results.append(
                        {
                            "scene_id": scene_id,
                            **self._fallback_payload(outcome),
                        }
                    )
                elif isinstance(outcome, VisualCriticValidationError):
                    critic_provider_results.append(
                        {
                            "scene_id": scene_id,
                            "status": "audit-rejected",
                            "detail": str(outcome),
                            "critic_audit": outcome.audit.model_dump(
                                mode="json"
                            ),
                        }
                    )
                elif isinstance(outcome, BaseException):
                    critic_provider_results.append(
                        {
                            "scene_id": scene_id,
                            "status": "failed-closed",
                            "error_type": type(outcome).__name__,
                            "detail": str(outcome),
                        }
                    )
                else:
                    raise TypeError("Visual Critic returned an unknown result")
        self._write_run_artifact(
            "critic-provider-results.json",
            {
                "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
                "expected_pairs": self._expected_critic_pairs,
                "completed_pairs": len(self._critic_reports),
                "calibration_gate_sha256": (
                    canonical_sha256(self.critic_calibration_gate)
                    if self.critic_calibration_gate is not None
                    else None
                ),
                "items": critic_provider_results,
            },
        )
        critic_calibrated = bool(
            self._critic_reports
            and all(item.calibration_authorized for item in self._critic_reports)
        )
        reflection = self._run_reflection_shadow(
            survivors=survivors,
            briefs_by_id=briefs_by_id,
            strategy_by_brief=strategy_by_brief,
            search_state=search.state,
        )
        if (
            reflection.completed
            and reflection.outcome is not None
            and reflection.outcome.accepted
            and reflection.refined_record is not None
        ):
            self._records.append(reflection.refined_record)
        selected_reflection_record = reflection.selected_record
        preferred = (
            selected_reflection_record.candidate_id
            if selected_reflection_record is not None
            else survivors[0].candidate_id
        )
        runner_up = next(
            item.candidate_id
            for item in survivors
            if item.candidate_id != preferred
        )
        application_records = [
            (
                reflection.refined_record
                if (
                    reflection.completed
                    and reflection.outcome is not None
                    and reflection.outcome.accepted
                    and reflection.parent_record is not None
                    and reflection.refined_record is not None
                    and item.candidate_id
                    == reflection.parent_record.candidate_id
                )
                else item
            )
            for item in survivors
        ]
        manifest_assets: list[CandidateApplicationAsset] = []
        for record in application_records:
            strategy = strategy_by_brief[record.brief_id]
            manifest_assets.append(
                CandidateApplicationAsset(
                    candidate_id=record.candidate_id,
                    graph_relative_path=Path(record.graph_path)
                    .resolve()
                    .relative_to(self.project_root)
                    .as_posix(),
                    graph_digest=record.compiled_graph_digest,
                    undo_graph_relative_path=Path(record.undo_graph_path)
                    .resolve()
                    .relative_to(self.project_root)
                    .as_posix(),
                    application_scopes=[
                        item.scope for item in strategy.actions
                    ],
                )
            )
        self.ui_store.save_application_manifest(
            AgentApplicationManifest(
                project_id=self.request.project_id,
                run_id=self.request.run_id,
                source_graph_digest=graph_digest(self.graph),
                candidates=manifest_assets,
            )
        )
        provider_pipeline_complete = bool(
            self.provider_runtime is not None
            and self._director_provider_used
            and self._strategist_provider_successes == len(thesis.briefs)
            and self._expected_critic_pairs > 0
            and len(self._critic_reports) == self._expected_critic_pairs
        )
        provider_requested_path_complete = bool(
            provider_pipeline_complete
            and (
                not self.request.reflection_shadow_enabled
                or reflection.completed
            )
        )
        snapshot = self._save_snapshot(
            status=(
                AgentUIRunStatus.READY_FOR_REVIEW
                if provider_requested_path_complete
                else AgentUIRunStatus.OFFLINE_FALLBACK
            ),
            stage=AgentUIStage.READY,
            progress=100,
            message=(
                (
                    (
                        "Provider Shadow candidates, blind Critic reports, and "
                        "one bounded Reflection are ready for human review. "
                        "No candidate was applied automatically."
                    )
                    if self.request.reflection_shadow_enabled
                    else (
                        "Provider Shadow candidates and blind Critic reports are "
                        "ready for human review. No candidate was applied "
                        "automatically."
                    )
                )
                if provider_requested_path_complete
                else (
                    "Shadow candidates are ready with explicit local fallbacks. "
                    "Real rendering and hard QC completed; unavailable model stages "
                    "were not fabricated."
                )
            ),
            records=self._records,
            state=search.state,
            preferred_candidate_id=preferred,
            runner_up_candidate_id=runner_up,
            selection_status=(
                "provider-shadow-awaiting-human-review"
                if provider_requested_path_complete
                else "fallback-provisional-awaiting-human-review"
            ),
            gate_trace=[
                "deterministic-compiler:passed",
                "real-frame-rendering:passed",
                "non-waivable-qc:passed",
                (
                    "visual-critic:shadow-completed"
                    if self._critic_reports
                    else "visual-critic:skipped-or-fallback"
                ),
                (
                    "critic-calibration:authorized"
                    if critic_calibrated
                    else "critic-calibration:not-authorized"
                ),
                f"reflection:{reflection.stage_status}",
                "user-confirmation:required",
            ],
            skipped_stages=(
                []
                if reflection.stage_executed
                else [AgentUIStage.REFINING]
                if self._critic_reports
                else [
                    AgentUIStage.CRITICIZING,
                    AgentUIStage.REFINING,
                ]
            ),
            clear_control_requests=True,
        )
        self._write_run_artifact(
            "pipeline-result.json",
            {
                "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
                "status": snapshot.status.value,
                "snapshot_digest": snapshot.snapshot_digest,
                "search_state_digest": canonical_sha256(search.state),
                "hard_pass_candidate_ids": [
                    item.candidate_id for item in survivors
                ],
                "preferred_candidate_id": preferred,
                "runner_up_candidate_id": runner_up,
                "provider_pipeline_complete": provider_pipeline_complete,
                "provider_requested_path_complete": (
                    provider_requested_path_complete
                ),
                "director_provider_used": self._director_provider_used,
                "strategist_provider_successes": (
                    self._strategist_provider_successes
                ),
                "strategist_brief_count": len(thesis.briefs),
                "critic_stage": (
                    "shadow-completed"
                    if self._critic_reports
                    else "skipped-or-fallback"
                ),
                "critic_completed_pairs": len(self._critic_reports),
                "critic_expected_pairs": self._expected_critic_pairs,
                "critic_calibration_authorized": critic_calibrated,
                "reflection_requested": self.request.reflection_shadow_enabled,
                "reflection_stage": reflection.stage_status,
                "reflection_stage_executed": reflection.stage_executed,
                "reflection_completed": reflection.completed,
                "reflection_parent_candidate_id": (
                    reflection.parent_record.candidate_id
                    if reflection.parent_record is not None
                    else None
                ),
                "reflection_refined_candidate_id": (
                    reflection.refined_record.candidate_id
                    if reflection.refined_record is not None
                    else None
                ),
                "reflection_selected_candidate_id": (
                    reflection.selected_record.candidate_id
                    if reflection.selected_record is not None
                    else None
                ),
                "reflection_outcome_sha256": (
                    canonical_sha256(reflection.outcome)
                    if reflection.outcome is not None
                    else None
                ),
                "reflection_automatic_selection_allowed": False,
                "user_confirmation_required": True,
                "current_graph_unchanged": True,
            },
        )
        return OfflineCreativePipelineResult(
            snapshot=snapshot,
            search=search,
            cancelled=False,
        )

    def run(self) -> OfflineCreativePipelineResult:
        provider_released = False
        try:
            result = self._run()
            if self._provider_loop is not None and self.provider_runtime is not None:
                self._provider_loop.run_until_complete(
                    self.provider_runtime.release()
                )
                provider_released = True
            return result
        except Exception as exc:
            snapshot = self._save_snapshot(
                status=AgentUIRunStatus.FAILED,
                stage=self._last_stage,
                progress=100,
                message=(
                    "Offline Shadow run failed closed; the current Grade Graph "
                    "was not changed."
                ),
                records=self._records,
                selection_status="failed-closed",
                skipped_stages=[
                    AgentUIStage.CRITICIZING,
                    AgentUIStage.REFINING,
                ],
                last_error=f"{type(exc).__name__}: {exc}",
                clear_control_requests=True,
            )
            self._write_run_artifact(
                "pipeline-failure.json",
                {
                    "schema_version": OFFLINE_CREATIVE_PIPELINE_VERSION,
                    "status": "failed",
                    "stage": self._last_stage.value,
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                    "current_graph_unchanged": True,
                },
            )
            raise RuntimeError(snapshot.last_error) from exc
        finally:
            if self._provider_loop is not None:
                if not provider_released and self.provider_runtime is not None:
                    with suppress(Exception):
                        self._provider_loop.run_until_complete(
                            self.provider_runtime.release()
                        )
                self._provider_loop.close()
                self._provider_loop = None
