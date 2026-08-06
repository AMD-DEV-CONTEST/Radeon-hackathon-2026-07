from __future__ import annotations

from typing import Any

from agent_factory.models.adapters.base import (
    OpenAIChatCompletionsAdapter,
    reasoning_effort,
    reasoning_enabled,
)


class DeepSeekChatAdapter(OpenAIChatCompletionsAdapter):
    def extra_body(self, settings: Any) -> dict[str, Any]:
        enabled = reasoning_enabled(settings)
        if enabled is None:
            return {}
        thinking: dict[str, Any] = {"type": "enabled" if enabled else "disabled"}
        effort = reasoning_effort(settings)
        if effort:
            thinking["reasoning_effort"] = effort
        return {"thinking": thinking}
