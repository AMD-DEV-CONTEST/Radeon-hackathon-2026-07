from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import (
    interrupt_accepts_message,
    message_resume_command,
    session_payload,
)
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    PendingAgentPackageRun,
)
from agent_factory.factory_graph.session import (
    record_has_any_source,
    record_has_mode_source,
    without_mode_source,
)
from agent_factory.runtime_attachments import has_attachment_payload


MESSAGE_MODES = {"create_agent", "evolve_agent"}
SESSION_MODES = {"create_agent", "evolve_agent"}


class RuntimeSessionCommandMixin:
    def start_session(self, command: FactoryFrontendCommand) -> None:
        requested_mode = _session_mode(command.mode)
        if command.mode is not None and requested_mode is None:
            self._emit_error(command, f"unsupported factory session mode: {command.mode}")
            return
        requested_evolution_package_id = _command_evolution_package_id(command, requested_mode)
        if command.session_id:
            previous_record = self.session_record
            previous_mode = self.mode
            self.session_record = self.session_manager.load(command.session_id)
            self.mode = requested_mode or self.session_record.current_mode
            if not self._session_source_available(self.session_record, self.mode):
                self.session_record = previous_record
                self.mode = previous_mode
                self._emit_missing_session_source(command, requested_mode or "factory")
                return
            if requested_mode is not None and requested_mode != self.session_record.current_mode:
                self.session_record = self.session_manager.set_mode(self.session_record.session_id, requested_mode)
            if requested_evolution_package_id:
                self.session_record = self.session_manager.set_evolution_package(
                    self.session_record.session_id,
                    requested_evolution_package_id,
                )
            session_event_type = "session_switched"
        elif command.resume_latest:
            existing = self._latest_session_for_start(
                requested_mode,
                requested_evolution_package_id,
            )
            if existing is None:
                self.session_record = None
                self.mode = requested_mode
                self._restore_session_mode_context()
                self._emit_empty_session_event(
                    command.request_id,
                    mode=requested_mode,
                    package_id=requested_evolution_package_id,
                )
                return
            self.session_record = existing
            self.mode = requested_mode or existing.current_mode
            if requested_evolution_package_id:
                self.session_record = self.session_manager.set_evolution_package(
                    self.session_record.session_id,
                    requested_evolution_package_id,
                )
            session_event_type = "session_switched"
        else:
            self.session_record = self.session_manager.create(mode=requested_mode)
            self.mode = requested_mode
            if requested_evolution_package_id:
                self.session_record = self.session_manager.set_evolution_package(
                    self.session_record.session_id,
                    requested_evolution_package_id,
                )
            session_event_type = "session_started"
        self._restore_session_mode_context()
        self._emit_session_event(command.request_id, session_event_type=session_event_type)

    def list_sessions(self, command: FactoryFrontendCommand) -> None:
        self.emit(
            event(
                "sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"sessions": self._session_payloads_for_client()},
            )
        )

    def switch_session(self, command: FactoryFrontendCommand) -> None:
        if not command.session_id:
            self._emit_error(command, "switch_session requires session_id")
            return
        requested_mode = _session_mode(command.mode)
        if command.mode is not None and requested_mode is None:
            self._emit_error(command, f"unsupported factory session mode: {command.mode}")
            return
        previous_record = self.session_record
        previous_mode = self.mode
        self.session_record = self.session_manager.load(command.session_id)
        self.mode = requested_mode or self.session_record.current_mode
        if not self._session_source_available(self.session_record, self.mode):
            self.session_record = previous_record
            self.mode = previous_mode
            self._emit_missing_session_source(command, requested_mode or "factory")
            return
        if requested_mode is not None and requested_mode != self.session_record.current_mode:
            self.session_record = self.session_manager.set_mode(self.session_record.session_id, requested_mode)
        self._restore_session_mode_context()
        self._emit_session_event(
            command.request_id,
            session_event_type="session_switched",
        )

    def new_session(self, command: FactoryFrontendCommand) -> None:
        self.mode = _session_mode(command.mode)
        if self.mode is None:
            self._emit_error(command, "new_session requires create_agent or evolve_agent mode")
            return
        self.session_record = self.session_manager.create(mode=self.mode)
        requested_evolution_package_id = _command_evolution_package_id(command, self.mode)
        if requested_evolution_package_id:
            self.session_record = self.session_manager.set_evolution_package(
                self.session_record.session_id,
                requested_evolution_package_id,
            )
        self._restore_session_mode_context()
        self._emit_session_event(
            command.request_id,
            session_event_type="session_started",
        )

    def delete_session(self, command: FactoryFrontendCommand) -> None:
        session_id = str(command.session_id or command.payload.get("session_id") or "").strip()
        if not session_id:
            self._emit_error(command, "delete_session requires session_id")
            return
        record = self.session_manager.load_if_exists(session_id)
        if record is None:
            deleted_active = self.session_record is not None and self.session_record.session_id == session_id
            if deleted_active:
                self.session_record = None
                self.pending_create_agent_run = None
                self.pending_evolution_run = None
            self.emit(
                event(
                    "session_deleted",
                    request_id=command.request_id,
                    session_id=None if deleted_active else self._session_id(),
                    mode=self.mode,
                    payload={
                        "session_id": session_id,
                        "session_ids": [session_id],
                        "deleted": False,
                        "already_absent": True,
                        "deleted_active": deleted_active,
                        "linked_artifacts": {},
                        "recent_agent_sessions": [],
                        "sessions": self._session_payloads_for_client(),
                    },
                )
            )
            return
        delete_mode = (
            _session_mode(command.mode)
            or _session_mode(str(command.payload.get("mode") or ""))
            or _session_mode(self.mode)
            or record.current_mode
        )
        linked_artifacts = self._delete_linked_session_artifacts(record, mode=delete_mode)
        recent_agent_sessions = _recent_agent_sessions_from_linked_artifacts(linked_artifacts)
        affected_session_ids = self._delete_or_detach_logical_session(record, mode=delete_mode)
        deleted_active = (
            self.session_record is not None
            and self.session_record.session_id in affected_session_ids
            and delete_mode == self.mode
        )
        if deleted_active:
            self.session_record = None
            self.pending_create_agent_run = None
            self.pending_evolution_run = None
        self.emit(
            event(
                "session_deleted",
                request_id=command.request_id,
                session_id=None if deleted_active else self._session_id(),
                mode=self.mode,
                payload={
                    "session_id": record.session_id,
                    "session_ids": sorted(affected_session_ids),
                    "deleted": True,
                    "deleted_active": deleted_active,
                    "linked_artifacts": linked_artifacts,
                    "recent_agent_sessions": recent_agent_sessions,
                    "sessions": self._session_payloads_for_client(),
                },
            )
        )

    def set_mode(self, command: FactoryFrontendCommand) -> None:
        mode = _session_mode(command.mode)
        if mode is None:
            self._emit_error(command, f"unsupported factory session mode: {command.mode}")
            return
        if not self._ensure_session(command, mode=mode):
            return
        self._apply_mode(command, mode)

    def send_message(self, command: FactoryFrontendCommand) -> None:
        requested_mode = _session_mode(command.mode) or _session_mode(self.mode)
        if requested_mode is None:
            self._emit_error(command, "send_message requires create_agent or evolve_agent mode")
            return
        if not self._ensure_session(command, mode=requested_mode):
            return
        if command.mode in MESSAGE_MODES and command.mode != self.mode:
            self._apply_mode(command, command.mode)
        if self.mode not in {"create_agent", "evolve_agent"}:
            self._emit_error(command, "enter /create-agent or /evolve-agent before sending messages")
            return
        message = (command.message or "").strip()
        if not message and not has_attachment_payload(command.payload.get("attachments")):
            self._emit_error(command, "send_message requires message")
            return
        if self.mode == "create_agent":
            if self.pending_create_agent_run is not None:
                if interrupt_accepts_message(self.pending_create_agent_run):
                    self._resume_create_agent_interrupt(message_resume_command(command, message))
                else:
                    self._emit_error(command, "cannot send a new message while an interrupt decision is pending")
                return
            self._run_create_agent(command, message)
        else:
            if self.pending_evolution_run is not None:
                if interrupt_accepts_message(self.pending_evolution_run):
                    self._resume_evolution_interrupt(message_resume_command(command, message))
                else:
                    self._emit_error(command, "cannot send a new message while an interrupt decision is pending")
                return
            self._run_evolve_agent(command, message)

    def _apply_mode(self, command: FactoryFrontendCommand, mode: str | None) -> None:
        if self.session_record is None:
            if not self._ensure_session(command, mode=_session_mode(mode)):
                return
        self.mode = mode
        self.session_record = self.session_manager.set_mode(self.session_record.session_id, self.mode)
        self._restore_session_mode_context()
        self.emit(
            event(
                "mode_changed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={
                    "mode": self.mode,
                    **({"graph_id": "create_agent_react"} if self.mode == "create_agent" else {}),
                },
            )
        )

    def resume_interrupt(self, command: FactoryFrontendCommand) -> None:
        target = _interrupt_resume_target(command.payload)
        group_run_id = str(command.payload.get("group_run_id") or "").strip()
        if group_run_id:
            pending_group_run = self.pending_agent_group_runs.pop(group_run_id, None)
            if pending_group_run is None:
                self._emit_error(command, "no matching agent-group interrupt to resume")
                return
            self.resume_agent_group_interrupt(command, pending_group_run)
            return
        if self.pending_create_agent_run is not None and _pending_create_agent_matches(self.pending_create_agent_run, target):
            self._resume_create_agent_interrupt(command)
            return
        if self.pending_evolution_run is not None and _pending_evolution_matches(self.pending_evolution_run, target):
            self._resume_evolution_interrupt(command)
            return
        pending_agent_package_run = self._take_pending_agent_package_run(target)
        if pending_agent_package_run is not None:
            self._resume_agent_package_interrupt(command, pending_agent_package_run)
            return
        if target.explicit:
            self._emit_error(command, "no matching pending interrupt to resume")
            return
        self._emit_error(command, "no pending interrupt to resume")

    def _remember_pending_agent_package_run(self, pending: PendingAgentPackageRun) -> None:
        key = _pending_agent_package_key(pending)
        with self.pending_agent_package_runs_lock:
            self.pending_agent_package_runs[key] = pending

    def _has_pending_agent_package_run(self, package_id: str, session_id: str) -> bool:
        key = (str(package_id).strip(), str(session_id).strip())
        with self.pending_agent_package_runs_lock:
            return key in self.pending_agent_package_runs

    def _take_pending_agent_package_for_message(
        self,
        package_id: str,
        session_id: str,
    ) -> PendingAgentPackageRun | None:
        key = (str(package_id).strip(), str(session_id).strip())
        with self.pending_agent_package_runs_lock:
            return self.pending_agent_package_runs.pop(key, None)

    def _take_pending_agent_package_run(
        self,
        target: _InterruptResumeTarget,
    ) -> PendingAgentPackageRun | None:
        with self.pending_agent_package_runs_lock:
            matches = [
                (key, pending)
                for key, pending in self.pending_agent_package_runs.items()
                if _pending_agent_package_matches(pending, target)
            ]
            if len(matches) != 1:
                return None
            key, pending = matches[0]
            self.pending_agent_package_runs.pop(key, None)
            return pending

    def _emit_session_event(
        self,
        request_id: str | None,
        *,
        session_event_type: str = "session_switched",
        payload_metadata: dict[str, object] | None = None,
    ) -> None:
        self.emit(
            event(
                session_event_type,
                request_id=request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"session": self._session_payload(), **(payload_metadata or {})},
            )
        )

    def _emit_empty_session_event(
        self,
        request_id: str | None,
        *,
        mode: str | None,
        package_id: str | None,
    ) -> None:
        self.emit(
            event(
                "session_empty",
                request_id=request_id,
                session_id=None,
                mode=mode,
                payload={
                    "mode": mode,
                    "package_id": package_id,
                    "sessions": self._session_payloads_for_client(),
                },
            )
        )

    def _emit_error(self, command: FactoryFrontendCommand, message: str) -> None:
        self.emit(
            event(
                "error",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                message=message,
            )
        )

    def _delete_linked_session_artifacts(self, record, *, mode: str | None = None) -> dict[str, object]:
        artifacts: dict[str, object] = {}
        create_session_id = str(getattr(record, "create_agent_session_id", "") or "").strip()
        if (mode in {None, "create_agent"}) and create_session_id and self.create_agent_runtime is not None:
            artifacts["create_agent"] = self.create_agent_runtime.delete_session_artifacts(create_session_id)

        evolve_package_id = str(getattr(record, "evolve_agent_package_id", "") or "").strip()
        if (mode in {None, "evolve_agent"}) and evolve_package_id and self.evolution_runtime is not None:
            artifacts["evolve_agent"] = self.evolution_runtime.delete_session_artifacts(
                package_id=evolve_package_id,
                session_id=record.session_id,
                request_ids=_turn_request_ids(getattr(record, "evolve_agent_turns", [])),
            )
        return artifacts

    def _ensure_session(
        self,
        command: FactoryFrontendCommand,
        *,
        mode: str | None = None,
    ) -> bool:
        requested_session_id = str(command.session_id or "").strip()
        if requested_session_id:
            requested_record = self.session_manager.load_if_exists(requested_session_id)
            if requested_record is None:
                self._emit_error(command, f"factory session not found: {requested_session_id}")
                return False
            self.session_record = requested_record
            self.mode = _session_mode(mode) or _session_mode(command.mode) or requested_record.current_mode
            self._restore_session_mode_context()
        if self.session_record is None:
            resolved_mode = _session_mode(mode) or _session_mode(command.mode) or _session_mode(self.mode)
            if resolved_mode is None:
                self._emit_error(command, "factory session requires create_agent or evolve_agent mode")
                return False
            self.start_session(
                FactoryFrontendCommand(
                    type="start_session",
                    request_id=command.request_id,
                    mode=resolved_mode,
                )
            )
        return self.session_record is not None

    def _latest_session_for_start(
        self,
        requested_mode: str | None,
        requested_evolution_package_id: str | None,
    ):
        records = self._client_session_records()
        if requested_evolution_package_id:
            for record in records:
                if _evolve_agent_package_id(record) == requested_evolution_package_id:
                    return record
            return None
        if requested_mode is not None:
            for record in records:
                if _client_record_matches_mode(record, requested_mode):
                    return record
            return None
        return records[0] if records else None

    def _restore_session_mode_context(self) -> None:
        if self.session_record is None:
            return
        if self.mode == "evolve_agent":
            self.evolution_package_id = str(getattr(self.session_record, "evolve_agent_package_id", "") or "").strip() or None
            return
        if self.mode != "agent_package":
            self.evolution_package_id = None

    def _session_id(self) -> str | None:
        if self.session_record is None:
            return None
        return str(self.session_record.session_id)

    def _session_payload(self) -> dict[str, object]:
        payload = session_payload(self.session_record, snapshot_mode=self.mode)
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
        linked_agent_session = self._linked_agent_session_payload()
        if linked_agent_session is not None:
            snapshot = {
                **snapshot,
                "agent_session": linked_agent_session,
            }
        payload["snapshot"] = snapshot
        return payload

    def _session_payloads_for_client(self) -> list[dict[str, object]]:
        return [session_payload(item) for item in self._client_session_records()]

    def _client_session_records(self) -> list[Any]:
        return [
            record
            for record in self.session_manager.list_sessions()
            if _client_record_has_source(record)
        ]

    def _session_source_available(self, record: Any, mode: str | None) -> bool:
        del record, mode
        return True

    def _emit_missing_session_source(self, command: FactoryFrontendCommand, mode: str) -> None:
        self._emit_error(command, f"{mode} session source is no longer available")
        self.emit(
            event(
                "sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"sessions": self._session_payloads_for_client()},
            )
        )

    def _delete_or_detach_logical_session(self, record: Any, *, mode: str | None) -> set[str]:
        targets = self._logical_session_records(record, mode=mode)
        affected: set[str] = set()
        for target in targets:
            affected.add(target.session_id)
            updated = without_mode_source(target, mode)
            if record_has_any_source(updated):
                self.session_manager.save(updated)
            else:
                self.session_manager.delete(target.session_id)
        return affected

    def _logical_session_records(self, record: Any, *, mode: str | None) -> list[Any]:
        if mode == "create_agent":
            create_session_id = _create_agent_session_id(record)
            if create_session_id:
                return [
                    item
                    for item in self.session_manager.list_sessions()
                    if _create_agent_session_id(item) == create_session_id
                ]
        return [record]

    def _linked_agent_session_payload(self) -> dict[str, object] | None:
        if self.session_record is None:
            return None
        if self.mode != "create_agent" or self.create_agent_runtime is None or not self.session_record.create_agent_session_id:
            return None
        try:
            return self.create_agent_runtime.load_session_snapshot(self.session_record.create_agent_session_id)
        except Exception:
            return None

    def checkpointer_payload(self) -> dict[str, object]:
        return {
            "backend": "system_package",
            "persistent": True,
            "path": None,
        }

    def _options_payload(self) -> dict[str, object]:
        return asdict(self.options)


