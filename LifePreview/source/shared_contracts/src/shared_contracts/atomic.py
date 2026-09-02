from __future__ import annotations

import hashlib
import hmac
import json
import unicodedata
from collections.abc import Iterator, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    AfterValidator,
    Field,
    JsonValue,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    PlainSerializer,
    field_validator,
    model_validator,
)

from .models import (
    CanonicalJson,
    EntityRef,
    Identifier,
    MimeType,
    ModelName,
    SafeText,
    Sha256Digest,
    StrictFrozenModel,
    canonical_json,
    stable_json_sha256,
)


IdempotencyKey = Annotated[str, Field(min_length=1, max_length=255)]
MaximumAttempts = Annotated[int, Field(ge=1, le=32)]
Entrypoint = Annotated[
    str,
    Field(
        min_length=3,
        max_length=500,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$",
    ),
]
StorageUri = Annotated[
    str,
    Field(
        min_length=12,
        max_length=2048,
        pattern=r"^artifact://[A-Za-z0-9][A-Za-z0-9._~/-]*$",
    ),
]


class ImmutableJsonObject(Mapping[str, JsonValue]):
    """Canonical snapshot-backed, deeply immutable JSON object."""

    __slots__ = ("_decoded", "_payload_json")

    def __init__(self, value: Mapping[str, JsonValue] | None = None) -> None:
        payload_json = canonical_json(dict(value or {}))
        if len(payload_json.encode("utf-8")) > 1_000_000:
            raise ValueError("immutable JSON object exceeds the 1 MB contract limit")
        decoded = json.loads(payload_json)
        if not isinstance(decoded, dict):
            raise ValueError("immutable JSON object must be a JSON object")
        nodes = 0
        stack: list[tuple[JsonValue, int]] = [(decoded, 1)]
        while stack:
            current, depth = stack.pop()
            nodes += 1
            if nodes > 100_000:
                raise ValueError("immutable JSON object exceeds the node limit")
            if depth > 64:
                raise ValueError("immutable JSON object exceeds the depth limit")
            if isinstance(current, dict):
                stack.extend((item, depth + 1) for item in current.values())
            elif isinstance(current, list):
                stack.extend((item, depth + 1) for item in current)
        object.__setattr__(self, "_payload_json", payload_json)
        object.__setattr__(self, "_decoded", _freeze_json(decoded))

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("immutable JSON snapshot cannot be changed")
        object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, JsonValue]:
        decoded = _thaw_json(self._decoded)
        if not isinstance(decoded, dict):
            raise AssertionError("immutable JSON object snapshot is not an object")
        return decoded

    def __getitem__(self, key: str) -> JsonValue:
        value = _thaw_json(self._decoded[key])
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(self._decoded)

    def __len__(self) -> int:
        return len(self._decoded)

    def __repr__(self) -> str:
        return f"ImmutableJsonObject({self._payload_json})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self.to_dict() == dict(other)
        return False

    __hash__ = None


def _freeze_json(value: JsonValue) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"immutable JSON snapshot contains {type(value).__name__}")


ImmutableJsonObjectField = Annotated[
    dict[str, JsonValue],
    AfterValidator(ImmutableJsonObject),
    PlainSerializer(
        lambda value: value.to_dict(),
        return_type=dict[str, JsonValue],
    ),
]


class SchemaRevision(StrictFrozenModel):
    """A revision of one immutable wire schema.

    Minor revisions may only add optional fields. A different major revision is
    incompatible unless an explicit upcaster is available.
    """

    major: PositiveInt = 1
    minor: NonNegativeInt = 0


IMPLEMENTATION_MANIFEST_SCHEMA_REVISION = SchemaRevision(major=1, minor=0)
ARTIFACT_REF_SCHEMA_REVISION = SchemaRevision(major=1, minor=0)
SAFE_ERROR_SCHEMA_REVISION = SchemaRevision(major=1, minor=0)
OPERATION_REQUEST_SCHEMA_REVISION = SchemaRevision(major=1, minor=0)
OPERATION_RESULT_SCHEMA_REVISION = SchemaRevision(major=1, minor=0)


def _require_current_schema(
    revision: SchemaRevision,
    *,
    current: SchemaRevision,
    label: str,
) -> None:
    if revision != current:
        raise ValueError(
            f"unsupported {label} schema revision "
            f"{revision.major}.{revision.minor}; "
            f"available: {current.major}.{current.minor}"
        )


