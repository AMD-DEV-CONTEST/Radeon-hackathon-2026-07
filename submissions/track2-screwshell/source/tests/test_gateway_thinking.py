"""Gateway thinking-schedule tests (no GPU required)."""
from __future__ import annotations

from screwshell.gateway.thinking import decide, is_agentic


def test_agentic_request_thinking_off():
    payload = {"messages": [{"role": "user", "content": "hi"}],
               "tools": [{"type": "function", "function": {"name": "x"}}]}
    d = decide(payload)
    assert d.enable_thinking is False
    assert d.reasoning_budget is None


def test_agentic_with_tool_calls_thinking_off():
    payload = {"messages": [{"role": "assistant",
                             "tool_calls": [{"function": {"name": "f"}}]}]}
    assert is_agentic(payload)
    d = decide(payload)
    assert d.enable_thinking is False


def test_client_optin_thinking_capped():
    payload = {"messages": [{"role": "user", "content": "explain"}],
               "chat_template_kwargs": {"enable_thinking": True}}
    d = decide(payload)
    assert d.enable_thinking is True
    assert d.reasoning_budget is not None
    assert d.reasoning_budget > 0          # never -1 / unlimited


def test_default_thinking_off():
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    d = decide(payload)
    assert d.enable_thinking is False
