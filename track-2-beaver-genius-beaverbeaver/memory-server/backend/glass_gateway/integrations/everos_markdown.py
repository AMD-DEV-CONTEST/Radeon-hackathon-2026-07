from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any


_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ENTRY = re.compile(
    r"<!-- entry:(?P<id>[A-Za-z0-9_.-]+) -->\s*(?P<body>.*?)"
    r"<!-- /entry:(?P=id) -->",
    re.DOTALL,
)


class EverOSMarkdownReader:
    """Read EverOS's documented Markdown truth source when its index is stale.

    This does not extract or aggregate memories. EverOS has already generated
    these Episode/Fact files; the reader only provides a degraded list view
    while the rebuildable LanceDB cascade is unavailable.
    """

    def __init__(self, *, root: str | Path, app_id: str, project_id: str) -> None:
        self.root = Path(root).resolve()
        self.app_id = self._safe(app_id)
        self.project_id = self._safe(project_id)

    def get_episodes(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = self._safe(user_id)
        user_root = self.root / self.app_id / self.project_id / "users" / user
        facts = self._facts_by_episode(user_root, user)
        episodes: list[dict[str, Any]] = []
        for path in sorted((user_root / "episodes").glob("episode-*.md"), reverse=True):
            for entry_id, body in self._entries(path):
                inline = self._inline_fields(body)
                timestamp = inline.get("timestamp") or ""
                session_id = inline.get("session_id") or ""
                item = {
                    "id": f"{user}_{entry_id}",
                    "user_id": user,
                    "app_id": self.app_id,
                    "project_id": self.project_id,
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "sender_ids": self._inline_list(inline.get("sender_ids")),
                    "subject": self._section(body, "Subject"),
                    "summary": self._section(body, "Summary"),
                    "episode": self._section(body, "Content"),
                    "type": "Conversation",
                    "score": None,
                    "atomic_facts": facts.get(entry_id, []),
                    "metadata": {
                        "everos_markdown": str(path),
                        "source": "everos_markdown_truth",
                    },
                }
                if self._matches(item, filters):
                    episodes.append(item)
        episodes.sort(key=lambda item: self._timestamp(item.get("timestamp")), reverse=True)
        start = (max(1, page) - 1) * max(1, page_size)
        end = start + max(1, page_size)
        return {
            "request_id": "everos-markdown-truth",
            "status": "markdown_truth_fallback",
            "data": {
                "episodes": episodes[start:end],
                "profiles": [],
                "agent_cases": [],
                "agent_skills": [],
                "unprocessed_messages": [],
                "page": max(1, page),
                "page_size": max(1, page_size),
                "total": len(episodes),
            },
        }

    def _facts_by_episode(
        self,
        user_root: Path,
        user_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for path in sorted((user_root / ".atomic_facts").glob("atomic_fact-*.md")):
            for entry_id, body in self._entries(path):
                inline = self._inline_fields(body)
                parent_id = inline.get("parent_id") or ""
                content = self._section(body, "Fact")
                if not parent_id or not content:
                    continue
                grouped.setdefault(parent_id, []).append(
                    {
                        "id": f"{user_id}_{entry_id}",
                        "content": content,
                        "score": None,
                    }
                )
        return grouped

    @staticmethod
    def _entries(path: Path) -> list[tuple[str, str]]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return [(match.group("id"), match.group("body")) for match in _ENTRY.finditer(text)]

    @staticmethod
    def _inline_fields(body: str) -> dict[str, str]:
        return {
            key.strip(): value.strip()
            for key, value in re.findall(r"^\*\*([^*]+)\*\*:\s*(.*)$", body, re.MULTILINE)
        }

    @staticmethod
    def _section(body: str, name: str) -> str:
        match = re.search(
            rf"^###\s+{re.escape(name)}\s*$\n(?P<value>.*?)(?=^###\s+|\Z)",
            body,
            re.MULTILINE | re.DOTALL,
        )
        return match.group("value").strip() if match else ""

    @staticmethod
    def _inline_list(value: str | None) -> list[str]:
        if not value:
            return []
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        return [part.strip().strip("'\"") for part in text.split(",") if part.strip()]

    @classmethod
    def _matches(cls, item: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        session_id = filters.get("session_id")
        if isinstance(session_id, str) and item.get("session_id") != session_id:
            return False
        timestamp_filter = filters.get("timestamp")
        if isinstance(timestamp_filter, dict):
            value_ms = int(cls._timestamp(item.get("timestamp")).timestamp() * 1000)
            gte = timestamp_filter.get("gte")
            if isinstance(gte, (int, float)) and value_ms < int(gte):
                return False
            lt = timestamp_filter.get("lt")
            if isinstance(lt, (int, float)) and value_ms >= int(lt):
                return False
        return True

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _safe(value: str) -> str:
        if value in {".", ".."} or not _SAFE_SCOPE.fullmatch(value):
            raise ValueError(f"unsafe EverOS scope id: {value!r}")
        return value
