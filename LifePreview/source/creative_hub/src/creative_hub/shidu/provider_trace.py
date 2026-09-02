"""Bounded, digest-only audit traces for structured model calls."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol


_TRACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_IN_MEMORY_TRACES = 1_024
_MAX_LOG_TRACE_BYTES = 1_024


def _canonical_json_digest(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("structured provider digest input must be a mapping")
    encoded = json.dumps(
        dict(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def structured_provider_request_digest(
    *,
    system_prompt: str,
    input_payload: Mapping[str, Any],
    response_schema: Mapping[str, Any],
) -> str:
    """Digest the complete canonical structured-model request."""

    if not isinstance(system_prompt, str):
        raise TypeError("structured provider system prompt must be text")
    return _canonical_json_digest(
        {
            "input_payload": dict(input_payload),
            "response_schema": dict(response_schema),
            "system_prompt": system_prompt,
        }
    )


def structured_provider_response_digest(response: Mapping[str, Any]) -> str:
    """Digest a decoded structured-model response without retaining its content."""

    return _canonical_json_digest(response)


@dataclass(frozen=True, slots=True)
class StructuredProviderTrace:
    """Immutable metadata for one successful structured-model completion."""

    requested_provider_id: str
    requested_model_id: str
    actual_provider_id: str
    actual_model_id: str
    request_digest: str
    response_digest: str
    fallback_reason: Literal["glm_http_429"] | None
    status: Literal["success"] = "success"

    def __post_init__(self) -> None:
        identifiers = (
            self.requested_provider_id,
            self.requested_model_id,
            self.actual_provider_id,
            self.actual_model_id,
        )
        if any(
            not isinstance(identifier, str)
            or _TRACE_ID.fullmatch(identifier) is None
            for identifier in identifiers
        ):
            raise ValueError("structured provider trace identifier is invalid")
        if (
            not isinstance(self.request_digest, str)
            or _SHA256.fullmatch(self.request_digest) is None
        ):
            raise ValueError("structured provider request digest is invalid")
        if (
            not isinstance(self.response_digest, str)
            or _SHA256.fullmatch(self.response_digest) is None
        ):
            raise ValueError("structured provider response digest is invalid")
        if self.status != "success":
            raise ValueError("structured provider trace status is invalid")
        if self.fallback_reason not in {None, "glm_http_429"}:
            raise ValueError("structured provider fallback reason is invalid")
        if self.fallback_reason is None:
            if (
                self.actual_provider_id != self.requested_provider_id
                or self.actual_model_id != self.requested_model_id
            ):
                raise ValueError("structured provider trace is missing fallback reason")
        elif (
            self.actual_provider_id == self.requested_provider_id
            and self.actual_model_id == self.requested_model_id
        ):
            raise ValueError("structured provider trace has a spurious fallback reason")


class StructuredProviderTraceSink(Protocol):
    def record(self, trace: StructuredProviderTrace) -> None: ...


@dataclass(frozen=True, slots=True)
class StructuredLoggingProviderTraceSink:
    """Emit a fixed, digest-only provider trace to the service log."""

    logger: logging.Logger

    def __post_init__(self) -> None:
        if not callable(getattr(self.logger, "info", None)):
            raise TypeError("structured provider trace logger is invalid")

    def record(self, trace: StructuredProviderTrace) -> None:
        if not isinstance(trace, StructuredProviderTrace):
            raise TypeError("structured provider trace is invalid")
        payload = {
            "actual_model_id": trace.actual_model_id,
            "actual_provider_id": trace.actual_provider_id,
            "event": "structured_provider_completion",
            "fallback_reason": trace.fallback_reason,
            "request_digest": trace.request_digest,
            "requested_model_id": trace.requested_model_id,
            "requested_provider_id": trace.requested_provider_id,
            "response_digest": trace.response_digest,
            "status": trace.status,
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(encoded.encode("ascii")) > _MAX_LOG_TRACE_BYTES:
            raise OverflowError("structured provider log trace is too large")
        self.logger.info("structured_provider_trace=%s", encoded)


class InMemoryStructuredProviderTraceSink:
    """A bounded test/diagnostic sink that exposes immutable snapshots."""

    __slots__ = ("_max_traces", "_traces")

    def __init__(self, *, max_traces: int = 128) -> None:
        if (
            type(max_traces) is not int
            or max_traces < 1
            or max_traces > _MAX_IN_MEMORY_TRACES
        ):
            raise ValueError("structured provider trace bound is invalid")
        self._max_traces = max_traces
        self._traces: list[StructuredProviderTrace] = []

    @property
    def traces(self) -> tuple[StructuredProviderTrace, ...]:
        return tuple(self._traces)

    def record(self, trace: StructuredProviderTrace) -> None:
        if not isinstance(trace, StructuredProviderTrace):
            raise TypeError("structured provider trace is invalid")
        if len(self._traces) >= self._max_traces:
            raise OverflowError("structured provider trace sink is full")
        self._traces.append(trace)


__all__ = [
    "InMemoryStructuredProviderTraceSink",
    "StructuredLoggingProviderTraceSink",
    "StructuredProviderTrace",
    "StructuredProviderTraceSink",
    "structured_provider_request_digest",
    "structured_provider_response_digest",
]
