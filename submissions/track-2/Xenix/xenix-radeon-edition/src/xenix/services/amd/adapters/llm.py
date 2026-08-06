"""AMD-managed Chat factory over one exact private runtime binding.

This is an AMD-specific composition adapter. It translates an LLM-owned managed
reference into an ordinary OpenAI-compatible provider while retaining the AMD
generation permit for the entire semantic operation.  It deliberately contains
no deployment, settings, or selection authority.
"""

from __future__ import annotations

import threading

from ...llm.provider_factory import ProviderOperationScope
from ...llm.providers import OpenAICompatibleChatProvider, ProviderBindingError
from ...llm.settings import LLMProviderConfig, ManagedLlmProviderRef
from ..placement import AmdPlacementError, AmdRuntimeKey
from ..runtime import (
    AmdRuntimeDirectory,
    AmdRuntimeError,
    AmdRuntimeRetiringError,
    AmdRuntimeScope,
)


class AmdLlmAdapterError(ProviderBindingError):
    """Base pre-dispatch error from the AMD LLM composition edge."""


class AmdLlmProviderUnavailableError(AmdLlmAdapterError):
    """The exact managed generation has no usable private runtime binding."""

    def __init__(self) -> None:
        super().__init__(
            "Managed LLM provider is unavailable.",
            error_code="llm_provider_unavailable",
            retryable=False,
            dispatch_may_have_happened=False,
        )


class AmdLlmProviderRetiringError(AmdLlmAdapterError):
    """The exact generation no longer admits a new semantic operation."""

    def __init__(self) -> None:
        super().__init__(
            "Managed LLM provider is retiring.",
            error_code="llm_provider_retiring",
            retryable=False,
            dispatch_may_have_happened=False,
        )


class AmdLlmDescriptorMismatchError(AmdLlmAdapterError):
    """The caller did not supply an exact managed LLM provider/model pair."""

    def __init__(self) -> None:
        super().__init__(
            "Managed LLM provider does not match the requested model.",
            error_code="llm_provider_descriptor_mismatch",
            retryable=False,
            dispatch_may_have_happened=False,
        )


class AmdLlmOperationScope(ProviderOperationScope):
    """One LLM operation scope retaining the exact AMD generation permit."""

    __slots__ = ("_close_lock", "_runtime_scope")

    def __init__(
        self,
        provider: OpenAICompatibleChatProvider,
        *,
        runtime_scope: AmdRuntimeScope,
    ) -> None:
        super().__init__(provider)
        self._runtime_scope = runtime_scope
        self._close_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(closed={self.closed!r})"

    @property
    def closed(self) -> bool:
        with self._close_lock:
            return self._closed

    def close(self) -> None:
        """Release the exact runtime scope once, including generator close paths."""

        with self._close_lock:
            if self._closed:
                return
            try:
                self._runtime_scope.close()
            finally:
                super().close()


class AmdLlmAdapter:
    """Managed-provider factory contribution backed by ``AmdRuntimeDirectory``.

    The generic LLM registry selects this factory by the opaque ``manager_id``
    before calling :meth:`provider_scope`.  This adapter intentionally does not
    interpret that ID: it only resolves the exact installation/generation pair.
    """

    def __init__(self, runtime_directory: AmdRuntimeDirectory) -> None:
        if not isinstance(runtime_directory, AmdRuntimeDirectory):
            raise TypeError("AMD LLM adapter requires an AMD runtime directory.")
        self._runtime_directory = runtime_directory

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def provider_scope(
        self,
        provider: LLMProviderConfig,
        *,
        model_key: str,
    ) -> AmdLlmOperationScope:
        """Acquire one exact generation/binding and wrap it in an LLM scope.

        Acquisition happens before any HTTP request, so every mapped error is a
        proven pre-dispatch failure.  Once returned, the scope retains the same
        binding and permit across all outer retry attempts and streaming yields.
        """

        reference = self._require_managed_reference(provider, model_key)
        if bool(getattr(provider, "retiring", False)):
            raise AmdLlmProviderRetiringError()

        try:
            key = AmdRuntimeKey(
                installation_id=reference.installation_id,
                component_generation_id=reference.component_generation_id,
            )
            runtime_scope = self._runtime_directory.acquire(key)
        except AmdRuntimeRetiringError:
            raise AmdLlmProviderRetiringError() from None
        except (AmdRuntimeError, AmdPlacementError):
            raise AmdLlmProviderUnavailableError() from None
        except Exception:
            # The private runtime boundary must never leak a binding, URL, port,
            # token, or placement diagnostics into LLM retry/UI error paths.
            raise AmdLlmProviderUnavailableError() from None

        try:
            wire_provider = OpenAICompatibleChatProvider(
                provider_key=provider.provider_id,
                base_url=runtime_scope.binding.base_url,
                api_key=runtime_scope.binding.bearer_token,
                model=model_key.strip(),
                timeout_seconds=provider.timeout_seconds,
                streaming_enabled=provider.streaming_enabled,
            )
            return AmdLlmOperationScope(wire_provider, runtime_scope=runtime_scope)
        except Exception:
            runtime_scope.close()
            raise AmdLlmProviderUnavailableError() from None

    @staticmethod
    def _require_managed_reference(
        provider: LLMProviderConfig,
        model_key: str,
    ) -> ManagedLlmProviderRef:
        target = getattr(provider, "target", None)
        if not isinstance(target, ManagedLlmProviderRef):
            raise AmdLlmDescriptorMismatchError()
        if not isinstance(model_key, str) or model_key.strip() not in provider.models:
            raise AmdLlmDescriptorMismatchError()
        return target


# Both names describe the same explicit registry contribution.  ``Chat`` makes
# the transport role obvious at composition; ``Llm`` follows the generic port.
AmdLlmProviderFactory = AmdLlmAdapter
AmdChatProviderFactory = AmdLlmAdapter


__all__ = [
    "AmdChatProviderFactory",
    "AmdLlmAdapter",
    "AmdLlmAdapterError",
    "AmdLlmDescriptorMismatchError",
    "AmdLlmOperationScope",
    "AmdLlmProviderFactory",
    "AmdLlmProviderRetiringError",
    "AmdLlmProviderUnavailableError",
]
