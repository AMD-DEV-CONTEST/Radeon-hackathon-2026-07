from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from agent_factory.file_lock import exclusive_file_lock
from agent_factory.memory_system.namespace import (
    agent_memory_namespace,
    user_memory_namespace,
    workspace_memory_namespace,
)
from agent_factory.memory_system.schema import MemoryRetrievalSource, MemoryTargetScope
from agent_factory.paths import factory_artifact_path


@dataclass(frozen=True, slots=True)
class MemoryScopeContext:
    agent_id: str
    user_id: str
    workspace_id: str | None = None

    def namespaces(self) -> dict[MemoryTargetScope, tuple[str, ...]]:
        result: dict[MemoryTargetScope, tuple[str, ...]] = {
            "agent": agent_memory_namespace(self.agent_id),
            "user": user_memory_namespace(self.user_id),
        }
        if self.workspace_id:
            result["workspace"] = workspace_memory_namespace(self.workspace_id)
        return result

    def retrieval_sources(self) -> list[MemoryRetrievalSource]:
        namespaces = self.namespaces()
        ordered_scopes: tuple[MemoryTargetScope, ...] = ("workspace", "agent", "user")
        selected = [scope for scope in ordered_scopes if scope in namespaces]
        return [
            MemoryRetrievalSource(
                scope=scope,
                namespace=namespaces[scope],
                priority=len(selected) - index,
            )
            for index, scope in enumerate(selected)
        ]


def local_memory_user_id(identity_path: Path | None = None) -> str:
    path = (identity_path or factory_artifact_path("memory", "identity.json")).expanduser().resolve()
    with exclusive_file_lock(path.with_suffix(f"{path.suffix}.lock")):
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            identifier = str(payload.get("user_id") or "").strip()
            if identifier:
                return identifier
        path.parent.mkdir(parents=True, exist_ok=True)
        identifier = uuid4().hex
        payload = {
            "version": "memory_identity.v1",
            "user_id": identifier,
            "created_at": datetime.now(UTC).isoformat(),
        }
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return identifier


def application_memory_store_path() -> Path:
    return factory_artifact_path("memory", "memory.sqlite").expanduser().resolve()


def memory_migration_log_path(runtime_root: Path) -> Path:
    return runtime_root.expanduser().resolve() / "memory" / "migrations" / "workspace_memory_v1.json"