def _client_record_has_source(record: Any) -> bool:
    return (
        _client_record_matches_mode(record, "create_agent")
        or _client_record_matches_mode(record, "evolve_agent")
    )


def _client_record_matches_mode(record: Any, mode: str) -> bool:
    if mode == "create_agent":
        return record_has_mode_source(record, "create_agent")
    return bool(getattr(record, "evolve_agent_turn_count", 0) or getattr(record, "evolve_agent_turns", []))


def _create_agent_session_id(record: Any) -> str:
    return str(getattr(record, "create_agent_session_id", "") or "").strip()


def _evolve_agent_package_id(record: Any) -> str:
    return str(getattr(record, "evolve_agent_package_id", "") or "").strip()


def _record_order_key(record: Any) -> tuple[str, str]:
    return (
        str(getattr(record, "updated_at", "") or ""),
        str(getattr(record, "session_id", "") or ""),
    )


def _recent_agent_sessions_from_linked_artifacts(artifacts: dict[str, object]) -> list[dict[str, Any]] | None:
    for artifact in artifacts.values():
        if not isinstance(artifact, dict):
            continue
        sessions = artifact.get("recent_agent_sessions")
        if isinstance(sessions, list):
            return [dict(session) for session in sessions if isinstance(session, dict)]
    return None


