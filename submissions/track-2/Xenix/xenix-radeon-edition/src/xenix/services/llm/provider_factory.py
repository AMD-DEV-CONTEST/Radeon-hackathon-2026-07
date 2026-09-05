"""Explicit process-local construction registry for LLM provider operations.

The registry is deliberately not a provider catalog.  Durable provider instances,
their exact managed references, and selections belong to :mod:`.settings`; this
module only chooses a factory already supplied by application composition.
"""

from __future__ import annotations

import threading
from typing import Protocol

from ...exceptions import ValidationError
from .providers import AgentProvider, OpenAICompatibleChatProvider
from .settings import (
    LLMDialect,
    LLMProviderConfig,
    ManagedLlmProviderRef,
    PACKAGED_TRIAL_SECRET_SOURCE,
    StaticLlmTarget,
    load_packaged_trial_llm_config,
)


class ProviderImplementationUnavailableError(ValidationError):
    """The durable ref is valid but no composed factory can implement it."""

    def __init__(self) -> None:
        super().__init__(
            "The required LLM provider implementation is unavailable in this build.",
            error_code="provider_implementation_unavailable",
        )


class ProviderOperationScope:
    """One complete or stream semantic operation over one provider binding.

    Factories for managed providers subclass or wrap this scope to acquire an
    exact-generation permit and release it from ``close``.  The scope is held by
    the outer LLM retry loop, never re-created for an individual attempt.
    """

    def __init__(self, provider: AgentProvider) -> None:
        self._provider = provider
        self._closed = False
        self._dispatch_may_have_happened = False

    @property
    def provider(self) -> AgentProvider:
        return self._provider

    @property
    def dispatch_may_have_happened(self) -> bool:
        return self._dispatch_may_have_happened

    def mark_dispatch_may_have_happened(self) -> None:
        """Record the one-way boundary after which semantic replay is unsafe."""

        self._dispatch_may_have_happened = True

    # Adapter code commonly reads more naturally with this shorter name.
    mark_dispatch_possible = mark_dispatch_may_have_happened

    def observe_exception(self, exc: BaseException) -> None:
        if bool(getattr(exc, "dispatch_may_have_happened", False)):
            self.mark_dispatch_may_have_happened()

    def retry_allowed_after(self, exc: BaseException) -> bool:
        self.observe_exception(exc)
        return not self._dispatch_may_have_happened

    def close(self) -> None:
        """Release a factory-owned operation permit exactly once.

        The default static scope owns no resource.  A manager adapter overrides
        this method (and should keep it idempotent) to release its private permit.
        """

        self._closed = True

    def __enter__(self) -> "ProviderOperationScope":
        if self._closed:
            raise RuntimeError("LLM provider operation scope is already closed.")
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


class LLMProviderFactory(Protocol):
    """Construction port implemented by explicit static/manager factories."""

    def provider_scope(
        self,
        provider: LLMProviderConfig,
        *,
        model_key: str,
    ) -> ProviderOperationScope: ...


class ManagedLlmProviderFactory(LLMProviderFactory, Protocol):
    """Marker protocol for a manager contribution registered at composition."""


class StaticLlmProviderFactory:
    """Built-in construction for the ordinary OpenAI-compatible target."""

    def provider_scope(
        self,
        provider: LLMProviderConfig,
        *,
        model_key: str,
    ) -> ProviderOperationScope:
        target = provider.target
        if not isinstance(target, StaticLlmTarget):
            raise TypeError("Static LLM factory received a non-static provider target.")
        if target.dialect is not LLMDialect.OPENAI_COMPATIBLE:
            raise ValidationError(
                f"LLM dialect '{target.dialect.value}' is not supported yet.",
                error_code="llm_dialect_unsupported",
            )

        base_url = target.base_url
        api_key = target.api_key
        if target.dialect_config.get("secret_source") == PACKAGED_TRIAL_SECRET_SOURCE:
            trial_config = load_packaged_trial_llm_config()
            if not trial_config.enabled:
                raise ValidationError(
                    "Packaged trial LLM provider is not available in this build.",
                    error_code="llm_trial_provider_unavailable",
                )
            base_url = trial_config.base_url
            api_key = trial_config.api_key

        return ProviderOperationScope(
            OpenAICompatibleChatProvider(
                provider_key=provider.provider_id,
                base_url=base_url,
                api_key=api_key,
                model=model_key,
                timeout_seconds=target.timeout_seconds,
                streaming_enabled=target.streaming_enabled,
            )
        )


