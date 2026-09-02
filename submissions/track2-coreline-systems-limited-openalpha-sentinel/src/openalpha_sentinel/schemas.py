from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceDocument(BaseModel):
    path: str
    title: str
    text: str
    content_type: str = "text/markdown"
    source_url: str | None = None
    line_offset: int = Field(default=0, ge=0)


class FetchedArtifact(BaseModel):
    kind: str
    canonical_url: str
    external_id: str
    title: str
    author: str | None = None
    revision_key: str
    immutable_url: str
    license_spdx: str = "NOASSERTION"
    documents: list[SourceDocument]
    metadata: dict[str, Any] = Field(default_factory=dict)
    etag: str | None = None
    last_modified: str | None = None


class Chunk(BaseModel):
    id: str
    document_id: str
    revision_id: str
    ordinal: int
    start_line: int
    end_line: int
    text: str
    content_sha256: str


class EvidenceRef(BaseModel):
    id: str | None = None
    field: str
    chunk_id: str
    quote: str
    source_url: str
    line_start: int | None = None
    line_end: int | None = None


class StrategyCard(BaseModel):
    id: str | None = None
    source_id: str | None = None
    revision_id: str | None = None
    title: str
    summary: str
    strategy_type: str = "unknown"
    markets: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    license_spdx: str = "NOASSERTION"
    cost_disclosure: Literal["disclosed", "not_disclosed", "unknown"] = "unknown"
    risk_flags: list[str] = Field(default_factory=list)
    source_url: str
    immutable_url: str
    revision_key: str
    author: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    fingerprint: str = ""
    created_at: str | None = None


class RetrievalHit(BaseModel):
    chunk_id: str
    card_id: str | None = None
    card_title: str | None = None
    text: str
    source_url: str
    immutable_url: str
    start_line: int
    end_line: int
    lexical_score: float = 0.0
    vector_score: float = 0.0
    score: float = 0.0


class Citation(BaseModel):
    label: str
    title: str
    url: str
    quote: str
    line_start: int | None = None
    line_end: int | None = None


class AgentStep(BaseModel):
    name: str
    tool: str
    status: Literal["planned", "running", "completed", "failed"] = "planned"
    detail: str = ""


class ChatAnswer(BaseModel):
    session_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    backend: str = "heuristic"


class PipelineResult(BaseModel):
    job_id: str
    state: Literal["COMPLETED", "PARTIAL_SUCCESS", "FAILED", "SKIPPED"]
    processed: int = 0
    created_cards: int = 0
    skipped_revisions: int = 0
    errors: list[str] = Field(default_factory=list)


class DashboardStats(BaseModel):
    strategies: int = 0
    sources: int = 0
    revisions: int = 0
    active_watch_rules: int = 0
    jobs_last_24h: int = 0
    notifications: int = 0
    offline: bool = False
    llm_backend: str = "unknown"

