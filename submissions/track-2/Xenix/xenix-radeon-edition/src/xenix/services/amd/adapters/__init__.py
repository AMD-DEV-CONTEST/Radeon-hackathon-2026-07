"""Explicit AMD capability adapters.

Importing this package performs no registration or runtime work.  Application
composition supplies each adapter to the matching capability-owned registry.
"""

from .llm import (
    AmdChatProviderFactory,
    AmdLlmAdapter,
    AmdLlmAdapterError,
    AmdLlmDescriptorMismatchError,
    AmdLlmOperationScope,
    AmdLlmProviderFactory,
    AmdLlmProviderRetiringError,
    AmdLlmProviderUnavailableError,
)
from .embedding import (
    AmdEmbeddingAdapter,
    AmdEmbeddingAdapterError,
    AmdEmbeddingDescriptorMismatchError,
    AmdEmbeddingOperationScope,
    AmdEmbeddingProviderFactory,
    AmdEmbeddingProviderRetiringError,
    AmdEmbeddingProviderUnavailableError,
)
from .ocr import (
    AmdOcrAdapter,
    AmdOcrAdapterError,
    AmdOcrAttempt,
    AmdOcrAttemptFactory,
    AmdOcrDescriptorMismatchError,
    AmdOcrProviderFactory,
    AmdOcrProviderRetiringError,
    AmdOcrProviderUnavailableError,
    OcrRuntimeDescriptorResolver,
)

__all__ = [
    "AmdEmbeddingAdapter",
    "AmdEmbeddingAdapterError",
    "AmdEmbeddingDescriptorMismatchError",
    "AmdEmbeddingOperationScope",
    "AmdEmbeddingProviderFactory",
    "AmdEmbeddingProviderRetiringError",
    "AmdEmbeddingProviderUnavailableError",
    "AmdChatProviderFactory",
    "AmdLlmAdapter",
    "AmdLlmAdapterError",
    "AmdLlmDescriptorMismatchError",
    "AmdLlmOperationScope",
    "AmdLlmProviderFactory",
    "AmdLlmProviderRetiringError",
    "AmdLlmProviderUnavailableError",
    "AmdOcrAdapter",
    "AmdOcrAdapterError",
    "AmdOcrAttempt",
    "AmdOcrAttemptFactory",
    "AmdOcrDescriptorMismatchError",
    "AmdOcrProviderFactory",
    "AmdOcrProviderRetiringError",
    "AmdOcrProviderUnavailableError",
    "OcrRuntimeDescriptorResolver",
]
