"""ReportGraph — report-generation workflow topology."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.registry import AgentRegistry
from agents.types import AgentType
from workflows.base import BaseWorkflow
from workflows.llm import LLMProvider
from workflows.nodes import (
    NODE_EVALUATION,
    NODE_HIRING,
    REPORT_PIPELINE,
    make_agent_node,
)
from workflows.state import WorkflowState


class ReportGraph(BaseWorkflow):
    """Report workflow graph focused on evaluation and hiring outputs.

    Evaluation → Hiring

    Prepared so future OpenAI-backed summarization can plug into these nodes
    without changing the graph contract.
    """

    name = "report_graph"

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        super().__init__(registry, llm_provider=llm_provider)

    def build(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        graph = StateGraph(WorkflowState)

        graph.add_node(
            NODE_EVALUATION,
            make_agent_node(
                AgentType.EVALUATION,
                self.registry,
                node_name=NODE_EVALUATION,
            ),
        )
        graph.add_node(
            NODE_HIRING,
            make_agent_node(
                AgentType.HIRING,
                self.registry,
                node_name=NODE_HIRING,
            ),
        )

        graph.add_edge(START, NODE_EVALUATION)
        graph.add_edge(NODE_EVALUATION, NODE_HIRING)
        graph.add_edge(NODE_HIRING, END)

        return graph.compile()

    @property
    def pipeline(self) -> tuple[str, ...]:
        return REPORT_PIPELINE


def build_report_graph(
    registry: AgentRegistry,
    *,
    llm_provider: LLMProvider | None = None,
) -> ReportGraph:
    """Factory helper for ReportGraph."""
    return ReportGraph(registry, llm_provider=llm_provider)
