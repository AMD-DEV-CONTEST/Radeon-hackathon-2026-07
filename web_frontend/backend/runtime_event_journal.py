from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

from agent_factory.paths import resolve_project_path


DEFAULT_RUNTIME_EVENT_JOURNAL_PATH = ".agentfactory/runtime_events"
FACTORY_SESSION_SNAPSHOT_EVENTS = {
    "session_started",
    "session_switched",
    "agent_package_selected",
}
AGENT_SESSION_SNAPSHOT_EVENTS = {"agent_package_session_loaded"}
SESSION_DELETION_EVENTS = {"session_deleted", "agent_package_session_deleted"}
NESTED_SESSION_PAYLOAD_KEYS = {"agent_session", "session", "sessions"}


class RuntimeEventJournal:
    """Durable normalized process events used to rebuild WebUI runtime state."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = root or os.getenv("AGENTFACTORY_RUNTIME_EVENT_JOURNAL_PATH") or DEFAULT_RUNTIME_EVENT_JOURNAL_PATH
        self.root = resolve_project_path(configured)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def prepare_for_delivery(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        prepared = _copy_event(event_payload)
        event_type = str(prepared.get("event_type") or "")
        if event_type in SESSION_DELETION_EVENTS:
            self.delete(_session_id_from_event(prepared))
            return prepared
        if prepared.get("persistence") != "transient" and bool(prepared.get("process_event")):
            self.append(prepared)
        if event_type in FACTORY_SESSION_SNAPSHOT_EVENTS:
            return self._hydrate_factory_snapshot(prepared)
        if event_type in AGENT_SESSION_SNAPSHOT_EVENTS:
            return self._hydrate_agent_snapshot(prepared)
        return prepared

    def append(self, event_payload: dict[str, Any]) -> None:
        session_id = _session_id_from_event(event_payload)
        if not session_id:
            return
        record = _journal_record(event_payload, session_id=session_id)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self._path(session_id).open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def read(self, session_id: str, *, mode: str | None = None) -> list[dict[str, Any]]:
        if not session_id:
            return []
        with self._lock:
            path = self._path(session_id)
            if not path.is_file():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
        events: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if mode and str(item.get("mode") or "") != mode:
                continue
            event_id = str(item.get("event_id") or "")
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            events.append(item)
        return events

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            self._path(session_id).unlink(missing_ok=True)

    def _hydrate_factory_snapshot(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        session_id = str(session.get("session_id") or payload.get("session_id") or event_payload.get("session_id") or "").strip()
        if not session_id:
            return event_payload
        snapshot = session.get("snapshot") if isinstance(session.get("snapshot"), dict) else {}
        mode = str(snapshot.get("mode") or session.get("current_mode") or event_payload.get("mode") or "").strip() or None
        hydrated_snapshot = {**snapshot, "process_events": self.read(session_id, mode=mode)}
        hydrated_session = {**session, "snapshot": hydrated_snapshot}
        return {**event_payload, "payload": {**payload, "session": hydrated_session}}

    def _hydrate_agent_snapshot(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        session_id = str(session.get("session_id") or payload.get("session_id") or event_payload.get("session_id") or "").strip()
        if not session_id:
            return event_payload
        hydrated_session = {**session, "process_events": self.read(session_id)}
        return {**event_payload, "payload": {**payload, "session": hydrated_session}}

    def _path(self, session_id: str) -> Path:
        digest = sha256(session_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.jsonl"


def _copy_event(event_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **event_payload,
        "payload": dict(event_payload.get("payload")) if isinstance(event_payload.get("payload"), dict) else {},
    }


def _session_id_from_event(event_payload: dict[str, Any]) -> str:
    payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    return str(
        payload.get("session_id")
        or session.get("session_id")
        or event_payload.get("session_id")
        or ""
    ).strip()


def _journal_record(event_payload: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
    return {
        **event_payload,
        "session_id": session_id,
        "payload": {
            key: value
            for key, value in payload.items()
            if key not in NESTED_SESSION_PAYLOAD_KEYS
        },
    }
