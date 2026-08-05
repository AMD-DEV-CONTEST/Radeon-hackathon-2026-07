from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=8000)
    document_ids: list[str] = Field(default_factory=list)
    model: str | None = None


class TimelineEntry(BaseModel):
    agent: str
    status: str
    started_at: str
    finished_at: str
    duration_ms: int
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    document_id: str
    filename: str
    page: int | None = None
    snippet: str


class ToolExecution(BaseModel):
    name: str
    input: str
    output: str
    status: str


class PlanResult(BaseModel):
    goal: str
    tasks: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    conversation_id: str
    message_id: str
    model: str | None = None
    response: str
    planner: PlanResult
    citations: list[Citation] = Field(default_factory=list)
    tools: list[ToolExecution] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    benchmark: dict[str, Any] = Field(default_factory=dict)
    system_alert: str | None = None
    agent_status: dict[str, Any] = Field(default_factory=dict)


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    last_message_preview: str


class ConversationMessage(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    model: str | None = None
    plan: dict[str, Any] | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    benchmark: dict[str, Any] = Field(default_factory=dict)


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ConversationMessage] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    id: str
    filename: str
    mime_type: str
    page_count: int
    chunk_count: int
    created_at: str


class UploadResponse(BaseModel):
    document: DocumentRecord
    extracted_preview: str


class HealthResponse(BaseModel):
    ok: bool
    ollama_running: bool
    selected_model: str | None = None
    available_models: list[str] = Field(default_factory=list)
    database_ready: bool
    chroma_ready: bool
    message: str


class BenchmarksResponse(BaseModel):
    totals: dict[str, Any] = Field(default_factory=dict)
    recent_runs: list[dict[str, Any]] = Field(default_factory=list)
    tool_usage: list[dict[str, Any]] = Field(default_factory=list)


class SystemInfoResponse(BaseModel):
    cpu: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    gpu: list[dict[str, Any]] = Field(default_factory=list)
    platform: dict[str, Any] = Field(default_factory=dict)
    ollama: dict[str, Any] = Field(default_factory=dict)