class LLMProviderFactoryRegistry:
    """An application-scoped explicit factory registry.

    There is no module-global mutable registry, import-time registration, plugin
    scan, or entry-point discovery.  Optional managers register their factory
    with the composed registry instance and cannot affect durable selection.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._static_factory: LLMProviderFactory | None = None
        self._managed_factories: dict[str, ManagedLlmProviderFactory] = {}

    def register_static_factory(self, factory: LLMProviderFactory) -> None:
        if factory is None:
            raise TypeError("LLM static provider factory cannot be None.")
        with self._lock:
            if self._static_factory is not None:
                raise ValueError("An LLM static provider factory is already registered.")
            self._static_factory = factory

    def register_managed_factory(
        self,
        manager_id: str,
        factory: ManagedLlmProviderFactory,
    ) -> None:
        normalized_manager_id = manager_id.strip()
        if not normalized_manager_id:
            raise ValueError("Managed LLM provider manager ID cannot be blank.")
        if factory is None:
            raise TypeError("Managed LLM provider factory cannot be None.")
        with self._lock:
            if normalized_manager_id in self._managed_factories:
                raise ValueError("A managed LLM provider factory is already registered for this manager.")
            self._managed_factories[normalized_manager_id] = factory

    # Composition code often uses the more explicit spelling.
    register_managed_provider_factory = register_managed_factory

    @property
    def registered_manager_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._managed_factories)

    def has_factory_for(self, provider: LLMProviderConfig) -> bool:
        """Whether composition can construct this target without acquiring it."""

        target = provider.target
        with self._lock:
            if isinstance(target, StaticLlmTarget):
                return self._static_factory is not None
            if isinstance(target, ManagedLlmProviderRef):
                return target.manager_id in self._managed_factories
        return False

    def provider_scope(
        self,
        provider: LLMProviderConfig,
        *,
        model_key: str,
    ) -> ProviderOperationScope:
        """Construct one scope for an exact configured provider/model pair."""

        target = provider.target
        if isinstance(target, StaticLlmTarget):
            with self._lock:
                factory = self._static_factory
            if factory is None:
                raise ProviderImplementationUnavailableError()
            return factory.provider_scope(provider, model_key=model_key)

        if isinstance(target, ManagedLlmProviderRef):
            with self._lock:
                factory = self._managed_factories.get(target.manager_id)
            if factory is None:
                # Preserve the durable exact reference.  In particular, do not
                # reach for another manager, a static endpoint, or a newer G2.
                raise ProviderImplementationUnavailableError()
            return factory.provider_scope(provider, model_key=model_key)

        raise TypeError("LLM provider target is unsupported.")


# Keep both capitalization styles available to external composition while the
# project otherwise uses ``LLM`` for services and ``Llm`` for target variants.
LlmProviderFactoryRegistry = LLMProviderFactoryRegistry


def create_builtin_llm_provider_factory_registry() -> LLMProviderFactoryRegistry:
    """Create a fresh registry with only the explicit ordinary built-in."""

    registry = LLMProviderFactoryRegistry()
    registry.register_static_factory(StaticLlmProviderFactory())
    return registry


def register_builtin_llm_provider_factories(registry: LLMProviderFactoryRegistry) -> None:
    """Explicit composition helper; never invoked at import time."""

    registry.register_static_factory(StaticLlmProviderFactory())


__all__ = [
    "LLMProviderFactory",
    "LLMProviderFactoryRegistry",
    "LlmProviderFactoryRegistry",
    "ManagedLlmProviderFactory",
    "ProviderImplementationUnavailableError",
    "ProviderOperationScope",
    "StaticLlmProviderFactory",
    "create_builtin_llm_provider_factory_registry",
    "register_builtin_llm_provider_factories",
]
