"""Typed state shared by LangGraph nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict


class XiangLensState(TypedDict, total=False):
    run_id: str
    thread_id: str
    user_id: str
    message: str
    platform: str
    audience: str
    intent_keywords: list[str]
    enabled_packs: list[str]
    enable_private_lens: bool
    image_paths: list[Path]
    image_labels: dict[str, str]
    reuse_latest_analysis: bool
    cached_analysis: dict[str, Any]

    plan: list[str]
    blocked_reason: str | None
    history: list[dict[str, Any]]
    recalled_memories: list[dict[str, Any]]
    measurements: list[dict[str, Any]]
    visual_observations: list[dict[str, Any]]
    private_lens_readings: list[dict[str, Any]]
    privacy_findings: list[dict[str, Any]]
    rights_findings: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    comparison: dict[str, Any] | None
    memory_proposal_draft: dict[str, Any] | None
    structured_report: dict[str, Any]
    report_markdown: str
    tool_trace: list[dict[str, Any]]
