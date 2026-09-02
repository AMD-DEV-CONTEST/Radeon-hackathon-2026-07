from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Protocol, runtime_checkable
from uuid import UUID

from shared_contracts import (
    AtomicArtifactRef,
    DeterminismClass,
    OperationRequest,
    OperationResult,
    OperationStatus,
    PersistentArtifactRef,
    RetentionClass,
    stable_json_sha256,
)


FACTORY_OPERATION_TYPES = (
    "two_shot.bootstrap",
    "two_shot.plan",
    "generation.bind",
    "assembly.plan",
    "episode.shot.plan",
    "book.split",
    "chapter.enrich",
    "bible.story.generate",
    "bible.character.generate",
    "bible.world.generate",
    "bible.style.generate",
    "asset.plan",
    "asset.character.generate",
    "asset.scene.generate",
    "asset.prop.generate",
    "storyboard.generate",
    "prompt.compile",
    "keyframe.generate",
    "video.generate",
    "speech.synthesize",
    "subtitle.generate",
    "audio.mix",
    "final.assemble",
)

VIDEO_GENERATION_MODES = frozenset({"t2v", "i2v", "first_last_frame"})

SEEDED_OPERATION_TYPES = frozenset(
    {
        "asset.character.generate",
        "asset.scene.generate",
        "asset.prop.generate",
        "keyframe.generate",
        "video.generate",
    }
)

NONDETERMINISTIC_OPERATION_TYPES = frozenset(
    {
        "chapter.enrich",
        "bible.story.generate",
        "bible.character.generate",
        "bible.world.generate",
        "asset.plan",
        "storyboard.generate",
        "speech.synthesize",
    }
)


class FactoryAtomicError(RuntimeError):
    """Base class for errors safe-mapped at the atomic capability boundary."""


class FactoryAtomicContractError(FactoryAtomicError):
    """The request or injected executor identity violates the factory contract."""


class FactoryCoreError(FactoryAtomicError):
    """A wrapped legacy/V3 core rejected a valid atomic operation."""


class FactoryProviderOutcomeUnknown(FactoryAtomicError):
    """A provider submission may exist and must be reconciled, not resubmitted."""


@dataclass(frozen=True, slots=True)
class FactoryProducedArtifact:
    """Path-free artifact payload returned by a wrapped Factory core."""

    payload: bytes
    mime_type: str
    logical_role: str
    retention_class: RetentionClass = RetentionClass.WORKFLOW

    def __post_init__(self) -> None:
        payload = bytes(self.payload)
        if not payload:
            raise FactoryAtomicContractError("produced artifact payload is empty")
        if not self.mime_type or not self.logical_role:
            raise FactoryAtomicContractError(
                "produced artifact requires MIME type and logical role"
            )
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class FactoryCoreOutput:
    """Result of one core call before publication by the artifact authority."""

    artifacts: tuple[FactoryProducedArtifact, ...]
    structured_output: Mapping[str, object] = field(default_factory=dict)
    metrics: Mapping[str, object] = field(default_factory=dict)
    seed: int | None = None
    provider_identity: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        artifacts = tuple(self.artifacts)
        if not all(isinstance(item, FactoryProducedArtifact) for item in artifacts):
            raise FactoryAtomicContractError(
                "core output contains an invalid produced artifact"
            )
        if not artifacts:
            raise FactoryAtomicContractError(
                "successful factory operations must produce an artifact"
            )
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "structured_output", dict(self.structured_output))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@runtime_checkable
class FactoryArtifactGateway(Protocol):
    """The only artifact dependency visible to Factory atomic wrappers."""

    def read_bytes(self, artifact: AtomicArtifactRef, /) -> bytes: ...

    def publish(
        self,
        artifact: FactoryProducedArtifact,
        /,
        *,
        request: OperationRequest,
        created_at: datetime,
    ) -> PersistentArtifactRef: ...


