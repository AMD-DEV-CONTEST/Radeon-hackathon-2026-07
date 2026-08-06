"""AMD-managed Embedding factory over one exact private runtime binding.

The generic Embedding service owns batching, vector validation, and the
semantic operation scope. This AMD-specific adapter only acquires the exact AMD
generation before that scope begins, constructs the ordinary OpenAI-compatible
wire client from the in-memory binding, and releases the permit once.
"""

from __future__ import annotations

import threading

from ...embedding_provider_factory import EmbeddingOperationScope
from ...embedding_service import EmbeddingValidationError, OpenAICompatibleEmbeddingBackend
from ...embedding_settings import EmbeddingProviderProjection, ManagedEmbeddingProviderRef
from ..placement import AmdPlacementError, AmdRuntimeKey
from ..runtime import (
    AmdRuntimeDirectory,
    AmdRuntimeError,
    AmdRuntimeRetiringError,
    AmdRuntimeScope,
)


class AmdEmbeddingAdapterError(EmbeddingValidationError):
    """Base pre-dispatch failure from the AMD Embedding edge."""


class AmdEmbeddingProviderUnavailableError(AmdEmbeddingAdapterError):
    def __init__(self) -> None:
        super().__init__(
            "Managed Embedding provider is unavailable.",
            error_code="embedding_provider_unavailable",
        )


class AmdEmbeddingProviderRetiringError(AmdEmbeddingAdapterError):
    def __init__(self) -> None:
        super().__init__(
            "Managed Embedding provider is retiring.",
            error_code="embedding_provider_retiring",
        )


class AmdEmbeddingDescriptorMismatchError(AmdEmbeddingAdapterError):
    def __init__(self) -> None:
        super().__init__(
            "Managed Embedding provider does not match the selected generation.",
            error_code="embedding_provider_descriptor_mismatch",
        )


class AmdEmbeddingOperationScope(EmbeddingOperationScope):
    """One entire embedding operation pinned to an exact AMD generation."""

    __slots__ = ("_close_lock", "_runtime_scope")

    def __init__(
        self,
        provider: OpenAICompatibleEmbeddingBackend,
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
        with self._close_lock:
            if self._closed:
                return
            try:
                self._runtime_scope.close()
            finally:
                super().close()


class AmdEmbeddingAdapter:
    """Explicit managed factory contribution for the opaque AMD manager ID."""

    def __init__(self, runtime_directory: AmdRuntimeDirectory) -> None:
        if not isinstance(runtime_directory, AmdRuntimeDirectory):
            raise TypeError("AMD Embedding adapter requires an AMD runtime directory.")
        self._runtime_directory = runtime_directory

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def provider_scope(
        self,
        projection: EmbeddingProviderProjection,
    ) -> AmdEmbeddingOperationScope:
        reference = self._require_managed_reference(projection)
        if projection.retiring:
            raise AmdEmbeddingProviderRetiringError()
        try:
            runtime_scope = self._runtime_directory.acquire(
                AmdRuntimeKey(
                    installation_id=reference.installation_id,
                    component_generation_id=reference.component_generation_id,
                )
            )
        except AmdRuntimeRetiringError:
            raise AmdEmbeddingProviderRetiringError() from None
        except (AmdRuntimeError, AmdPlacementError):
            raise AmdEmbeddingProviderUnavailableError() from None
        except Exception:
            raise AmdEmbeddingProviderUnavailableError() from None

        try:
            # BGE-M3 exposes its native dimensionality.  The ordinary client
            # therefore omits OpenAI's optional ``dimensions`` field; the
            # generic service validates the response against the immutable
            # projection dimension instead.
            provider = OpenAICompatibleEmbeddingBackend(
                base_url=runtime_scope.binding.base_url,
                api_key=runtime_scope.binding.bearer_token,
                model=projection.model,
                timeout_seconds=projection.timeout_seconds,
                request_dimensions=None,
            )
            return AmdEmbeddingOperationScope(provider, runtime_scope=runtime_scope)
        except Exception:
            runtime_scope.close()
            raise AmdEmbeddingProviderUnavailableError() from None

    @staticmethod
    def _require_managed_reference(
        projection: EmbeddingProviderProjection,
    ) -> ManagedEmbeddingProviderRef:
        target = projection.target
        if not isinstance(target, ManagedEmbeddingProviderRef):
            raise AmdEmbeddingDescriptorMismatchError()
        if not projection.model or not projection.manifest_digest or not projection.tokenizer_identity:
            raise AmdEmbeddingDescriptorMismatchError()
        return target


AmdEmbeddingProviderFactory = AmdEmbeddingAdapter


__all__ = [
    "AmdEmbeddingAdapter",
    "AmdEmbeddingAdapterError",
    "AmdEmbeddingDescriptorMismatchError",
    "AmdEmbeddingOperationScope",
    "AmdEmbeddingProviderFactory",
    "AmdEmbeddingProviderRetiringError",
    "AmdEmbeddingProviderUnavailableError",
]
