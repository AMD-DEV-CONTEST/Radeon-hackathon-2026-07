"""Pydantic schemas for the Live-Science web API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

EngineName = Literal["auto", "deterministic", "generative"]


class JobCreate(BaseModel):
    text: str = Field(min_length=1, description="User content / request text")
    engine: EngineName = "auto"
    style: dict[str, Any] = Field(default_factory=dict)


class JobOut(BaseModel):
    id: str
    engine: str
    status: str
    progress: float
    message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    text: Optional[str] = None
    # bridge manifest (route / key moments) when produced by Phase 1
    manifest: Optional[dict[str, Any]] = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: Optional[dict[str, Any]] = None


class JobListResponse(BaseModel):
    jobs: list[JobOut]
    total: int


class EngineHealth(BaseModel):
    available: bool
    detail: str


class HealthResponse(BaseModel):
    status: str
    python: str
    gpu: dict[str, Any]
    engines: dict[str, EngineHealth]
