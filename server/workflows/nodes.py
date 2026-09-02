"""Modular LangGraph node builders.

Nodes delegate to independent agents and intentionally contain no LLM/prompt logic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from agents.base import BaseAgent
from agents.registry import AgentRegistry
from agents.types import AgentContext, AgentType
from workflows.state import WorkflowState

AgentNode = Callable[[WorkflowState], Awaitable[dict[str, Any]]]


def _parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def _context_from_state(state: WorkflowState) -> AgentContext:
    return AgentContext(
        interview_id=_parse_uuid(state.get("interview_id")),
        candidate_id=_parse_uuid(state.get("candidate_id")),
        resume_id=_parse_uuid(state.get("resume_id")),
        user_id=_parse_uuid(state.get("user_id")),
        payload={
            "metadata": state.get("metadata", {}),
            "agent_outputs": state.get("agent_outputs", {}),
            "llm_enabled": state.get("llm_enabled", False),
            "model_name": state.get("model_name"),
        },
    )


def make_agent_node(
    agent_type: AgentType,
    registry: AgentRegistry,
    *,
    node_name: str | None = None,
) -> AgentNode:
    """Build a LangGraph node that runs a single registered agent."""

    name = node_name or agent_type.value

    async def agent_node(state: WorkflowState) -> dict[str, Any]:
        agent: BaseAgent = registry.get(agent_type)
        context = _context_from_state(state)
        result = await agent.run(context)

        outputs = dict(state.get("agent_outputs") or {})
        outputs[agent_type.value] = {
            "success": result.success,
            "data": result.data,
            "message": result.message,
            "error": result.error,
        }

        completed = list(state.get("completed_nodes") or [])
        if name not in completed:
            completed.append(name)

        errors = list(state.get("errors") or [])
        if not result.success and result.error:
            errors.append(f"{agent_type.value}: {result.error}")

        return {
            "current_node": name,
            "completed_nodes": completed,
            "agent_outputs": outputs,
            "errors": errors,
        }

    agent_node.__name__ = f"{name}_node"
    agent_node.__qualname__ = f"{name}_node"
    return agent_node


# Stable node names used by graph wiring
NODE_RESUME = AgentType.RESUME.value
NODE_PLANNER = AgentType.PLANNER.value
NODE_TECHNICAL = AgentType.TECHNICAL.value
NODE_BEHAVIORAL = AgentType.BEHAVIORAL.value
NODE_FACT_CHECKER = AgentType.FACT_CHECKER.value
NODE_EVALUATION = AgentType.EVALUATION.value
NODE_HIRING = AgentType.HIRING.value

INTERVIEW_PIPELINE: tuple[str, ...] = (
    NODE_RESUME,
    NODE_PLANNER,
    NODE_TECHNICAL,
    NODE_BEHAVIORAL,
    NODE_FACT_CHECKER,
    NODE_EVALUATION,
    NODE_HIRING,
)

REPORT_PIPELINE: tuple[str, ...] = (
    NODE_EVALUATION,
    NODE_HIRING,
)
