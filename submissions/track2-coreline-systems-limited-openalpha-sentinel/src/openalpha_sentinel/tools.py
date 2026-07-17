from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .database import Database
from .retrieval import HybridRetriever


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    handler: Callable[..., Any]


class ToolRegistry:
    def __init__(self, database: Database, retriever: HybridRetriever):
        self.database = database
        self.retriever = retriever
        self._tools = {
            "search_knowledge": ToolDefinition(
                "search_knowledge",
                "Hybrid keyword and vector retrieval over locally stored source chunks.",
                retriever.search,
            ),
            "list_strategy_cards": ToolDefinition(
                "list_strategy_cards",
                "List structured strategy cards and their provenance.",
                database.list_cards,
            ),
            "get_strategy_card": ToolDefinition(
                "get_strategy_card",
                "Read one strategy card and its field-level evidence.",
                database.get_card,
            ),
            "save_preference": ToolDefinition(
                "save_preference",
                "Persist an explicitly requested local research preference.",
                database.set_preference,
            ),
        }

    def call(self, name: str, **arguments: Any) -> Any:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        self.database.audit("tool_call", {"tool": name, "arguments": arguments})
        return self._tools[name].handler(**arguments)

    def descriptions(self) -> list[dict[str, str]]:
        return [{"name": item.name, "description": item.description} for item in self._tools.values()]

