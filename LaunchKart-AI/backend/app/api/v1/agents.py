"""
LaunchKart AI 2.0 — Agents API Routes

Endpoints for monitoring agent execution, tasks, graph visualization, and timeline.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

from app.dependencies import DbSessionDep, SellerOrAdminDep

router = APIRouter()


# ---- Response Schemas ----


class AgentInfo(BaseModel):
    name: str
    description: str
    status: str
    phase: int
    dependencies: list[str]


class AgentListResponse(BaseModel):
    agents: list[AgentInfo]


class AgentTaskResponse(BaseModel):
    id: UUID
    launch_id: UUID
    agent_name: str
    status: str
    input_data: dict | None
    output_data: dict | None
    reasoning_trace: dict | None
    error_message: str | None
    confidence_score: float | None
    retry_count: int
    duration_seconds: float | None
    tokens_used: float | None
    started_at: Any = None
    completed_at: Any = None
    created_at: Any = None

    model_config = {"from_attributes": True}


class AgentTaskListResponse(BaseModel):
    tasks: list[AgentTaskResponse]
    total: int


class AgentGraphNode(BaseModel):
    id: str
    type: str
    label: str
    status: str
    phase: int
    position: dict


class AgentGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    animated: bool
    label: str | None = None


class AgentGraphResponse(BaseModel):
    nodes: list[AgentGraphNode]
    edges: list[AgentGraphEdge]


class AgentTimelineEntry(BaseModel):
    agent_name: str
    status: str
    started_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    phase: int


class AgentTimelineResponse(BaseModel):
    timeline: list[AgentTimelineEntry]


# ---- Endpoints ----


@router.get("", response_model=AgentListResponse)
async def list_agents(_auth: SellerOrAdminDep) -> AgentListResponse:
    """List all available agents with their current status."""
    from app.services.agent_orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator()
    return orchestrator.get_agent_info()


@router.get("/{launch_id}/tasks", response_model=AgentTaskListResponse)
async def get_agent_tasks(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> AgentTaskListResponse:
    """Get all agent tasks for a specific launch."""
    from app.services.agent_orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator()
    return await orchestrator.get_launch_tasks(launch_id=launch_id, db=db)


@router.get("/{launch_id}/graph", response_model=AgentGraphResponse)
async def get_agent_graph(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> AgentGraphResponse:
    """Get the agent execution graph for React Flow visualization."""
    from app.services.agent_orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator()
    return await orchestrator.get_agent_graph(launch_id=launch_id, db=db)


@router.get("/{launch_id}/timeline", response_model=AgentTimelineResponse)
async def get_agent_timeline(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> AgentTimelineResponse:
    """Get the agent execution timeline for a launch."""
    from app.services.agent_orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator()
    return await orchestrator.get_agent_timeline(launch_id=launch_id, db=db)