def _turn_request_ids(turns: object) -> list[str]:
    if not isinstance(turns, list):
        return []
    request_ids: list[str] = []
    for turn in turns:
        request_id = str(getattr(turn, "request_id", "") or "").strip()
        if request_id:
            request_ids.append(request_id)
    return request_ids


class _InterruptResumeTarget:
    def __init__(self, payload: dict[str, object]) -> None:
        self.mode = _normalized_optional(payload.get("mode") or payload.get("original_mode"))
        self.package_id = _normalized_optional(payload.get("package_id"))
        self.session_id = _normalized_optional(
            payload.get("agent_session_id") or payload.get("session_id") or payload.get("original_session_id")
        )
        self.request_id = _normalized_optional(
            payload.get("pending_request_id") or payload.get("original_request_id")
        )
        self.interrupt_id = _normalized_optional(payload.get("interrupt_id"))
        self.interrupt_event_id = _normalized_optional(payload.get("interrupt_event_id"))

    @property
    def explicit(self) -> bool:
        return any([
            self.mode,
            self.package_id,
            self.session_id,
            self.request_id,
            self.interrupt_id,
            self.interrupt_event_id,
        ])


def _interrupt_resume_target(payload: object) -> _InterruptResumeTarget:
    return _InterruptResumeTarget(payload if isinstance(payload, dict) else {})


