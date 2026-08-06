"""Session manager: JSON-based conversation persistence.

Stores sessions as individual JSON files in the configured directory.
Supports listing recent sessions and loading full conversation history.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages conversation sessions with JSON persistence."""

    def __init__(self, persist_dir: str, max_recent: int = 10) -> None:
        self.persist_dir = Path(persist_dir)
        self.max_recent = max_recent
        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> str:
        """Create a new session and return its ID."""
        session_id = f"sess_{int(time.time())}_{id(self):x}"
        session_data = {
            "session_id": session_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "title": "",
            "messages": [],
        }
        self._save(session_id, session_data)
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a message to a session."""
        data = self._load(session_id)
        if data is None:
            data = {
                "session_id": session_id,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "title": "",
                "messages": [],
            }

        message: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if metadata:
            message["metadata"] = metadata

        data["messages"].append(message)

        # Auto-title from first user message
        if role == "user" and not data.get("title"):
            data["title"] = content[:60] + ("..." if len(content) > 60 else "")

        self._save(session_id, data)

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Get all messages from a session."""
        data = self._load(session_id)
        if data is None:
            return []
        return data.get("messages", [])

    def list_sessions(self) -> list[dict[str, Any]]:
        """List recent sessions sorted by creation time."""
        sessions = []
        for f in sorted(self.persist_dir.glob("sess_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                sessions.append({
                    "session_id": data["session_id"],
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "title": data.get("title", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions[: self.max_recent]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        path = self.persist_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def _load(self, session_id: str) -> dict[str, Any] | None:
        path = self.persist_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load session %s: %s", session_id, e)
            return None

    def _save(self, session_id: str, data: dict[str, Any]) -> None:
        path = self.persist_dir / f"{session_id}.json"
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except OSError as e:
            logger.error("Failed to save session %s: %s", session_id, e)
