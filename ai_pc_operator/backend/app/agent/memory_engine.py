"""Memory engine - workflow templates + persistent memory entries.

Workflow templates are reusable DAG plans that the planner can match
against incoming commands. Memory entries store user facts, preferences,
and corrections that survive across sessions.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.db.database import db_session

logger = logging.getLogger(__name__)


class MemoryEngine:
    """Persistent memory + workflow templates."""

    # ------------------------------------------------------------------
    # Memory entries
    # ------------------------------------------------------------------

    async def remember(
        self,
        kind: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = "user",
    ) -> None:
        """Insert or update a memory entry."""
        async with db_session() as db:
            await db.execute(
                """
                INSERT INTO memory_entries (kind, key, value, confidence, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kind, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    last_used_at = CURRENT_TIMESTAMP
                """,
                (kind, key, value, confidence, source),
            )
            await db.commit()

    async def recall(self, kind: str, key: str) -> Optional[Dict[str, Any]]:
        """Fetch a memory entry by kind+key."""
        async with db_session() as db:
            cur = await db.execute(
                "SELECT * FROM memory_entries WHERE kind = ? AND key = ?",
                (kind, key),
            )
            row = await cur.fetchone()
            if not row:
                return None
            await db.execute(
                "UPDATE memory_entries SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            await db.commit()
            return dict(row)

    async def search_memory(
        self,
        query: str,
        kind: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search memory entries by substring."""
        async with db_session() as db:
            sql = "SELECT * FROM memory_entries WHERE (key LIKE ? OR value LIKE ?)"
            params: List[Any] = [f"%{query}%", f"%{query}%"]
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            sql += " ORDER BY last_used_at DESC, id DESC LIMIT ?"
            params.append(max(1, min(limit, 200)))
            cur = await db.execute(sql, params)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def forget(self, kind: str, key: str) -> bool:
        """Delete a memory entry."""
        async with db_session() as db:
            cur = await db.execute(
                "DELETE FROM memory_entries WHERE kind = ? AND key = ?",
                (kind, key),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def list_memory(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all memory entries, optionally filtered by kind."""
        async with db_session() as db:
            if kind:
                cur = await db.execute(
                    "SELECT * FROM memory_entries WHERE kind = ? ORDER BY id DESC",
                    (kind,),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM memory_entries ORDER BY id DESC"
                )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Workflow templates
    # ------------------------------------------------------------------

    async def save_template(
        self,
        template_id: str,
        name: str,
        plan: List[Dict[str, Any]],
        description: str = "",
        trigger_text: str = "",
    ) -> None:
        """Insert or update a workflow template."""
        async with db_session() as db:
            await db.execute(
                """
                INSERT INTO workflow_templates (id, name, description, trigger_text, plan_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    trigger_text = excluded.trigger_text,
                    plan_json = excluded.plan_json
                """,
                (template_id, name, description, trigger_text, json.dumps(plan, default=str)),
            )
            await db.commit()

    async def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a workflow template by id."""
        async with db_session() as db:
            cur = await db.execute(
                "SELECT * FROM workflow_templates WHERE id = ?", (template_id,)
            )
            row = await cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["plan"] = json.loads(d.pop("plan_json")) if d.get("plan_json") else []
            return d

    async def list_templates(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """List workflow templates."""
        async with db_session() as db:
            sql = "SELECT * FROM workflow_templates"
            if enabled_only:
                sql += " WHERE enabled = 1"
            sql += " ORDER BY use_count DESC, id DESC"
            cur = await db.execute(sql)
            rows = await cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["plan"] = json.loads(d.pop("plan_json")) if d.get("plan_json") else []
                results.append(d)
            return results

    async def match_template(self, text: str) -> Optional[Dict[str, Any]]:
        """Find a template whose trigger_text matches the user command."""
        async with db_session() as db:
            cur = await db.execute(
                "SELECT * FROM workflow_templates WHERE enabled = 1"
            )
            rows = await cur.fetchall()
        text_lower = text.lower().strip()
        best: Optional[Dict[str, Any]] = None
        best_score = 0
        for r in rows:
            trigger = (r["trigger_text"] or "").lower().strip()
            if not trigger:
                continue
            score = self._trigger_score(text_lower, trigger)
            if score > best_score:
                best_score = score
                d = dict(r)
                d["plan"] = json.loads(d.pop("plan_json")) if d.get("plan_json") else []
                best = d
        if best is not None:
            await self._bump_template_usage(best["id"])
        return best

    async def record_template_use(self, template_id: str) -> None:
        """Increment use_count and update last_used_at."""
        await self._bump_template_usage(template_id)

    async def _bump_template_usage(self, template_id: str) -> None:
        async with db_session() as db:
            await db.execute(
                """
                UPDATE workflow_templates
                SET use_count = use_count + 1, last_used_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (template_id,),
            )
            await db.commit()

    @staticmethod
    def _trigger_score(text: str, trigger: str) -> int:
        """Simple word-overlap score between user text and trigger."""
        text_words = set(text.split())
        trigger_words = set(trigger.split())
        if not trigger_words:
            return 0
        overlap = len(text_words & trigger_words)
        return overlap
