from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.paths import resolve_project_path
from agent_factory.runtime_attachments import normalized_runtime_attachments
from agent_factory.runtime_protocol.chat_parts import build_chat_turn_messages
from agent_factory.runtime_protocol.turn_lifecycle import (
    normalize_running_turn_sequence,
    stop_unidentified_running_turns,
    supersede_running_turns,
)
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphCheckpointerHandle,
    is_checkpointer_persistent,
)


FactorySessionMode = Literal["create_agent", "evolve_agent"]
FactoryCheckpointerBackend = Literal["sqlite", "memory"]
FactorySessionKind = Literal["normal", "collaboration_main"]
NORMAL_FACTORY_SESSION_KIND: FactorySessionKind = "normal"
COLLABORATION_MAIN_FACTORY_SESSION_KIND: FactorySessionKind = "collaboration_main"

DEFAULT_SESSION_ROOT = ".agentfactory/sessions"
DEFAULT_CHECKPOINT_PATH = ".agentfactory/checkpoints/factory.sqlite"
DEFAULT_CHECKPOINTER_BACKEND: FactoryCheckpointerBackend = "sqlite"


class FactorySessionTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    created_at: str
    updated_at: str
    request_id: str | None = None
    user_input: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_content: str | None = None
    final_answer: str | None = None
    tool_activities: list[dict[str, Any]] = Field(default_factory=list)
    message_metadata: dict[str, Any] = Field(default_factory=dict)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    status: str | None = None
    trace_ref: dict[str, str] | None = None


class FactorySessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    created_at: str
    updated_at: str
    first_user_input: str | None = None
    display_title: str | None = None
    session_kind: FactorySessionKind = NORMAL_FACTORY_SESSION_KIND
    collaboration_id: str | None = None
    visible_in_factory_session_list: bool = True
    current_mode: FactorySessionMode | None = None
    create_agent_session_id: str | None = None
    evolve_agent_package_id: str | None = None
    create_agent_turn_count: int = 0
    evolve_agent_turn_count: int = 0
    create_agent_turns: list[FactorySessionTurn] = Field(default_factory=list)
    evolve_agent_turns: list[FactorySessionTurn] = Field(default_factory=list)


@dataclass(slots=True)
class FactorySessionConfig:
    root: Path

    @classmethod
    def from_env(cls) -> "FactorySessionConfig":
        root = resolve_project_path(os.getenv("AGENTFACTORY_SESSION_ROOT", DEFAULT_SESSION_ROOT))
        return cls(root=root)


@dataclass(frozen=True, slots=True)
class FactoryCheckpointerConfig:
    backend: FactoryCheckpointerBackend
    path: Path

    @classmethod
    def from_env(cls) -> "FactoryCheckpointerConfig":
        raw_backend = os.getenv("AGENTFACTORY_CHECKPOINTER_BACKEND", DEFAULT_CHECKPOINTER_BACKEND).strip().lower()
        if raw_backend not in {"sqlite", "memory"}:
            raise ValueError(
                "AGENTFACTORY_CHECKPOINTER_BACKEND must be one of: sqlite, memory"
            )
        return cls(
            backend=raw_backend,
            path=checkpoint_path_from_env(),
        )


@dataclass(frozen=True, slots=True)
class FactoryCheckpointerHandle:
    saver: Any
    backend: FactoryCheckpointerBackend
    persistent: bool
    path: Path | None = None


