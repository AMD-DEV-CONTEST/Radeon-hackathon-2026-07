from __future__ import annotations

from typing import Any

from agent_factory.models.adapters.base import OpenAIChatCompletionsAdapter, reasoning_enabled


class MiMoChatAdapter(OpenAIChatCompletionsAdapter):
    def extra_body(self, settings: Any) -> dict[str, Any]:
        enabled = reasoning_enabled(settings)
        if enabled is None:
            return {}
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
