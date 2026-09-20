"""External tools protocol — unified return envelope for every tool call.

Design goals (from the "general quant assistant" review):
- Every external/info result is distinguishable from model-internal
  knowledge: it always carries source, retrieval time, data mode, TTL,
  and explicit limitations.
- `confidence` is split into TWO numbers (per review):
    * source_confidence — trustworthiness of the SOURCE:
        official/exchange = 0.9, aggregator (e.g. akshare) = 0.6,
        mock/synthetic = 0.4
    * relevance_score   — how well the CONTENT matches the question
  They answer different questions and must not be collapsed into one.
- `effective_until` — TTL so stale market data is never treated as fact.
- `steps` — auditable trace of the agent's routing (intent → RAG →
  external fallback). Dify nodes render this so judges can SEE the
  autonomous planning, not just the final answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))

# Source trustworthiness, per review: official 0.9 / aggregator 0.6 / mock 0.4
SOURCE_CONFIDENCE = {
    "official": 0.9,
    "aggregator": 0.6,
    "mock": 0.4,
    "rag": 0.7,
    "local": 1.0,
}


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def ttl_iso(minutes: float = 5) -> str:
    """Expiry timestamp for a snapshot: market data ~5min, news ~24h."""
    return (datetime.now(CN_TZ) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def tools_mode() -> str:
    """Global mode: 'mock' (default, deterministic, no network) | 'real'."""
    return os.environ.get("EXTERNAL_TOOLS_MODE", "mock").strip().lower() or "mock"


@dataclass
class ToolResult:
    """Unified envelope returned by every external/local info tool."""

    success: bool
    tool: str
    source: str
    source_confidence: float
    relevance_score: float
    data_mode: str          # mock | public_snapshot | historical | synthetic | rag
    data: dict
    retrieved_at: str = field(default_factory=now_iso)
    effective_until: str = field(default_factory=lambda: ttl_iso(5))
    limitations: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    route: str = "external"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "route": self.route,
            "tool": self.tool,
            "source": self.source,
            "source_confidence": self.source_confidence,
            "relevance_score": self.relevance_score,
            "retrieved_at": self.retrieved_at,
            "effective_until": self.effective_until,
            "data_mode": self.data_mode,
            "data": self.data,
            "limitations": self.limitations,
            "steps": self.steps,
        }
