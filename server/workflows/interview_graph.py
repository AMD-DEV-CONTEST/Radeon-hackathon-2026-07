"""InterviewGraph — full multi-agent interview pipeline topology."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.registry import AgentRegistry
from agents.types import AgentType
from workflows.base import BaseWorkflow
from workflows.llm import LLMProvider
from workflows.nodes import (
    INTERVIEW_PIPELINE,
    NODE_BEHAVIORAL,
    NODE_EVALUATION,
    NODE_FACT_CHECKER,
    NODE_HIRING,
    NODE_PLANNER,
    NODE_RESUME,
    NODE_TECHNICAL,
    make_agent_node,
)
from workflows.state import WorkflowState


class InterviewGraph(BaseWorkflow):
    """Linear interview workflow graph.

    Resume → Planner → Technical → Behavioral → Fact Checker → Evaluation → Hiring
    """

    name = "interview_graph"

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        super().__init__(registry, llm_provider=llm_provider)

    def build(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        graph = StateGraph(WorkflowState)

        node_specs: tuple[tuple[str, AgentType], ...] = (
            (NODE_RESUME, AgentType.RESUME),
            (NODE_PLANNER, AgentType.PLANNER),
            (NODE_TECHNICAL, AgentType.TECHNICAL),
            (NODE_BEHAVIORAL, AgentType.BEHAVIORAL),
            (NODE_FACT_CHECKER, AgentType.FACT_CHECKER),
            (NODE_EVALUATION, AgentType.EVALUATION),
            (NODE_HIRING, AgentType.HIRING),
        )

        for node_name, agent_type in node_specs:
            graph.add_node(
                node_name,
                make_agent_node(agent_type, self.registry, node_name=node_name),
            )

        # Topology only — no conditional routing or LLM branching yet.
        graph.add_edge(START, NODE_RESUME)
        graph.add_edge(NODE_RESUME, NODE_PLANNER)
        graph.add_edge(NODE_PLANNER, NODE_TECHNICAL)
        graph.add_edge(NODE_TECHNICAL, NODE_BEHAVIORAL)
        graph.add_edge(NODE_BEHAVIORAL, NODE_FACT_CHECKER)
        graph.add_edge(NODE_FACT_CHECKER, NODE_EVALUATION)
        graph.add_edge(NODE_EVALUATION, NODE_HIRING)
        graph.add_edge(NODE_HIRING, END)

        return graph.compile()

    @property
    def pipeline(self) -> tuple[str, ...]:
        return INTERVIEW_PIPELINE


def build_interview_graph(
    registry: AgentRegistry,
    *,
    llm_provider: LLMProvider | None = None,
) -> InterviewGraph:
    """Factory helper for InterviewGraph."""
    return InterviewGraph(registry, llm_provider=llm_provider)