@runtime_checkable
class FactoryOperationRunner(Protocol):
    """Adapter over existing agents/V3 cores; it owns no orchestration state."""

    def run(
        self,
        request: OperationRequest,
        artifacts: FactoryArtifactGateway,
        /,
    ) -> FactoryCoreOutput: ...


@dataclass(frozen=True, slots=True)
class FactoryAtomicExecutorContext:
    """Explicitly injected dependencies and exact invocation identity.

    The context intentionally has no state store, scheduler, retry policy, or
    provider polling policy. Those remain owned by the control plane and the
    existing provider core respectively.
    """

    op_type: str
    project_id: UUID
    workflow_run_id: UUID
    operation_run_id: UUID
    operation_attempt_id: UUID
    operation_spec_digest: str
    implementation_digest: str
    runner: FactoryOperationRunner
    artifacts: FactoryArtifactGateway
    determinism_class: DeterminismClass
    provider_identity: str
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        if self.op_type not in FACTORY_OPERATION_TYPES:
            raise FactoryAtomicContractError(
                f"unsupported factory operation: {self.op_type}"
            )
        if not isinstance(self.runner, FactoryOperationRunner):
            raise FactoryAtomicContractError(
                "factory context runner does not implement FactoryOperationRunner"
            )
        if not isinstance(self.artifacts, FactoryArtifactGateway):
            raise FactoryAtomicContractError(
                "factory context artifacts does not implement FactoryArtifactGateway"
            )
        if not self.provider_identity.strip():
            raise FactoryAtomicContractError("provider identity must be pinned")


def _path_key(key: str) -> bool:
    normalized = key.strip().lower()
    return (
        normalized in {"path", "paths", "file", "files", "filename", "filenames"}
        or normalized.endswith("_path")
        or normalized.endswith("_paths")
        or normalized.endswith("_file")
        or normalized.endswith("_files")
        or normalized.endswith("_filename")
        or normalized.endswith("_filenames")
    )


_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_path(value: str) -> bool:
    return (
        bool(_WINDOWS_PATH.match(value))
        or value.startswith(("/", "\\\\", "file://"))
        or "\\" in value
        or any(segment == ".." for segment in value.split("/"))
    )


