"""Pipeline factory: builds component graph from registry pins (no auto download)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from specstyle.errors import DomainError
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry


@dataclass(frozen=True, slots=True)
class PipelineGraph:
    profile: str  # preview | production
    base: ModelDescriptor
    ip_adapter: ModelDescriptor
    controlnet: ModelDescriptor
    preview_adapter: ModelDescriptor | None
    cache_root: str  # relative logical root name only


class PipelineFactory:
    def __init__(self, registry: ModelRegistry, cache_root: Path) -> None:
        if type(registry) is not ModelRegistry:
            raise DomainError("invalid registry")
        if not isinstance(cache_root, Path):
            raise DomainError("invalid cache root")
        # Do not store absolute path into graphs — only name marker.
        self._registry = registry
        self._cache_name = cache_root.name or "model-cache"

    def build_production(
        self, base_id: str, ip_id: str, controlnet_id: str
    ) -> PipelineGraph:
        base = self._registry.require_production(base_id)
        ip = self._registry.require_production(ip_id)
        cn = self._registry.require_production(controlnet_id)
        if base.role != "base" or ip.role != "ip_adapter" or cn.role != "controlnet":
            raise DomainError("model role mismatch")
        if base.family != ip.family or base.family != cn.family:
            raise DomainError("model family mismatch")
        return PipelineGraph("production", base, ip, cn, None, self._cache_name)

    def build_preview(
        self, base_id: str, ip_id: str, controlnet_id: str, preview_id: str
    ) -> PipelineGraph:
        prod = self.build_production(base_id, ip_id, controlnet_id)
        preview = self._registry.require_production(preview_id)
        if preview.role != "preview_adapter":
            raise DomainError("model role mismatch")
        if preview.family != prod.base.family:
            raise DomainError("model family mismatch")
        return PipelineGraph(
            "preview",
            prod.base,
            prod.ip_adapter,
            prod.controlnet,
            preview,
            self._cache_name,
        )
