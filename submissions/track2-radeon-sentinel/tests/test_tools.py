from pathlib import Path

from radeon_sentinel.tools import DiagnosticEnvironment, ToolBroker


ROOT = Path(__file__).parents[1]


def build_broker() -> ToolBroker:
    environment = DiagnosticEnvironment.from_json(
        ROOT / "demo_data/incidents/api_latency.json"
    )
    return ToolBroker(environment)


def test_unknown_tools_are_denied() -> None:
    result = build_broker().execute("shell", {"command": "anything"})

    assert result.status == "denied"
    assert "shell" not in result.output["allowed_tools"]


def test_mutating_tool_requires_approval() -> None:
    broker = build_broker()

    denied = broker.execute("restart_service", {"service": "api"})
    approved = broker.execute(
        "restart_service", {"service": "api"}, approved=True
    )

    assert denied.status == "approval_required"
    assert broker.environment.simulated_actions == [approved.output]
    assert approved.status == "completed"
    assert approved.output["simulated"] is True
