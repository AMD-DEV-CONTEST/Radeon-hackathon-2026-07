from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=500_000)


class TaskRequest(BaseModel):
    task: str = Field(min_length=3, max_length=2_000)


class PlanStep(BaseModel):
    id: str
    title: str
    tool: str
    description: str
    permission: Literal["read", "transform", "write"]
    requires_approval: bool = False


class AgentPlan(BaseModel):
    id: str
    task: str
    steps: list[PlanStep]
    status: Literal["draft", "approved", "completed", "blocked"] = "draft"


class ExecuteRequest(BaseModel):
    plan_id: str
    approved_tools: list[str] = Field(default_factory=list)


class SensitiveFinding(BaseModel):
    kind: str
    value: str
    start: int
    end: int
    replacement: str


class EvidenceHit(BaseModel):
    document_id: str
    name: str
    score: float
    excerpt: str


class ExecutionResult(BaseModel):
    plan_id: str
    status: Literal["completed", "blocked"]
    summary: str
    findings: list[SensitiveFinding]
    evidence: list[EvidenceHit]
    redacted_documents: dict[str, str]
    blocked_tools: list[str] = Field(default_factory=list)

