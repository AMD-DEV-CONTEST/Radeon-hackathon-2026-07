"""Engine-neutral OCR capability contracts and ordinary provider composition."""

from .contracts import (
    OcrAttempt,
    OcrAttemptFactory,
    OcrFailure,
    OcrRuntimeDescriptor,
    OcrService,
    OcrSession,
    OcrSpawnSpec,
)

__all__ = [
    "OcrAttempt",
    "OcrAttemptFactory",
    "OcrFailure",
    "OcrRuntimeDescriptor",
    "OcrService",
    "OcrSession",
    "OcrSpawnSpec",
]
