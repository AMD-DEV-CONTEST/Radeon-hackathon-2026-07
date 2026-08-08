"""Task graph - DAG executor with checkpoints.

A task is a directed acyclic graph of nodes. Each node has a type
(observe, decide, act, verify, rollback, ask_user, summarize) and
optional dependencies on other nodes. The executor walks the DAG
in topological order, runs each node, persists checkpoints, and
supports resume after interruption.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from app.db.database import db_session
from app.skills.contracts import SkillRunResult, SkillStatus
from app.skills.registry import SkillRegistry
from app.skills.verification import VerificationEngine

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    OBSERVE = "observe"
    DECIDE = "decide"
    ACT = "act"
    VERIFY = "verify"
    ROLLBACK = "rollback"
    ASK_USER = "ask_user"
    SUMMARIZE = "summarize"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskNode:
    id: str
    node_type: NodeType
    skill_id: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    attempts: int = 0
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class Task:
    id: str
    name: str
    nodes: List[TaskNode]
    status: TaskStatus = TaskStatus.PENDING
    current_node: Optional[str] = None
    checkpoint: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    command_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


NodeHandler = Callable[[TaskNode, "TaskContext"], Awaitable[Dict[str, Any]]]


@dataclass
class TaskContext:
    """Runtime context passed to node handlers."""

    task: Task
    skill_registry: SkillRegistry
    verification_engine: VerificationEngine
    extra: Dict[str, Any] = field(default_factory=dict)


class TaskGraphExecutor:
    """Walks a DAG of nodes and persists state for resume."""

    def __init__(
        self,
        skill_registry: SkillRegistry,
        verification_engine: VerificationEngine,
        node_handlers: Optional[Dict[NodeType, NodeHandler]] = None,
    ) -> None:
        self.skill_registry = skill_registry
        self.verification_engine = verification_engine
        self.node_handlers = node_handlers or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_task(
        self,
        name: str,
        nodes: List[Dict[str, Any]],
        command_id: Optional[int] = None,
    ) -> Task:
        """Create and persist a new task from a node spec list."""
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        task_nodes: List[TaskNode] = []
        for spec in nodes:
            node_id = spec.get("id") or f"node-{uuid.uuid4().hex[:8]}"
            task_nodes.append(
                TaskNode(
                    id=node_id,
                    node_type=NodeType(spec.get("node_type", "act")),
                    skill_id=spec.get("skill_id"),
                    depends_on=list(spec.get("depends_on", [])),
                    inputs=dict(spec.get("inputs", {})),
                )
            )
        task = Task(
            id=task_id,
            name=name,
            nodes=task_nodes,
            command_id=command_id,
        )
        await self._persist_task(task)
        return task

    async def run(self, task: Task, context: Optional[Dict[str, Any]] = None) -> Task:
        """Execute a task to completion (or failure)."""
        await self._load_task_state(task)
        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or time.time()
        await self._update_task_status(task)

        ctx = TaskContext(
            task=task,
            skill_registry=self.skill_registry,
            verification_engine=self.verification_engine,
            extra=context or {},
        )

        try:
            for node in self._topological_order(task.nodes):
                if task.status in (TaskStatus.CANCELLED, TaskStatus.PAUSED):
                    break
                if node.status == "success":
                    continue
                task.current_node = node.id
                await self._update_task_current(task)
                await self._run_node(node, ctx)
                await self._persist_node(node, task.id)
                await self._checkpoint(task)
                if node.status == "failed":
                    task.status = TaskStatus.FAILED
                    task.error = node.error
                    break
            else:
                task.status = TaskStatus.COMPLETED
        except asyncio.CancelledError:
            task.status = TaskStatus.PAUSED
            raise
        except Exception as exc:  # noqa: BLE001
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            logger.exception("Task %s failed", task.id)
        finally:
            task.finished_at = time.time()
            await self._update_task_status(task)
        return task

    async def cancel(self, task_id: str) -> bool:
        """Mark a task as cancelled."""
        async with db_session() as db:
            cur = await db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            row = await cur.fetchone()
            if not row:
                return False
            if row["status"] not in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value, TaskStatus.PAUSED.value):
                return False
            await db.execute(
                "UPDATE tasks SET status = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (TaskStatus.CANCELLED.value, task_id),
            )
            await db.commit()
            return True

    async def get(self, task_id: str) -> Optional[Task]:
        """Load a task from the database."""
        async with db_session() as db:
            cur = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = await cur.fetchone()
            if not row:
                return None
            cur = await db.execute(
                "SELECT * FROM task_nodes WHERE task_id = ? ORDER BY id", (task_id,)
            )
            node_rows = await cur.fetchall()
        nodes = [
            TaskNode(
                id=r["id"],
                node_type=NodeType(r["node_type"]),
                skill_id=r["skill_id"],
                depends_on=json.loads(r["depends_on"]) if r["depends_on"] else [],
                inputs=json.loads(r["input_json"]) if r["input_json"] else {},
                outputs=json.loads(r["output_json"]) if r["output_json"] else {},
                status=r["status"],
                attempts=r["attempts"],
                error=r["error"],
            )
            for r in node_rows
        ]
        return Task(
            id=row["id"],
            name=row["name"],
            nodes=nodes,
            status=TaskStatus(row["status"]),
            current_node=row["current_node"],
            checkpoint=json.loads(row["checkpoint_json"]) if row["checkpoint_json"] else {},
            error=row["error"],
            command_id=row["command_id"],
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _run_node(self, node: TaskNode, ctx: TaskContext) -> None:
        node.started_at = time.time()
        node.attempts += 1
        node.status = "running"
        handler = self.node_handlers.get(node.node_type)
        try:
            if handler is None:
                # Default: act nodes call the skill registry; others are no-ops.
                if node.node_type == NodeType.ACT and node.skill_id:
                    result = await self._default_act(node, ctx)
                    node.outputs = result.outputs
                    node.status = "success" if result.status == SkillStatus.SUCCESS else "failed"
                    node.error = result.error
                else:
                    node.status = "success"
            else:
                outputs = await handler(node, ctx)
                node.outputs = outputs or {}
                node.status = "success"
        except Exception as exc:  # noqa: BLE001
            node.status = "failed"
            node.error = str(exc)
            logger.exception("Node %s failed", node.id)
        finally:
            node.finished_at = time.time()

    async def _default_act(self, node: TaskNode, ctx: TaskContext) -> SkillRunResult:
        """Default act handler: invoke the skill via the registry."""
        from app.skills.runtime import SkillRuntime

        runtime: SkillRuntime = ctx.extra.get("skill_runtime")  # type: ignore[assignment]
        if runtime is None:
            return SkillRunResult(
                skill_id=node.skill_id or "",
                status=SkillStatus.FAILED,
                error="no skill_runtime in context",
            )
        return await runtime.execute(
            node.skill_id or "",
            node.inputs,
            task_id=ctx.task.id,
            node_id=node.id,
        )

    def _topological_order(self, nodes: List[TaskNode]) -> List[TaskNode]:
        by_id = {n.id: n for n in nodes}
        visited: Set[str] = set()
        order: List[TaskNode] = []

        def visit(n: TaskNode) -> None:
            if n.id in visited:
                return
            visited.add(n.id)
            for dep in n.depends_on:
                if dep in by_id:
                    visit(by_id[dep])
            order.append(n)

        for n in nodes:
            visit(n)
        return order

    async def _persist_task(self, task: Task) -> None:
        async with db_session() as db:
            await db.execute(
                """
                INSERT INTO tasks (id, command_id, name, status, plan_json, current_node)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.command_id,
                    task.name,
                    task.status.value,
                    json.dumps([n.__dict__ for n in task.nodes], default=str),
                    task.current_node,
                ),
            )
            for n in task.nodes:
                await db.execute(
                    """
                    INSERT INTO task_nodes (
                        id, task_id, node_type, skill_id, depends_on, input_json, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        n.id,
                        task.id,
                        n.node_type.value,
                        n.skill_id,
                        json.dumps(n.depends_on),
                        json.dumps(n.inputs, default=str),
                        n.status,
                    ),
                )
            await db.commit()

    async def _persist_node(self, node: TaskNode, task_id: str) -> None:
        async with db_session() as db:
            await db.execute(
                """
                UPDATE task_nodes SET
                    status = ?, output_json = ?, attempts = ?, error = ?,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ? AND task_id = ?
                """,
                (
                    node.status,
                    json.dumps(node.outputs, default=str),
                    node.attempts,
                    node.error,
                    node.id,
                    task_id,
                ),
            )
            await db.commit()

    async def _update_task_status(self, task: Task) -> None:
        async with db_session() as db:
            await db.execute(
                """
                UPDATE tasks SET
                    status = ?, current_node = ?, error = ?,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    finished_at = CASE WHEN ? IN ('completed','failed','cancelled')
                                      THEN CURRENT_TIMESTAMP ELSE finished_at END
                WHERE id = ?
                """,
                (
                    task.status.value,
                    task.current_node,
                    task.error,
                    task.status.value,
                    task.id,
                ),
            )
            await db.commit()

    async def _update_task_current(self, task: Task) -> None:
        async with db_session() as db:
            await db.execute(
                "UPDATE tasks SET current_node = ? WHERE id = ?",
                (task.current_node, task.id),
            )
            await db.commit()

    async def _checkpoint(self, task: Task) -> None:
        task.checkpoint = {
            "current_node": task.current_node,
            "node_statuses": {n.id: n.status for n in task.nodes},
            "ts": time.time(),
        }
        async with db_session() as db:
            await db.execute(
                "UPDATE tasks SET checkpoint_json = ? WHERE id = ?",
                (json.dumps(task.checkpoint, default=str), task.id),
            )
            await db.commit()

    async def _load_task_state(self, task: Task) -> None:
        """Reload node statuses from DB so resume works."""
        async with db_session() as db:
            cur = await db.execute(
                "SELECT id, status FROM task_nodes WHERE task_id = ?", (task.id,)
            )
            rows = await cur.fetchall()
        statuses = {r["id"]: r["status"] for r in rows}
        for n in task.nodes:
            if n.id in statuses:
                n.status = statuses[n.id]
