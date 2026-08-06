from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeImplementation


class NodeProvider(Protocol):
    provider_id: str

    def implementations(self) -> list[NodeImplementation]:
        ...


class NodeProviderFactory(Protocol):
    provider_id: str

    def build(self, *, package_root: Path, config: dict[str, Any]) -> NodeProvider:
        ...


@dataclass(frozen=True, slots=True)
class StaticNodeProvider:
    provider_id: str
    nodes: tuple[NodeImplementation, ...]

    def implementations(self) -> list[NodeImplementation]:
        return list(self.nodes)


class NodeProviderRegistry:
    def __init__(
        self,
        providers: list[NodeProvider] | tuple[NodeProvider, ...] | None = None,
        provider_factories: list[NodeProviderFactory] | tuple[NodeProviderFactory, ...] | None = None,
    ) -> None:
        self._providers: dict[str, NodeProvider] = {}
        self._factories: dict[str, NodeProviderFactory] = {}
        for provider in providers or ():
            self.register(provider)
        for factory in provider_factories or ():
            self.register_factory(factory)

    def register(self, provider: NodeProvider) -> None:
        provider_id = str(provider.provider_id).strip()
        if not provider_id:
            raise RuntimeKernelError("node provider id must not be empty")
        if provider_id in self._providers or provider_id in self._factories:
            raise RuntimeKernelError(f"duplicate node provider id: {provider_id}")
        self._providers[provider_id] = provider

    def register_factory(self, factory: NodeProviderFactory) -> None:
        provider_id = str(factory.provider_id).strip()
        if not provider_id:
            raise RuntimeKernelError("node provider factory id must not be empty")
        if provider_id in self._factories or provider_id in self._providers:
            raise RuntimeKernelError(f"duplicate node provider factory id: {provider_id}")
        self._factories[provider_id] = factory

    def has_factory(self, provider_id: str) -> bool:
        return provider_id in self._factories

    def get(self, provider_id: str) -> NodeProvider:
        if provider_id not in self._providers:
            raise RuntimeKernelError(f"unknown node provider id: {provider_id}")
        return self._providers[provider_id]

    def resolve_references(
        self,
        provider_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        package_root: Path,
    ) -> list[NodeProvider]:
        providers: list[NodeProvider] = []
        for provider_ref in provider_refs:
            provider_id = str(provider_ref.get("provider_id") or "").strip()
            if not provider_id:
                raise RuntimeKernelError("node provider reference must include provider_id")
            config = provider_ref.get("config") or {}
            if not isinstance(config, dict):
                raise RuntimeKernelError(f"node provider config must be an object: {provider_id}")
            if provider_id in self._factories:
                providers.append(self._factories[provider_id].build(package_root=package_root, config=config))
                continue
            providers.append(self.get(provider_id))
        return providers

    def list_provider_ids(self) -> list[str]:
        return sorted({*self._providers, *self._factories})
