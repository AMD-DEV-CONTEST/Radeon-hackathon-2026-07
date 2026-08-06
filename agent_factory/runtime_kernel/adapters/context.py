from __future__ import annotations

from typing import Any, Protocol


class ContextEngineAdapter(Protocol):
    def build_model_context(
        self,
        *,
        state: Any,
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def build_tool_context(
        self,
        *,
        state: Any,
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...