def _pending_create_agent_matches(pending: object, target: _InterruptResumeTarget) -> bool:
    if target.mode and target.mode != "create_agent":
        return False
    return _pending_common_matches(
        session_id=getattr(pending, "session_id", None),
        request_id=getattr(pending, "request_id", None),
        interrupt_id=getattr(pending, "interrupt_id", None),
        interrupt_event_id=getattr(pending, "interrupt_event_id", None),
        target=target,
    )


def _pending_evolution_matches(pending: object, target: _InterruptResumeTarget) -> bool:
    if target.mode and target.mode != "evolve_agent":
        return False
    if target.package_id and target.package_id != _normalized_optional(getattr(pending, "package_id", None)):
        return False
    return _pending_common_matches(
        session_id=getattr(pending, "session_id", None),
        request_id=getattr(pending, "request_id", None),
        interrupt_id=getattr(pending, "interrupt_id", None),
        interrupt_event_id=getattr(pending, "interrupt_event_id", None),
        target=target,
    )


def _pending_agent_package_matches(pending: object, target: _InterruptResumeTarget) -> bool:
    if target.mode and target.mode not in {"agent_package", "agent_group"}:
        return False
    if target.package_id and target.package_id != _normalized_optional(getattr(pending, "package_id", None)):
        return False
    normalizer = getattr(pending, "normalizer", None)
    return _pending_common_matches(
        session_id=getattr(pending, "session_id", None),
        request_id=getattr(normalizer, "request_id", None),
        interrupt_id=getattr(pending, "interrupt_id", None),
        interrupt_event_id=getattr(pending, "interrupt_event_id", None),
        target=target,
    )


