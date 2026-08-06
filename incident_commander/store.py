from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .errors import AgentError


class SessionStore:
    """Atomic JSON snapshots plus an append-only audit file."""

    def __init__(self, root: Path):
        self.root = root
        self.sessions = root / "sessions"
        self.quarantine = root / "quarantine"
        self.sessions.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)
        self._audit_lock = Lock()

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.is_file():
            raise AgentError("investigation not found", "not_found", 404)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("id") != session_id:
                raise ValueError("invalid session snapshot")
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            target = self.quarantine / f"{session_id}-{stamp}.json"
            try:
                os.replace(path, target)
            except OSError:
                pass
            raise AgentError(f"session snapshot is corrupt: {exc}", "corrupt_session", 500) from exc

    def save(self, snapshot: dict[str, Any]) -> None:
        session_id = str(snapshot.get("id", ""))
        path = self._path(session_id)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        rendered = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def append_audit(self, event: dict[str, Any]) -> None:
        rendered = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._audit_lock:
            with (self.root / "audit.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())

    def _path(self, session_id: str) -> Path:
        if not session_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in session_id):
            raise AgentError("invalid investigation id", "invalid_id", 400)
        return self.sessions / f"{session_id}.json"
