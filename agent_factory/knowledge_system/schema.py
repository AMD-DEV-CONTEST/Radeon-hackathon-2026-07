from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SourceType = Literal[
    "filesystem",
    "codebase",
    "web_snapshot",
    "database",
    "mcp",
    "skill",
    "artifact_report",
    "manual_note",
]
MountMode = Literal["index_only", "rag"]
SourceStatus = Literal["registered", "indexing", "ready", "failed", "partial", "disabled", "removed"]
IngestionPhase = Literal["discover", "load", "normalize", "chunk", "embed", "index", "finalize"]
IngestionStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
SplitterKind = Literal["auto", "recursive", "markdown", "code", "json"]
VectorStoreBackend = Literal["sqlite", "memory", "postgres", "redis", "mongodb"]
KnowledgeAction = Literal[
    "list_sources",
    "describe_source",
    "prepare_source",
    "confirm_source",
    "list_documents",
    "search",
    "open",
    "read",
    "reindex",
    "remove_source",
]

SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class KnowledgeLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_preview_files: int = Field(default=200, ge=1, le=5000)
    max_file_bytes: int = Field(default=2_000_000, ge=1024)
    max_search_results: int = Field(default=12, ge=1, le=100)
    max_read_chars: int = Field(default=20000, ge=1000, le=200000)
    chunk_size: int = Field(default=800, ge=100, le=8000)
    chunk_overlap: int = Field(default=120, ge=0, le=2000)
    splitter_overrides: dict[str, "KnowledgeSplitterOverride"] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "KnowledgeLimits":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeSplitterOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    splitter: SplitterKind = "auto"
    chunk_size: int | None = Field(default=None, ge=100, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "KnowledgeSplitterOverride":
        if self.chunk_size is not None and self.chunk_overlap is not None and self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeSplitterRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: str
    splitter: SplitterKind
    chunk_size: int = Field(ge=100, le=8000)
    chunk_overlap: int = Field(ge=0, le=2000)
    reason: str = ""

    @field_validator("match")
    @classmethod
    def _match_not_empty(cls, value: str) -> str:
        text = str(value).strip().lower()
        if not text:
            raise ValueError("match must not be empty")
        return text

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "KnowledgeSplitterRule":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeIngestionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner: Literal["task_model", "system_default"] = "system_default"
    default_splitter: SplitterKind = "recursive"
    default_chunk_size: int = Field(default=800, ge=100, le=8000)
    default_chunk_overlap: int = Field(default=120, ge=0, le=2000)
    rules: list[KnowledgeSplitterRule] = Field(default_factory=list, max_length=32)
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "KnowledgeIngestionPlan":
        if self.default_chunk_overlap >= self.default_chunk_size:
            raise ValueError("default_chunk_overlap must be smaller than default_chunk_size")
        return self


class KnowledgeRagStoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: VectorStoreBackend = "sqlite"
    path: str = ".agent_runtime/knowledge/catalog/knowledge_store.sqlite"
    connection_uri: str | None = None
    database_name: str | None = None
    collection_name: str | None = None
    setup: bool = True
    provider_options: dict[str, Any] = Field(default_factory=dict)
    namespace_prefix: list[str] = Field(default_factory=lambda: ["knowledge"])
    index_fields: list[str] = Field(default_factory=lambda: ["content", "title", "summary"])

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

    @field_validator("namespace_prefix", "index_fields")
    @classmethod
    def _non_empty_items(cls, value: list[str]) -> list[str]:
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            raise ValueError("list must contain at least one non-empty item")
        return items

    @model_validator(mode="after")
    def _store_location_matches_backend(self) -> "KnowledgeRagStoreConfig":
        if self.backend == "sqlite" and not str(self.path or "").strip():
            raise ValueError("sqlite rag_store requires path")
        if self.backend in {"postgres", "redis", "mongodb"} and not str(self.connection_uri or "").strip():
            raise ValueError(f"{self.backend} rag_store requires connection_uri")
        return self


class KnowledgeGuidanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_sources: int = Field(default=24, ge=1, le=200)
    max_description_chars: int = Field(default=160, ge=40, le=1000)


class KnowledgeRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = ".agent_runtime/knowledge"
    catalog_path: str = ".agent_runtime/knowledge/catalog/knowledge.sqlite"
    keyword_backend: Literal["sqlite_fts5"] = "sqlite_fts5"
    default_mount_mode: MountMode = "index_only"
    rag_store: KnowledgeRagStoreConfig = Field(default_factory=KnowledgeRagStoreConfig)
    limits: KnowledgeLimits = Field(default_factory=KnowledgeLimits)
    guidance: KnowledgeGuidanceConfig = Field(default_factory=KnowledgeGuidanceConfig)

    @field_validator("root", "catalog_path")
    @classmethod
    def _path_not_empty(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("path must not be empty")
        return str(value)


class KnowledgeSourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_type: SourceType
    display_name: str
    mount_mode: MountMode = "index_only"
    uri: str
    original_uri: str | None = None
    enabled: bool = True
    status: SourceStatus = "registered"
    capabilities: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        source_id = str(value).strip()
        if not SOURCE_ID_RE.fullmatch(source_id):
            raise ValueError("source_id must be snake_case and 2-64 characters")
        return source_id

    @field_validator("display_name", "uri")
    @classmethod
    def _non_empty_string(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @field_validator("capabilities")
    @classmethod
    def _dedupe_capabilities(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            capability = str(item).strip()
            if capability and capability not in seen:
                result.append(capability)
                seen.add(capability)
        return result


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_id: str
    title: str
    uri: str
    document_type: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    source_id: str
    document_id: str
    title: str
    content: str
    content_hash: str
    chunk_index: int = Field(ge=0)
    position: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class KnowledgeIngestionJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    source_id: str
    mode: MountMode
    status: IngestionStatus = "queued"
    phase: IngestionPhase | None = None
    error: str | None = None
    report_path: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class KnowledgeSourcePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_type: SourceType
    display_name: str
    mount_mode: MountMode
    uri: str
    owner_type: str
    owner_id: str
    capabilities: list[str] = Field(default_factory=list)
    estimated_documents: int = 0
    file_type_counts: dict[str, int] = Field(default_factory=dict)
    requires_embedding: bool = False
    planned_phases: list[IngestionPhase] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSourceInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "anyOf": [
                {"required": ["uri"]},
                {"required": ["path"]},
                {"required": ["url"]},
                {"required": ["content"]},
            ]
        },
    )

    source_id: str | None = None
    source_type: SourceType = "filesystem"
    display_name: str | None = None
    mount_mode: MountMode = "index_only"
    uri: str | None = None
    path: str | None = None
    url: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ingestion_plan: KnowledgeIngestionPlan | None = None

    @model_validator(mode="after")
    def _requires_source_locator(self) -> "KnowledgeSourceInput":
        locators = (self.uri, self.path, self.url, self.content)
        if not any(str(value or "").strip() for value in locators):
            raise ValueError("knowledge source requires uri, path, url, or content")
        if self.source_type == "manual_note" and not str(self.content or self.uri or "").strip():
            raise ValueError("manual_note knowledge source requires content or uri")
        return self


class KnowledgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str
    source_id: str
    document_id: str | None = None
    chunk_id: str | None = None
    title: str
    content: str
    score: float | None = None
    uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: KnowledgeAction
    source: KnowledgeSourceInput | None = None
    source_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    query: str | None = None
    mode: Literal["auto", "keyword", "semantic", "hybrid", "readable"] = "auto"
    top_k: int = Field(default=8, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    include_content: bool = True


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
