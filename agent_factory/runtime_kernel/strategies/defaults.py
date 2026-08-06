from __future__ import annotations

from agent_factory.runtime_kernel.strategies.registry import StrategyRegistry


def default_strategy_registry() -> StrategyRegistry:
    return StrategyRegistry()
