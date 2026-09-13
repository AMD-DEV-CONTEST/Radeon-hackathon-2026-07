"""
LangGraph workflow definition (Phase 5).

Graph shape:

    planner --fan-out--> {log_analyst, metrics_analyst, deploy_correlator, runbook_retriever}
                                 (only the subset planner.investigation_plan selected)
                --fan-in--> synthesizer --> remediation (PROPOSES action only) --> END

Why LangGraph (not a hand-rolled sequence of function calls):
  - Conditional fan-out: the set of investigator nodes actually run is decided
    at runtime by the Planner's output, not hardcoded — this is genuine
    planning, not a fixed pipeline with a planning-shaped label on it.

Human-approval gate design:
  The "remediation" node only calls the LLM to PROPOSE an action (read-only,
  safe to auto-run). The graph never calls RemediationActionsTool itself.
  Actual execution is a separate, explicit step at the service layer
  (IncidentService.approve_and_execute_remediation, Phase 11) that requires
  an authenticated SRE/admin to approve first. This keeps the one
  production-touching capability outside the autonomous graph entirely,
  rather than relying on LangGraph's interrupt/checkpoint machinery (which
  requires a durable checkpointer to survive an approval that may come hours
  later — a real but separable upgrade documented in docs/ARCHITECTURE.md).
"""
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deploy_correlator import DeployCorrelatorAgent
from app.agents.log_analyst import LogAnalystAgent
from app.agents.metrics_analyst import MetricsAnalystAgent
from app.agents.planner import PlannerAgent
from app.agents.remediation import RemediationAgent
from app.agents.runbook_retriever import RunbookRetrieverAgent
from app.agents.state import IncidentInvestigationState
from app.agents.synthesizer import SynthesizerAgent

_INVESTIGATOR_AGENTS = {
    "log_analyst": LogAnalystAgent,
    "metrics_analyst": MetricsAnalystAgent,
    "deploy_correlator": DeployCorrelatorAgent,
    "runbook_retriever": RunbookRetrieverAgent,
}


def _make_node(agent_cls, db: AsyncSession):
    agent = agent_cls(db)

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        return await agent.run(state)

    return _node


def _route_after_planner(state: dict[str, Any]) -> list[str]:
    """Conditional edge: fan out only to the investigator agents the Planner
    selected. Falls back to the two cheapest/most-informative agents if the
    planner returned nothing usable, so the graph never dead-ends."""
    plan = state.get("investigation_plan") or ["log_analyst", "metrics_analyst"]
    return [name for name in plan if name in _INVESTIGATOR_AGENTS]


def build_incident_graph(db: AsyncSession) -> Any:
    graph = StateGraph(IncidentInvestigationState)

    graph.add_node("planner", _make_node(PlannerAgent, db))
    for name, cls in _INVESTIGATOR_AGENTS.items():
        graph.add_node(name, _make_node(cls, db))
    graph.add_node("synthesizer", _make_node(SynthesizerAgent, db))
    graph.add_node("remediation", _make_node(RemediationAgent, db))

    graph.set_entry_point("planner")

    # Conditional fan-out: each selected investigator node runs concurrently,
    # then all edges converge on "synthesizer" (LangGraph's implicit join).
    graph.add_conditional_edges(
        "planner",
        _route_after_planner,
        {name: name for name in _INVESTIGATOR_AGENTS},
    )
    for name in _INVESTIGATOR_AGENTS:
        graph.add_edge(name, "synthesizer")

    graph.add_edge("synthesizer", "remediation")
    graph.add_edge("remediation", END)

    # No interrupt here by design — see module docstring: "remediation" only
    # proposes an action via the LLM, it never executes one.
    return graph.compile()
