"""Fail-closed JSON logging that accepts only explicitly safe context."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    AttemptId,
    DecisionId,
    Identifier,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError
from specstyle.observability.environment import JsonValue, _is_safe_observation_text

MAX_LOG_DEPTH = 6
MAX_LOG_NODES = 128
MAX_LOG_CONTAINER_ITEMS = 64
MAX_LOG_TEXT_CHARS = 512
MAX_LOG_KEY_CHARS = 64
_EVENT = re.compile(r"[A-Z][A-Z0-9_]{0,63}", re.ASCII)
_LOGGER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", re.ASCII)
_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_SENSITIVE = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "credential",
    "cookie",
    "session",
    "apikey",
    "accesskey",
    "privatekey",
    "clientsecret",
)
_EXACT_SENSITIVE = {
    "env",
    "environ",
    "environment",
    "environmentvariables",
    "hostname",
    "user",
    "username",
    "home",
    "homedir",
}
_REDACTED_UNSUPPORTED = "[REDACTED_UNSUPPORTED]"
_IDENTIFIER_TYPES = (
    Identifier,
    JobId,
    AssetId,
    AttemptId,
    ArtifactId,
    DecisionId,
    RuleId,
)
_IDENTIFIER_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)
_SHA_VALUE = re.compile(r"[0-9a-f]{64}", re.ASCII)


@dataclass(frozen=True, slots=True)
class LogEvent:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _EVENT.fullmatch(self.value) is None:
            raise DomainError("invalid log event")


@dataclass(frozen=True, slots=True)
class PublicLogText:
    value: str

    def __post_init__(self) -> None:
        if not _is_safe_observation_text(self.value):
            raise DomainError("public log text is unsafe") from None


LogScalar: TypeAlias = None | bool | int | float | Identifier | Sha256 | PublicLogText
LogValue: TypeAlias = (
    LogScalar | tuple["LogValue", ...] | list["LogValue"] | dict[str, "LogValue"]
)


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("_", "").replace("-", "").replace(".", "")
    return normalized in _EXACT_SENSITIVE or any(
        word in normalized for word in _SENSITIVE
    )


def sanitize_log_value(value: object, /) -> JsonValue:
    """Copy allowed values recursively without formatting or traversing others."""
    try:
        return _sanitize(value, 0, [0], set())
    except Exception:
        return _REDACTED_UNSUPPORTED


def _scalar(value: object) -> tuple[bool, JsonValue]:
    if value is None or type(value) is bool:
        return True, value  # type: ignore[return-value]
    if type(value) is int:
        return True, value if -(2**63) <= value <= 2**63 - 1 else _REDACTED_UNSUPPORTED
    if type(value) is float:
        return True, value if math.isfinite(value) else _REDACTED_UNSUPPORTED
    if type(value) in _IDENTIFIER_TYPES:
        return _validated_scalar(value, _IDENTIFIER_VALUE, _REDACTED_UNSUPPORTED)
    if type(value) is Sha256:
        return _validated_scalar(value, _SHA_VALUE, _REDACTED_UNSUPPORTED)
    if type(value) is PublicLogText:
        try:
            text = object.__getattribute__(value, "value")
            return True, text if _is_safe_observation_text(
                text
            ) else _REDACTED_UNSUPPORTED
        except Exception:
            return True, _REDACTED_UNSUPPORTED
    return False, _REDACTED_UNSUPPORTED


def _validated_scalar(
    value: object, pattern: re.Pattern[str], fallback: str
) -> tuple[bool, JsonValue]:
    try:
        text = object.__getattribute__(value, "value")
        return True, text if type(text) is str and pattern.fullmatch(text) else fallback
    except Exception:
        return True, fallback


def _sanitize(
    value: object, depth: int, nodes: list[int], active: set[int]
) -> JsonValue:
    nodes[0] += 1
    if nodes[0] > MAX_LOG_NODES:
        return "[REDACTED_NODES]"
    if depth > MAX_LOG_DEPTH:
        return "[REDACTED_DEPTH]"
    scalar, result = _scalar(value)
    if scalar:
        return result
    if type(value) not in {dict, list, tuple}:
        return _REDACTED_UNSUPPORTED
    object_id = id(value)
    if object_id in active:
        return "[REDACTED_CYCLE]"
    if len(value) > MAX_LOG_CONTAINER_ITEMS:
        return "[REDACTED_CONTAINER]"
    active.add(object_id)
    try:
        if type(value) is dict:
            if any(
                type(key) is not str or _KEY.fullmatch(key) is None for key in value
            ):
                return "[REDACTED_CONTAINER]"
            result: dict[str, JsonValue] = {}
            for key in sorted(value):
                if _sensitive_key(key):
                    result[key] = "[REDACTED_SENSITIVE]"
                else:
                    result[key] = _sanitize(value[key], depth + 1, nodes, active)
            return result
        return [_sanitize(item, depth + 1, nodes, active) for item in value]
    finally:
        active.remove(object_id)


def _validated_created(value: object) -> datetime | None:
    if type(value) is int:
        valid = value >= 0
    elif type(value) is float:
        valid = math.isfinite(value) and value >= 0
    else:
        return None
    if not valid:
        return None
    try:
        result = datetime.fromtimestamp(value, UTC)
        return result if 1 <= result.year <= 9999 else None
    except Exception:
        return None


def _valid_event(value: object) -> bool:
    if type(value) is not LogEvent:
        return False
    try:
        event = object.__getattribute__(value, "value")
        return type(event) is str and _EVENT.fullmatch(event) is not None
    except Exception:
        return False


def _valid_record(record: logging.LogRecord) -> bool:
    try:
        if (
            not _valid_event(record.msg)
            or type(record.args) is not tuple
            or record.args
        ):
            return False
        if (
            record.exc_info is not None
            or getattr(record, "exc_text", None) is not None
            or getattr(record, "stack_info", None) is not None
        ):
            return False
        if type(record.name) is not str or _LOGGER.fullmatch(record.name) is None:
            return False
        if type(record.levelname) is not str or record.levelname not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            return False
        if _validated_created(record.created) is None:
            return False
        context = getattr(record, "safe_context", {})
        return type(context) is dict and type(sanitize_log_value(context)) is dict
    except Exception:
        return False


class SafeJsonFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return _valid_record(record)
        except Exception:
            return False


def _fallback() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "timestamp": None,
            "level": "ERROR",
            "logger": "specstyle",
            "event": "LOG_RECORD_REDACTED",
            "context": {},
        },
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            if not _valid_record(record):
                return _fallback()
            created = _validated_created(record.created)
            if created is None:
                return _fallback()
            timestamp = created.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            )
            context = sanitize_log_value(getattr(record, "safe_context", {}))
            payload = {
                "schema_version": "1.0",
                "timestamp": timestamp,
                "level": record.levelname,
                "logger": record.name,
                "event": record.msg.value,
                "context": context,
            }
            return json.dumps(
                payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            )
        except Exception:
            return _fallback()