class FactorySessionManager:
    def __init__(self, config: FactorySessionConfig | None = None) -> None:
        self.config = config or FactorySessionConfig.from_env()
        self.config.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "FactorySessionManager":
        return cls(FactorySessionConfig.from_env())

    def create(
        self,
        *,
        mode: FactorySessionMode | None = None,
        session_kind: FactorySessionKind = NORMAL_FACTORY_SESSION_KIND,
        collaboration_id: str | None = None,
        visible_in_factory_session_list: bool = True,
    ) -> FactorySessionRecord:
        now = _now()
        record = FactorySessionRecord(
            session_id=uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            session_kind=session_kind,
            collaboration_id=_normalized_optional_text(collaboration_id),
            visible_in_factory_session_list=visible_in_factory_session_list,
            current_mode=mode,
        )
        self.save(record)
        return record

    def load(self, session_id: str) -> FactorySessionRecord:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Factory session not found: {session_id}")
        return _normalized_record(_factory_session_record_from_json(path.read_text(encoding="utf-8")))

    def load_if_exists(self, session_id: str) -> FactorySessionRecord | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return _normalized_record(_factory_session_record_from_json(path.read_text(encoding="utf-8")))

    def save(self, record: FactorySessionRecord) -> None:
        record.updated_at = _now()
        self._path(record.session_id).write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def latest(
        self,
        *,
        mode: FactorySessionMode | None = None,
        include_internal: bool = False,
    ) -> FactorySessionRecord | None:
        records = self.list_sessions(include_internal=include_internal)
        if mode is not None:
            records = [record for record in records if _record_matches_mode(record, mode)]
        if not records:
            return None
        return records[0]

    def latest_evolution_for_package(self, package_id: str) -> FactorySessionRecord | None:
        normalized_package_id = package_id.strip()
        if not normalized_package_id:
            return None
        for record in self.list_sessions():
            if _record_evolution_package_id(record) == normalized_package_id:
                return record
        return None

    def latest_for_collaboration(
        self,
        collaboration_id: str,
        *,
        mode: FactorySessionMode | None = None,
    ) -> FactorySessionRecord | None:
        normalized_collaboration_id = _normalized_optional_text(collaboration_id)
        if not normalized_collaboration_id:
            return None
        for record in self.list_sessions(include_internal=True):
            if record.collaboration_id != normalized_collaboration_id:
                continue
            if mode is None or _record_matches_mode(record, mode):
                return record
        return None

    def list_sessions(self, *, include_internal: bool = False) -> list[FactorySessionRecord]:
        records: list[FactorySessionRecord] = []
        for path in self.config.root.glob("*.json"):
            try:
                record = _normalized_record(_factory_session_record_from_json(path.read_text(encoding="utf-8")))
                if include_internal or record.visible_in_factory_session_list:
                    records.append(record)
            except Exception:
                continue
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def delete(self, session_id: str) -> FactorySessionRecord:
        record = self.load(session_id)
        self._path(record.session_id).unlink(missing_ok=True)
        return record

    def set_mode(self, session_id: str, mode: FactorySessionMode | None) -> FactorySessionRecord:
        record = self.load(session_id)
        record.current_mode = mode
        self.save(record)
        return record

    def set_evolution_package(self, session_id: str, package_id: str) -> FactorySessionRecord:
        record = self.load(session_id)
        record.current_mode = "evolve_agent"
        record.evolve_agent_package_id = package_id.strip() or None
        self.save(record)
        return record

    def update_presentation_context(
        self,
        session_id: str,
        *,
        session_kind: FactorySessionKind,
        collaboration_id: str | None,
        visible_in_factory_session_list: bool,
    ) -> FactorySessionRecord:
        record = self.load(session_id)
        record.session_kind = session_kind
        record.collaboration_id = _normalized_optional_text(collaboration_id)
        record.visible_in_factory_session_list = visible_in_factory_session_list
        self.save(record)
        return record

    def remember_first_user_input(self, session_id: str, value: str) -> FactorySessionRecord:
        record = self.load(session_id)
        if not record.first_user_input:
            record.first_user_input = value.strip() or None
        if not record.display_title:
            record.display_title = _display_title(record.first_user_input)
        self.save(record)
        return record

    def thread_id(self, record: FactorySessionRecord, mode: FactorySessionMode) -> str:
        raise ValueError(f"{mode} mode is backed by a SystemPackage session")

    def messages(self, record: FactorySessionRecord, mode: FactorySessionMode) -> list[Any]:
        raise ValueError(f"{mode} mode messages are stored in the SystemPackage session")

    def replace_messages(
        self,
        session_id: str,
        mode: FactorySessionMode,
        messages: list[Any],
    ) -> FactorySessionRecord:
        record = self.load(session_id)
        if not record.first_user_input:
            record.first_user_input = _first_user_input(messages)
        if not record.display_title:
            record.display_title = _display_title(record.first_user_input)
        if mode == "create_agent":
            record.create_agent_turn_count = _human_message_count(messages)
        elif mode == "evolve_agent":
            record.evolve_agent_turn_count = _human_message_count(messages)
        self.save(record)
        return record

    def start_turn(
        self,
        session_id: str,
        mode: FactorySessionMode,
        *,
        request_id: str,
        user_input: str,
        attachments: Any = None,
    ) -> FactorySessionRecord:
        resolved_request_id = _required_request_id(request_id)
        record = self.load(session_id)
        _remember_record_title(record, user_input)
        record.current_mode = mode
        turns = _turns_for_mode(record, mode)
        turn = _find_turn(turns, request_id=resolved_request_id)
        now = _now()
        for superseded in supersede_running_turns(turns, updated_at=now, keep=turn):
            superseded.messages = _turn_messages(superseded)
        if turn is None:
            turn = FactorySessionTurn(
                index=len(turns) + 1,
                created_at=now,
                updated_at=now,
                request_id=resolved_request_id,
                user_input=user_input.strip() or None,
                attachments=normalized_runtime_attachments(attachments),
                status="running",
            )
            turn.messages = _turn_messages(turn)
            turns.append(turn)
        else:
            if not turn.user_input:
                turn.user_input = user_input.strip() or None
            if not turn.attachments:
                turn.attachments = normalized_runtime_attachments(attachments)
            turn.status = turn.status or "running"
            turn.updated_at = now
            turn.messages = _turn_messages(turn)
        _sync_turn_count(record, mode)
        self.save(record)
        return record

    def finish_turn(
        self,
        session_id: str,
        mode: FactorySessionMode,
        *,
        request_id: str,
        final_answer: str | None,
        status: str,
        reasoning_content: str | None = None,
        tool_activities: list[dict[str, Any]] | None = None,
        trace_ref: dict[str, str] | None = None,
    ) -> FactorySessionRecord:
        resolved_request_id = _required_request_id(request_id)
        record = self.load(session_id)
        turns = _turns_for_mode(record, mode)
        turn = _find_turn(turns, request_id=resolved_request_id)
        if turn is None:
            raise LookupError(
                f"Factory session turn not found: session={session_id}, mode={mode}, request={resolved_request_id}"
            )
        turn.final_answer = (final_answer or "").strip() or None
        turn.reasoning_content = (reasoning_content or "").strip() or None
        turn.status = status.strip() or None
        if tool_activities is not None:
            turn.tool_activities = list(tool_activities)
        if trace_ref is not None:
            turn.trace_ref = trace_ref or None
        turn.messages = _turn_messages(turn)
        turn.updated_at = _now()
        _sync_turn_count(record, mode)
        self.save(record)
        return record

    def _path(self, session_id: str) -> Path:
        return self.config.root / f"{session_id}.json"