class ResourceClass(StrEnum):
    CPU = "cpu"
    LOCAL_GPU = "local_gpu"
    CLOUD_IMAGE = "cloud_image"
    CLOUD_VIDEO = "cloud_video"
    LLM = "llm"


class DeterminismClass(StrEnum):
    DETERMINISTIC = "deterministic"
    SEEDED = "seeded"
    NONDETERMINISTIC = "nondeterministic"


class CacheMode(StrEnum):
    DISABLED = "disabled"
    INPUT_DIGEST = "input_digest"


class ReplayClass(StrEnum):
    REPLAYABLE = "replayable"
    IDENTIFIABLE_ONLY = "identifiable_only"
    NON_REPLAYABLE = "non_replayable"


class OperationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown"


class RetryClass(StrEnum):
    NEVER = "never"
    RETRY_ATTEMPT = "retry_attempt"
    RECONCILE_PROVIDER = "reconcile_provider"
    HUMAN_REQUIRED = "human_required"


class ProviderState(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    SUBMITTED = "submitted"
    OUTCOME_UNKNOWN = "outcome_unknown"
    OBSERVED_TERMINAL = "observed_terminal"
    NOT_APPLICABLE = "not_applicable"


class RetentionClass(StrEnum):
    EPHEMERAL = "ephemeral"
    WORKFLOW = "workflow"
    AUDIT = "audit"
    CANON = "canon"


class CachePolicy(StrictFrozenModel):
    mode: CacheMode = CacheMode.DISABLED
    ttl_seconds: PositiveInt | None = None

    @model_validator(mode="after")
    def ttl_requires_cache(self) -> CachePolicy:
        if self.mode is CacheMode.DISABLED and self.ttl_seconds is not None:
            raise ValueError("disabled cache policy cannot declare a TTL")
        return self


class TimeoutPolicy(StrictFrozenModel):
    execution_timeout_seconds: PositiveFloat
    heartbeat_timeout_seconds: PositiveFloat
    reconciliation_timeout_seconds: PositiveFloat | None = None

    @model_validator(mode="after")
    def heartbeat_must_precede_execution_timeout(self) -> TimeoutPolicy:
        if self.heartbeat_timeout_seconds >= self.execution_timeout_seconds:
            raise ValueError("heartbeat timeout must be shorter than execution timeout")
        return self


class InfrastructureRetryPolicy(StrictFrozenModel):
    maximum_attempts: MaximumAttempts = 1
    initial_backoff_seconds: NonNegativeFloat = 0
    maximum_backoff_seconds: NonNegativeFloat = 0

    @model_validator(mode="after")
    def backoff_is_ordered(self) -> InfrastructureRetryPolicy:
        if self.maximum_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("maximum backoff must not be less than initial backoff")
        return self


class ResourceRequirement(StrictFrozenModel):
    """Structured scheduling requirements for a GPU implementation."""

    device_type: Identifier
    minimum_vram_mb: PositiveInt
    target_vram_mb: PositiveInt
    model_digest: Sha256Digest
    workflow_digest: Sha256Digest
    custom_node_environment_digest: Sha256Digest
    estimated_duration_seconds: PositiveFloat
    warm_model_affinity: tuple[ModelName, ...] = Field(default=(), max_length=32)
    gpu_pin: Identifier | None = None

    @model_validator(mode="after")
    def target_vram_covers_minimum(self) -> ResourceRequirement:
        if self.target_vram_mb < self.minimum_vram_mb:
            raise ValueError("target VRAM must not be less than minimum VRAM")
        if len(self.warm_model_affinity) != len(set(self.warm_model_affinity)):
            raise ValueError("warm model affinity values must be unique")
        return self


class ImplementationManifest(StrictFrozenModel):
    """Content identity and replay promise for the implementation actually run."""

    manifest_schema_version: SchemaRevision = Field(default_factory=SchemaRevision)
    replay_class: ReplayClass
    code_image_digest: Sha256Digest
    adapter_digest: Sha256Digest
    comfy_workflow_digest: Sha256Digest | None = None
    custom_node_set_digest: Sha256Digest | None = None
    model_weight_digests: tuple[Sha256Digest, ...] = Field(default=(), max_length=128)
    prompt_digest: Sha256Digest | None = None
    rubric_digest: Sha256Digest | None = None
    upcaster_digest: Sha256Digest
    provider_identity: ModelName | None = None
    implementation_digest: Sha256Digest

    @field_validator("model_weight_digests")
    @classmethod
    def model_weight_digests_are_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("model weight digests must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def digest_matches_manifest(self) -> ImplementationManifest:
        _require_current_schema(
            self.manifest_schema_version,
            current=IMPLEMENTATION_MANIFEST_SCHEMA_REVISION,
            label="implementation manifest",
        )
        validate_canonical_digest(
            implementation_manifest_identity_payload(self),
            self.implementation_digest,
            label="implementation manifest",
        )
        if (
            self.replay_class is ReplayClass.IDENTIFIABLE_ONLY
            and self.provider_identity is None
        ):
            raise ValueError(
                "identifiable-only implementation must declare provider identity"
            )
        return self


class AtomicArtifactRef(StrictFrozenModel):
    """Storage-independent artifact identity used across operation boundaries."""

    ref_schema_version: SchemaRevision = Field(default_factory=SchemaRevision)
    artifact_id: UUID
    project_id: UUID
    content_digest: Sha256Digest
    mime_type: MimeType
    byte_size: PositiveInt
    logical_role: Identifier

    @model_validator(mode="after")
    def schema_revision_is_supported(self) -> AtomicArtifactRef:
        _require_current_schema(
            self.ref_schema_version,
            current=ARTIFACT_REF_SCHEMA_REVISION,
            label="artifact ref",
        )
        return self


class PersistentArtifactRef(AtomicArtifactRef):
    """Published immutable artifact metadata.

    Lineage is deliberately absent. ``ArtifactLineageEdge`` in PostgreSQL is
    the sole writable lineage authority.
    """

    storage_uri: StorageUri
    produced_by_operation_run_id: UUID
    produced_by_operation_attempt_id: UUID
    created_at: AwareDatetime
    retention_class: RetentionClass

    @field_validator("storage_uri")
    @classmethod
    def storage_uri_is_opaque(cls, value: str) -> str:
        locator = value.removeprefix("artifact://")
        if (
            "\\" in locator
            or "@" in locator
            or "?" in locator
            or "#" in locator
            or any(segment in {".", ".."} for segment in locator.split("/"))
        ):
            raise ValueError("storage URI must be an opaque artifact locator")
        return value

    @model_validator(mode="after")
    def producer_identities_are_distinct(self) -> PersistentArtifactRef:
        if (
            self.produced_by_operation_run_id
            == self.produced_by_operation_attempt_id
        ):
            raise ValueError("artifact producer run and attempt IDs must differ")
        return self


class SafeErrorV2(StrictFrozenModel):
    error_schema_version: SchemaRevision = Field(default_factory=SchemaRevision)
    error_code: Identifier
    retry_class: RetryClass
    public_message: SafeText
    operator_detail: str = Field(min_length=1, max_length=20_000)
    provider_state: ProviderState
    evidence_refs: tuple[AtomicArtifactRef, ...] = Field(default=(), max_length=256)
    correlation_id: UUID

    @model_validator(mode="after")
    def provider_recovery_is_safe(self) -> SafeErrorV2:
        _require_current_schema(
            self.error_schema_version,
            current=SAFE_ERROR_SCHEMA_REVISION,
            label="safe error",
        )
        unresolved_provider_states = {
            ProviderState.SUBMITTED,
            ProviderState.OUTCOME_UNKNOWN,
        }
        if (
            self.provider_state in unresolved_provider_states
            and self.retry_class
            not in {
                RetryClass.RECONCILE_PROVIDER,
                RetryClass.HUMAN_REQUIRED,
            }
        ):
            raise ValueError(
                "unresolved provider submission must reconcile or require human review"
            )
        if (
            self.retry_class is RetryClass.RECONCILE_PROVIDER
            and self.provider_state not in unresolved_provider_states
        ):
            raise ValueError(
                "provider reconciliation requires an unresolved provider submission"
            )
        return self


def implementation_manifest_identity_payload(
    manifest: ImplementationManifest,
) -> dict[str, JsonValue]:
    payload = manifest.model_dump(mode="json", exclude={"implementation_digest"})
    return payload


def build_implementation_digest(
    *,
    manifest_schema_version: SchemaRevision,
    replay_class: ReplayClass,
    code_image_digest: str,
    adapter_digest: str,
    upcaster_digest: str,
    comfy_workflow_digest: str | None = None,
    custom_node_set_digest: str | None = None,
    model_weight_digests: tuple[str, ...] = (),
    prompt_digest: str | None = None,
    rubric_digest: str | None = None,
    provider_identity: str | None = None,
) -> str:
    payload: dict[str, JsonValue] = {
        "manifest_schema_version": manifest_schema_version.model_dump(mode="json"),
        "replay_class": replay_class.value,
        "code_image_digest": code_image_digest,
        "adapter_digest": adapter_digest,
        "comfy_workflow_digest": comfy_workflow_digest,
        "custom_node_set_digest": custom_node_set_digest,
        "model_weight_digests": sorted(model_weight_digests),
        "prompt_digest": prompt_digest,
        "rubric_digest": rubric_digest,
        "upcaster_digest": upcaster_digest,
        "provider_identity": provider_identity,
    }
    return stable_json_sha256(payload)


def validate_canonical_digest(
    value: JsonValue,
    expected_digest: str,
    *,
    label: str = "payload",
) -> str:
    """Validate a SHA-256 digest over the canonical UTF-8 JSON spelling."""

    actual_digest = stable_json_sha256(value)
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise ValueError(
            f"{label} digest mismatch: expected {expected_digest}, got {actual_digest}"
        )
    return actual_digest


def validate_content_digest(content: bytes, expected_digest: str) -> str:
    actual_digest = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise ValueError(
            f"content digest mismatch: expected {expected_digest}, got {actual_digest}"
        )
    return actual_digest


def operation_input_identity_payload(
    *,
    project_id: UUID,
    op_type: str,
    op_version: SchemaRevision,
    input_schema_version: SchemaRevision,
    subject_ref: EntityRef,
    input_artifact_refs: tuple[AtomicArtifactRef, ...],
    structured_inputs: Mapping[str, JsonValue],
    parameter_snapshot: Mapping[str, JsonValue],
    policy_snapshot_id: UUID,
    policy_snapshot_digest: str,
) -> dict[str, JsonValue]:
    """Return the only fields that define a logical operation input.

    Command, run, attempt, trace, parent, and repair identities are
    intentionally excluded.
    """

    return {
        "project_id": str(project_id),
        "op_type": op_type,
        "op_version": op_version.model_dump(mode="json"),
        "input_schema_version": input_schema_version.model_dump(mode="json"),
        "subject_ref": subject_ref.model_dump(mode="json"),
        "input_artifact_refs": [
            {
                "content_digest": artifact.content_digest,
                "mime_type": artifact.mime_type,
                "byte_size": artifact.byte_size,
                "logical_role": artifact.logical_role,
            }
            for artifact in input_artifact_refs
        ],
        "structured_inputs": dict(structured_inputs),
        "parameter_snapshot": dict(parameter_snapshot),
        "policy_snapshot_id": str(policy_snapshot_id),
        "policy_snapshot_digest": policy_snapshot_digest,
    }


def build_operation_input_digest(
    *,
    project_id: UUID,
    op_type: str,
    op_version: SchemaRevision,
    input_schema_version: SchemaRevision,
    subject_ref: EntityRef,
    input_artifact_refs: tuple[AtomicArtifactRef, ...],
    structured_inputs: Mapping[str, JsonValue],
    parameter_snapshot: Mapping[str, JsonValue],
    policy_snapshot_id: UUID,
    policy_snapshot_digest: str,
) -> str:
    return stable_json_sha256(
        operation_input_identity_payload(
            project_id=project_id,
            op_type=op_type,
            op_version=op_version,
            input_schema_version=input_schema_version,
            subject_ref=subject_ref,
            input_artifact_refs=input_artifact_refs,
            structured_inputs=structured_inputs,
            parameter_snapshot=parameter_snapshot,
            policy_snapshot_id=policy_snapshot_id,
            policy_snapshot_digest=policy_snapshot_digest,
        )
    )


class OperationSpec(StrictFrozenModel):
    op_type: Identifier
    op_version: SchemaRevision
    input_schema_version: SchemaRevision
    output_schema_version: SchemaRevision
    resource_class: ResourceClass
    resource_requirement: ResourceRequirement | None = None
    determinism_class: DeterminismClass
    cache_policy: CachePolicy
    timeout_policy: TimeoutPolicy
    infrastructure_retry_policy: InfrastructureRetryPolicy
    supported_defect_codes: tuple[Identifier, ...] = Field(default=(), max_length=256)
    supported_repair_actions: tuple[Identifier, ...] = Field(default=(), max_length=256)
    implementation_entrypoint: Entrypoint
    spec_digest: Sha256Digest

    @field_validator("supported_defect_codes", "supported_repair_actions")
    @classmethod
    def unordered_capability_sets_are_canonical(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("operation capability set values must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def resource_requirement_matches_class(self) -> OperationSpec:
        if self.resource_class is ResourceClass.LOCAL_GPU:
            if self.resource_requirement is None:
                raise ValueError(
                    "local GPU operation must declare a resource requirement"
                )
        elif self.resource_requirement is not None:
            raise ValueError(
                "only local GPU operations may declare a GPU resource requirement"
            )
        validate_canonical_digest(
            operation_spec_identity_payload(self),
            self.spec_digest,
            label="operation spec",
        )
        return self


def operation_spec_identity_payload(
    spec: OperationSpec,
) -> dict[str, JsonValue]:
    """Return the complete immutable spec identity, excluding its own digest."""

    return spec.model_dump(mode="json", exclude={"spec_digest"})


def build_operation_spec_digest(
    *,
    op_type: str,
    op_version: SchemaRevision,
    input_schema_version: SchemaRevision,
    output_schema_version: SchemaRevision,
    resource_class: ResourceClass,
    determinism_class: DeterminismClass,
    cache_policy: CachePolicy,
    timeout_policy: TimeoutPolicy,
    infrastructure_retry_policy: InfrastructureRetryPolicy,
    implementation_entrypoint: str,
    resource_requirement: ResourceRequirement | None = None,
    supported_defect_codes: tuple[str, ...] = (),
    supported_repair_actions: tuple[str, ...] = (),
) -> str:
    payload: dict[str, JsonValue] = {
        "op_type": op_type,
        "op_version": op_version.model_dump(mode="json"),
        "input_schema_version": input_schema_version.model_dump(mode="json"),
        "output_schema_version": output_schema_version.model_dump(mode="json"),
        "resource_class": resource_class.value,
        "resource_requirement": (
            resource_requirement.model_dump(mode="json")
            if resource_requirement is not None
            else None
        ),
        "determinism_class": determinism_class.value,
        "cache_policy": cache_policy.model_dump(mode="json"),
        "timeout_policy": timeout_policy.model_dump(mode="json"),
        "infrastructure_retry_policy": infrastructure_retry_policy.model_dump(
            mode="json"
        ),
        "supported_defect_codes": sorted(supported_defect_codes),
        "supported_repair_actions": sorted(supported_repair_actions),
        "implementation_entrypoint": implementation_entrypoint,
    }
    return stable_json_sha256(payload)


class OperationRequest(StrictFrozenModel):
    request_schema_version: SchemaRevision = Field(default_factory=SchemaRevision)
    project_id: UUID
    workflow_run_id: UUID
    node_run_id: UUID
    operation_run_id: UUID
    operation_attempt_id: UUID
    op_type: Identifier
    op_version: SchemaRevision
    operation_spec_digest: Sha256Digest
    implementation_digest: Sha256Digest
    input_schema_version: SchemaRevision
    required_output_schema_version: SchemaRevision
    subject_ref: EntityRef
    input_artifact_refs: tuple[AtomicArtifactRef, ...] = Field(
        default=(),
        max_length=10_000,
    )
    structured_inputs: ImmutableJsonObjectField = Field(
        default_factory=ImmutableJsonObject
    )
    parameter_snapshot: ImmutableJsonObjectField = Field(
        default_factory=ImmutableJsonObject
    )
    policy_snapshot_id: UUID
    policy_snapshot_digest: Sha256Digest
    command_idempotency_key: IdempotencyKey
    operation_input_digest: Sha256Digest
    trace_id: UUID
    parent_operation_run_id: UUID | None = None
    repair_plan_id: UUID | None = None

    @field_validator("command_idempotency_key")
    @classmethod
    def idempotency_key_is_safe(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("command idempotency key cannot have surrounding whitespace")
        if any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("command idempotency key cannot contain control characters")
        return value

    @model_validator(mode="after")
    def validate_identity_and_scope(self) -> OperationRequest:
        _require_current_schema(
            self.request_schema_version,
            current=OPERATION_REQUEST_SCHEMA_REVISION,
            label="operation request",
        )
        run_identities = {
            self.workflow_run_id,
            self.node_run_id,
            self.operation_run_id,
            self.operation_attempt_id,
        }
        if len(run_identities) != 4:
            raise ValueError("workflow, node, operation run, and attempt IDs must differ")
        if self.parent_operation_run_id == self.operation_run_id:
            raise ValueError("operation run cannot be its own parent")
        identity_strings = {str(value) for value in run_identities}
        digest_identities = {
            self.operation_input_digest,
            self.operation_spec_digest,
            self.implementation_digest,
            self.policy_snapshot_digest,
        }
        if (
            self.command_idempotency_key in identity_strings
            or self.command_idempotency_key in digest_identities
        ):
            raise ValueError("command idempotency key cannot reuse another identity")
        if len(digest_identities) != 4:
            raise ValueError("input, spec, implementation, and policy digests must differ")
        validate_canonical_digest(
            operation_input_identity_payload(
                project_id=self.project_id,
                op_type=self.op_type,
                op_version=self.op_version,
                input_schema_version=self.input_schema_version,
                subject_ref=self.subject_ref,
                input_artifact_refs=self.input_artifact_refs,
                structured_inputs=self.structured_inputs,
                parameter_snapshot=self.parameter_snapshot,
                policy_snapshot_id=self.policy_snapshot_id,
                policy_snapshot_digest=self.policy_snapshot_digest,
            ),
            self.operation_input_digest,
            label="operation input",
        )
        mismatched_artifacts = [
            str(artifact.artifact_id)
            for artifact in self.input_artifact_refs
            if artifact.project_id != self.project_id
        ]
        if mismatched_artifacts:
            raise ValueError(
                "input artifacts must belong to request project: "
                + ", ".join(mismatched_artifacts)
            )
        return self


class OperationResult(StrictFrozenModel):
    result_schema_version: SchemaRevision = Field(default_factory=SchemaRevision)
    project_id: UUID
    operation_run_id: UUID
    operation_attempt_id: UUID
    op_type: Identifier
    op_version: SchemaRevision
    output_schema_version: SchemaRevision
    status: OperationStatus
    output_artifact_refs: tuple[PersistentArtifactRef, ...] = Field(
        default=(),
        max_length=10_000,
    )
    structured_output: ImmutableJsonObjectField = Field(
        default_factory=ImmutableJsonObject
    )
    metrics: ImmutableJsonObjectField = Field(default_factory=ImmutableJsonObject)
    evidence_refs: tuple[AtomicArtifactRef, ...] = Field(default=(), max_length=1_000)
    warnings: tuple[SafeText, ...] = Field(default=(), max_length=1_000)
    error: SafeErrorV2 | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime
    implementation_digest: Sha256Digest

    @model_validator(mode="after")
    def result_is_internally_consistent(self) -> OperationResult:
        _require_current_schema(
            self.result_schema_version,
            current=OPERATION_RESULT_SCHEMA_REVISION,
            label="operation result",
        )
        if self.operation_run_id == self.operation_attempt_id:
            raise ValueError("operation result run and attempt IDs must differ")
        if self.completed_at < self.started_at:
            raise ValueError("operation completion cannot precede start")
        if self.status is OperationStatus.SUCCEEDED and self.error is not None:
            raise ValueError("succeeded operation cannot contain an error")
        if self.status is not OperationStatus.SUCCEEDED and self.error is None:
            raise ValueError("non-succeeded operation must contain an error")
        if self.error is not None:
            if (
                self.status is OperationStatus.OUTCOME_UNKNOWN
                and self.error.provider_state
                not in {
                    ProviderState.SUBMITTED,
                    ProviderState.OUTCOME_UNKNOWN,
                }
            ):
                raise ValueError(
                    "unknown operation outcome requires unresolved provider state"
                )
            if (
                self.error.provider_state
                in {
                    ProviderState.SUBMITTED,
                    ProviderState.OUTCOME_UNKNOWN,
                }
                and self.status is not OperationStatus.OUTCOME_UNKNOWN
            ):
                raise ValueError(
                    "unresolved provider state requires unknown operation outcome"
                )
        error_evidence = self.error.evidence_refs if self.error is not None else ()
        for artifact in (
            *self.output_artifact_refs,
            *self.evidence_refs,
            *error_evidence,
        ):
            if artifact.project_id != self.project_id:
                raise ValueError("result artifacts must belong to result project")
        for artifact in self.output_artifact_refs:
            if artifact.produced_by_operation_run_id != self.operation_run_id:
                raise ValueError("output artifact operation run does not match result")
            if (
                artifact.produced_by_operation_attempt_id
                != self.operation_attempt_id
            ):
                raise ValueError("output artifact attempt does not match result")
        return self


def canonical_contract_json(model: StrictFrozenModel) -> CanonicalJson:
    return canonical_json(model.model_dump(mode="json"))
