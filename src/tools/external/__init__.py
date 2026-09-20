"""External tools package — general-quant-assistant tooling.

Layers:
  protocol.py  — unified ToolResult envelope (source/relevance/TTL/steps)
  intent.py    — three-way intent routing (strategy / compute / query)
  providers.py — market_data & announcement, mock/real dual mode
  registry.py  — auditable chain: intent → RAG → external fallback
  routes.py    — FastAPI endpoints under /api/tools/*
"""

from .protocol import ToolResult, tools_mode
from .intent import classify_intent
from .registry import handle_query

__all__ = ["ToolResult", "tools_mode", "classify_intent", "handle_query"]
