from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AppPaths
from ..exceptions import ValidationError
from .storage.layout import knowledge_import_logs_path, knowledge_import_task_root

_TASK_ID = re.compile(r"[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"[a-z0-9_.-]{1,80}\Z")
_LEVELS = frozenset({"debug", "info", "warning", "error"})
_LOG_SCHEMA_VERSION = 1
_MAX_LOG_BYTES = 2 * 1024 * 1024
_MAX_LOG_LINE_BYTES = 1024
_MAX_RETURNED_EVENTS = 2_000
_LOG_KEYS = frozenset(
    {"schema_version", "timestamp", "level", "phase", "event_code"}
)


@dataclass(frozen=True)
class KnowledgeTaskLogEntry:
    timestamp: str
    level: str
    phase: str
    event_code: str


class KnowledgeTaskLogStore:
    """Append and read bounded, content-free Knowledge task events."""

    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths
        self._lock = threading.Lock()

    def append(
        self,
        import_id: str,
        *,
        phase: str,
        event_code: str,
        level: str = "info",
    ) -> None:
        _require_task_id(import_id)
        normalized_phase = _require_token(phase, "phase")
        normalized_code = _require_token(event_code, "event code")
        normalized_level = level.casefold().strip()
        if normalized_level not in _LEVELS:
            raise ValueError("Knowledge task log level is invalid.")
        payload = {
            "schema_version": _LOG_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": normalized_level,
            "phase": normalized_phase,
            "event_code": normalized_code,
        }
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > _MAX_LOG_LINE_BYTES:
            raise ValueError("Knowledge task log event is too large.")
        path = knowledge_import_logs_path(self._paths, import_id)
        with self._lock:
            task_root = knowledge_import_task_root(self._paths, import_id)
            task_root.mkdir(parents=True, exist_ok=True)
            current_size = path.stat().st_size if path.exists() else 0
            if current_size + len(encoded) > _MAX_LOG_BYTES:
                return
            with path.open("ab") as stream:
                stream.write(encoded)
                stream.flush()

    def read(self, import_id: str) -> tuple[KnowledgeTaskLogEntry, ...]:
        _require_task_id(import_id)
        path = knowledge_import_logs_path(self._paths, import_id)
        with self._lock:
            if not path.is_file():
                return ()
            try:
                size = path.stat().st_size
                if size < 0 or size > _MAX_LOG_BYTES:
                    raise ValueError("log size")
                entries = _read_entries(path)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                raise ValidationError(
                    "Knowledge import log could not be read safely.",
                    error_code="knowledge_import_log_invalid",
                ) from exc
        return tuple(entries[-_MAX_RETURNED_EVENTS:])

    def remove(self, import_id: str) -> bool:
        """Remove one app-owned import task directory without following links."""

        _require_task_id(import_id)
        task_root = knowledge_import_task_root(self._paths, import_id)
        expected_parent = knowledge_import_task_root(self._paths, "0" * 32).parent
        absolute_task_root = Path(os.path.abspath(task_root))
        absolute_parent = Path(os.path.abspath(expected_parent))
        if absolute_task_root.parent != absolute_parent:
            raise ValidationError("Knowledge task log path is invalid.")
        with self._lock:
            if task_root.is_symlink():
                return False
            if not task_root.exists():
                return True
            if not task_root.is_dir():
                return False
            try:
                shutil.rmtree(task_root)
            except OSError:
                return False
        return not task_root.exists()


def _read_entries(path: Path) -> list[KnowledgeTaskLogEntry]:
    entries: list[KnowledgeTaskLogEntry] = []
    with path.open("rb") as stream:
        for raw_line in stream:
            if not raw_line.endswith(b"\n") or len(raw_line) > _MAX_LOG_LINE_BYTES:
                raise ValueError("log line")
            payload: Any = json.loads(raw_line)
            if not isinstance(payload, dict) or set(payload) != _LOG_KEYS:
                raise ValueError("log shape")
            if payload.get("schema_version") != _LOG_SCHEMA_VERSION:
                raise ValueError("log version")
            timestamp = payload.get("timestamp")
            level = payload.get("level")
            phase = payload.get("phase")
            event_code = payload.get("event_code")
            if (
                not isinstance(timestamp, str)
                or not isinstance(level, str)
                or level not in _LEVELS
                or not isinstance(phase, str)
                or not isinstance(event_code, str)
            ):
                raise ValueError("log fields")
            datetime.fromisoformat(timestamp)
            _require_token(phase, "phase")
            _require_token(event_code, "event code")
            entries.append(
                KnowledgeTaskLogEntry(
                    timestamp=timestamp,
                    level=level,
                    phase=phase,
                    event_code=event_code,
                )
            )
    return entries


def _require_task_id(value: str) -> None:
    if not isinstance(value, str) or _TASK_ID.fullmatch(value) is None:
        raise ValidationError("Knowledge task identity is invalid.")


def _require_token(value: str, label: str) -> str:
    normalized = value.casefold().strip() if isinstance(value, str) else ""
    if _TOKEN.fullmatch(normalized) is None:
        raise ValueError(f"Knowledge task log {label} is invalid.")
    return normalized


__all__ = ["KnowledgeTaskLogEntry", "KnowledgeTaskLogStore"]
