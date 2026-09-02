"""Shared LangGraph workflow state definitions."""

from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    """Graph state shared across interview/report workflows.

    Designed to carry identifiers and agent outputs today, and to accept
    future LLM configuration without changing graph topology.
    """

    # Domain identifiers
    interview_id: str | None
    candidate_id: str | None
    resume_id: str | None
    user_id: str | None

    # Execution tracking
    current_node: str | None
    completed_nodes: list[str]
    agent_outputs: dict[str, dict[str, Any]]
    errors: list[str]
    metadata: dict[str, Any]

    # Future OpenAI integration hooks (unused for now)
    llm_enabled: bool
    model_name: str | None


def initial_workflow_state(
    *,
    interview_id: str | None = None,
    candidate_id: str | None = None,
    resume_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    llm_enabled: bool = False,
    model_name: str | None = None,
) -> WorkflowState:
    """Create a blank workflow state for graph invocation."""
    return WorkflowState(
        interview_id=interview_id,
        candidate_id=candidate_id,
        resume_id=resume_id,
        user_id=user_id,
        current_node=None,
        completed_nodes=[],
        agent_outputs={},
        errors=[],
        metadata=metadata or {},
        llm_enabled=llm_enabled,
        model_name=model_name,
    )
