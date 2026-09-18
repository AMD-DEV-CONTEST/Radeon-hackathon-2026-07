"""Local task-history query tool."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from buildguard.tools.base import ToolDefinition
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import QueryTaskHistoryInput, QueryTaskHistoryOutput

HistoryProvider = Callable[[str | None, int], list[dict[str, Any]]]


def register_history_tools(
    registry: ToolRegistry,
    provider: HistoryProvider,
    *,
    timeout_seconds: float = 5,
) -> None:
    def query_history(raw: object) -> QueryTaskHistoryOutput:
        request = QueryTaskHistoryInput.model_validate(raw)
        return QueryTaskHistoryOutput(tasks=provider(request.session_id, request.limit))

    registry.register(
        ToolDefinition(
            name="query_task_history",
            description="Read bounded local task history without modifying memory.",
            input_schema=QueryTaskHistoryInput,
            output_schema=QueryTaskHistoryOutput,
            permission="auto",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="history",
            max_items=500,
        ),
        query_history,
    )

