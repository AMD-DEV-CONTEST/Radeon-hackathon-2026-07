"""Normalized visual model invocation cost."""

from __future__ import annotations

from buildguard.config import VisionRoutingConfig
from buildguard.vision.routing.schemas import RoutingModel


class CostModel:
    def __init__(self, config: VisionRoutingConfig) -> None:
        self.config = config

    def normalized_latency(self, model: RoutingModel) -> float:
        return model.estimated_latency_ms / self.config.latency_reference_ms

    def normalized_memory(self, model: RoutingModel) -> float:
        return model.estimated_memory_mb / self.config.memory_reference_mb

    def cost(self, model: RoutingModel) -> float:
        return (
            self.config.latency_weight * self.normalized_latency(model)
            + self.config.memory_weight * self.normalized_memory(model)
            + model.fixed_call_cost
        )
