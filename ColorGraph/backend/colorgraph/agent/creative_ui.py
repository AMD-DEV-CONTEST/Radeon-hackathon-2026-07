from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

from colorgraph.agent.creative_contracts import (
    CreativeDirection,
    CritiqueDimension,
    NonEmptyString,
    NormalizedScore,
    Sha256,
    StrategyScope,
    StrictFrozenModel,
    canonical_sha256,
)
from colorgraph.domain.grade_graph import GradeGraph
from colorgraph.grading.looks import graph_digest
from colorgraph.storage import ProjectStore

AGENT_UI_CONTRACT_VERSION = "colorgraph.creative-agent-ui/v1"


class AgentUIStage(StrEnum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    INTERPRETING = "interpreting"
    RETRIEVING = "retrieving"
    COMPILING = "compiling"
    RENDERING = "rendering"
    CRITICIZING = "criticizing"
    REFINING = "refining"
    READY = "ready"


class AgentUIRunStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_CONSENT = "waiting_for_consent"
    READY_FOR_REVIEW = "ready_for_review"
    FAILED = "failed"
    CANCELLED = "cancelled"
    OFFLINE_FALLBACK = "offline_fallback"


class AgentUIControlAction(StrEnum):
    CANCEL = "cancel"
    RESUME = "resume"


class AgentUIProviderSnapshot(StrictFrozenModel):
    provider_id: NonEmptyString
    model_id: NonEmptyString
    model_revision: NonEmptyString
    boundary: Literal["local", "cloud", "openai_compatible"]
    network_enabled: bool
    cloud_upload_required: bool
    cloud_upload_consented: bool

    @model_validator(mode="after")
    def validate_upload_boundary(self) -> AgentUIProviderSnapshot:
        if self.boundary == "local" and self.cloud_upload_required:
            raise ValueError("a local provider cannot require cloud upload")
        if self.cloud_upload_consented and not self.cloud_upload_required:
            raise ValueError("upload consent cannot be claimed when upload is not required")
        return self


class AgentUIBudgetSnapshot(StrictFrozenModel):
    model_calls_used: int = Field(ge=0)
    model_calls_limit: int = Field(ge=0)
    rendered_frames_used: int = Field(ge=0)
    rendered_frames_limit: int = Field(ge=0)
    cost_usd_used: float = Field(ge=0)
    cost_usd_limit: float = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    wall_seconds_limit: float = Field(gt=0)
    refinements_used: int = Field(ge=0, le=1)
    refinements_limit: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def remain_within_budget(self) -> AgentUIBudgetSnapshot:
        if (
            self.model_calls_used > self.model_calls_limit
            or self.rendered_frames_used > self.rendered_frames_limit
            or self.cost_usd_used > self.cost_usd_limit
            or self.elapsed_seconds > self.wall_seconds_limit
            or self.refinements_used > self.refinements_limit
        ):
            raise ValueError("Agent UI snapshot reports usage beyond its frozen budget")
        return self


class AgentUIEvidenceSnapshot(StrictFrozenModel):
    evidence_id: NonEmptyString
    label: NonEmptyString
    role: Literal["support", "counterevidence", "source", "current", "candidate"]
    scene_id: NonEmptyString | None = None
    shot_id: NonEmptyString | None = None
    frame_index: int | None = Field(default=None, ge=0)
    thumbnail_url: NonEmptyString | None = None


class AgentUICritiqueDimension(StrictFrozenModel):
    dimension: CritiqueDimension
    score: NormalizedScore
    confidence: NormalizedScore
    concise_reason: NonEmptyString


class AgentUIRefinementDiff(StrictFrozenModel):
    patch_id: NonEmptyString
    status: NonEmptyString
    hypothesis: NonEmptyString
    changes: list[NonEmptyString] = Field(min_length=1)
    rollback_available: bool


class AgentUIDirectionSnapshot(StrictFrozenModel):
    brief_id: NonEmptyString
    direction: CreativeDirection
    title: NonEmptyString
    interpretation: NonEmptyString
    emotional_target: NonEmptyString
    support_evidence_ids: list[NonEmptyString] = Field(min_length=1)
    counterevidence_ids: list[NonEmptyString] = Field(min_length=1)
    protections: list[NonEmptyString] = Field(min_length=1)
    intentional_exceptions: list[NonEmptyString]
    failure_conditions: list[NonEmptyString] = Field(min_length=1)
    candidate_id: NonEmptyString | None = None
    candidate_thumbnail_urls: list[NonEmptyString]
    qc_status: Literal["pending", "pass", "fail"]
    critique: list[AgentUICritiqueDimension]
    is_pareto: bool
    is_preferred: bool
    is_runner_up: bool
    application_scopes: list[StrategyScope]
    refinement: AgentUIRefinementDiff | None = None

    @model_validator(mode="after")
    def validate_candidate_state(self) -> AgentUIDirectionSnapshot:
        if self.is_preferred and self.is_runner_up:
            raise ValueError("one direction cannot be both preferred and runner-up")
        if (
            self.candidate_id is None
            and (
                self.candidate_thumbnail_urls
                or self.critique
                or self.qc_status != "pending"
                or self.is_pareto
                or self.is_preferred
                or self.is_runner_up
                or self.application_scopes
            )
        ):
            raise ValueError("direction claims candidate evidence before a candidate exists")
        dimensions = [item.dimension for item in self.critique]
        if dimensions and set(dimensions) != set(CritiqueDimension):
            raise ValueError("UI critique must expose every independent dimension")
        return self


class AgentUISceneSnapshot(StrictFrozenModel):
    scene_id: NonEmptyString
    scene_label: NonEmptyString
    narrative_role: NonEmptyString
    continuity_notes: list[NonEmptyString] = Field(min_length=1)
    evidence: list[AgentUIEvidenceSnapshot]
    directions: list[AgentUIDirectionSnapshot] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def exact_directions(self) -> AgentUISceneSnapshot:
        if {item.direction for item in self.directions} != set(CreativeDirection):
            raise ValueError("Agent UI scene must expose all three creative directions")
        known_evidence = {item.evidence_id for item in self.evidence}
        for direction in self.directions:
            unknown = (
                set(direction.support_evidence_ids)
                | set(direction.counterevidence_ids)
            ) - known_evidence
            if unknown:
                raise ValueError(
                    f"Agent UI direction references unknown evidence: {sorted(unknown)}"
                )
        return self


class AgentUISelectionSnapshot(StrictFrozenModel):
    status: NonEmptyString
    preferred_candidate_id: NonEmptyString | None = None
    runner_up_candidate_id: NonEmptyString | None = None
    pareto_candidate_ids: list[NonEmptyString]
    gate_trace: list[NonEmptyString]
    automatic_selection_allowed: bool
    requires_user_confirmation: bool
    applied_candidate_id: NonEmptyString | None = None
    undo_revision: NonEmptyString | None = None
    applied_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> AgentUISelectionSnapshot:
        if (self.preferred_candidate_id is None) != (
            self.runner_up_candidate_id is None
        ):
            raise ValueError("UI selection requires preferred and runner-up together")
        if (
            self.preferred_candidate_id is not None
            and self.preferred_candidate_id == self.runner_up_candidate_id
        ):
            raise ValueError("preferred and runner-up must differ")
        if self.automatic_selection_allowed and self.requires_user_confirmation:
            raise ValueError("automatic selection conflicts with required confirmation")
        application_fields = (
            self.applied_candidate_id,
            self.undo_revision,
            self.applied_at,
        )
        if any(value is not None for value in application_fields) and not all(
            value is not None for value in application_fields
        ):
            raise ValueError("applied candidate, undo revision, and timestamp are atomic")
        if self.applied_candidate_id is not None:
            if self.applied_candidate_id not in {
                self.preferred_candidate_id,
                self.runner_up_candidate_id,
            }:
                raise ValueError("only a retained candidate may be recorded as applied")
            if self.requires_user_confirmation:
                raise ValueError("an applied candidate cannot still require confirmation")
        return self


class AgentUIControlRequest(StrictFrozenModel):
    action: AgentUIControlAction
    requested_at: AwareDatetime
    expected_snapshot_revision: int = Field(ge=0)


class AgentFeedbackRequest(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-feedback-request/v1"] = (
        "colorgraph.agent-feedback-request/v1"
    )
    project_id: NonEmptyString
    run_id: NonEmptyString
    candidate_id: NonEmptyString
    feedback: NonEmptyString
    expected_snapshot_revision: int = Field(ge=0)
    requested_at: AwareDatetime
    mode: Literal["adjust_existing_strategy", "new_thesis_branch"]


class AgentRunUISnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["colorgraph.creative-agent-ui/v1"] = (
        AGENT_UI_CONTRACT_VERSION
    )
    project_id: NonEmptyString
    run_id: NonEmptyString
    snapshot_revision: int = Field(ge=0)
    snapshot_digest: Sha256
    status: AgentUIRunStatus
    stage: AgentUIStage
    progress: int = Field(ge=0, le=100)
    message: NonEmptyString
    updated_at: AwareDatetime
    shadow_mode: bool
    current_graph_digest: Sha256
    current_graph_unchanged: bool
    offline_available: bool
    project_visual_thesis: NonEmptyString | None = None
    palette_character: NonEmptyString | None = None
    contrast_character: NonEmptyString | None = None
    provider: AgentUIProviderSnapshot
    budget: AgentUIBudgetSnapshot
    scenes: list[AgentUISceneSnapshot]
    selection: AgentUISelectionSnapshot
    skipped_stages: list[AgentUIStage] = Field(default_factory=list)
    cancellation_requested: bool = False
    resume_requested: bool = False
    last_error: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_snapshot(
        self,
        info: ValidationInfo,
    ) -> AgentRunUISnapshot:
        candidate_ids = {
            direction.candidate_id
            for scene in self.scenes
            for direction in scene.directions
            if direction.candidate_id is not None
        }
        selected = {
            self.selection.preferred_candidate_id,
            self.selection.runner_up_candidate_id,
            self.selection.applied_candidate_id,
            *self.selection.pareto_candidate_ids,
        } - {None}
        if not selected <= candidate_ids:
            raise ValueError("Agent UI selection references an unknown candidate")
        preferred = [
            item.candidate_id
            for scene in self.scenes
            for item in scene.directions
            if item.is_preferred
        ]
        runner_up = [
            item.candidate_id
            for scene in self.scenes
            for item in scene.directions
            if item.is_runner_up
        ]
        if preferred not in (
            [],
            [self.selection.preferred_candidate_id],
        ):
            raise ValueError("direction preferred marker differs from selection")
        if runner_up not in ([], [self.selection.runner_up_candidate_id]):
            raise ValueError("direction runner-up marker differs from selection")
        if self.status == AgentUIRunStatus.FAILED and self.last_error is None:
            raise ValueError("failed Agent UI run requires an error")
        if (
            self.status == AgentUIRunStatus.WAITING_FOR_CONSENT
            and (
                not self.provider.cloud_upload_required
                or self.provider.cloud_upload_consented
            )
        ):
            raise ValueError("consent wait state differs from provider boundary")
        if (
            self.shadow_mode
            and not self.current_graph_unchanged
            and self.selection.requires_user_confirmation
        ):
            raise ValueError(
                "shadow run cannot mutate the graph before explicit confirmation"
            )
        invalid_skips = set(self.skipped_stages) - {
            AgentUIStage.CRITICIZING,
            AgentUIStage.REFINING,
        }
        if invalid_skips:
            raise ValueError(
                "only optional Critic and Reflection stages may be marked skipped"
            )
        if len(self.skipped_stages) != len(set(self.skipped_stages)):
            raise ValueError("Agent UI skipped stages must be unique")
        if not (info.context or {}).get("allow_unsealed_snapshot"):
            expected_digest = snapshot_digest(self)
            if self.snapshot_digest != expected_digest:
                raise ValueError("Agent UI snapshot digest mismatch")
        return self


class CandidateApplicationAsset(StrictFrozenModel):
    candidate_id: NonEmptyString
    graph_relative_path: NonEmptyString
    graph_digest: Sha256
    undo_graph_relative_path: NonEmptyString
    application_scopes: list[StrategyScope] = Field(min_length=1)


class AgentApplicationManifest(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-application-manifest/v1"] = (
        "colorgraph.agent-application-manifest/v1"
    )
    project_id: NonEmptyString
    run_id: NonEmptyString
    source_graph_digest: Sha256
    candidates: list[CandidateApplicationAsset] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_candidates(self) -> AgentApplicationManifest:
        identifiers = [item.candidate_id for item in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("application manifest candidate IDs must be unique")
        return self


class AgentApplyRequest(StrictFrozenModel):
    candidate_id: NonEmptyString
    expected_graph_digest: Sha256
    expected_snapshot_revision: int = Field(ge=0)
    confirmation: Literal[True]


class AgentApplicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["applied"] = "applied"
    candidate_id: NonEmptyString
    previous_graph_digest: Sha256
    applied_graph_digest: Sha256
    undo_revision: NonEmptyString
    application_scopes: list[StrategyScope]
    graph: GradeGraph


class AgentPreferenceEntry(StrictFrozenModel):
    entry_id: NonEmptyString
    project_id: NonEmptyString
    user_scope_id: NonEmptyString
    selected_candidate_id: NonEmptyString
    compared_candidate_ids: list[NonEmptyString] = Field(min_length=2)
    preferred_strength: NormalizedScore | None = None
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def validate_preference(self) -> AgentPreferenceEntry:
        if len(self.compared_candidate_ids) != len(
            set(self.compared_candidate_ids)
        ):
            raise ValueError("preference comparison candidates must be unique")
        if self.selected_candidate_id not in self.compared_candidate_ids:
            raise ValueError("preference selection must belong to its comparison")
        return self


class AgentPreferenceMemory(StrictFrozenModel):
    schema_version: Literal["colorgraph.project-preference-memory/v1"] = (
        "colorgraph.project-preference-memory/v1"
    )
    project_id: NonEmptyString
    user_scope_id: NonEmptyString
    entries: list[AgentPreferenceEntry]


def snapshot_digest(snapshot: AgentRunUISnapshot) -> str:
    payload = snapshot.model_dump(mode="json")
    payload["snapshot_digest"] = "0" * 64
    return canonical_sha256(payload)


def seal_snapshot(**values: object) -> AgentRunUISnapshot:
    provisional = AgentRunUISnapshot.model_validate(
        {
            **values,
            "snapshot_digest": "0" * 64,
        },
        context={"allow_unsealed_snapshot": True},
    )
    return AgentRunUISnapshot.model_validate(
        {
            **provisional.model_dump(mode="python"),
            "snapshot_digest": snapshot_digest(provisional),
        }
    )


def idle_agent_ui_snapshot(
    *,
    project_id: str,
    graph: GradeGraph,
    updated_at: datetime | None = None,
) -> AgentRunUISnapshot:
    timestamp = updated_at or datetime.now(UTC)
    return seal_snapshot(
        project_id=project_id,
        run_id="none",
        snapshot_revision=0,
        status=AgentUIRunStatus.IDLE,
        stage=AgentUIStage.IDLE,
        progress=0,
        message="No creative Agent shadow run has been started for this project.",
        updated_at=timestamp,
        shadow_mode=True,
        current_graph_digest=graph_digest(graph),
        current_graph_unchanged=True,
        offline_available=True,
        project_visual_thesis=None,
        palette_character=None,
        contrast_character=None,
        provider=AgentUIProviderSnapshot(
            provider_id="offline-rules",
            model_id="local-clip-rule-planner",
            model_revision="v1",
            boundary="local",
            network_enabled=False,
            cloud_upload_required=False,
            cloud_upload_consented=False,
        ),
        budget=AgentUIBudgetSnapshot(
            model_calls_used=0,
            model_calls_limit=0,
            rendered_frames_used=0,
            rendered_frames_limit=1,
            cost_usd_used=0,
            cost_usd_limit=0,
            elapsed_seconds=0,
            wall_seconds_limit=1,
            refinements_used=0,
            refinements_limit=0,
        ),
        scenes=[],
        selection=AgentUISelectionSnapshot(
            status="not-started",
            preferred_candidate_id=None,
            runner_up_candidate_id=None,
            pareto_candidate_ids=[],
            gate_trace=[],
            automatic_selection_allowed=False,
            requires_user_confirmation=True,
        ),
        skipped_stages=[],
        cancellation_requested=False,
        resume_requested=False,
        last_error=None,
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class AgentUIStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.root = self.project_root / "creative-agent"

    @property
    def current_snapshot_path(self) -> Path:
        return self.root / "ui-current.json"

    @property
    def application_manifest_path(self) -> Path:
        return self.root / "application-manifest.json"

    @property
    def control_path(self) -> Path:
        return self.root / "control-request.json"

    @property
    def feedback_path(self) -> Path:
        return self.root / "feedback-request.json"

    def load_snapshot(self) -> AgentRunUISnapshot | None:
        if not self.current_snapshot_path.is_file():
            return None
        content = self.current_snapshot_path.read_text(encoding="utf-8")
        try:
            return AgentRunUISnapshot.model_validate_json(content)
        except ValueError:
            # skipped_stages was added without changing the v1 wire identifier.
            # Accept only a correctly sealed pre-field payload, then reseal the
            # in-memory representation. Any other digest mismatch still fails.
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError("Agent UI snapshot must be a JSON object") from None
            if (
                payload.get("schema_version") != AGENT_UI_CONTRACT_VERSION
                or "skipped_stages" in payload
            ):
                raise
            legacy_digest = payload.get("snapshot_digest")
            legacy_payload = dict(payload)
            legacy_payload["snapshot_digest"] = "0" * 64
            if legacy_digest != canonical_sha256(legacy_payload):
                raise
            migrated = {
                **payload,
                "skipped_stages": [],
                "snapshot_digest": "0" * 64,
            }
            provisional = AgentRunUISnapshot.model_validate_json(
                json.dumps(migrated, ensure_ascii=False),
                context={"allow_unsealed_snapshot": True},
            )
            values = provisional.model_dump(mode="python")
            values.pop("snapshot_digest")
            return seal_snapshot(**values)

    def save_snapshot(self, snapshot: AgentRunUISnapshot) -> Path:
        if snapshot.project_id != self.project_root.name:
            raise ValueError("Agent UI snapshot belongs to another project")
        existing = self.load_snapshot()
        expected_revision = (
            0 if existing is None else existing.snapshot_revision + 1
        )
        if snapshot.snapshot_revision != expected_revision:
            raise ValueError(
                f"Agent UI snapshot revision must be {expected_revision}"
            )
        revision_path = (
            self.root
            / f"ui-snapshot-{snapshot.snapshot_revision:06d}.json"
        )
        content = snapshot.model_dump_json(indent=2)
        if revision_path.exists():
            if revision_path.read_text(encoding="utf-8") != content:
                raise ValueError("Agent UI snapshot revision is immutable")
        else:
            _atomic_write(revision_path, content)
        _atomic_write(self.current_snapshot_path, content)
        return revision_path

    def request_control(
        self,
        action: AgentUIControlAction,
        *,
        expected_revision: int,
        requested_at: datetime | None = None,
    ) -> AgentRunUISnapshot:
        snapshot = self.load_snapshot()
        if snapshot is None:
            raise FileNotFoundError("creative Agent snapshot is missing")
        if snapshot.snapshot_revision != expected_revision:
            raise ValueError("creative Agent control request is stale")
        if action == AgentUIControlAction.CANCEL and snapshot.status not in {
            AgentUIRunStatus.RUNNING,
            AgentUIRunStatus.WAITING_FOR_CONSENT,
        }:
            raise ValueError("creative Agent run is not cancellable")
        if action == AgentUIControlAction.RESUME and snapshot.status not in {
            AgentUIRunStatus.CANCELLED,
            AgentUIRunStatus.FAILED,
        }:
            raise ValueError("creative Agent run is not resumable")
        request = AgentUIControlRequest(
            action=action,
            requested_at=requested_at or datetime.now(UTC),
            expected_snapshot_revision=expected_revision,
        )
        _atomic_write(self.control_path, request.model_dump_json(indent=2))
        values = snapshot.model_dump(mode="python")
        values.update(
            {
                "snapshot_revision": snapshot.snapshot_revision + 1,
                "updated_at": request.requested_at,
                "cancellation_requested": (
                    action == AgentUIControlAction.CANCEL
                ),
                "resume_requested": action == AgentUIControlAction.RESUME,
            }
        )
        values.pop("snapshot_digest")
        updated = seal_snapshot(**values)
        self.save_snapshot(updated)
        return updated

    def save_application_manifest(
        self,
        manifest: AgentApplicationManifest,
    ) -> None:
        if manifest.project_id != self.project_root.name:
            raise ValueError("application manifest belongs to another project")
        _atomic_write(
            self.application_manifest_path,
            manifest.model_dump_json(indent=2),
        )

    def request_feedback(
        self,
        *,
        candidate_id: str,
        feedback: str,
        expected_revision: int,
        requested_at: datetime | None = None,
        mode: Literal[
            "adjust_existing_strategy",
            "new_thesis_branch",
        ] = "adjust_existing_strategy",
    ) -> AgentFeedbackRequest:
        snapshot = self.load_snapshot()
        if snapshot is None:
            raise FileNotFoundError("creative Agent snapshot is missing")
        if snapshot.snapshot_revision != expected_revision:
            raise ValueError("creative Agent feedback request is stale")
        if snapshot.status not in {
            AgentUIRunStatus.READY_FOR_REVIEW,
            AgentUIRunStatus.OFFLINE_FALLBACK,
        }:
            raise ValueError("creative Agent run is not ready for feedback")
        if candidate_id not in {
            snapshot.selection.preferred_candidate_id,
            snapshot.selection.runner_up_candidate_id,
        }:
            raise ValueError("feedback may target only a retained candidate")
        request = AgentFeedbackRequest(
            project_id=snapshot.project_id,
            run_id=snapshot.run_id,
            candidate_id=candidate_id,
            feedback=feedback.strip(),
            expected_snapshot_revision=expected_revision,
            requested_at=requested_at or datetime.now(UTC),
            mode=mode,
        )
        _atomic_write(
            self.feedback_path,
            request.model_dump_json(indent=2),
        )
        return request

    def reconcile_graph(
        self,
        graph: GradeGraph,
        *,
        updated_at: datetime | None = None,
    ) -> AgentRunUISnapshot | None:
        """Advance the UI audit snapshot after a graph write outside Agent apply."""
        snapshot = self.load_snapshot()
        if snapshot is None:
            return None
        digest = graph_digest(graph)
        if digest == snapshot.current_graph_digest:
            return snapshot
        timestamp = updated_at or datetime.now(UTC)
        manifest = (
            self.load_application_manifest()
            if self.application_manifest_path.is_file()
            else None
        )
        restored_source = bool(
            snapshot.selection.applied_candidate_id is not None
            and manifest is not None
            and manifest.run_id == snapshot.run_id
            and manifest.source_graph_digest == digest
        )
        selection = snapshot.selection.model_copy(
            update={
                "status": (
                    "ready-after-explicit-undo"
                    if restored_source
                    else "stale-source-graph-changed"
                ),
                "automatic_selection_allowed": False,
                "requires_user_confirmation": True,
                "applied_candidate_id": None,
                "undo_revision": None,
                "applied_at": None,
            }
        )
        values = snapshot.model_dump(mode="python")
        values.update(
            {
                "snapshot_revision": snapshot.snapshot_revision + 1,
                "status": (
                    AgentUIRunStatus.READY_FOR_REVIEW
                    if restored_source
                    else AgentUIRunStatus.FAILED
                ),
                "stage": AgentUIStage.READY,
                "message": (
                    "The explicit Agent application was undone; retained "
                    "shadow candidates are available for review."
                    if restored_source
                    else "The project graph changed after candidate generation; "
                    "this shadow run is stale and cannot be applied."
                ),
                "updated_at": timestamp,
                "shadow_mode": True,
                "current_graph_digest": digest,
                "current_graph_unchanged": True,
                "selection": selection,
                "cancellation_requested": False,
                "resume_requested": False,
                "last_error": (
                    None
                    if restored_source
                    else "Current graph digest differs from the frozen Agent source."
                ),
            }
        )
        values.pop("snapshot_digest")
        reconciled = seal_snapshot(**values)
        self.save_snapshot(reconciled)
        return reconciled

    def load_application_manifest(self) -> AgentApplicationManifest:
        if not self.application_manifest_path.is_file():
            raise FileNotFoundError("Agent application manifest is missing")
        return AgentApplicationManifest.model_validate_json(
            self.application_manifest_path.read_text(encoding="utf-8")
        )

    def preference_path(self, user_scope_id: str) -> Path:
        safe = "".join(
            character
            for character in user_scope_id
            if character.isalnum() or character in {"-", "_"}
        )
        if not safe:
            raise ValueError("invalid preference user scope")
        return self.root / "preferences" / f"{safe[:80]}.json"

    def load_preferences(self, user_scope_id: str) -> AgentPreferenceMemory:
        path = self.preference_path(user_scope_id)
        if not path.is_file():
            return AgentPreferenceMemory(
                project_id=self.project_root.name,
                user_scope_id=user_scope_id,
                entries=[],
            )
        memory = AgentPreferenceMemory.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if (
            memory.project_id != self.project_root.name
            or memory.user_scope_id != user_scope_id
        ):
            raise ValueError("preference memory scope mismatch")
        return memory

    def add_preference(self, entry: AgentPreferenceEntry) -> AgentPreferenceMemory:
        if entry.project_id != self.project_root.name:
            raise ValueError("preference belongs to another project")
        memory = self.load_preferences(entry.user_scope_id)
        entries = [item for item in memory.entries if item.entry_id != entry.entry_id]
        entries.append(entry)
        updated = memory.model_copy(update={"entries": entries})
        _atomic_write(
            self.preference_path(entry.user_scope_id),
            updated.model_dump_json(indent=2),
        )
        return updated

    def delete_preferences(self, user_scope_id: str) -> None:
        self.preference_path(user_scope_id).unlink(missing_ok=True)


def _safe_project_asset(project_root: Path, relative_path: str) -> Path:
    candidate = (project_root / relative_path).resolve()
    if (
        candidate == project_root
        or not candidate.is_relative_to(project_root)
        or not candidate.is_file()
    ):
        raise ValueError("Agent application asset escapes the project or is missing")
    return candidate


def apply_agent_candidate(
    *,
    store: ProjectStore,
    project_id: str,
    request: AgentApplyRequest,
) -> AgentApplicationResult:
    project = store.get(project_id)
    ui_store = AgentUIStore(project.root)
    snapshot = ui_store.load_snapshot()
    if snapshot is None:
        raise FileNotFoundError("creative Agent snapshot is missing")
    if snapshot.snapshot_revision != request.expected_snapshot_revision:
        raise ValueError("creative Agent apply request is stale")
    manifest = ui_store.load_application_manifest()
    if manifest.run_id != snapshot.run_id:
        raise ValueError("Agent application manifest belongs to another run")
    current = store.load_graph(project_id)
    current_digest = graph_digest(current)
    if (
        current_digest != request.expected_graph_digest
        or current_digest != manifest.source_graph_digest
    ):
        raise ValueError("current graph changed after Agent candidate generation")
    asset = next(
        (
            item
            for item in manifest.candidates
            if item.candidate_id == request.candidate_id
        ),
        None,
    )
    if asset is None:
        raise ValueError("unknown Agent candidate")
    if request.candidate_id not in {
        snapshot.selection.preferred_candidate_id,
        snapshot.selection.runner_up_candidate_id,
    }:
        raise ValueError("only the retained preferred or runner-up may be applied")
    graph_path = _safe_project_asset(project.root, asset.graph_relative_path)
    undo_path = _safe_project_asset(project.root, asset.undo_graph_relative_path)
    candidate = GradeGraph.model_validate(
        json.loads(graph_path.read_text(encoding="utf-8"))
    )
    undo = GradeGraph.model_validate(
        json.loads(undo_path.read_text(encoding="utf-8"))
    )
    if graph_digest(candidate) != asset.graph_digest:
        raise ValueError("Agent candidate graph digest mismatch")
    if graph_digest(undo) != current_digest:
        raise ValueError("Agent undo graph does not match the current graph")
    revision = store.save_graph_revision(
        project,
        current,
        label=f"pre-agent-{snapshot.run_id}-{request.candidate_id}",
    )
    applied_at = datetime.now(UTC)
    selection = snapshot.selection.model_copy(
        update={
            "status": "explicitly-applied",
            "requires_user_confirmation": False,
            "applied_candidate_id": request.candidate_id,
            "undo_revision": revision.name,
            "applied_at": applied_at,
        }
    )
    values = snapshot.model_dump(mode="python")
    values.update(
        {
            "snapshot_revision": snapshot.snapshot_revision + 1,
            "status": AgentUIRunStatus.READY_FOR_REVIEW,
            "stage": AgentUIStage.READY,
            "progress": 100,
            "message": (
                f"Candidate {request.candidate_id} was explicitly applied; "
                f"undo revision {revision.name} is available."
            ),
            "updated_at": applied_at,
            "shadow_mode": False,
            "current_graph_digest": asset.graph_digest,
            "current_graph_unchanged": False,
            "selection": selection,
            "cancellation_requested": False,
            "resume_requested": False,
        }
    )
    values.pop("snapshot_digest")
    applied_snapshot = seal_snapshot(**values)
    store.save_graph(project, candidate)
    try:
        ui_store.save_snapshot(applied_snapshot)
    except Exception:
        store.save_graph(project, current)
        raise
    return AgentApplicationResult(
        candidate_id=request.candidate_id,
        previous_graph_digest=current_digest,
        applied_graph_digest=asset.graph_digest,
        undo_revision=revision.name,
        application_scopes=asset.application_scopes,
        graph=candidate,
    )
