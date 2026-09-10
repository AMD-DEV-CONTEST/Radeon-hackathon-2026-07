"""Pure canonical encoding, decoding, and structural round-trips for JobStore."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass

from specstyle.domain.enums import ArtifactStatus, DecisionReason, RepairStopReason
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
from specstyle.workflow.job_models import (
    AttemptFinishedPayload,
    AttemptStartedPayload,
    CancelRequestedPayload,
    Event,
    EventType,
    ExportPublishedPayload,
    ExportStartedPayload,
    FatalPayload,
    Job,
    JobBudget,
    JobSnapshot,
    JobStartedPayload,
    JobStatus,
    RecoverablePayload,
    RepairStepPayload,
    SpecCompiledPayload,
    VerifierFinishedPayload,
)

SNAPSHOT_VERSION = "specstyle.workflow.snapshot.v1"


def _canonical(value: object) -> object:
    if type(value) is float:
        return 0.0 if value == 0.0 else value
    if type(value) is dict:
        return {key: _canonical(item) for key, item in value.items()}
    if type(value) is list:
        return [_canonical(item) for item in value]
    return value


def canonical_json(value: object) -> bytes:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if type(key) is not str or key in result:
            raise DomainError("invalid job snapshot")
        result[key] = value
    return result


def parse_canonical(data: bytes) -> object:
    if type(data) is not bytes:
        raise DomainError("invalid job snapshot")
    try:
        value = json.loads(
            data,
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                DomainError("invalid job snapshot")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as cause:
        raise DomainError("invalid job snapshot") from cause
    if canonical_json(value) != data:
        raise DomainError("invalid job snapshot")
    return value


def _parse_json(data: bytes) -> object:
    if type(data) is not bytes:
        raise DomainError("invalid job snapshot")
    try:
        return json.loads(
            data,
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                DomainError("invalid job snapshot")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as cause:
        raise DomainError("invalid job snapshot") from cause


def _exact_keys(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise DomainError("invalid job snapshot")
    return dict(value)


def _id_value(value: dict[str, object], key: str, kind: type[Identifier]) -> Identifier:
    raw = value[key]
    if type(raw) is not str:
        raise DomainError("invalid job snapshot")
    return kind(raw)


def _sha_value(value: dict[str, object], key: str) -> Sha256:
    raw = value[key]
    if type(raw) is not str:
        raise DomainError("invalid job snapshot")
    return Sha256(raw)


def _int_value(value: dict[str, object], key: str) -> int:
    raw = value[key]
    if type(raw) is not int:
        raise DomainError("invalid job snapshot")
    return raw


def _str_value(value: dict[str, object], key: str) -> str:
    raw = value[key]
    if type(raw) is not str:
        raise DomainError("invalid job snapshot")
    return raw


def _enum_value(value: dict[str, object], key: str, kind: type) -> object:
    raw = value[key]
    if type(raw) is not str:
        raise DomainError("invalid job snapshot")
    try:
        return kind(raw)
    except ValueError:
        raise DomainError("invalid job snapshot") from None


def _str_list(value: object, name: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise DomainError(f"invalid {name}")
    return value


def _job_to_primitive(job: Job) -> dict[str, object]:
    return {
        "job_id": job.job_id.value,
        "compiled_spec_hash": job.compiled_spec_hash.value,
        "cohort_profiles": list(job.cohort_profiles),
        "budget": {"max_attempts_per_item": job.budget.max_attempts_per_item},
        "status": job.status.value,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _job_from_primitive(value: object) -> Job:
    data = _exact_keys(
        value,
        {
            "job_id",
            "compiled_spec_hash",
            "cohort_profiles",
            "budget",
            "status",
            "created_at",
            "updated_at",
        },
    )
    budget = _exact_keys(data["budget"], {"max_attempts_per_item"})
    return Job(
        _id_value(data, "job_id", JobId),
        _sha_value(data, "compiled_spec_hash"),
        tuple(_str_list(data["cohort_profiles"], "cohort profiles")),
        JobBudget(_int_value(budget, "max_attempts_per_item")),
        JobStatus(_str_value(data, "status")),
        _str_value(data, "created_at"),
        _str_value(data, "updated_at"),
    )


_PAYLOAD_KEYS = {
    EventType.JOB_STARTED: {"compiled_spec_hash", "cohort_profiles", "budget"},
    EventType.SPEC_COMPILED: {"compiled_spec_hash"},
    EventType.ATTEMPT_STARTED: {
        "cohort_index",
        "item_index",
        "attempt_id",
        "parent_attempt_id",
    },
    EventType.ATTEMPT_FINISHED: {
        "cohort_index",
        "item_index",
        "attempt_id",
        "artifact_id",
        "request_hash",
    },
    EventType.VERIFIER_FINISHED: {
        "cohort_index",
        "item_index",
        "artifact_id",
        "artifact_status",
        "decision_reason",
        "repair_stop_reason",
    },
    EventType.REPAIR_STEP: {
        "cohort_index",
        "item_index",
        "decision_id",
        "action_id",
        "trigger_rule_id",
        "parent_attempt_id",
        "child_attempt_id",
    },
    EventType.EXPORT_PUBLISHED: {
        "bundle_name",
        "manifest_sha256",
        "payload_sha256",
        "bundle_sha256",
    },
    EventType.EXPORT_STARTED: {"bundle_name"},
    EventType.RECOVERABLE: {"reason"},
    EventType.CANCEL_REQUESTED: {"reason"},
    EventType.FATAL: {"error_family", "reason"},
}


def _job_started(data: dict[str, object]) -> JobStartedPayload:
    budget = _exact_keys(data["budget"], {"max_attempts_per_item"})
    return JobStartedPayload(
        _sha_value(data, "compiled_spec_hash"),
        tuple(_str_list(data["cohort_profiles"], "cohort profiles")),
        JobBudget(_int_value(budget, "max_attempts_per_item")),
    )


def _attempt_started(data: dict[str, object]) -> AttemptStartedPayload:
    parent = data["parent_attempt_id"]
    return AttemptStartedPayload(
        _int_value(data, "cohort_index"),
        _int_value(data, "item_index"),
        _id_value(data, "attempt_id", AttemptId),
        _id_value(data, "parent_attempt_id", AttemptId) if parent is not None else None,
    )


def _verifier_finished(data: dict[str, object]) -> VerifierFinishedPayload:
    stop = data["repair_stop_reason"]
    return VerifierFinishedPayload(
        _int_value(data, "cohort_index"),
        _int_value(data, "item_index"),
        _id_value(data, "artifact_id", ArtifactId),
        _enum_value(data, "artifact_status", ArtifactStatus),
        _enum_value(data, "decision_reason", DecisionReason),
        None
        if stop is None
        else _enum_value(data, "repair_stop_reason", RepairStopReason),
    )


_PAYLOAD_BUILDERS = {
    EventType.JOB_STARTED: _job_started,
    EventType.SPEC_COMPILED: lambda data: SpecCompiledPayload(
        _sha_value(data, "compiled_spec_hash")
    ),
    EventType.ATTEMPT_STARTED: _attempt_started,
    EventType.ATTEMPT_FINISHED: lambda data: AttemptFinishedPayload(
        _int_value(data, "cohort_index"),
        _int_value(data, "item_index"),
        _id_value(data, "attempt_id", AttemptId),
        _id_value(data, "artifact_id", ArtifactId),
        _sha_value(data, "request_hash"),
    ),
    EventType.VERIFIER_FINISHED: _verifier_finished,
    EventType.REPAIR_STEP: lambda data: RepairStepPayload(
        _int_value(data, "cohort_index"),
        _int_value(data, "item_index"),
        _id_value(data, "decision_id", DecisionId),
        _id_value(data, "action_id", Identifier),
        _id_value(data, "trigger_rule_id", RuleId),
        _id_value(data, "parent_attempt_id", AttemptId),
        _id_value(data, "child_attempt_id", AttemptId),
    ),
    EventType.EXPORT_PUBLISHED: lambda data: ExportPublishedPayload(
        _str_value(data, "bundle_name"),
        _sha_value(data, "manifest_sha256"),
        _sha_value(data, "payload_sha256"),
        _sha_value(data, "bundle_sha256"),
    ),
    EventType.EXPORT_STARTED: lambda data: ExportStartedPayload(
        _str_value(data, "bundle_name")
    ),
    EventType.RECOVERABLE: lambda data: RecoverablePayload(_str_value(data, "reason")),
    EventType.CANCEL_REQUESTED: lambda data: CancelRequestedPayload(
        _str_value(data, "reason")
    ),
    EventType.FATAL: lambda data: FatalPayload(
        _str_value(data, "error_family"), _str_value(data, "reason")
    ),
}


def _payload_to_primitive(event_type: EventType, payload: object) -> dict[str, object]:
    import enum

    result: dict[str, object] = {}
    for key in _PAYLOAD_KEYS[event_type]:
        value = getattr(payload, key)
        if isinstance(value, (Identifier, Sha256)):
            result[key] = value.value
        elif isinstance(value, enum.Enum):
            result[key] = value.value
        elif isinstance(value, JobBudget):
            result[key] = {"max_attempts_per_item": value.max_attempts_per_item}
        elif type(value) is tuple:
            result[key] = list(value)
        else:
            result[key] = value
    return result


def event_to_primitive(event: Event) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "job_id": event.job_id.value,
        "event_type": event.event_type.value,
        "from_state": event.from_state.value,
        "to_state": event.to_state.value,
        "timestamp": event.timestamp,
        "payload": _payload_to_primitive(event.event_type, event.payload),
    }


def event_from_primitive(value: object) -> Event:
    data = _exact_keys(
        value,
        {
            "sequence",
            "job_id",
            "event_type",
            "from_state",
            "to_state",
            "timestamp",
            "payload",
        },
    )
    event_type = _enum_value(data, "event_type", EventType)
    payload_data = _exact_keys(data["payload"], _PAYLOAD_KEYS[event_type])
    return Event(
        _int_value(data, "sequence"),
        JobId(_str_value(data, "job_id")),
        event_type,
        _enum_value(data, "from_state", JobStatus),
        _enum_value(data, "to_state", JobStatus),
        _str_value(data, "timestamp"),
        _PAYLOAD_BUILDERS[event_type](payload_data),
    )


def snapshot_to_primitive(snapshot: JobSnapshot) -> dict[str, object]:
    return {
        "schema_version": SNAPSHOT_VERSION,
        "job": _job_to_primitive(snapshot.job),
        "last_sequence": snapshot.last_sequence,
        "attempt_ids": [item.value for item in snapshot.attempt_ids],
        "bundle_names": list(snapshot.bundle_names),
    }


def snapshot_from_primitive(value: object) -> JobSnapshot:
    data = _exact_keys(
        value,
        {"schema_version", "job", "last_sequence", "attempt_ids", "bundle_names"},
    )
    if data["schema_version"] != SNAPSHOT_VERSION:
        raise DomainError("invalid job snapshot")
    return JobSnapshot(
        SNAPSHOT_VERSION,
        _job_from_primitive(data["job"]),
        _int_value(data, "last_sequence"),
        tuple(
            AttemptId(item) for item in _str_list(data["attempt_ids"], "attempt ids")
        ),
        tuple(_str_list(data["bundle_names"], "bundle names")),
    )


def _same_structure(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if is_dataclass(left):
        return all(
            _same_structure(getattr(left, field.name), getattr(right, field.name))
            for field in fields(left)
        )
    if type(left) is tuple:
        return len(left) == len(right) and all(
            _same_structure(item, other) for item, other in zip(left, right)
        )
    return left == right


def rebuild_snapshot(value: object) -> JobSnapshot:
    if type(value) is not JobSnapshot:
        raise DomainError("invalid job snapshot") from None
    try:
        rebuilt = snapshot_from_primitive(snapshot_to_primitive(value))
    except Exception:
        raise DomainError("invalid job snapshot") from None
    if not _same_structure(value, rebuilt):
        raise DomainError("invalid job snapshot") from None
    return rebuilt


def rebuild_event(value: object) -> Event:
    if type(value) is not Event:
        raise DomainError("invalid job event") from None
    try:
        rebuilt = event_from_primitive(event_to_primitive(value))
    except Exception:
        raise DomainError("invalid job event") from None
    if not _same_structure(value, rebuilt):
        raise DomainError("invalid job event") from None
    return rebuilt


def encode_snapshot(snapshot: JobSnapshot) -> bytes:
    return canonical_json(snapshot_to_primitive(snapshot))


def decode_snapshot(data: bytes) -> JobSnapshot:
    return snapshot_from_primitive(_parse_json(data))


def encode_event(event: Event) -> bytes:
    return canonical_json(event_to_primitive(event)) + b"\n"


def decode_events(job_id: JobId, data: bytes) -> tuple[Event, ...]:
    if data and not data.endswith(b"\n"):
        raise DomainError("invalid job event")
    result: list[Event] = []
    for line in data.splitlines():
        if not line:
            raise DomainError("invalid job event")
        event = event_from_primitive(_parse_json(line))
        if event.job_id != job_id:
            raise DomainError("invalid job event")
        result.append(event)
    return tuple(result)
