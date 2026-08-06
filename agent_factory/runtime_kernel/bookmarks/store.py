from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class BookmarkRecord:
    bookmark_id: str
    thread_id: str
    node_id: str
    position: str
    checkpoint_id: str | None
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


class InMemoryBookmarkStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, BookmarkRecord] = {}

    def record(
        self,
        *,
        thread_id: str,
        node_id: str,
        position: str,
        checkpoint_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BookmarkRecord:
        bookmark = BookmarkRecord(
            bookmark_id=uuid4().hex,
            thread_id=thread_id,
            node_id=node_id,
            position=position,
            checkpoint_id=checkpoint_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._records[bookmark.bookmark_id] = bookmark
        return bookmark

    def get(self, bookmark_id: str) -> BookmarkRecord | None:
        with self._lock:
            return self._records.get(bookmark_id)

    def list(
        self,
        *,
        thread_id: str | None = None,
        node_id: str | None = None,
        position: str | None = None,
    ) -> list[BookmarkRecord]:
        with self._lock:
            records = list(self._records.values())
        if thread_id is not None:
            records = [record for record in records if record.thread_id == thread_id]
        if node_id is not None:
            records = [record for record in records if record.node_id == node_id]
        if position is not None:
            records = [record for record in records if record.position == position]
        return records
