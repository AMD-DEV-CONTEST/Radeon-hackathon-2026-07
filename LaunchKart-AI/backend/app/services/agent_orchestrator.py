"""
LaunchKart AI 2.0 — Agent Orchestrator Service

Coordinates the LangGraph multi-agent pipeline.
Stub implementation for Phase 1 — full agent logic in Phase 3.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.agents import (
    AgentGraphEdge,
    AgentGraphNode,
    AgentGraphResponse,
    AgentInfo,
    AgentListResponse,
    AgentTaskListResponse,
    AgentTaskResponse,
    AgentTimelineEntry,
    AgentTimelineResponse,
)
from app.infrastructure.database.models.agent_task_model import AgentTaskModel

logger = structlog.get_logger(__name__)

from typing import TypedDict

class AgentDef(TypedDict):
    name: str
    description: str
    phase: int
    deps: list[str]

# Agent definitions with metadata
AGENT_DEFINITIONS: list[AgentDef] = [
    {"name": "planner", "description": "Creates execution plan from product image", "phase": 0, "deps": []},
    {"name": "coordinator", "description": "Distributes tasks to worker agents", "phase": 0, "deps": ["planner"]},
    {"name": "vision", "description": "Analyzes product image using vision model", "phase": 1, "deps": ["coordinator"]},
    {"name": "product_analysis", "description": "Extracts detailed product features", "phase": 1, "deps": ["coordinator"]},
    {"name": "research", "description": "Researches market and product category", "phase": 2, "deps": ["vision", "product_analysis"]},
    {"name": "competitor", "description": "Analyzes competitor products and pricing", "phase": 2, "deps": ["vision", "product_analysis"]},
    {"name": "pricing", "description": "Recommends optimal pricing strategy", "phase": 3, "deps": ["research", "competitor"]},
    {"name": "seo", "description": "Generates SEO keywords and metadata", "phase": 3, "deps": ["research", "competitor"]},
    {"name": "branding", "description": "Creates brand voice and identity", "phase": 3, "deps": ["research"]},
    {"name": "listing", "description": "Generates marketplace product listings", "phase": 4, "deps": ["pricing", "seo", "branding"]},
    {"name": "marketing", "description": "Creates marketing campaigns and content", "phase": 4, "deps": ["pricing", "seo", "branding"]},
    {"name": "qa", "description": "Validates all outputs for quality", "phase": 5, "deps": ["listing", "marketing"]},
    {"name": "marketplace", "description": "Formats and exports for each marketplace", "phase": 5, "deps": ["listing", "qa"]},
    {"name": "memory_agent", "description": "Stores results in persistent memory", "phase": 6, "deps": ["qa", "marketplace"]},
    {"name": "analytics_agent", "description": "Records metrics and performance data", "phase": 6, "deps": ["qa", "marketplace"]},
]


from langgraph.graph import StateGraph, START, END
from app.domain.agent_state import LaunchState
from app.services.agents import core_agents

class AgentOrchestrator:
    """Manages agent execution pipeline and provides monitoring data."""
    
    def build_graph(self):
        """Compile the LangGraph for product launch."""
        workflow = StateGraph(LaunchState)  # type: ignore
        
        # Add nodes
        workflow.add_node("planner", core_agents.planner_agent)
        workflow.add_node("coordinator", core_agents.coordinator_agent)
        workflow.add_node("vision", core_agents.vision_agent)
        workflow.add_node("product_analysis", core_agents.product_analysis_agent)
        workflow.add_node("research", core_agents.research_agent)
        workflow.add_node("competitor", core_agents.competitor_agent)
        workflow.add_node("pricing", core_agents.pricing_agent)
        workflow.add_node("seo", core_agents.seo_agent)
        workflow.add_node("branding", core_agents.branding_agent)
        workflow.add_node("listing", core_agents.listing_agent)
        workflow.add_node("marketing", core_agents.marketing_agent)
        workflow.add_node("qa", core_agents.qa_agent)
        workflow.add_node("marketplace", core_agents.marketplace_agent)
        workflow.add_node("memory_agent", core_agents.memory_agent)
        workflow.add_node("analytics_agent", core_agents.analytics_agent)
        
        # Add edges (Dependencies)
        workflow.add_edge(START, "planner")
        workflow.add_edge("planner", "coordinator")
        
        # Parallel Phase 1
        workflow.add_edge("coordinator", "vision")
        workflow.add_edge("coordinator", "product_analysis")
        
        # Parallel Phase 2
        workflow.add_edge("vision", "research")
        workflow.add_edge("product_analysis", "research")
        workflow.add_edge("vision", "competitor")
        workflow.add_edge("product_analysis", "competitor")
        
        # Parallel Phase 3
        workflow.add_edge("research", "pricing")
        workflow.add_edge("competitor", "pricing")
        workflow.add_edge("research", "seo")
        workflow.add_edge("competitor", "seo")
        workflow.add_edge("research", "branding")
        
        # Parallel Phase 4
        workflow.add_edge("pricing", "listing")
        workflow.add_edge("seo", "listing")
        workflow.add_edge("branding", "listing")
        
        workflow.add_edge("pricing", "marketing")
        workflow.add_edge("seo", "marketing")
        workflow.add_edge("branding", "marketing")
        
        # Phase 5 Review
        workflow.add_edge("listing", "qa")
        workflow.add_edge("marketing", "qa")
        
        workflow.add_edge("qa", "marketplace")
        
        # Phase 6 Persist
        workflow.add_edge("marketplace", "memory_agent")
        workflow.add_edge("marketplace", "analytics_agent")
        
        workflow.add_edge("memory_agent", END)
        workflow.add_edge("analytics_agent", END)
        
        return workflow.compile()

    async def run_pipeline(self, initial_state: dict):
        """Execute the LangGraph pipeline asynchronously."""
        graph = self.build_graph()
        try:
            final_state = await graph.ainvoke(initial_state)
            return final_state
        except Exception as e:
            logger.error("Pipeline failed", error=str(e), launch_id=initial_state.get("launch_id"))
            return None

    def get_agent_info(self) -> AgentListResponse:
        """Get the list of all agents with their metadata."""
        agents = [
            AgentInfo(
                name=a["name"],
                description=a["description"],
                status="idle",
                phase=a["phase"],
                dependencies=a["deps"],
            )
            for a in AGENT_DEFINITIONS
        ]
        return AgentListResponse(agents=agents)

    async def get_launch_tasks(
        self, launch_id: UUID, db: AsyncSession
    ) -> AgentTaskListResponse:
        """Get all agent tasks for a specific launch."""
        result = await db.execute(
            select(AgentTaskModel)
            .where(AgentTaskModel.launch_id == launch_id)
            .order_by(AgentTaskModel.created_at)
        )
        tasks = result.scalars().all()
        return AgentTaskListResponse(
            tasks=[AgentTaskResponse.model_validate(t) for t in tasks],
            total=len(tasks),
        )

    async def get_agent_graph(
        self, launch_id: UUID, db: AsyncSession
    ) -> AgentGraphResponse:
        """Generate React Flow graph data for agent visualization."""
        # Fetch task statuses for this launch
        result = await db.execute(
            select(AgentTaskModel).where(AgentTaskModel.launch_id == launch_id)
        )
        tasks = {t.agent_name: t.status for t in result.scalars().all()}

        # Build nodes with positions arranged in phases
        nodes: list[AgentGraphNode] = []
        phase_x_positions = {0: 50, 1: 300, 2: 550, 3: 800, 4: 1050, 5: 1300, 6: 1550}

        phase_agent_counts: dict[int, int] = {}
        for agent_def in AGENT_DEFINITIONS:
            phase = agent_def["phase"]
            phase_agent_counts[phase] = phase_agent_counts.get(phase, 0) + 1

        phase_current_index: dict[int, int] = {}
        for agent_def in AGENT_DEFINITIONS:
            phase = agent_def["phase"]
            idx = phase_current_index.get(phase, 0)
            phase_current_index[phase] = idx + 1

            total_in_phase = phase_agent_counts[phase]
            y_offset = (idx - (total_in_phase - 1) / 2) * 120

            status = tasks.get(agent_def["name"], "idle")

            nodes.append(
                AgentGraphNode(
                    id=agent_def["name"],
                    type="agentNode",
                    label=agent_def["name"].replace("_", " ").title(),
                    status=status,
                    phase=phase,
                    position={"x": phase_x_positions[phase], "y": 300 + y_offset},
                )
            )

        # Build edges from dependencies
        edges: list[AgentGraphEdge] = []
        for agent_def in AGENT_DEFINITIONS:
            for dep in agent_def["deps"]:
                source_status = tasks.get(dep, "idle")
                edges.append(
                    AgentGraphEdge(
                        id=f"{dep}-{agent_def['name']}",
                        source=dep,
                        target=agent_def["name"],
                        animated=source_status == "running",
                    )
                )

        return AgentGraphResponse(nodes=nodes, edges=edges)

    async def get_agent_timeline(
        self, launch_id: UUID, db: AsyncSession
    ) -> AgentTimelineResponse:
        """Get the execution timeline for a launch."""
        result = await db.execute(
            select(AgentTaskModel)
            .where(AgentTaskModel.launch_id == launch_id)
            .order_by(AgentTaskModel.started_at)
        )
        tasks = result.scalars().all()

        # Build timeline from task data
        agent_phases = {a["name"]: a["phase"] for a in AGENT_DEFINITIONS}

        timeline = [
            AgentTimelineEntry(
                agent_name=t.agent_name,
                status=t.status,
                started_at=t.started_at.isoformat() if t.started_at else None,
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
                duration_seconds=t.duration_seconds,
                phase=agent_phases.get(t.agent_name, 0),
            )
            for t in tasks
        ]

        return AgentTimelineResponse(timeline=timeline)
