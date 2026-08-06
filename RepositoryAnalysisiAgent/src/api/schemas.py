"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="User's question about the codebase")
    session_id: str | None = Field(None, description="Session ID for conversation continuity")
    repo_path: str | None = Field(None, description="Repository path (defaults to configured root)")


class ChatEvent(BaseModel):
    type: str = Field(..., description="Event type: thinking|tool_call|tool_result|text|done|error")
    content: str = ""
    iteration: int = 0
    tool: str | None = None
    arguments: dict | None = None


class IndexRequest(BaseModel):
    repo_path: str = Field(..., description="Path to the repository to index")
    force: bool = Field(False, description="Force full re-index")


class IndexStatsSchema(BaseModel):
    files_indexed: int = 0
    files_skipped: int = 0
    chunks_created: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = Field(default_factory=list)


class IndexStatusResponse(BaseModel):
    is_indexing: bool = False
    chunk_count: int = 0
    last_stats: IndexStatsSchema | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    llm_available: bool = False
    llm_model: str = ""
    gpu_available: bool = False
    gpu_name: str = ""
    indexing: bool = False
    chunk_count: int = 0
    backend: str = ""


class WorkspaceEntry(BaseModel):
    name: str
    is_dir: bool
    size: int = 0


class WorkspaceTreeResponse(BaseModel):
    path: str
    entries: list[WorkspaceEntry] = Field(default_factory=list)


class FileContentResponse(BaseModel):
    path: str
    content: str
    lines: int = 0


class SessionInfo(BaseModel):
    session_id: str
    created_at: str
    message_count: int
    title: str = ""


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo] = Field(default_factory=list)


class SessionDetailResponse(BaseModel):
    session_id: str
    messages: list[dict] = Field(default_factory=list)
