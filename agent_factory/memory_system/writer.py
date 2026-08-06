from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.store.base import BaseStore

from agent_factory.memory_system.schema import (
    MemoryContextPack,
    MemoryExtractionAction,
    MemoryExtractionDecision,
    MemoryWriteJob,
    MemoryWriteReport,
)


class MemoryWriteError(RuntimeError):
    pass


class MemoryStoreWriter:
    def __init__(self, store: BaseStore) -> None:
        self.store = store

    def apply(
        self,
        *,
        job: MemoryWriteJob,
        decision: MemoryExtractionDecision,
        related_memories: MemoryContextPack | None = None,
    ) -> MemoryWriteReport:
        started = perf_counter()
        counts = {"add": 0, "update": 0, "delete": 0, "noop": 0}
        scope_counts: dict[str, dict[str, int]] = {}
        touched_namespaces: set[tuple[str, ...]] = set()
        try:
            for action in decision.actions:
                namespace = self._apply_action(
                    job=job,
                    action=action,
                    related_memories=related_memories,
                )
                counts[action.action] = counts.get(action.action, 0) + 1
                scope_counts.setdefault(action.target_scope, {})
                scope_counts[action.target_scope][action.action] = (
                    scope_counts[action.target_scope].get(action.action, 0) + 1
                )
                if namespace:
                    touched_namespaces.add(namespace)
            status = "noop" if not decision.actions or counts.get("noop", 0) == len(decision.actions) else "completed"
            return MemoryWriteReport(
                job_id=job.job_id,
                status=status,
                namespace=job.namespace,
                namespaces=sorted(touched_namespaces),
                action_counts=counts,
                scope_action_counts=scope_counts,
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return MemoryWriteReport(
                job_id=job.job_id,
                status="failed",
                namespace=job.namespace,
                namespaces=sorted(touched_namespaces),
                action_counts=counts,
                scope_action_counts=scope_counts,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((perf_counter() - started) * 1000),
            )

    def _apply_action(
        self,
        *,
        job: MemoryWriteJob,
        action: MemoryExtractionAction,
        related_memories: MemoryContextPack | None,
    ) -> tuple[str, ...] | None:
        if action.action == "noop":
            if action.target_scope != "none":
                raise MemoryWriteError("noop action must use target_scope=none")
            return None
        if action.target_scope == "none":
            raise MemoryWriteError(f"{action.action} action requires a writable target_scope")
        namespace = self._target_namespace(
            job=job,
            action=action,
            related_memories=related_memories,
        )
        if action.action == "delete":
            if not action.merge_target_id:
                raise MemoryWriteError("delete action requires merge_target_id")
            self.store.delete(namespace, action.merge_target_id)
            return namespace
        if action.action == "update":
            if not action.merge_target_id:
                raise MemoryWriteError("update action requires merge_target_id")
            existing = self.store.get(namespace, action.merge_target_id)
            if existing is None:
                raise MemoryWriteError(f"cannot update missing memory: {action.merge_target_id}")
            value = dict(existing.value or {})
            value["content"] = action.content or str(value.get("content") or "")
            value["kind"] = action.kind or str(value.get("kind") or "fact")
            value["memory_type"] = action.memory_type or str(value.get("memory_type") or _default_memory_type(value["kind"]))
            value["metadata"] = {**dict(value.get("metadata") or {}), **_metadata(action)}
            value["scope"] = action.target_scope
            value["updated_at"] = datetime.now(UTC).isoformat()
            self.store.put(namespace, action.merge_target_id, value)
            return namespace
        if action.action == "add":
            if not action.kind:
                raise MemoryWriteError("add action requires kind")
            if not action.content.strip():
                raise MemoryWriteError("add action requires content")
            now = datetime.now(UTC).isoformat()
            memory_id = uuid4().hex
            record = {
                "memory_id": memory_id,
                "scope": action.target_scope,
                "kind": action.kind,
                "memory_type": action.memory_type or _default_memory_type(action.kind),
                "content": action.content.strip(),
                "metadata": _metadata(action),
                "source": job.source,
                "created_at": now,
                "updated_at": now,
            }
            self.store.put(namespace, memory_id, record)
            return namespace
        raise MemoryWriteError(f"unsupported memory action: {action.action}")

    def _target_namespace(
        self,
        *,
        job: MemoryWriteJob,
        action: MemoryExtractionAction,
        related_memories: MemoryContextPack | None,
    ) -> tuple[str, ...]:
        configured = job.available_namespaces.get(action.target_scope)
        if configured is None:
            raise MemoryWriteError(f"target_scope is not available for this run: {action.target_scope}")
        if action.action not in {"update", "delete"}:
            return tuple(configured)
        matches = [
            item
            for item in (related_memories.items if related_memories is not None else [])
            if item.memory_id == action.merge_target_id and item.source_scope == action.target_scope
        ]
        if len(matches) != 1:
            raise MemoryWriteError(
                f"cannot resolve a unique {action.target_scope} memory target: {action.merge_target_id}"
            )
        namespace = tuple(matches[0].namespace)
        if namespace != tuple(configured):
            raise MemoryWriteError("memory target namespace does not match the current scope context")
        return namespace


def _metadata(action: MemoryExtractionAction) -> dict[str, Any]:
    return {
        **dict(action.metadata or {}),
        "importance": action.importance,
        "confidence": action.confidence,
        "reason": action.reason,
    }


def _default_memory_type(kind: str | None) -> str:
    if kind in {"decision", "constraint", "fact", "preference", "artifact"}:
        return "semantic"
    return "episodic"