def checkpoint_path_from_env() -> Path:
    return resolve_project_path(os.getenv("AGENTFACTORY_CHECKPOINT_PATH", DEFAULT_CHECKPOINT_PATH))


class FactoryCheckpointerFactory:
    def build(self, config: FactoryCheckpointerConfig | None = None) -> FactoryCheckpointerHandle:
        config = config or FactoryCheckpointerConfig.from_env()
        handle = LangGraphCheckpointerFactory().build(
            LangGraphCheckpointerConfig(backend=config.backend, path=config.path)
        )
        return FactoryCheckpointerHandle(
            saver=handle.saver,
            backend=handle.backend,
            persistent=handle.persistent,
            path=handle.path,
        )


def build_factory_checkpointer():
    return build_factory_checkpointer_handle().saver


def build_factory_checkpointer_handle() -> FactoryCheckpointerHandle:
    return FactoryCheckpointerFactory().build()


def is_factory_checkpointer_persistent(checkpointer: object | None) -> bool:
    return is_checkpointer_persistent(checkpointer)


def _human_message_count(messages: list[Any]) -> int:
    return sum(1 for message in messages if message.__class__.__name__ == "HumanMessage")


def _first_user_input(messages: list[Any]) -> str | None:
    for message in messages:
        if message.__class__.__name__ == "HumanMessage":
            content = message.content
            if isinstance(content, str):
                value = content.strip()
                if value:
                    return value
    return None


def _display_title(value: str | None, *, limit: int = 42) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_matches_mode(record: FactorySessionRecord, mode: FactorySessionMode) -> bool:
    if mode == "create_agent":
        return (
            record.current_mode == mode
            or record.create_agent_turn_count > 0
            or bool(record.create_agent_turns)
            or bool(record.create_agent_session_id)
        )
    return (
        record.current_mode == mode
        or record.evolve_agent_turn_count > 0
        or bool(record.evolve_agent_turns)
        or bool(record.evolve_agent_package_id)
    )


def without_mode_source(
    record: FactorySessionRecord,
    mode: FactorySessionMode | None,
) -> FactorySessionRecord:
    view = record.model_copy(deep=True)
    if mode in {None, "create_agent"}:
        view.create_agent_session_id = None
        view.create_agent_turn_count = 0
        view.create_agent_turns = []
    if mode in {None, "evolve_agent"}:
        view.evolve_agent_package_id = None
        view.evolve_agent_turn_count = 0
        view.evolve_agent_turns = []
    if mode is None or view.current_mode == mode:
        view.current_mode = fallback_current_mode(view)
    return view