def _reject_path_fields(value: object, *, location: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            rendered_key = str(key)
            if _path_key(rendered_key):
                raise FactoryAtomicContractError(
                    f"{location} must use ArtifactRefs, not path field {rendered_key!r}"
                )
            _reject_path_fields(item, location=location)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_path_fields(item, location=location)
    elif isinstance(value, str) and _looks_like_path(value):
        raise FactoryAtomicContractError(
            f"{location} must use ArtifactRefs, not path-like string values"
        )


def _determinism_for(op_type: str) -> DeterminismClass:
    if op_type in SEEDED_OPERATION_TYPES:
        return DeterminismClass.SEEDED
    if op_type in NONDETERMINISTIC_OPERATION_TYPES:
        return DeterminismClass.NONDETERMINISTIC
    return DeterminismClass.DETERMINISTIC


class FactoryAtomicExecutor:
    __slots__ = ("_context",)

    def __init__(self, context: FactoryAtomicExecutorContext) -> None:
        self._context = context

    def _validate_request(self, request: OperationRequest) -> None:
        context = self._context
        mismatches = {
            "op_type": request.op_type != context.op_type,
            "project_id": request.project_id != context.project_id,
            "workflow_run_id": request.workflow_run_id != context.workflow_run_id,
            "operation_run_id": request.operation_run_id != context.operation_run_id,
            "operation_attempt_id": (
                request.operation_attempt_id != context.operation_attempt_id
            ),
            "operation_spec_digest": (
                request.operation_spec_digest != context.operation_spec_digest
            ),
            "implementation_digest": (
                request.implementation_digest != context.implementation_digest
            ),
        }
        failed = tuple(key for key, mismatch in mismatches.items() if mismatch)
        if failed:
            raise FactoryAtomicContractError(
                "factory invocation identity mismatch: " + ", ".join(failed)
            )
        expected_determinism = _determinism_for(request.op_type)
        if context.determinism_class is not expected_determinism:
            raise FactoryAtomicContractError(
                "executor determinism does not match the pinned operation"
            )
        _reject_path_fields(request.structured_inputs, location="structured inputs")
        _reject_path_fields(request.parameter_snapshot, location="parameter snapshot")
        if request.op_type == "video.generate":
            mode = request.structured_inputs.get("mode")
            if mode not in VIDEO_GENERATION_MODES:
                raise FactoryAtomicContractError(
                    "video.generate mode must be t2v, i2v, or first_last_frame"
                )
        if expected_determinism is DeterminismClass.SEEDED:
            seed = request.parameter_snapshot.get("seed")
            if (
                isinstance(seed, bool)
                or not isinstance(seed, int)
                or seed < 0
                or seed > 2**63 - 1
            ):
                raise FactoryAtomicContractError(
                    f"{request.op_type} requires a pinned integer seed"
                )

    @staticmethod
    def _validate_published(
        artifact: PersistentArtifactRef,
        *,
        produced: FactoryProducedArtifact,
        request: OperationRequest,
    ) -> None:
        if not isinstance(artifact, PersistentArtifactRef):
            raise FactoryAtomicContractError(
                "artifact gateway did not return PersistentArtifactRef"
            )
        if (
            artifact.project_id != request.project_id
            or artifact.produced_by_operation_run_id != request.operation_run_id
            or artifact.produced_by_operation_attempt_id
            != request.operation_attempt_id
            or artifact.mime_type != produced.mime_type
            or artifact.logical_role != produced.logical_role
            or artifact.byte_size != len(produced.payload)
        ):
            raise FactoryAtomicContractError(
                "published artifact identity does not match the operation output"
            )

    def execute(self, request: OperationRequest, /) -> OperationResult:
        self._validate_request(request)
        started_at = self._context.clock()
        core = self._context.runner.run(request, self._context.artifacts)
        if not isinstance(core, FactoryCoreOutput):
            raise FactoryAtomicContractError(
                "factory runner did not return FactoryCoreOutput"
            )
        expected_seed = request.parameter_snapshot.get("seed")
        if request.op_type in SEEDED_OPERATION_TYPES and core.seed != expected_seed:
            raise FactoryAtomicContractError(
                "core seed does not match the pinned request seed"
            )
        provider = core.provider_identity or self._context.provider_identity
        if provider != self._context.provider_identity:
            raise FactoryAtomicContractError(
                "core provider does not match the pinned executor provider"
            )
        _reject_path_fields(core.structured_output, location="structured output")

        published: list[PersistentArtifactRef] = []
        shidu_dialogue_ref: PersistentArtifactRef | None = None
        shidu_take_digest: str | None = None
        for produced in core.artifacts:
            published_artifact = produced
            is_shidu_speech = (
                request.op_type == "speech.synthesize"
                and request.structured_inputs.get("compiler_revision")
                == "shidu-episode-compiler.v2"
            )
            if is_shidu_speech and produced.logical_role.startswith(
                "tts_take."
            ):
                if shidu_dialogue_ref is None:
                    raise FactoryAtomicContractError(
                        "Shidu TTS take must follow its published WAV artifact"
                    )
                try:
                    take_payload = json.loads(produced.payload.decode("utf-8"))
                    audio = take_payload["audio_artifact"]
                    if (
                        audio["sha256"] != shidu_dialogue_ref.content_digest
                        or audio["byte_size"] != shidu_dialogue_ref.byte_size
                        or audio["mime"] != shidu_dialogue_ref.mime_type
                    ):
                        raise ValueError("audio authority mismatch")
                    audio["artifact_id"] = str(shidu_dialogue_ref.artifact_id)
                    raw_created_at = take_payload["created_at"]
                    if not isinstance(raw_created_at, str):
                        raise ValueError("take creation time is invalid")
                    created_at = datetime.fromisoformat(
                        raw_created_at.removesuffix("Z") + "+00:00"
                        if raw_created_at.endswith("Z")
                        else raw_created_at
                    )
                    if created_at.tzinfo is None or created_at.utcoffset() is None:
                        raise ValueError("take creation time is invalid")
                    take_payload["created_at"] = created_at.astimezone(
                        timezone.utc
                    ).isoformat()
                    take_identity = {
                        key: value
                        for key, value in take_payload.items()
                        if key != "take_digest"
                    }
                    shidu_take_digest = stable_json_sha256(take_identity)
                    take_payload["take_digest"] = shidu_take_digest
                    published_artifact = FactoryProducedArtifact(
                        payload=json.dumps(
                            take_payload,
                            ensure_ascii=False,
                            indent=2,
                        ).encode("utf-8"),
                        mime_type=produced.mime_type,
                        logical_role=produced.logical_role,
                        retention_class=produced.retention_class,
                    )
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ) as exc:
                    raise FactoryAtomicContractError(
                        "Shidu TTS take cannot bind the published WAV authority"
                    ) from exc
            ref = self._context.artifacts.publish(
                published_artifact,
                request=request,
                created_at=self._context.clock(),
            )
            self._validate_published(
                ref,
                produced=published_artifact,
                request=request,
            )
            published.append(ref)
            if is_shidu_speech and produced.logical_role.startswith(
                "dialogue."
            ):
                shidu_dialogue_ref = ref

        execution_manifest = {
            "operation_spec_digest": request.operation_spec_digest,
            "implementation_digest": request.implementation_digest,
            "determinism_class": self._context.determinism_class.value,
            "seed": core.seed,
            "provider_identity": provider,
        }
        structured_output = dict(core.structured_output)
        if shidu_take_digest is not None:
            structured_output["tts_take_digest"] = shidu_take_digest
            structured_output["audio_artifact_id"] = str(
                shidu_dialogue_ref.artifact_id  # type: ignore[union-attr]
            )
        structured_output["implementation_manifest"] = execution_manifest
        metrics = dict(core.metrics)
        if core.seed is not None:
            metrics.setdefault("seed", core.seed)
        metrics.setdefault("provider_identity", provider)
        completed_at = self._context.clock()
        return OperationResult(
            project_id=request.project_id,
            operation_run_id=request.operation_run_id,
            operation_attempt_id=request.operation_attempt_id,
            op_type=request.op_type,
            op_version=request.op_version,
            output_schema_version=request.required_output_schema_version,
            status=OperationStatus.SUCCEEDED,
            output_artifact_refs=tuple(published),
            structured_output=structured_output,
            metrics=metrics,
            warnings=core.warnings,
            started_at=started_at,
            completed_at=completed_at,
            implementation_digest=request.implementation_digest,
        )


def create_atomic_factory_executor(
    context: FactoryAtomicExecutorContext,
    /,
) -> FactoryAtomicExecutor:
    if not isinstance(context, FactoryAtomicExecutorContext):
        raise FactoryAtomicContractError(
            "factory executor requires FactoryAtomicExecutorContext"
        )
    return FactoryAtomicExecutor(context)


__all__ = [
    "FACTORY_OPERATION_TYPES",
    "NONDETERMINISTIC_OPERATION_TYPES",
    "SEEDED_OPERATION_TYPES",
    "VIDEO_GENERATION_MODES",
    "FactoryArtifactGateway",
    "FactoryAtomicContractError",
    "FactoryAtomicError",
    "FactoryAtomicExecutor",
    "FactoryAtomicExecutorContext",
    "FactoryCoreError",
    "FactoryCoreOutput",
    "FactoryOperationRunner",
    "FactoryProducedArtifact",
    "FactoryProviderOutcomeUnknown",
    "create_atomic_factory_executor",
]
