from pathlib import Path

from radeon_sentinel.agent import RadeonSentinel
from radeon_sentinel.memory import CaseMemory
from radeon_sentinel.model import MockModelClient
from radeon_sentinel.retrieval import LocalRetriever
from radeon_sentinel.tools import DiagnosticEnvironment


ROOT = Path(__file__).parents[1]


def build_agent() -> RadeonSentinel:
    return RadeonSentinel(
        model=MockModelClient(),
        retriever=LocalRetriever.from_directory(
            ROOT / "demo_data/runbooks"
        ),
        memory=CaseMemory(":memory:"),
        environment=DiagnosticEnvironment.from_json(
            ROOT / "demo_data/incidents/api_latency.json"
        ),
    )


def test_vertical_slice_requires_approval_by_default() -> None:
    agent = build_agent()
    try:
        response = agent.investigate(
            "Investigate api latency and timeout errors",
            case_id="case-default-deny",
        )

        assert response.status == "needs_approval"
        assert response.evidence[0].source == "api-latency.md"
        assert [item.name for item in response.tool_results] == [
            "inspect_service_health",
            "search_logs",
            "restart_service",
        ]
        assert response.tool_results[-1].status == "approval_required"
        assert agent.environment.simulated_actions == []
        assert "resource saturation" in response.summary
        assert len(agent.memory.history("case-default-deny")) == 2
        assert {
            event["event_type"]
            for event in agent.memory.audit("case-default-deny")
        } >= {
            "retrieval_completed",
            "tool_result",
            "investigation_completed",
        }
    finally:
        agent.close()


def test_explicit_approval_only_runs_simulation() -> None:
    agent = build_agent()
    try:
        response = agent.investigate(
            "Investigate api timeout and restart if safe",
            approve_remediation=True,
        )

        assert response.status == "completed"
        assert response.tool_results[-1].status == "completed"
        assert response.tool_results[-1].output["simulated"] is True
        assert len(agent.environment.simulated_actions) == 1
    finally:
        agent.close()
