from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, TypeAlias
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.event_persistence import EventPersistence, event_persistence


_PROTOCOL_CATALOG_PATH = Path(__file__).with_name("protocol_catalog.json")
_PROTOCOL_CATALOG = json.loads(_PROTOCOL_CATALOG_PATH.read_text(encoding="utf-8"))

FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION = str(_PROTOCOL_CATALOG["version"])
FRONTEND_MODES = tuple(str(item) for item in _PROTOCOL_CATALOG["modes"])
FRONTEND_COMMAND_TYPES = tuple(str(item) for item in _PROTOCOL_CATALOG["command_types"])
FRONTEND_EVENT_TYPES = tuple(str(item) for item in _PROTOCOL_CATALOG["event_types"])
FRONTEND_PROCESS_EVENT_TYPES = frozenset(str(item) for item in _PROTOCOL_CATALOG["process_event_types"])
_UNKNOWN_PROCESS_EVENT_TYPES = FRONTEND_PROCESS_EVENT_TYPES.difference(FRONTEND_EVENT_TYPES)
if _UNKNOWN_PROCESS_EVENT_TYPES:
    raise ValueError(f"unknown process event types in protocol catalog: {sorted(_UNKNOWN_PROCESS_EVENT_TYPES)}")

FactoryFrontendCommandType: TypeAlias = str
FactoryFrontendEventType: TypeAlias = str
FactoryMode: TypeAlias = str


class FactoryFrontendCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: FactoryFrontendCommandType
    request_id: str | None = None
    session_id: str | None = None
    resume_latest: bool = False
    mode: FactoryMode | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _known_command_type(cls, value: str) -> str:
        return _validate_catalog_value("command type", value, FRONTEND_COMMAND_TYPES)

    @field_validator("mode")
    @classmethod
    def _known_command_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_catalog_value("mode", value, FRONTEND_MODES)


class FactoryFrontendEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    protocol_version: str = FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION
    event_type: FactoryFrontendEventType
    persistence: EventPersistence = "durable"
    producer_type: str = "factory_runtime"
    request_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    thread_id: str | None = None
    mode: FactoryMode | None = None
    graph_id: str | None = None
    node_id: str | None = None
    node_label: str | None = None
    node_kind: str | None = None
    stage_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    sequence: int = 0
    timestamp: str
    severity: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    process_event: bool = False

    @model_validator(mode="after")
    def _derive_process_event(self) -> "FactoryFrontendEvent":
        self.persistence = event_persistence(self.event_type)
        self.process_event = self.persistence == "durable" and self.event_type in FRONTEND_PROCESS_EVENT_TYPES
        return self

    @field_validator("event_type")
    @classmethod
    def _known_event_type(cls, value: str) -> str:
        return _validate_catalog_value("event type", value, FRONTEND_EVENT_TYPES)

    @field_validator("protocol_version")
    @classmethod
    def _known_protocol_version(cls, value: str) -> str:
        if value != FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION:
            raise ValueError(
                f"unknown frontend protocol version: {value!r}; "
                f"expected {FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION!r}"
            )
        return value

    @field_validator("mode")
    @classmethod
    def _known_event_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_catalog_value("mode", value, FRONTEND_MODES)


def event(
    event_type: FactoryFrontendEventType,
    *,
    request_id: str | None = None,
    protocol_version: str | None = None,
    producer_type: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    mode: FactoryMode | None = None,
    node_id: str | None = None,
    node_label: str | None = None,
    node_kind: str | None = None,
    stage_id: str | None = None,
    run_id: str | None = None,
    graph_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sequence: int = 0,
    timestamp: str | None = None,
    severity: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> FactoryFrontendEvent:
    return FactoryFrontendEvent(
        event_id=uuid.uuid4().hex,
        protocol_version=protocol_version or FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION,
        event_type=event_type,
        producer_type=producer_type or "factory_runtime",
        request_id=request_id,
        run_id=run_id,
        session_id=session_id,
        thread_id=thread_id,
        mode=mode,
        graph_id=graph_id,
        node_id=node_id,
        node_label=node_label,
        node_kind=node_kind,
        stage_id=stage_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        sequence=sequence,
        timestamp=timestamp or datetime.now(UTC).isoformat(),
        severity=severity,
        message=message,
        payload=payload or {},
    )


def _validate_catalog_value(label: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        expected = ", ".join(allowed)
        raise ValueError(f"unknown frontend {label}: {value!r}; expected one of: {expected}")
    return value
