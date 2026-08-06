"""Persistent scheduler settings shared by every task type."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_factory.collaboration_system.capacity import normalize_max_parallel_sub_agents
from agent_factory.contracts import ConflictError
from agent_factory.sqlite_runtime import sqlite_session


class SchedulerSettingsRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def get(self) -> dict[str, int | str]:
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True, query_only=True) as conn:
            row = conn.execute(
                "select max_parallel_sub_agents,revision,updated_at from background_task_settings where singleton=1"
            ).fetchone()
            if row is None:
                raise RuntimeError("background-task settings row is missing")
            return {
                "max_parallel_sub_agents": int(row[0]),
                "revision": int(row[1]),
                "updated_at": str(row[2]),
            }

    def update_max_parallel(self, value: int, *, expected_revision: int | None = None) -> dict[str, int | str]:
        normalized = normalize_max_parallel_sub_agents(value)
        now = datetime.now(UTC).isoformat()
        clauses = ["singleton=1"]
        params: list[object] = [normalized, now]
        if expected_revision is not None:
            clauses.append("revision=?")
            params.append(int(expected_revision))
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True) as conn:
            conn.execute("begin immediate")
            cursor = conn.execute(
                "update background_task_settings set max_parallel_sub_agents=?,updated_at=?,revision=revision+1 "
                f"where {' and '.join(clauses)}",
                tuple(params),
            )
            if cursor.rowcount != 1:
                raise ConflictError("可并行子 Agent 数量设置已被其他请求修改。")
            conn.commit()
        return self.get()
