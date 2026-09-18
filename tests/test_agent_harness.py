import json
from pathlib import Path

import httpx

from buildguard.config import load_settings
from buildguard.evaluation.agent_harness import AgentExecutionHarness
from buildguard.llm.base import ChatMessage
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.llm.openai_compatible import OpenAICompatibleLocalBackend


def _write_cases(path: Path, cases: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(case) + "\n" for case in cases),
        encoding="utf-8",
    )
    return path


def test_agent_harness_records_failures_and_resumes(
    config_tree: Path, tmp_path: Path
) -> None:
    settings = load_settings(config_tree)
    cases = _write_cases(
        tmp_path / "cases.jsonl",
        [
            {
                "case_id": "ok",
                "input": "simple local query",
                "expected_tools": ["echo"],
                "expected_outcome": "completed",
            },
            {
                "case_id": "mismatch",
                "input": "simple local query",
                "expected_tools": ["inspect_image"],
                "expected_outcome": "completed",
            },
        ],
    )
    output = tmp_path / "results.jsonl"
    harness = AgentExecutionHarness(settings, MockLLMBackend())

    first = harness.run(cases, output)
    second = harness.run(cases, output)

    assert first.executed_cases == 2
    assert first.succeeded_cases == 1
    assert first.failed_cases == 1
    assert second.executed_cases == 0
    assert second.resumed_cases == 2
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_generation_profile_controls_local_payload(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ready"}}]},
        )

    backend = OpenAICompatibleLocalBackend(
        settings.llm,
        settings.permissions,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    backend.chat(
        [ChatMessage(role="user", content="plan")],
        profile="complex_replan",
    )

    assert captured["temperature"] == 0.6
    assert captured["top_p"] == 0.95
    assert captured["max_tokens"] == 1200
    assert captured["chat_template_kwargs"] == {"enable_thinking": True}
