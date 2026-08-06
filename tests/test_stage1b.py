from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from buildguard.agent.graph import BuildGuardAgent
from buildguard.api.app import create_app
from buildguard.config import AgentConfig, load_settings
from buildguard.llm.base import ChatMessage
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.llm.openai_compatible import OpenAICompatibleLocalBackend
from buildguard.llm.structured_output import StructuredOutputError, parse_structured


def agent(
    *,
    tools: dict[str, Any] | None = None,
    max_replans: int = 1,
    confirmation_tools: list[str] | None = None,
) -> BuildGuardAgent:
    config = AgentConfig(
        max_replans=max_replans,
        registered_tools=list(tools) if tools else ["echo", "inspect_image", "search_memory"],
        confirmation_tools=confirmation_tools or [],
    )
    return BuildGuardAgent(MockLLMBackend(), config, tools)


def test_single_tool_task() -> None:
    state = agent().chat("simple local query")
    assert state["status"] == "completed"
    assert len(state["tool_results"]) == 1
    assert state["tool_results"][0].success


def test_multi_step_task_and_thinking_metrics() -> None:
    state = agent().chat("multi step inspection")
    assert state["status"] == "completed"
    assert len(state["tool_results"]) == 2
    assert any(metric.thinking_mode for metric in state["performance_trace"])


def test_illegal_tool_enters_safe_failure() -> None:
    state = agent().chat("illegal tool request")
    assert state["status"] == "safe_failure"
    assert any("not registered" in error for error in state["errors"])


def test_plan_cycle_is_rejected() -> None:
    state = agent().chat("cycle plan request")
    assert state["status"] == "safe_failure"
    assert any("DAG" in error for error in state["errors"])


class RepairSchema(BaseModel):
    name: str
    count: int


def test_json_fence_and_repair() -> None:
    repaired = parse_structured("```json\n{name: 'guard', count: 2,}\n```", RepairSchema)
    assert repaired == RepairSchema(name="guard", count=2)
    with pytest.raises(StructuredOutputError):
        parse_structured('{"name": 5}', RepairSchema)


def test_replan_once_after_recoverable_tool_failure() -> None:
    calls = 0

    def flaky(arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return {"text": arguments["text"]}

    state = agent(tools={"echo": flaky}).chat("simple query")
    assert state["status"] == "completed"
    assert state["retry_count"] == 1
    assert calls == 2


def test_retry_limit_enters_safe_failure() -> None:
    def broken(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("still broken")

    state = agent(tools={"echo": broken}, max_replans=1).chat("simple query")
    assert state["status"] == "safe_failure"
    assert state["retry_count"] == 1


def test_confirmation_wait_and_resume() -> None:
    runner = agent(confirmation_tools=["inspect_image"])
    waiting = runner.chat("confirm inspection")
    assert waiting["status"] == "WAIT_FOR_CONFIRMATION"
    assert waiting["pending_confirmation"] is not None
    completed = runner.confirm(waiting["task_id"], True)
    assert completed["status"] == "completed"


def test_multi_turn_session_reuses_memory() -> None:
    runner = agent()
    first = runner.chat("first query", session_id="session-1")
    second = runner.chat("history query", session_id="session-1")
    assert first["session_id"] == second["session_id"]
    assert len(second["memory_messages"]) == 4
    assert second["intent"] is not None
    assert second["intent"].category == "history"


def test_openai_adapter_metrics_and_local_policy(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    settings.llm.mode = "local"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1"
        payload = {
            "choices": [{"message": {"content": "ready"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenAICompatibleLocalBackend(settings.llm, settings.permissions, client)
    response = backend.chat([ChatMessage(role="user", content="hello local")])
    assert response.content == "ready"
    assert response.metrics.total_tokens == 3
    assert response.metrics.tokens_per_second > 0


def test_agent_api_routes(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    settings.app.agent.confirmation_tools = []
    application = create_app(settings, MockLLMBackend())
    assert (
        application.state.agent.tools["inspect_image"].__module__
        == "buildguard.agent.production_tools"
    )
    assert (
        application.state.agent.tools["search_memory"].__module__
        == "buildguard.agent.production_tools"
    )
    client = TestClient(application)
    health = client.get("/health")
    assert health.status_code == 200
    response = client.post("/agent/chat", json={"message": "simple query", "session_id": "api"})
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    task = client.get(f"/agent/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["status"] == "completed"
    stored = application.state.memory.get_task(task_id)
    assert stored is not None
    assert stored.result["agent_state"]["task_id"] == task_id


def test_agent_api_confirmation_resumes_the_owning_graph_task(
    config_tree: Path,
) -> None:
    settings = load_settings(config_tree)
    settings.app.agent.confirmation_tools = ["inspect_image"]
    client = TestClient(create_app(settings, MockLLMBackend()))

    waiting = client.post(
        "/agent/chat",
        json={"message": "confirm inspection", "session_id": "agent-confirm-api"},
    )

    assert waiting.status_code == 200
    assert waiting.json()["status"] == "WAIT_FOR_CONFIRMATION"
    confirmed = client.post(
        "/agent/confirm",
        json={"task_id": waiting.json()["task_id"], "approved": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["task_id"] == waiting.json()["task_id"]
    assert confirmed.json()["status"] in {"completed", "safe_failure"}
