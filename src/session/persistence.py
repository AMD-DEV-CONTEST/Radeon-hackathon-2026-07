"""Session persistence: serialize context_window + memo to disk.

C1 fix: agently-request skill requires "Use a RecordStore when memory must
survive process restart". This project uses a JSON file persistence scheme (lightweight and reliable for the competition),
which can be migrated to the Agently RecordStore after the competition.

Persistence strategy:
- save_session: called after the pipeline finishes, writes sessions/{session_id}.json
- load_session: called in SessionRegistry.get_or_create, restores the historical state
- file format: {context_window: [...], memo: {...}, saved_at: timestamp}
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionPersistence:
    """JSON file persistence for Session state."""

    def __init__(self, sessions_dir: str | Path):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def save_session(
        self,
        session_id: str,
        context_window: list | None,
        memo: dict | None,
    ) -> bool:
        """Write the session state to disk.

        Args:
            session_id: the session identifier
            context_window: the current conversation window
            memo: the structured summary

        Returns:
            True if the save succeeded
        """
        # sanitize: remove surrogate characters from all strings to prevent JSON serialization crashes
        def _sanitize(obj):
            if isinstance(obj, str):
                return obj.encode("utf-8", errors="replace").decode("utf-8")
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize(v) for v in obj]
            return obj

        data = {
            "session_id": session_id,
            "context_window": _sanitize(context_window or []),
            "memo": _sanitize(memo or {}),
            "saved_at": time.time(),
        }
        try:
            path = self._session_path(session_id)
            path.write_text(
                json.dumps(data, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            logger.debug("Session persisted: %s (%d turns)", session_id, len(data["context_window"]))
            return True
        except Exception as e:
            logger.warning("Session persistence failed: %s, %s", session_id, e)
            return False

    def load_session(self, session_id: str) -> dict | None:
        """Restore the session state from disk.

        Args:
            session_id: the session identifier

        Returns:
            {context_window, memo, saved_at} or None (when the file does not exist)
        """
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info(
                "Session restored: %s (%d turns, saved at %s)",
                session_id,
                len(data.get("context_window", [])),
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data.get("saved_at", 0))),
            )
            return data
        except Exception as e:
            logger.warning("Session restore failed: %s, %s", session_id, e)
            return None

    def delete_session(self, session_id: str) -> bool:
        """Delete the session persistence file."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(self) -> list[str]:
        """List all persisted session_ids."""
        return [
            f.stem for f in self.sessions_dir.glob("*.json")
        ]


def extract_memo_from_turn(
    user_input: str,
    answer: str,
    citations: list[dict] | None,
    query_type: str | None,
) -> dict:
    """Extract key memory fields from a conversation turn (simplified SessionMemory extractor).

    C1 fix: agently-request skill requires "Use a SessionMemory plugin for
    extraction/compression and accepted memory writes". This implements a lightweight
    key-field extractor, which can be replaced with an LLM-driven extractor after the competition.

    Args:
        user_input: user input
        answer: Agent answer
        citations: citation list
        query_type: query type

    Returns:
        extracted memory fields
    """
    memo_entry = {
        "user_question": user_input[:200],
        "query_type": query_type,
        "answer_summary": answer[:300] if answer else "",
        "source_count": len(citations) if citations else 0,
        "extracted_at": time.time(),
    }

    # simple keyword extraction: extract insurance product names from the user's question
    insurance_keywords = [
        "Employer Liability Insurance", "Public Liability Insurance", "Product Liability Insurance", "Professional Liability Insurance",
        "Accident Insurance", "Medical Insurance", "Auto Insurance", "Property Insurance", "Life Insurance",
    ]
    mentioned_products = [
        kw for kw in insurance_keywords if kw in user_input
    ]
    if mentioned_products:
        memo_entry["mentioned_products"] = mentioned_products

    return memo_entry