def record_has_any_source(record: FactorySessionRecord) -> bool:
    return any(
        record_has_mode_source(record, mode)
        for mode in ("create_agent", "evolve_agent")
    )


def record_has_mode_source(record: FactorySessionRecord, mode: FactorySessionMode) -> bool:
    if mode == "create_agent":
        return (
            bool(str(record.create_agent_session_id or "").strip())
            or record.create_agent_turn_count > 0
            or bool(record.create_agent_turns)
        )
    return (
        bool(str(record.evolve_agent_package_id or "").strip())
        or record.evolve_agent_turn_count > 0
        or bool(record.evolve_agent_turns)
    )


def fallback_current_mode(record: FactorySessionRecord) -> FactorySessionMode | None:
    for mode in ("create_agent", "evolve_agent"):
        if record_has_mode_source(record, mode):
            return mode
    return None


def _record_evolution_package_id(record: FactorySessionRecord) -> str | None:
    value = (record.evolve_agent_package_id or "").strip()
    return value or None


def _turns_for_mode(record: FactorySessionRecord, mode: FactorySessionMode) -> list[FactorySessionTurn]:
    if mode == "create_agent":
        return record.create_agent_turns
    if mode == "evolve_agent":
        return record.evolve_agent_turns
    raise ValueError(f"{mode} mode does not have Factory session turns")


def _set_turns_for_mode(record: FactorySessionRecord, mode: FactorySessionMode, turns: list[FactorySessionTurn]) -> None:
    if mode == "create_agent":
        record.create_agent_turns = turns
        return
    if mode == "evolve_agent":
        record.evolve_agent_turns = turns
        return
    raise ValueError(f"{mode} mode does not have Factory session turns")


def _find_turn(turns: list[FactorySessionTurn], *, request_id: str | None) -> FactorySessionTurn | None:
    needle = (request_id or "").strip()
    if not needle:
        return None
    for turn in reversed(turns):
        if turn.request_id == needle:
            return turn
    return None


def _sync_turn_count(record: FactorySessionRecord, mode: FactorySessionMode) -> None:
    if mode == "create_agent":
        record.create_agent_turn_count = len(record.create_agent_turns)
    elif mode == "evolve_agent":
        record.evolve_agent_turn_count = len(record.evolve_agent_turns)


def _safe_turn_index(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalized_optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _remember_record_title(record: FactorySessionRecord, user_input: str | None) -> None:
    if not record.first_user_input:
        record.first_user_input = (user_input or "").strip() or None
    if not record.display_title:
        record.display_title = _display_title(record.first_user_input)


def _first_turn_input(turns: list[FactorySessionTurn]) -> str | None:
    for turn in turns:
        value = (turn.user_input or "").strip()
        if value:
            return value
    return None


def _turn_messages(turn: FactorySessionTurn) -> list[dict[str, Any]]:
    return build_chat_turn_messages(
        index=turn.index,
        created_at=turn.created_at,
        updated_at=turn.updated_at,
        user_input=turn.user_input,
        attachments=turn.attachments,
        reasoning_content=turn.reasoning_content,
        final_answer=turn.final_answer,
        tool_activities=turn.tool_activities,
        message_metadata=turn.message_metadata,
        status=turn.status,
    )


def _normalized_record(record: FactorySessionRecord) -> FactorySessionRecord:
    for mode in ("create_agent", "evolve_agent"):
        turns = _turns_for_mode(record, mode)
        for stopped in stop_unidentified_running_turns(turns, updated_at=_now()):
            stopped.messages = _turn_messages(stopped)
        for superseded in normalize_running_turn_sequence(turns, updated_at=_now()):
            superseded.messages = _turn_messages(superseded)
        for turn in turns:
            turn.messages = _turn_messages(turn)
    return record


def _required_request_id(value: str | None) -> str:
    request_id = str(value or "").strip()
    if not request_id:
        raise ValueError("Factory session turn requires request_id")
    return request_id


def _factory_session_record_from_json(value: str) -> FactorySessionRecord:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("Factory session payload must be an object")
    if payload.get("current_mode") == "chat":
        payload["current_mode"] = fallback_current_mode(
            FactorySessionRecord.model_validate(
                {
                    **payload,
                    "current_mode": None,
                }
            )
        )
    return FactorySessionRecord.model_validate(payload)


def _message_metadata_from_messages(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, list):
        return {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            return metadata
    return {}
