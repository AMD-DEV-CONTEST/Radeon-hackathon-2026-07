"""Gateway Layer 3 — inference scheduling: thinking-budget policy.

The relay/coordinator already defaults ``enable_thinking=False`` for
OpenAI-standard clients (opencode / pi), because Qwen3.6 defaults thinking ON
and with the standard protocol every completion comes back as reasoning_content
with an EMPTY content and tool calls never fire.

This module makes the policy explicit and testable, and guards against the
HANDOFF §6 deadlock: a server launched with ``--reasoning-budget -1`` lets a
single "hi" think for 133s. We therefore NEVER allow an unbounded budget:
agentic (tool-calling) requests get thinking OFF (reasoning would starve the
tool-call path), and any request that opts into thinking gets a finite, capped
budget.
"""
from __future__ import annotations

from dataclasses import dataclass

# Hard ceiling on reasoning budget (tokens). Never -1 / unlimited.
MAX_REASONING_BUDGET = 4096


@dataclass
class ThinkingDecision:
    enable_thinking: bool
    reasoning_budget: int | None
    reason: str


def is_agentic(payload: dict) -> bool:
    """True when the request carries tool definitions or tool calls."""
    if payload.get("tools") or payload.get("tool_choice"):
        return True
    for m in payload.get("messages", []) or []:
        if isinstance(m, dict) and (m.get("tool_calls") or m.get("role") == "tool"):
            return True
    return False


def decide(payload: dict,
           max_budget: int = MAX_REASONING_BUDGET) -> ThinkingDecision:
    """Decide thinking policy for one request.

    Rules:
      * Agentic requests -> thinking OFF (tool calls must fire; reasoning would
        eat the budget and block them). No budget set.
      * Non-agentic + client explicitly asked for thinking -> keep it ON but
        cap the budget to ``max_budget`` (never unlimited).
      * Non-agentic + no client preference -> thinking OFF (safe default).
    """
    if is_agentic(payload):
        return ThinkingDecision(
            enable_thinking=False, reasoning_budget=None,
            reason="agentic/tool request: thinking OFF so tool calls fire")
    if payload.get("thinking") is True or \
       (payload.get("chat_template_kwargs", {}) or {}).get("enable_thinking") is True:
        return ThinkingDecision(
            enable_thinking=True, reasoning_budget=max_budget,
            reason=f"client opted in: capped budget={max_budget} (never -1)")
    return ThinkingDecision(
        enable_thinking=False, reasoning_budget=None,
        reason="default: thinking OFF for OpenAI-standard clients")
