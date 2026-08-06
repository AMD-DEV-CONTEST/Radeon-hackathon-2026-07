from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .model_registry import ExecutionPhase, RadeonModelRouter
from .multimodal_ingest import MediaArtifact, MediaKind
from .quality_contract import (
    QualityAcceptanceContract,
    QualityTier,
    contract_for,
)


class MissionError(RuntimeError):
    pass


class DeliverableKind(str, Enum):
    SOCIAL_IMAGE = "social_image"
    SHORT_VIDEO = "short_video"
    CAPTION_SET = "caption_set"
    CAMPAIGN_PACK = "campaign_pack"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DeliverableSpec:
    kind: DeliverableKind
    aspect_ratio: str
    duration_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.kind == DeliverableKind.SHORT_VIDEO:
            if self.duration_seconds is None or not 3 <= self.duration_seconds <= 30:
                raise MissionError("short video duration must be between 3 and 30 seconds")
        elif self.duration_seconds is not None:
            raise MissionError("duration is only valid for short video deliverables")


@dataclass(frozen=True)
class EvidenceObservation:
    id: str
    source_artifact_id: str
    claim: str
    locator: str
    confidence: float
    model_ref: str

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise MissionError("observation confidence must be between 0 and 1")
        if not self.claim.strip():
            raise MissionError("observation requires a non-empty claim")
        if not self.locator.strip():
            raise MissionError("observation requires a source locator")


@dataclass(frozen=True)
class MissionStep:
    id: str
    kind: str
    depends_on: tuple[str, ...]
    required_roles: tuple[str, ...] = ()
    max_attempts: int = 1
    human_approval_required: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise MissionError("step max_attempts must be positive")