def _pending_agent_package_key(pending: object) -> tuple[str, str]:
    package_id = _normalized_optional(getattr(pending, "package_id", None))
    session_id = _normalized_optional(getattr(pending, "session_id", None))
    if not package_id or not session_id:
        raise ValueError("pending agent package run requires package_id and session_id")
    return package_id, session_id


def _pending_common_matches(
    *,
    session_id: object,
    request_id: object,
    interrupt_id: object,
    interrupt_event_id: object,
    target: _InterruptResumeTarget,
) -> bool:
    if target.interrupt_event_id:
        return target.interrupt_event_id == _normalized_optional(interrupt_event_id)
    if target.session_id and target.session_id != _normalized_optional(session_id):
        return False
    if target.request_id and target.request_id != _normalized_optional(request_id):
        return False
    if target.interrupt_id and target.interrupt_id != _normalized_optional(interrupt_id):
        return False
    return True


def _normalized_optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _session_mode(mode: str | None) -> str | None:
    return mode if mode in SESSION_MODES else None


def _command_evolution_package_id(command: FactoryFrontendCommand, mode: str | None) -> str | None:
    if mode != "evolve_agent" or not isinstance(command.payload, dict):
        return None
    value = str(command.payload.get("package_id") or "").strip()
    return value or None
