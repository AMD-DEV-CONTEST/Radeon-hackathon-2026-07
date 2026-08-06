from __future__ import annotations

from typing import Any

from agent_factory.models.adapters.base import (
    OpenAIChatCompletionsAdapter,
    reasoning_budget_tokens,
    reasoning_enabled,
)


class QwenChatAdapter(OpenAIChatCompletionsAdapter):
    def extra_body(self, settings: Any) -> dict[str, Any]:
        enabled = reasoning_enabled(settings)
        if enabled is None:
            return {}
        body: dict[str, Any] = {"enable_thinking": bool(enabled)}
        budget = reasoning_budget_tokens(settings)
        if budget is not None:
            body["thinking_budget"] = budget
        return body
