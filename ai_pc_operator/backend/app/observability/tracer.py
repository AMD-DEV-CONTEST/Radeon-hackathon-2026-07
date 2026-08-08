"""Observability - structured trace events for replay and debugging.

Every meaningful step in the agent pipeline emits a trace event.
Events are persisted to the trace_events table and can be replayed
to reconstruct what happened during a task.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from app.db.database import db_session

logger = logging.getLogger(__name__)


class Tracer:
    """Lightweight structured event recorder."""

    def __init__(self) -> None:
        self._enabled = True

    async def event(
        self,
        event_type: str,
        task_id: Optional[str] = None,
        node_id: Optional[str] = None,
        skill_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
    ) -> int:
        """Record a trace event."""
        if not self._enabled:
            return 0
        try:
            async with db_session() as db:
                cur = await db.execute(
                    """
                    INSERT INTO trace_events (
                        task_id, node_id, skill_id, event_type, payload_json, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        node_id,
                        skill_id,
                        event_type,
                        json.dumps(payload, default=str) if payload else None,
                        duration_ms,
                    ),
                )
                await db.commit()
                return cur.lastrowid or 0
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tracer event failed: %s", exc)
            return 0

    async def trace_task(self, task_id: str) -> Dict[str, Any]:
        """Return all events for a task grouped by type."""
        async with db_session() as db:
            cur = await db.execute(
                """
                SELECT id, event_type, node_id, skill_id, payload_json, duration_ms, created_at
                FROM trace_events WHERE task_id = ? ORDER BY id ASC
                """,
                (task_id,),
            )
            rows = await cur.fetchall()
        events = []
        for r in rows:
            d = dict(r)
            if d.get("payload_json"):
                try:
                    d["payload"] = json.loads(d.pop("payload_json"))
                except json.JSONDecodeError:
                    d["payload"] = None
            events.append(d)
        return {
            "task_id": task_id,
            "event_count": len(events),
            "events": events,
        }

    async def recent_events(self, limit: int = 100) -> list:
        """Return recent events across all tasks."""
        async with db_session() as db:
            cur = await db.execute(
                """
                SELECT id, task_id, event_type, skill_id, created_at
                FROM trace_events ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    def disable(self) -> None:
        self._enabled = False

    def enable(self) -> None:
        self._enabled = True
