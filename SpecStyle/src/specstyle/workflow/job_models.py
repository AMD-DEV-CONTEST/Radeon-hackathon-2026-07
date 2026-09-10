"""WF-001 job, event, and store value objects with defensive rebuilding.

The architect-frozen contract is derived from sections 5, 2, 4, and 8 and
depends only on domain and errors. IDs and ``Sha256`` are rebuilt with exact
types, tuples require ``type(value) is tuple``, and timestamps are RFC3339 UTC
strings with millisecond precision.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Literal

from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AttemptId,
    DecisionId,
    Identifier,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError

OutputProfile = Literal["xhs_grid", "talking_head_cover", "background_sequence"]
_OUTPUT_PROFILES = ("xhs_grid", "talking_head_cover", "background_sequence")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", re.ASCII)
_SAFE_TEXT_RE = re.compile(r"[^\x00-\x1f\x7f]+", re.ASCII)
FatalErrorFamily = Literal[
    "GENERATION_OOM",
    "GENERATION_FAILED",
    "VERIFIER_UNAVAILABLE",
    "VERIFIER_UNVERIFIABLE",
    "REPAIR_BUDGET_EXHAUSTED",
    "EXPORT_INVARIANT_VIOLATION",
    "EXPORT_HASH_MISMATCH",
    "ROCM_NOT_AVAILABLE",
    "SPEC_INVALID",
    "ASSET_UNLICENSED",
    "MODEL_UNLICENSED",
    "UNKNOWN",
]
_FATAL_FAMILIES = {
    "GENERATION_OOM",
    "GENERATION_FAILED",
    "VERIFIER_UNAVAILABLE",
    "VERIFIER_UNVERIFIABLE",
    "REPAIR_BUDGET_EXHAUSTED",
    "EXPORT_INVARIANT_VIOLATION",
    "EXPORT_HASH_MISMATCH",
    "ROCM_NOT_AVAILABLE",
    "SPEC_INVALID",
    "ASSET_UNLICENSED",
    "MODEL_UNLICENSED",
    "UNKNOWN",
}


class JobStatus(enum.StrEnum):
    CREATED = "CREATED"
    SPEC_VALIDATED = "SPEC_VALIDATED"
    SPEC_COMPILED = "SPEC_COMPILED"
    GENERATING = "GENERATING"
    VERIFYING = "VERIFYING"
    APPROVED = "APPROVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECTED = "REJECTED"
    REPAIR_SELECTING = "REPAIR_SELECTING"
    REPAIRING = "REPAIRING"
    EXPORTING = "EXPORTING"
    COMPLETED = "COMPLETED"
    RECOVERABLE_ERROR = "RECOVERABLE_ERROR"
    JOB_FAILED = "JOB_FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.JOB_FAILED,
        JobStatus.CANCELLED,
    }
)


class EventType(enum.StrEnum):
    JOB_STARTED = "JOB_STARTED"
    SPEC_COMPILED = "SPEC_COMPILED"
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    ATTEMPT_FINISHED = "ATTEMPT_FINISHED"
    VERIFIER_FINISHED = "VERIFIER_FINISHED"
    REPAIR_STEP = "REPAIR_STEP"
    EXPORT_STARTED = "EXPORT_STARTED"
    EXPORT_PUBLISHED = "EXPORT_PUBLISHED"
    RECOVERABLE = "RECOVERABLE"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    FATAL = "FATAL"


def _invalid(message: str) -> None:
    raise DomainError(message) from None


def _rebuild_id(value: object, kind: type[Identifier]) -> Identifier:
    if type(value) is not kind or type(value.value) is not str:
        _invalid("invalid job model")
    rebuilt = kind(str.__str__(value.value))
    if rebuilt.value != value.value:
        _invalid("invalid job model")
    return rebuilt


def _rebuild_sha(value: object) -> Sha256:
    if type(value) is not Sha256 or type(value.value) is not str:
        _invalid("invalid job model")
    rebuilt = Sha256(str.__str__(value.value))
    if rebuilt.value != value.value:
        _invalid("invalid job model")
    return rebuilt


def _exact_int(value: object, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        _invalid(f"invalid {name}")
    return value


def _profiles(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        _invalid("invalid cohort profiles")
    seen: set[str] = set()
    for item in value:
        if type(item) is not str or item not in _OUTPUT_PROFILES or item in seen:
            _invalid("invalid cohort profiles")
        seen.add(item)
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or _TS_RE.fullmatch(value) is None:
        _invalid("invalid timestamp")
    return value


def _safe_text(value: object, name: str, *, limit: int) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= limit
        or value != value.strip()
        or _SAFE_TEXT_RE.fullmatch(value) is None
    ):
        _invalid(f"invalid {name}")
    return value


def _bundle_name(value: object) -> str:
    if type(value) is not str or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value, re.ASCII
    ):
        _invalid("invalid bundle name")
    return value


@dataclass(frozen=True, slots=True)
class JobBudget:
    max_attempts_per_item: int

    def __post_init__(self) -> None:
        budget = _exact_int(self.max_attempts_per_item, "budget")
        if budget < 1:
            _invalid("invalid budget")
        object.__setattr__(self, "max_attempts_per_item", budget)


@dataclass(frozen=True, slots=True)
class Job:
    job_id: JobId
    compiled_spec_hash: Sha256
    cohort_profiles: tuple[str, ...]
    budget: JobBudget
    status: JobStatus
    created_at: str
    updated_at: str
    terminal: bool = field(init=False)

    def __post_init__(self) -> None:
        if type(self.status) is not JobStatus:
            _invalid("invalid job status")
        if type(self.budget) is not JobBudget:
            _invalid("invalid job budget")
        if self.updated_at < self.created_at:
            _invalid("invalid job timestamps")
        object.__setattr__(self, "job_id", _rebuild_id(self.job_id, JobId))
        object.__setattr__(
            self, "compiled_spec_hash", _rebuild_sha(self.compiled_spec_hash)
        )
        object.__setattr__(self, "cohort_profiles", _profiles(self.cohort_profiles))
        object.__setattr__(self, "created_at", _timestamp(self.created_at))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at))
        object.__setattr__(self, "terminal", self.status in TERMINAL_STATUSES)


def _indices(payload: object, cohort: object, item: object) -> tuple[int, int]:
    return _exact_int(cohort, "cohort index"), _exact_int(item, "item index")


@dataclass(frozen=True, slots=True)
class JobStartedPayload:
    compiled_spec_hash: Sha256
    cohort_profiles: tuple[str, ...]
    budget: JobBudget

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "compiled_spec_hash", _rebuild_sha(self.compiled_spec_hash)
        )
        object.__setattr__(self, "cohort_profiles", _profiles(self.cohort_profiles))
        if type(self.budget) is not JobBudget:
            _invalid("invalid budget")


@dataclass(frozen=True, slots=True)
class AttemptStartedPayload:
    cohort_index: int
    item_index: int
    attempt_id: AttemptId
    parent_attempt_id: AttemptId | None

    def __post_init__(self) -> None:
        cohort, item = _indices(self, self.cohort_index, self.item_index)
        object.__setattr__(self, "cohort_index", cohort)
        object.__setattr__(self, "item_index", item)
        object.__setattr__(self, "attempt_id", _rebuild_id(self.attempt_id, AttemptId))
        if self.parent_attempt_id is not None:
            object.__setattr__(
                self,
                "parent_attempt_id",
                _rebuild_id(self.parent_attempt_id, AttemptId),
            )


@dataclass(frozen=True, slots=True)
class AttemptFinishedPayload:
    cohort_index: int
    item_index: int
    attempt_id: AttemptId
    artifact_id: ArtifactId
    request_hash: Sha256

    def __post_init__(self) -> None:
        cohort, item = _indices(self, self.cohort_index, self.item_index)
        object.__setattr__(self, "cohort_index", cohort)
        object.__setattr__(self, "item_index", item)
        object.__setattr__(self, "attempt_id", _rebuild_id(self.attempt_id, AttemptId))
        object.__setattr__(
            self, "artifact_id", _rebuild_id(self.artifact_id, ArtifactId)
        )
        object.__setattr__(self, "request_hash", _rebuild_sha(self.request_hash))


@dataclass(frozen=True, slots=True)
class VerifierFinishedPayload:
    cohort_index: int
    item_index: int
    artifact_id: ArtifactId
    artifact_status: ArtifactStatus
    decision_reason: DecisionReason
    repair_stop_reason: RepairStopReason | None

    def __post_init__(self) -> None:
        cohort, item = _indices(self, self.cohort_index, self.item_index)
        object.__setattr__(self, "cohort_index", cohort)
        object.__setattr__(self, "item_index", item)
        object.__setattr__(
            self, "artifact_id", _rebuild_id(self.artifact_id, ArtifactId)
        )
        if type(self.artifact_status) is not ArtifactStatus:
            _invalid("invalid artifact status")
        if type(self.decision_reason) is not DecisionReason:
            _invalid("invalid decision reason")
        if (
            self.repair_stop_reason is not None
            and type(self.repair_stop_reason) is not RepairStopReason
        ):
            _invalid("invalid repair stop reason")


@dataclass(frozen=True, slots=True)
class RepairStepPayload:
    cohort_index: int
    item_index: int
    decision_id: DecisionId
    action_id: Identifier
    trigger_rule_id: RuleId
    parent_attempt_id: AttemptId
    child_attempt_id: AttemptId

    def __post_init__(self) -> None:
        cohort, item = _indices(self, self.cohort_index, self.item_index)
        object.__setattr__(self, "cohort_index", cohort)
        object.__setattr__(self, "item_index", item)
        object.__setattr__(
            self, "decision_id", _rebuild_id(self.decision_id, DecisionId)
        )
        object.__setattr__(self, "action_id", _rebuild_id(self.action_id, Identifier))
        object.__setattr__(
            self, "trigger_rule_id", _rebuild_id(self.trigger_rule_id, RuleId)
        )
        object.__setattr__(
            self, "parent_attempt_id", _rebuild_id(self.parent_attempt_id, AttemptId)
        )
        object.__setattr__(
            self, "child_attempt_id", _rebuild_id(self.child_attempt_id, AttemptId)
        )


@dataclass(frozen=True, slots=True)
class ExportPublishedPayload:
    bundle_name: str
    manifest_sha256: Sha256
    payload_sha256: Sha256
    bundle_sha256: Sha256

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_name", _bundle_name(self.bundle_name))
        object.__setattr__(self, "manifest_sha256", _rebuild_sha(self.manifest_sha256))
        object.__setattr__(self, "payload_sha256", _rebuild_sha(self.payload_sha256))
        object.__setattr__(self, "bundle_sha256", _rebuild_sha(self.bundle_sha256))


@dataclass(frozen=True, slots=True)
class CancelRequestedPayload:
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason", _safe_text(self.reason, "cancel reason", limit=256)
        )


@dataclass(frozen=True, slots=True)
class SpecCompiledPayload:
    compiled_spec_hash: Sha256

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "compiled_spec_hash", _rebuild_sha(self.compiled_spec_hash)
        )


@dataclass(frozen=True, slots=True)
class ExportStartedPayload:
    bundle_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_name", _bundle_name(self.bundle_name))


@dataclass(frozen=True, slots=True)
class RecoverablePayload:
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason", _safe_text(self.reason, "recoverable reason", limit=256)
        )


@dataclass(frozen=True, slots=True)
class FatalPayload:
    error_family: str
    reason: str

    def __post_init__(self) -> None:
        if self.error_family not in _FATAL_FAMILIES:
            _invalid("invalid error family")
        object.__setattr__(
            self, "reason", _safe_text(self.reason, "fatal reason", limit=256)
        )


_PAYLOAD_BY_EVENT = {
    EventType.JOB_STARTED: JobStartedPayload,
    EventType.SPEC_COMPILED: SpecCompiledPayload,
    EventType.ATTEMPT_STARTED: AttemptStartedPayload,
    EventType.ATTEMPT_FINISHED: AttemptFinishedPayload,
    EventType.VERIFIER_FINISHED: VerifierFinishedPayload,
    EventType.REPAIR_STEP: RepairStepPayload,
    EventType.EXPORT_STARTED: ExportStartedPayload,
    EventType.EXPORT_PUBLISHED: ExportPublishedPayload,
    EventType.RECOVERABLE: RecoverablePayload,
    EventType.CANCEL_REQUESTED: CancelRequestedPayload,
    EventType.FATAL: FatalPayload,
}


@dataclass(frozen=True, slots=True)
class Event:
    sequence: int
    job_id: JobId
    event_type: EventType
    from_state: JobStatus
    to_state: JobStatus
    timestamp: str
    payload: object

    def __post_init__(self) -> None:
        sequence = _exact_int(self.sequence, "sequence")
        if sequence < 1:
            _invalid("invalid sequence")
        if type(self.event_type) is not EventType:
            _invalid("invalid event type")
        if (
            type(self.from_state) is not JobStatus
            or type(self.to_state) is not JobStatus
        ):
            _invalid("invalid job status")
        if self.from_state == self.to_state and self.event_type is not EventType.FATAL:
            _invalid("invalid job transition")
        expected = _PAYLOAD_BY_EVENT[self.event_type]
        if type(self.payload) is not expected:
            _invalid("invalid job event")
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "job_id", _rebuild_id(self.job_id, JobId))
        object.__setattr__(self, "timestamp", _timestamp(self.timestamp))


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    schema_version: Literal["specstyle.workflow.snapshot.v1"]
    job: Job
    last_sequence: int
    attempt_ids: tuple[AttemptId, ...]
    bundle_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != "specstyle.workflow.snapshot.v1"
            or type(self.job) is not Job
        ):
            _invalid("invalid job snapshot")
        last = _exact_int(self.last_sequence, "last sequence")
        if last < 0:
            _invalid("invalid last sequence")
        if type(self.attempt_ids) is not tuple or type(self.bundle_names) is not tuple:
            _invalid("invalid job snapshot")
        attempts = tuple(_rebuild_id(item, AttemptId) for item in self.attempt_ids)
        bundles = tuple(_bundle_name(item) for item in self.bundle_names)
        if len({item.value for item in attempts}) != len(attempts) or len(
            set(bundles)
        ) != len(bundles):
            _invalid("invalid job snapshot")
        object.__setattr__(self, "last_sequence", last)
        object.__setattr__(self, "attempt_ids", attempts)
        object.__setattr__(self, "bundle_names", bundles)


@dataclass(frozen=True, slots=True)
class JobState:
    job: Job
    last_sequence: int
    attempt_ids: tuple[AttemptId, ...]
    bundle_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.job) is not Job:
            _invalid("invalid job state")
        last = _exact_int(self.last_sequence, "last sequence")
        if last < 0:
            _invalid("invalid last sequence")
        if type(self.attempt_ids) is not tuple or type(self.bundle_names) is not tuple:
            _invalid("invalid job state")
        attempts = tuple(_rebuild_id(item, AttemptId) for item in self.attempt_ids)
        bundles = tuple(_bundle_name(item) for item in self.bundle_names)
        if len({item.value for item in attempts}) != len(attempts) or len(
            set(bundles)
        ) != len(bundles):
            _invalid("invalid job state")
        object.__setattr__(self, "last_sequence", last)
        object.__setattr__(self, "attempt_ids", attempts)
        object.__setattr__(self, "bundle_names", bundles)
