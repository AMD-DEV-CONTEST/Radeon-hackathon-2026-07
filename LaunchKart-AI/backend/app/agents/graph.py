"""
LaunchKart AI 2.0 — LangGraph Master Graph

Defines the multi-agent execution graph using LangGraph.
Implements the hierarchical supervisor pattern with parallel execution phases.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from app.agents.state import LaunchState

logger = structlog.get_logger(__name__)


def create_agent_graph() -> StateGraph:
    """
    Build the LangGraph state graph for the multi-agent pipeline.

    Architecture:
    - Phase 0: Planner → Coordinator (sequential)
    - Phase 1: Vision + Product Analysis (parallel)
    - Phase 2: Research + Competitor (parallel)
    - Phase 3: Pricing + SEO + Branding (parallel)
    - Phase 4: Listing + Marketing (parallel)
    - Phase 5: QA + Marketplace (parallel)
    - Phase 6: Memory + Analytics (parallel)
    """

    graph = StateGraph(LaunchState)

    # ---- Register all agent nodes ----
    graph.add_node("planner", planner_node)
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("phase_1_vision", phase_1_vision_node)
    graph.add_node("phase_2_research", phase_2_research_node)
    graph.add_node("phase_3_strategy", phase_3_strategy_node)
    graph.add_node("phase_4_content", phase_4_content_node)
    graph.add_node("phase_5_quality", phase_5_quality_node)
    graph.add_node("phase_6_finalize", phase_6_finalize_node)

    # ---- Define edges (execution flow) ----
    graph.set_entry_point("planner")
    graph.add_edge("planner", "coordinator")
    graph.add_edge("coordinator", "phase_1_vision")
    graph.add_edge("phase_1_vision", "phase_2_research")
    graph.add_edge("phase_2_research", "phase_3_strategy")
    graph.add_edge("phase_3_strategy", "phase_4_content")
    graph.add_edge("phase_4_content", "phase_5_quality")
    graph.add_edge("phase_5_quality", "phase_6_finalize")
    graph.add_edge("phase_6_finalize", END)

    return graph


async def planner_node(state: LaunchState) -> LaunchState:
    """Planner Agent — Creates execution plan from product image."""
    from app.agents.planner.agent import PlannerAgent

    agent = PlannerAgent()
    return await agent.run(state)


async def coordinator_node(state: LaunchState) -> LaunchState:
    """Coordinator Agent — Validates plan and prepares for execution."""
    from app.agents.coordinator.agent import CoordinatorAgent

    agent = CoordinatorAgent()
    return await agent.run(state)


async def phase_1_vision_node(state: LaunchState) -> LaunchState:
    """Phase 1 — Vision + Product Analysis in parallel."""
    from app.agents.product_analysis.agent import ProductAnalysisAgent
    from app.agents.vision.agent import VisionAgent

    state["current_phase"] = 1

    vision_agent = VisionAgent()
    analysis_agent = ProductAnalysisAgent()

    # Run both agents in parallel
    results = await asyncio.gather(
        vision_agent.run(state),
        analysis_agent.run(state),
        return_exceptions=True,
    )

    # Merge results
    for result in results:
        if isinstance(result, dict):
            state.update(result)
        elif isinstance(result, Exception):
            logger.error("Phase 1 agent failed", error=str(result))

    return state


async def phase_2_research_node(state: LaunchState) -> LaunchState:
    """Phase 2 — Research + Competitor Analysis in parallel."""
    from app.agents.competitor.agent import CompetitorAgent
    from app.agents.research.agent import ResearchAgent

    state["current_phase"] = 2

    research_agent = ResearchAgent()
    competitor_agent = CompetitorAgent()

    results = await asyncio.gather(
        research_agent.run(state),
        competitor_agent.run(state),
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, dict):
            state.update(result)
        elif isinstance(result, Exception):
            logger.error("Phase 2 agent failed", error=str(result))

    return state


async def phase_3_strategy_node(state: LaunchState) -> LaunchState:
    """Phase 3 — Pricing + SEO + Branding in parallel."""
    from app.agents.branding.agent import BrandingAgent
    from app.agents.pricing.agent import PricingAgent
    from app.agents.seo.agent import SEOAgent

    state["current_phase"] = 3

    pricing_agent = PricingAgent()
    seo_agent = SEOAgent()
    branding_agent = BrandingAgent()

    results = await asyncio.gather(
        pricing_agent.run(state),
        seo_agent.run(state),
        branding_agent.run(state),
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, dict):
            state.update(result)
        elif isinstance(result, Exception):
            logger.error("Phase 3 agent failed", error=str(result))

    return state


async def phase_4_content_node(state: LaunchState) -> LaunchState:
    """Phase 4 — Listing Generation + Marketing in parallel."""
    from app.agents.listing.agent import ListingAgent
    from app.agents.marketing.agent import MarketingAgent

    state["current_phase"] = 4

    listing_agent = ListingAgent()
    marketing_agent = MarketingAgent()

    results = await asyncio.gather(
        listing_agent.run(state),
        marketing_agent.run(state),
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, dict):
            state.update(result)
        elif isinstance(result, Exception):
            logger.error("Phase 4 agent failed", error=str(result))

    return state


async def phase_5_quality_node(state: LaunchState) -> LaunchState:
    """Phase 5 — QA + Marketplace Export in parallel."""
    from app.agents.marketplace.agent import MarketplaceExportAgent
    from app.agents.qa.agent import QAAgent

    state["current_phase"] = 5

    qa_agent = QAAgent()
    marketplace_agent = MarketplaceExportAgent()

    # QA runs first, then marketplace uses QA results
    state = await qa_agent.run(state)
    state = await marketplace_agent.run(state)

    return state


async def phase_6_finalize_node(state: LaunchState) -> LaunchState:
    """Phase 6 — Memory + Analytics in parallel."""
    from app.agents.analytics.agent import AnalyticsRecorderAgent
    from app.agents.memory.agent import MemoryRecorderAgent

    state["current_phase"] = 6

    memory_agent = MemoryRecorderAgent()
    analytics_agent = AnalyticsRecorderAgent()

    results = await asyncio.gather(
        memory_agent.run(state),
        analytics_agent.run(state),
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, dict):
            state.update(result)
        elif isinstance(result, Exception):
            logger.error("Phase 6 agent failed", error=str(result))

    return state


def compile_graph() -> Any:
    """Compile the LangGraph for execution."""
    graph = create_agent_graph()
    return graph.compile()