@dataclass(frozen=True)
class MissionPlan:
    mission_id: str
    input_ids: tuple[str, ...]
    deliverables: tuple[DeliverableSpec, ...]
    steps: tuple[MissionStep, ...]
    model_phases: tuple[ExecutionPhase, ...]
    max_repairs: int = 2
    quality_tier: QualityTier = QualityTier.STANDARD
    quality_contract: QualityAcceptanceContract | None = None
    schema: str = "ProofLaunchMultimodalMissionV2"

    def __post_init__(self) -> None:
        if not 0 <= self.max_repairs <= 2:
            raise MissionError("repair budget cannot exceed two")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise MissionError("mission step IDs must be unique")
        known: set[str] = set()
        for step in self.steps:
            missing = set(step.depends_on) - known
            if missing:
                raise MissionError(
                    f"step {step.id} has forward or unknown dependencies: "
                    f"{', '.join(sorted(missing))}"
                )
            known.add(step.id)
        if not self.steps or self.steps[-1].kind != "human_release":
            raise MissionError("mission must terminate at a human release boundary")
        if any(not phase.unload_after for phase in self.model_phases):
            raise MissionError("every heavy model must unload after its phase")
        if self.quality_contract is None:
            object.__setattr__(self, "quality_contract", contract_for(self.quality_tier))
        elif self.quality_contract.tier != self.quality_tier:
            raise MissionError("quality contract tier does not match the mission tier")

    def serializable(self) -> dict:
        payload = asdict(self)
        for item, spec in zip(payload["deliverables"], self.deliverables):
            item["kind"] = spec.kind.value
        payload["quality_tier"] = self.quality_tier.value
        assert self.quality_contract is not None
        payload["quality_contract"] = self.quality_contract.to_dict()
        return payload

    @property
    def graph_hash(self) -> str:
        canonical = json.dumps(
            self.serializable(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


class MultimodalMissionPlanner:
    """Creates a bounded task graph and a sequential Radeon model plan."""

    def __init__(self, router: RadeonModelRouter | None = None) -> None:
        self.router = router or RadeonModelRouter()

    @staticmethod
    def required_roles(
        artifacts: Iterable[MediaArtifact],
        deliverables: Iterable[DeliverableSpec],
        *,
        quality_tier: QualityTier = QualityTier.STANDARD,
    ) -> tuple[str, ...]:
        kinds = {artifact.kind for artifact in artifacts}
        outputs = {item.kind for item in deliverables}
        roles: list[str] = []
        if kinds & {MediaKind.IMAGE, MediaKind.VIDEO}:
            roles.append("vision_language_audit")
        if MediaKind.AUDIO in kinds or MediaKind.VIDEO in kinds:
            roles.append("audio_transcription")
        roles.append("affect_critic")
        if DeliverableKind.SOCIAL_IMAGE in outputs:
            roles.extend(("image_generation", "image_text_scoring"))
        if DeliverableKind.SHORT_VIDEO in outputs:
            roles.extend(("video_generation", "image_text_scoring"))
        if quality_tier == QualityTier.COMPETITION_2X:
            if kinds & {MediaKind.IMAGE, MediaKind.VIDEO}:
                roles.append("open_set_detection")
            if MediaKind.VIDEO in kinds or DeliverableKind.SHORT_VIDEO in outputs:
                roles.extend(("temporal_segmentation", "audio_text_scoring"))
        return tuple(dict.fromkeys(roles))

    def build(
        self,
        *,
        mission_id: str,
        artifacts: tuple[MediaArtifact, ...],
        deliverables: tuple[DeliverableSpec, ...],
        available_vram_gb: float,
        quality_tier: QualityTier | str = QualityTier.STANDARD,
    ) -> MissionPlan:
        if not deliverables:
            raise MissionError("at least one deliverable is required")
        try:
            selected_tier = QualityTier(quality_tier)
        except ValueError as error:
            raise MissionError(f"unknown quality tier: {quality_tier}") from error
        roles = self.required_roles(
            artifacts,
            deliverables,
            quality_tier=selected_tier,
        )
        phases = tuple(
            self.router.plan(
                available_vram_gb=available_vram_gb,
                required_roles=roles,
                include_candidates=selected_tier == QualityTier.COMPETITION_2X,
            )
        )
        steps = (
            MissionStep("S01", "ingest", ()),
            MissionStep("S02", "understand", ("S01",), roles[:2]),
            MissionStep(
                "S03",
                "ground_evidence",
                ("S02",),
                tuple(
                    role
                    for role in ("open_set_detection", "temporal_segmentation")
                    if role in roles
                ),
            ),
            MissionStep("S04", "plan_creative", ("S03",), ("affect_critic",)),
            MissionStep(
                "S05",
                "create_deliverables",
                ("S04",),
                tuple(
                    role
                    for role in ("image_generation", "video_generation")
                    if role in roles
                ),
            ),
            MissionStep(
                "S06",
                "cross_media_audit",
                ("S05",),
                tuple(
                    role
                    for role in (
                        "image_text_scoring",
                        "vision_language_audit",
                        "audio_text_scoring",
                    )
                    if role in roles
                ),
            ),
            MissionStep("S07", "bounded_repair", ("S06",), max_attempts=2),
            MissionStep(
                "S08",
                "human_release",
                ("S07",),
                human_approval_required=True,
            ),
        )
        return MissionPlan(
            mission_id=mission_id,
            input_ids=tuple(item.id for item in artifacts),
            deliverables=deliverables,
            steps=steps,
            model_phases=phases,
            quality_tier=selected_tier,
            quality_contract=contract_for(selected_tier),
        )


@dataclass
class MissionCheckpoint:
    mission_id: str
    graph_hash: str
    statuses: dict[str, StepStatus]
    attempts: dict[str, int]
    outputs: dict[str, dict] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    head_hash: str = "0" * 64
    schema: str = "ProofLaunchMissionCheckpointV1"

    def serializable(self) -> dict:
        payload = asdict(self)
        payload["statuses"] = {
            key: value.value for key, value in self.statuses.items()
        }
        return payload


class MissionCheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, checkpoint: MissionCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                checkpoint.serializable(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def load(self) -> MissionCheckpoint:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return MissionCheckpoint(
            mission_id=payload["mission_id"],
            graph_hash=payload["graph_hash"],
            statuses={
                key: StepStatus(value) for key, value in payload["statuses"].items()
            },
            attempts={key: int(value) for key, value in payload["attempts"].items()},
            outputs=payload.get("outputs", {}),
            trace=payload.get("trace", []),
            head_hash=payload.get("head_hash", "0" * 64),
            schema=payload.get("schema", "ProofLaunchMissionCheckpointV1"),
        )


StepHandler = Callable[[MissionStep, Mapping[str, dict]], dict]


class DurableMissionExecutor:
    """Resumable, fail-closed executor. It never auto-approves the release step."""

    def __init__(self, store: MissionCheckpointStore) -> None:
        self.store = store

    @staticmethod
    def _append_trace(
        checkpoint: MissionCheckpoint, step: MissionStep, status: StepStatus
    ) -> None:
        event = {
            "index": len(checkpoint.trace) + 1,
            "step_id": step.id,
            "status": status.value,
            "previous_hash": checkpoint.head_hash,
        }
        event_hash = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        event["event_hash"] = event_hash
        checkpoint.trace.append(event)
        checkpoint.head_hash = event_hash

    def _new_checkpoint(self, plan: MissionPlan) -> MissionCheckpoint:
        return MissionCheckpoint(
            mission_id=plan.mission_id,
            graph_hash=plan.graph_hash,
            statuses={step.id: StepStatus.PENDING for step in plan.steps},
            attempts={step.id: 0 for step in plan.steps},
        )

    def run(
        self,
        plan: MissionPlan,
        handlers: Mapping[str, StepHandler],
        *,
        human_approved: bool = False,
    ) -> MissionCheckpoint:
        checkpoint = (
            self.store.load() if self.store.path.exists() else self._new_checkpoint(plan)
        )
        if (
            checkpoint.mission_id != plan.mission_id
            or checkpoint.graph_hash != plan.graph_hash
        ):
            raise MissionError("checkpoint does not match the immutable mission graph")
        for step in plan.steps:
            if checkpoint.statuses[step.id] == StepStatus.SUCCEEDED:
                continue
            if any(
                checkpoint.statuses[dependency] != StepStatus.SUCCEEDED
                for dependency in step.depends_on
            ):
                checkpoint.statuses[step.id] = StepStatus.BLOCKED
                self._append_trace(checkpoint, step, StepStatus.BLOCKED)
                self.store.save(checkpoint)
                break
            if step.human_approval_required and not human_approved:
                checkpoint.statuses[step.id] = StepStatus.BLOCKED
                checkpoint.outputs[step.id] = {"reason": "human approval required"}
                self._append_trace(checkpoint, step, StepStatus.BLOCKED)
                self.store.save(checkpoint)
                break
            handler = handlers.get(step.kind)
            if handler is None:
                checkpoint.statuses[step.id] = StepStatus.BLOCKED
                checkpoint.outputs[step.id] = {"reason": "missing step handler"}
                self._append_trace(checkpoint, step, StepStatus.BLOCKED)
                self.store.save(checkpoint)
                break
            if checkpoint.attempts[step.id] >= step.max_attempts:
                checkpoint.statuses[step.id] = StepStatus.BLOCKED
                checkpoint.outputs[step.id] = {"reason": "attempt budget exhausted"}
                self._append_trace(checkpoint, step, StepStatus.BLOCKED)
                self.store.save(checkpoint)
                break
            checkpoint.attempts[step.id] += 1
            checkpoint.statuses[step.id] = StepStatus.RUNNING
            self._append_trace(checkpoint, step, StepStatus.RUNNING)
            self.store.save(checkpoint)
            try:
                result = handler(step, checkpoint.outputs)
            except Exception as error:
                checkpoint.statuses[step.id] = StepStatus.FAILED
                checkpoint.outputs[step.id] = {
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                self._append_trace(checkpoint, step, StepStatus.FAILED)
                self.store.save(checkpoint)
                break
            checkpoint.outputs[step.id] = dict(result)
            checkpoint.statuses[step.id] = StepStatus.SUCCEEDED
            self._append_trace(checkpoint, step, StepStatus.SUCCEEDED)
            self.store.save(checkpoint)
        return checkpoint
