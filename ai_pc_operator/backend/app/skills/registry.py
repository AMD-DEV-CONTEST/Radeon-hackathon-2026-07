"""Skill registry - SQLite-backed CRUD + metrics for skills.

The registry is the single source of truth for what skills exist,
what they need, what they return, and how they are verified.
Handlers are looked up by dotted path at execution time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.database import db_session
from app.skills.contracts import (
    SkillDefinition,
    SkillInputSpec,
    SkillOutputSpec,
    SkillPermission,
    SkillRunResult,
    SkillStatus,
    SkillVerificationSpec,
)

logger = logging.getLogger(__name__)


class SkillRegistry:
    """SQLite-backed skill registry."""

    def __init__(self) -> None:
        self._cache: Dict[str, SkillDefinition] = {}
        self._cache_loaded = False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def register(self, skill: SkillDefinition) -> None:
        """Insert or update a skill definition."""
        async with db_session() as db:
            await db.execute(
                """
                INSERT INTO skills (
                    id, domain, name, description, version, risk_level,
                    requires_approval, reversible, idempotent, timeout_sec,
                    retry_limit, enabled, handler, tags, metadata_json,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    domain=excluded.domain,
                    name=excluded.name,
                    description=excluded.description,
                    version=excluded.version,
                    risk_level=excluded.risk_level,
                    requires_approval=excluded.requires_approval,
                    reversible=excluded.reversible,
                    idempotent=excluded.idempotent,
                    timeout_sec=excluded.timeout_sec,
                    retry_limit=excluded.retry_limit,
                    enabled=excluded.enabled,
                    handler=excluded.handler,
                    tags=excluded.tags,
                    metadata_json=excluded.metadata_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    skill.id,
                    skill.domain,
                    skill.name,
                    skill.description,
                    skill.version,
                    skill.risk_level,
                    1 if skill.requires_approval else 0,
                    1 if skill.reversible else 0,
                    1 if skill.idempotent else 0,
                    skill.timeout_sec,
                    skill.retry_limit,
                    1 if skill.enabled else 0,
                    skill.handler,
                    json.dumps(skill.tags),
                    json.dumps(skill.metadata),
                ),
            )

            # Replace inputs
            await db.execute("DELETE FROM skill_inputs WHERE skill_id = ?", (skill.id,))
            for inp in skill.inputs:
                await db.execute(
                    """
                    INSERT INTO skill_inputs (skill_id, name, type, required, description, default_value)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        skill.id,
                        inp.name,
                        inp.type,
                        1 if inp.required else 0,
                        inp.description,
                        json.dumps(inp.default) if inp.default is not None else None,
                    ),
                )

            # Replace outputs
            await db.execute("DELETE FROM skill_outputs WHERE skill_id = ?", (skill.id,))
            for out in skill.outputs:
                await db.execute(
                    """
                    INSERT INTO skill_outputs (skill_id, name, type, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    (skill.id, out.name, out.type, out.description),
                )

            # Replace dependencies
            await db.execute("DELETE FROM skill_dependencies WHERE skill_id = ?", (skill.id,))
            for dep in skill.dependencies:
                await db.execute(
                    """
                    INSERT INTO skill_dependencies (skill_id, depends_on, kind)
                    VALUES (?, ?, 'requires')
                    """,
                    (skill.id, dep),
                )

            # Replace verification methods
            await db.execute(
                "DELETE FROM skill_verification_methods WHERE skill_id = ?", (skill.id,)
            )
            for v in skill.verification:
                await db.execute(
                    """
                    INSERT INTO skill_verification_methods (skill_id, method, config_json, required)
                    VALUES (?, ?, ?, ?)
                    """,
                    (skill.id, v.method, json.dumps(v.config), 1 if v.required else 0),
                )

            # Replace permissions
            await db.execute("DELETE FROM skill_permissions WHERE skill_id = ?", (skill.id,))
            for perm in skill.permissions:
                await db.execute(
                    """
                    INSERT INTO skill_permissions (skill_id, scope) VALUES (?, ?)
                    """,
                    (skill.id, perm.value if isinstance(perm, SkillPermission) else perm),
                )

            await db.commit()

        self._cache[skill.id] = skill
        self._cache_loaded = True
        logger.info("Registered skill %s (domain=%s)", skill.id, skill.domain)

    async def get(self, skill_id: str) -> Optional[SkillDefinition]:
        """Fetch a skill by id (cached)."""
        if skill_id in self._cache:
            return self._cache[skill_id]

        async with db_session() as db:
            cur = await db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
            row = await cur.fetchone()
            if not row:
                return None
            skill = await self._row_to_skill(db, row)
        self._cache[skill_id] = skill
        return skill

    async def list(
        self,
        domain: Optional[str] = None,
        enabled_only: bool = True,
    ) -> List[SkillDefinition]:
        """List skills, optionally filtered by domain."""
        await self._ensure_cache()
        results: List[SkillDefinition] = []
        for skill in self._cache.values():
            if enabled_only and not skill.enabled:
                continue
            if domain and skill.domain != domain:
                continue
            results.append(skill)
        results.sort(key=lambda s: (s.domain, s.id))
        return results

    async def search(self, query: str, limit: int = 20) -> List[SkillDefinition]:
        """Search skills by id, name, description, or tags."""
        await self._ensure_cache()
        q = query.lower()
        scored: List[tuple[int, SkillDefinition]] = []
        for skill in self._cache.values():
            score = 0
            if q in skill.id.lower():
                score += 5
            if q in skill.name.lower():
                score += 3
            if q in skill.description.lower():
                score += 2
            for tag in skill.tags:
                if q in tag.lower():
                    score += 2
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:limit]]

    async def enable(self, skill_id: str, enabled: bool = True) -> None:
        """Enable or disable a skill."""
        async with db_session() as db:
            await db.execute(
                "UPDATE skills SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if enabled else 0, skill_id),
            )
            await db.commit()
        if skill_id in self._cache:
            self._cache[skill_id].enabled = enabled

    async def delete(self, skill_id: str) -> None:
        """Remove a skill and its related rows."""
        async with db_session() as db:
            await db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
            await db.commit()
        self._cache.pop(skill_id, None)

    # ------------------------------------------------------------------
    # Run tracking + metrics
    # ------------------------------------------------------------------

    async def record_run(
        self,
        skill_id: str,
        status: SkillStatus,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        duration_ms: int,
        task_id: Optional[str] = None,
        node_id: Optional[str] = None,
        command_id: Optional[int] = None,
        error: Optional[str] = None,
    ) -> int:
        """Persist a skill run and update aggregate metrics."""
        async with db_session() as db:
            cur = await db.execute(
                """
                INSERT INTO skill_runs (
                    skill_id, task_id, command_id, input_json, output_json,
                    status, error, duration_ms, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    skill_id,
                    task_id,
                    command_id,
                    json.dumps(inputs, default=str),
                    json.dumps(outputs, default=str),
                    status.value,
                    error,
                    duration_ms,
                ),
            )
            run_id = cur.lastrowid

            # Update metrics
            await db.execute(
                """
                INSERT INTO skill_metrics (
                    skill_id, total_runs, success_count, failure_count,
                    avg_duration_ms, last_run_at, last_status
                ) VALUES (?, 1, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    total_runs = total_runs + 1,
                    success_count = success_count + ?,
                    failure_count = failure_count + ?,
                    avg_duration_ms = ((avg_duration_ms * (total_runs - 1)) + ?) / total_runs,
                    last_run_at = CURRENT_TIMESTAMP,
                    last_status = excluded.last_status
                """,
                (
                    skill_id,
                    1 if status == SkillStatus.SUCCESS else 0,
                    1 if status != SkillStatus.SUCCESS else 0,
                    duration_ms,
                    status.value,
                    1 if status == SkillStatus.SUCCESS else 0,
                    1 if status != SkillStatus.SUCCESS else 0,
                    duration_ms,
                ),
            )
            await db.commit()
            return run_id or 0

    async def metrics(self, skill_id: str) -> Dict[str, Any]:
        """Return aggregate metrics for a skill."""
        async with db_session() as db:
            cur = await db.execute(
                "SELECT * FROM skill_metrics WHERE skill_id = ?", (skill_id,)
            )
            row = await cur.fetchone()
            if not row:
                return {
                    "skill_id": skill_id,
                    "total_runs": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "avg_duration_ms": 0.0,
                    "last_run_at": None,
                    "last_status": None,
                }
            return dict(row)

    async def recent_runs(self, skill_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent runs for a skill."""
        async with db_session() as db:
            cur = await db.execute(
                """
                SELECT id, status, duration_ms, started_at, finished_at, error
                FROM skill_runs WHERE skill_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (skill_id, max(1, min(limit, 200))),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _ensure_cache(self) -> None:
        if self._cache_loaded:
            return
        async with db_session() as db:
            cur = await db.execute("SELECT * FROM skills")
            rows = await cur.fetchall()
            for row in rows:
                skill = await self._row_to_skill(db, row)
                self._cache[skill.id] = skill
        self._cache_loaded = True

    async def _row_to_skill(self, db, row) -> SkillDefinition:
        row_dict = dict(row)
        cur = await db.execute(
            "SELECT name, type, required, description, default_value FROM skill_inputs WHERE skill_id = ?",
            (row_dict["id"],),
        )
        inputs = [
            SkillInputSpec(
                name=r[0],
                type=r[1],
                required=bool(r[2]),
                description=r[3] or "",
                default=json.loads(r[4]) if r[4] else None,
            )
            for r in await cur.fetchall()
        ]
        cur = await db.execute(
            "SELECT name, type, description FROM skill_outputs WHERE skill_id = ?",
            (row_dict["id"],),
        )
        outputs = [
            SkillOutputSpec(name=r[0], type=r[1], description=r[2] or "")
            for r in await cur.fetchall()
        ]
        cur = await db.execute(
            "SELECT depends_on FROM skill_dependencies WHERE skill_id = ?",
            (row_dict["id"],),
        )
        deps = [r[0] for r in await cur.fetchall()]
        cur = await db.execute(
            "SELECT method, config_json, required FROM skill_verification_methods WHERE skill_id = ?",
            (row_dict["id"],),
        )
        verification = [
            SkillVerificationSpec(
                method=r[0],
                config=json.loads(r[1]) if r[1] else {},
                required=bool(r[2]),
            )
            for r in await cur.fetchall()
        ]
        cur = await db.execute(
            "SELECT scope FROM skill_permissions WHERE skill_id = ?",
            (row_dict["id"],),
        )
        permissions = [SkillPermission(r[0]) for r in await cur.fetchall() if r[0] in SkillPermission._value2member_map_]
        return SkillDefinition(
            id=row_dict["id"],
            domain=row_dict["domain"],
            name=row_dict["name"],
            description=row_dict["description"],
            version=row_dict["version"],
            risk_level=row_dict["risk_level"],
            requires_approval=bool(row_dict["requires_approval"]),
            reversible=bool(row_dict["reversible"]),
            idempotent=bool(row_dict["idempotent"]),
            timeout_sec=row_dict["timeout_sec"],
            retry_limit=row_dict["retry_limit"],
            enabled=bool(row_dict["enabled"]),
            handler=row_dict["handler"],
            tags=json.loads(row_dict["tags"]) if row_dict["tags"] else [],
            metadata=json.loads(row_dict["metadata_json"]) if row_dict["metadata_json"] else {},
            inputs=inputs,
            outputs=outputs,
            dependencies=deps,
            verification=verification,
            permissions=permissions,
        )

    def invalidate_cache(self) -> None:
        """Drop the in-memory cache (used after bulk imports)."""
        self._cache.clear()
        self._cache_loaded = False
