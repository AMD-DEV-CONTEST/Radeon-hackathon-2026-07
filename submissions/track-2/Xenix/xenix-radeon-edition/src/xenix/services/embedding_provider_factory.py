"""Explicit process-local construction registry for Embedding operations.

Provider catalogs and active selections belong to ``embedding_settings``.  This
module only maps one already-selected target to a short-lived operation scope;
it has no persistence, selection, endpoint, or manager-lifecycle authority.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Protocol

from ..exceptions import ValidationError
from .embedding_settings import (
    EmbeddingProviderProjection,
    ManagedEmbeddingProviderRef,
    StaticEmbeddingTarget,
)


class EmbeddingProviderImplementationUnavailableError(ValidationError):
    """A durable managed reference has no composed implementation in this build."""

    def __init__(self) -> None:
        super().__init__(
            "The required Embedding provider implementation is unavailable in this build.",
            error_code="provider_implementation_unavailable",
        )


class EmbeddingBatchProvider(Protocol):
    """One protocol/client binding that can embed one already-prepared batch."""

    def embed_batch(
        self,
        texts: Sequence[str],
        *,
        expected_dimensions: int | None,
    ) -> list[tuple[float, ...]]: ...


class EmbeddingOperationScope:
    """One whole semantic Embedding operation over one concrete binding.

    Managed adapters wrap this scope to acquire/release an exact generation
    permit.  The generic service enters it once around all request batches, so a
    failure in a later batch cannot switch model generations or leak a permit.
    """

    def __init__(self, provider: EmbeddingBatchProvider) -> None:
        self._provider = provider
        self._closed = False
        self._dispatch_may_have_happened = False

    @property
    def provider(self) -> EmbeddingBatchProvider:
        return self._provider

    @property
    def dispatch_may_have_happened(self) -> bool:
        return self._dispatch_may_have_happened

    def mark_dispatch_may_have_happened(self) -> None:
        self._dispatch_may_have_happened = True

    mark_dispatch_possible = mark_dispatch_may_have_happened

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> EmbeddingOperationScope:
        if self._closed:
            raise RuntimeError("Embedding operation scope is already closed.")
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


class EmbeddingProviderFactory(Protocol):
    def provider_scope(
        self,
        projection: EmbeddingProviderProjection,
    ) -> EmbeddingOperationScope: ...


class ManagedEmbeddingProviderFactory(EmbeddingProviderFactory, Protocol):
    """Marker protocol for an explicit optional-manager composition contribution."""


class EmbeddingProviderFactoryRegistry:
    """App-scoped registry that owns construction only, never provider catalog state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._static_factory: EmbeddingProviderFactory | None = None
        self._managed_factories: dict[str, ManagedEmbeddingProviderFactory] = {}

    def register_static_factory(self, factory: EmbeddingProviderFactory) -> None:
        if factory is None:
            raise TypeError("Embedding static provider factory cannot be None.")
        with self._lock:
            if self._static_factory is not None:
                raise ValueError("An Embedding static provider factory is already registered.")
            self._static_factory = factory

    def register_managed_factory(
        self,
        manager_id: str,
        factory: ManagedEmbeddingProviderFactory,
    ) -> None:
        normalized = manager_id.strip()
        if not normalized:
            raise ValueError("Managed Embedding provider manager ID cannot be blank.")
        if factory is None:
            raise TypeError("Managed Embedding provider factory cannot be None.")
        with self._lock:
            if normalized in self._managed_factories:
                raise ValueError("An Embedding managed provider factory is already registered.")
            self._managed_factories[normalized] = factory

    register_managed_provider_factory = register_managed_factory

    @property
    def registered_manager_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._managed_factories)

    def require_implementation(self, projection: EmbeddingProviderProjection) -> None:
        """Fail before dispatch if the configured target has no composed factory."""

        target = projection.target
        with self._lock:
            available = (
                self._static_factory is not None
                if isinstance(target, StaticEmbeddingTarget)
                else self._managed_factories.get(target.manager_id) is not None
            )
        if not available:
            raise EmbeddingProviderImplementationUnavailableError()

    def provider_scope(self, projection: EmbeddingProviderProjection) -> EmbeddingOperationScope:
        target = projection.target
        if isinstance(target, StaticEmbeddingTarget):
            with self._lock:
                factory = self._static_factory
        elif isinstance(target, ManagedEmbeddingProviderRef):
            with self._lock:
                factory = self._managed_factories.get(target.manager_id)
        else:
            raise TypeError("Embedding provider target is unsupported.")
        if factory is None:
            raise EmbeddingProviderImplementationUnavailableError()
        return factory.provider_scope(projection)


__all__ = [
    "EmbeddingBatchProvider",
    "EmbeddingOperationScope",
    "EmbeddingProviderFactory",
    "EmbeddingProviderFactoryRegistry",
    "EmbeddingProviderImplementationUnavailableError",
    "ManagedEmbeddingProviderFactory",
]
