from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MemoryStoreBackend = Literal["sqlite", "memory", "postgres", "redis", "mongodb"]


class MemoryStoreRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: MemoryStoreBackend = "sqlite"
    path: str = ".agent_runtime/memory/agent.sqlite"
    connection_uri: str | None = None
    database_name: str | None = None
    collection_name: str | None = None
    setup: bool = True
    provider_options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_options")
    @classmethod
    def _provider_option_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            option_key = str(key).strip()
            if not option_key:
                raise ValueError("provider_options keys must not be empty")
            result[option_key] = item
        return result

    @model_validator(mode="after")
    def _store_location_matches_backend(self) -> "MemoryStoreRuntimeConfig":
        if self.backend in {"postgres", "redis", "mongodb"} and not str(self.connection_uri or "").strip():
            raise ValueError(f"{self.backend} memory store requires connection_uri")
        return self


class MemoryRankingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items_total: int = Field(default=8, ge=1, le=64)
    max_tokens_total: int = Field(default=1200, ge=100, le=32000)
    min_score: float = Field(default=0.55, ge=0.0, le=1.0)
    per_kind_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "constraint": 3,
            "preference": 3,
            "decision": 2,
            "fact": 2,
            "artifact": 1,
        }
    )


class MemorySemanticIndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    fields: list[str] = Field(
        default_factory=lambda: [
            "content",
            "metadata.evidence_summary",
            "metadata.keywords",
            "metadata.entities",
            "metadata.embedding_text",
        ]
    )


class MemoryBackgroundConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal_root: str = ".agent_runtime/memory/jobs"
    max_pending_jobs: int = Field(default=32, ge=1, le=256)
    concurrency: int = Field(default=1, ge=1, le=1)
    queue_full_policy: Literal["reject_new_when_full"] = "reject_new_when_full"
    write_interval_turns: int = Field(default=3, ge=1, le=1000)


class MemorySystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["memory_system.v0"] = "memory_system.v0"
    enabled: bool = True
    write_enabled: bool = True
    injection_enabled: bool = True
    store: MemoryStoreRuntimeConfig = Field(default_factory=MemoryStoreRuntimeConfig)
    ranking: MemoryRankingConfig = Field(default_factory=MemoryRankingConfig)
    semantic_index: MemorySemanticIndexConfig = Field(default_factory=MemorySemanticIndexConfig)
    background: MemoryBackgroundConfig = Field(default_factory=MemoryBackgroundConfig)


def default_agent_memory_config() -> MemorySystemConfig:
    config = MemorySystemConfig()
    from agent_factory.memory_system.scopes import application_memory_store_path

    return config.model_copy(
        update={
            "store": config.store.model_copy(
                update={"path": str(application_memory_store_path())}
            ),
            "background": config.background.model_copy(
                update={"write_interval_turns": memory_write_interval_turns_from_env()}
            ),
            "semantic_index": memory_semantic_index_config_from_env(),
        },
        deep=True,
    )


def default_factory_memory_config(project_root: str | Path = ".") -> MemorySystemConfig:
    root = Path(project_root)
    return MemorySystemConfig(
        store=MemoryStoreRuntimeConfig(
            backend="sqlite",
            path=str(root / ".agentfactory/memory/factory.sqlite"),
        ),
        background=MemoryBackgroundConfig(
            journal_root=str(root / ".agentfactory/memory/jobs"),
            write_interval_turns=memory_write_interval_turns_from_env(),
        ),
        semantic_index=memory_semantic_index_config_from_env(),
    )


def memory_write_interval_turns_from_env() -> int:
    raw = os.getenv("AGENTFACTORY_MEMORY_WRITE_INTERVAL_TURNS", "3")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 3
    return max(1, value)


def should_enqueue_memory_write(*, turn_index: int, config: MemorySystemConfig) -> bool:
    interval = max(1, int(config.background.write_interval_turns))
    if turn_index <= 0:
        return False
    return turn_index % interval == 0


def memory_semantic_index_config_from_env() -> MemorySemanticIndexConfig:
    return MemorySemanticIndexConfig(
        enabled=_env_bool("AGENTFACTORY_MEMORY_SEMANTIC_INDEX_ENABLED", default=False),
        fields=_env_csv(
            "AGENTFACTORY_MEMORY_INDEX_FIELDS",
            default=[
                "content",
                "metadata.evidence_summary",
                "metadata.keywords",
                "metadata.entities",
                "metadata.embedding_text",
            ],
        ),
    )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_csv(name: str, *, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or list(default)
