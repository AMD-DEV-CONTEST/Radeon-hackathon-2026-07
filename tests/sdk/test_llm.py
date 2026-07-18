from __future__ import annotations

import json

import httpx

from cortex.sdk.llm import vLLMClient


def _mock_transport(body_assertion):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        body_assertion(captured["body"])
        return httpx.Response(
            status_code=200,
            json={
                "id": "cmpl-1",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "FINAL: padded paddock"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    return httpx.MockTransport(handler), captured


def test_chat_posts_to_chat_completions_with_expected_body():
    received = {}

    def assert_body(body):
        received["body"] = body

    transport, captured = _mock_transport(assert_body)

    client = vLLMClient(
        base_url="http://localhost:8000/v1",
        model="meta-llama/Llama-3-8B-Instruct",
        transport=transport,
    )

    out = client.chat(
        messages=[
            {"role": "system", "content": "You are a SOC analyst."},
            {"role": "user", "content": "What is in the paddock?"},
        ]
    )

    assert out == "FINAL: padded paddock"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["content-type"] == "application/json"
    assert received["body"]["model"] == "meta-llama/Llama-3-8B-Instruct"
    assert received["body"]["temperature"] == 0.2
    assert received["body"]["max_tokens"] == 512
    assert received["body"]["messages"][0]["role"] == "system"


def test_scripted_reasoner_returns_final_after_one_tool_call():
    from cortex.sdk.llm import ScriptedReasoner

    calls = []

    def search_tool(query: str) -> str:
        calls.append(query)
        return "phishing link found"

    reasoner = ScriptedReasoner(
        steps=[
            {"tool": "cortex_search", "args": "phishing paddock"},
            {"final": "No further action needed."},
        ]
    )

    out = reasoner.step(tools={"cortex_search": {"func": search_tool}}, history=[])
    assert calls == ["phishing paddock"]
    assert "tool_result" in out and out["tool_result"] == "phishing link found"

    final = reasoner.step(tools={"cortex_search": {"func": search_tool}}, history=[out])
    assert final["final"] == "No further action needed."


def test_agent_step_dispatches_tool_then_returns_final():
    from cortex.sdk.llm import ScriptedReasoner, agent_step

    tool_invocations = []

    def fake_search(query: str) -> str:
        tool_invocations.append(query)
        return "found 2 articles"

    reasoner = ScriptedReasoner(
        steps=[
            {"tool": "cortex_search", "args": "phishing paddock"},
            {"final": "Insight: phishing campaign replay."},
        ]
    )

    tools = {
        "cortex_search": {
            "name": "cortex_search",
            "description": "Search the Cortex memory fabric.",
            "func": fake_search,
        }
    }

    answer = agent_step(
        system="You are a SOC analyst.",
        user="Investigate phishing in paddock.",
        tools=tools,
        llm=reasoner,
        max_iters=5,
    )

    assert answer == "Insight: phishing campaign replay."
    assert tool_invocations == ["phishing paddock"]
