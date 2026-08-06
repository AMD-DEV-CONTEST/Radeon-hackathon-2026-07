"""Session registry: manage Session instances by session_id.

C1 fix: integrate SessionPersistence to support restoring session state after a process restart.
The persistence scheme is a JSON file (a lightweight scheme for the competition); it can be migrated to the Agently RecordStore after the competition.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.session.persistence import SessionPersistence

logger = logging.getLogger(__name__)


class SessionRegistry:
    """Session registry: first parse the ownership of an incoming message, then find the corresponding Session.

    Persistence: C1 fix — use SessionPersistence to serialize context_window + memo
    to disk, restorable after a process restart.
    """

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self._sessions: dict[str, Any] = {}

        # C1: initialize the persistence backend
        workspace_root = self.settings.get("workspace", {}).get("root", "./.agently/runs/insurance")
        sessions_dir = Path(workspace_root) / "sessions"
        self._persistence = SessionPersistence(sessions_dir)

    def get_or_create(self, session_id: str) -> Any:
        """Get or create a Session.

        C1 fix: when creating a new Session, first try to restore the historical state from disk.

        Args:
            session_id: the session identifier

        Returns:
            a Session instance
        """
        if session_id not in self._sessions:
            from agently.core import Session
            from src.session.handlers import choose_strategy, key_fields_compress

            session = Session(id=session_id)
            session.register_analysis_handler(choose_strategy)
            session.register_resize_handler("key_fields_compress", key_fields_compress)

            # C1: restore the historical state from disk
            saved = self._persistence.load_session(session_id)
            if saved:
                try:
                    # restore context_window — extend in place (context_window is a read-only property)
                    if hasattr(session, "context_window") and saved.get("context_window"):
                        ctx = session.context_window
                        if isinstance(ctx, list):
                            ctx.extend(saved["context_window"])
                        else:
                            logger.debug("Session.context_window is not a list, skipping restore")
                    # restore memo — update in place (memo is a read-only property)
                    if hasattr(session, "memo") and saved.get("memo"):
                        memo = session.memo
                        if isinstance(memo, dict):
                            memo.update(saved["memo"])
                        else:
                            logger.debug("Session.memo is not a dict, skipping memo restore")
                    logger.info(
                        "Session restored successfully: %s (%d history turns)",
                        session_id, len(saved.get("context_window", [])),
                    )
                except Exception as e:
                    logger.warning("Session state restore error: %s, %s", session_id, e)

            self._sessions[session_id] = session
            logger.info("created new Session: %s", session_id)
        else:
            logger.debug("reusing Session: %s", session_id)

        return self._sessions[session_id]

    def save_session(self, session_id: str) -> bool:
        """Persist the current Session state to disk.

        C1 fix: called after the pipeline finishes.

        Args:
            session_id: the session identifier

        Returns:
            True if the save succeeded
        """
        session = self._sessions.get(session_id)
        if not session:
            return False

        context_window = getattr(session, "context_window", [])
        memo = getattr(session, "memo", {})
        return self._persistence.save_session(session_id, context_window, memo)

    def get_all_session_ids(self) -> list[str]:
        """Return all active session_ids."""
        return list(self._sessions.keys())

    def remove_session(self, session_id: str) -> bool:
        """Remove a Session (also deleting the persistence file)."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._persistence.delete_session(session_id)
            logger.info("removed Session: %s", session_id)
            return True
        return False