"""
LaunchKart AI 2.0 — Shared Agent State Schema

TypedDict defining the shared state that flows through the LangGraph pipeline.
Every agent reads from and writes to this state.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import BaseMessage


class AgentStatus(TypedDict):
    """Status of an individual agent."""

    status: str  # idle | queued | running | completed | failed
    progress: float  # 0.0 to 1.0
    current_step: str
    error: str | None
    confidence: float | None
    duration_seconds: float | None
    tokens_used: int
    started_at: str | None
    completed_at: str | None


class AgentError(TypedDict):
    """Recorded agent error."""

    agent_name: str
    error: str
    retry_count: int
    timestamp: str


class GPUMetric(TypedDict):
    """GPU metric recorded during inference."""

    agent_name: str
    gpu_utilization: float
    vram_used_gb: float
    inference_latency_ms: float
    tokens_per_second: float
    timestamp: str


class LaunchState(TypedDict, total=False):
    """
    Shared state for the entire launch pipeline.

    All agents read from and write to this state.
    Using `total=False` so agents only need to set the fields they produce.
    """

    # ---- Core Identifiers ----
    launch_id: str
    product_id: str
    user_id: str

    # ---- Input ----
    image_path: str
    user_preferences: dict[str, Any]
    target_marketplaces: list[str]

    # ---- Execution Plan (from Planner) ----
    execution_plan: dict[str, Any]
    current_phase: int

    # ---- Agent Outputs (accumulated) ----
    vision_result: dict[str, Any] | None
    product_analysis: dict[str, Any] | None
    research_data: dict[str, Any] | None
    competitor_data: dict[str, Any] | None
    pricing_recommendation: dict[str, Any] | None
    seo_data: dict[str, Any] | None
    branding_data: dict[str, Any] | None
    listings: dict[str, dict[str, Any]]
    marketing_content: dict[str, Any] | None
    qa_report: dict[str, Any] | None
    marketplace_exports: dict[str, str]

    # ---- Progress Tracking ----
    agent_statuses: dict[str, AgentStatus]
    errors: list[AgentError]
    messages: list[BaseMessage]

    # ---- GPU Metrics ----
    gpu_metrics: list[GPUMetric]
    total_tokens: int
    total_inference_time: float
