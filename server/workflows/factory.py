"""Workflow factory and process-wide accessors."""

from __future__ import annotations

from agents.registry import AgentRegistry, get_agent_registry
from workflows.interview_graph import InterviewGraph, build_interview_graph
from workflows.llm import LLMProvider, get_default_llm_provider
from workflows.report_graph import ReportGraph, build_report_graph


class WorkflowFactory:
    """Creates modular workflow graphs with shared dependencies."""

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        *,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.registry = registry or get_agent_registry()
        self.llm_provider = llm_provider or get_default_llm_provider()

    def create_interview_graph(self) -> InterviewGraph:
        return build_interview_graph(self.registry, llm_provider=self.llm_provider)

    def create_report_graph(self) -> ReportGraph:
        return build_report_graph(self.registry, llm_provider=self.llm_provider)


_factory: WorkflowFactory | None = None
_interview_graph: InterviewGraph | None = None
_report_graph: ReportGraph | None = None


def get_workflow_factory() -> WorkflowFactory:
    global _factory
    if _factory is None:
        _factory = WorkflowFactory()
    return _factory


def get_interview_graph() -> InterviewGraph:
    global _interview_graph
    if _interview_graph is None:
        _interview_graph = get_workflow_factory().create_interview_graph()
    return _interview_graph


def get_report_graph() -> ReportGraph:
    global _report_graph
    if _report_graph is None:
        _report_graph = get_workflow_factory().create_report_graph()
    return _report_graph


def reset_workflows() -> None:
    """Reset cached workflow instances (useful for tests)."""
    global _factory, _interview_graph, _report_graph
    _factory = None
    _interview_graph = None
    _report_graph = None
