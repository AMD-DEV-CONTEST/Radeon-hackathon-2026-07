from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


StrategyKind = Literal[
    "context.assemble",
    "context.compress",
    "knowledge.retrieve",
    "knowledge.rank",
    "policy.evaluate",
    "tool.access",
    "tool.retry",
    "output.format",
    "custom",
]


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    kind: StrategyKind
    impl: str
    description: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
