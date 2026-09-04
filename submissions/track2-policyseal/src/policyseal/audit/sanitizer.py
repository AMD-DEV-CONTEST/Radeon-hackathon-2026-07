from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast

from policyseal.audit.models import (
    AuditEventType,
    AuditValue,
    SanitizedPayload,
)


class AuditPayloadError(ValueError):
    """An audit event would retain raw or unsupported data."""


_FIELDS_BY_EVENT: dict[AuditEventType, frozenset[str]] = {
    AuditEventType.TASK_CREATED: frozenset(
        {"task_id", "source_sha256", "file_kind", "classification", "requester_hmac"}
    ),
    AuditEventType.SOURCE_VIEWED: frozenset({"task_id", "revision_id"}),
    AuditEventType.CONTEXT_CHANGED: frozenset(
        {
            "context_sha256",
            "recipient",
            "purpose",
            "channel",
            "classification",
            "policy_version",
        }
    ),
    AuditEventType.REVISION_CREATED: frozenset(
        {"revision_id", "revision_number", "source_sha256", "context_sha256", "status"}
    ),
    AuditEventType.ANALYSIS_STARTED: frozenset({"revision_id", "region_count", "status"}),
    AuditEventType.ANALYSIS_COMPLETED: frozenset(
        {"revision_id", "region_count", "decision_count", "output_sha256", "status"}
    ),
    AuditEventType.ANALYSIS_FAILED: frozenset({"revision_id", "reason_code", "status"}),
    AuditEventType.DECISION: frozenset(
        {
            "region_id",
            "category",
            "action",
            "rule_ids",
            "evidence_ids",
            "reason_code",
            "value_hmac",
        }
    ),
    AuditEventType.APPROVAL_REQUESTED: frozenset(
        {"approval_id", "binding_sha256", "expires_at", "status"}
    ),
    AuditEventType.APPROVED: frozenset(
        {"approval_id", "binding_sha256", "reviewer_hmac", "status"}
    ),
    AuditEventType.REJECTED: frozenset(
        {"approval_id", "binding_sha256", "reviewer_hmac", "reason_code", "status"}
    ),
    AuditEventType.EXCEPTION_REQUESTED: frozenset(
        {"request_id", "revision_id", "reason_code", "status"}
    ),
    AuditEventType.EXPORTED: frozenset(
        {"export_kind", "output_sha256", "decision_count", "status"}
    ),
    AuditEventType.COPILOT_USED: frozenset(
        {"intent", "turn_count", "rule_ids", "evidence_ids"}
    ),
    AuditEventType.TASK_DELETED: frozenset(
        {"task_id", "revision_count", "source_sha256", "deletion_fingerprint", "status"}
    ),
}

_FORBIDDEN_KEY_PARTS = (
    "raw",
    "source_text",
    "prompt",
    "hidden",
    "reasoning",
    "credential",
    "password",
    "secret",
    "token",
    "bank",
)
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9_.:@/+\-]{1,200}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,200}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _event_type(value: AuditEventType | str) -> AuditEventType:
    try:
        return AuditEventType(value)
    except ValueError as error:
        raise AuditPayloadError("unknown audit event type") from error


def _sanitize_value(key: str, value: object) -> AuditValue:
    if key.endswith(("sha256", "_hmac", "_fingerprint")) or key == "binding_sha256":
        if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
            raise AuditPayloadError(f"{key} must be a lowercase SHA-256 or HMAC digest")
        return value
    if key.endswith("_count") or key in {"revision_number", "region_count", "turn_count"}:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AuditPayloadError(f"{key} must be a non-negative integer")
        return value
    if key in {"rule_ids", "evidence_ids"}:
        if not isinstance(value, (list, tuple)) or not value:
            raise AuditPayloadError(f"{key} must contain controlled IDs")
        items = tuple(value)
        if any(not isinstance(item, str) or _SAFE_ID.fullmatch(item) is None for item in items):
            raise AuditPayloadError(f"{key} contains an invalid ID")
        return cast(tuple[str, ...], items)
    if isinstance(value, bool):
        return value
    if not isinstance(value, str) or _SAFE_TEXT.fullmatch(value) is None:
        raise AuditPayloadError(f"{key} must contain a controlled value, ID, or digest")
    return value


def sanitize_payload(
    event_type: AuditEventType | str,
    payload: Mapping[str, object],
) -> tuple[AuditEventType, SanitizedPayload]:
    controlled_type = _event_type(event_type)
    allowed = _FIELDS_BY_EVENT[controlled_type]
    sanitized: list[tuple[str, AuditValue]] = []
    for key, value in sorted(payload.items()):
        normalized_key = key.lower()
        if any(part in normalized_key for part in _FORBIDDEN_KEY_PARTS):
            raise AuditPayloadError(f"audit payload field is forbidden: {key}")
        if key not in allowed:
            raise AuditPayloadError(f"audit payload field is not allowed for this event: {key}")
        sanitized.append((key, _sanitize_value(key, value)))
    return controlled_type, tuple(sanitized)
