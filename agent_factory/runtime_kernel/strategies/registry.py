from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.strategies.schema import StrategySpec


@dataclass(slots=True)
class StrategyExecutionContext:
    state: Any
    binding: dict[str, Any] | None = None
    resources: dict[str, Any] = field(default_factory=dict)


StrategyHandler = Callable[[StrategySpec, StrategyExecutionContext], Any]


class StrategyRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, StrategyHandler] = {}

    def register(self, impl: str, handler: StrategyHandler) -> None:
        if not impl:
            raise RuntimeKernelError("Strategy impl must be non-empty.")
        self._handlers[impl] = handler

    def execute(self, strategy: StrategySpec, context: StrategyExecutionContext) -> Any:
        handler = self._handlers.get(strategy.impl)
        if handler is None:
            raise RuntimeKernelError(f"Unknown strategy implementation: {strategy.impl}")
        return handler(strategy, context)


def resolve_strategy_spec(
    *,
    binding: dict[str, Any] | None,
    kind: str,
    default: StrategySpec,
    strategy_specs: dict[str, StrategySpec] | None = None,
    id_keys: tuple[str, ...] = ("strategy_id",),
) -> StrategySpec:
    binding = binding or {}
    inline = binding.get("strategy")
    if isinstance(inline, dict):
        strategy = StrategySpec.model_validate(inline)
        if strategy.kind != kind:
            raise RuntimeKernelError(f"Strategy kind mismatch: expected {kind}, got {strategy.kind}")
        return strategy

    strategy_specs = strategy_specs or {}
    for key in id_keys:
        strategy_id = binding.get(key)
        if not strategy_id:
            continue
        strategy = strategy_specs.get(str(strategy_id))
        if strategy is None:
            raise RuntimeKernelError(f"Unknown strategy id: {strategy_id}")
        if strategy.kind != kind:
            raise RuntimeKernelError(f"Strategy kind mismatch: expected {kind}, got {strategy.kind}")
        return strategy

    return default.model_copy(update={"config": {**default.config, **_config_from_binding(binding)}})


def _config_from_binding(binding: dict[str, Any]) -> dict[str, Any]:
    config = binding.get("config")
    if isinstance(config, dict):
        return dict(config)
    return {}
