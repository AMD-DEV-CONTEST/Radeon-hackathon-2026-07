"""Ticket 09 — cross-artifact invalidation after readiness."""

from .matrix import (
    INVALIDATION_MATRIX,
    REDACTS_COPIED_CONTENT,
    Artifact,
    MutationEvent,
    Outcome,
)
from .service import InvalidationResult, InvalidationService

__all__ = [
    "INVALIDATION_MATRIX",
    "REDACTS_COPIED_CONTENT",
    "Artifact",
    "InvalidationResult",
    "InvalidationService",
    "MutationEvent",
    "Outcome",
]
