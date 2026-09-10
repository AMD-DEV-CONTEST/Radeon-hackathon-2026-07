"""Data models shared across RadeonPilot modules."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Evidence:
    source: str
    quote: str
    score: float
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentReport:
    key: str
    role: str
    ok: bool
    text: str = ""
    duration_ms: int = 0
    parsed: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
