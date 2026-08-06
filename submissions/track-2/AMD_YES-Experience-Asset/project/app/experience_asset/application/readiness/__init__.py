"""Ticket 03 — explicit acceptance to KnowledgeCardReady.

This package owns the readiness transition and nothing else. It does not start
discovery: acceptance costs the user nothing and a search costs local model time
and puts historical summaries in front of someone who has not asked to compare
anything. Keeping them separate is also what makes the guarantee testable — if
acceptance and discovery landed together, no test could show that acceptance
alone creates no run.
"""

from .service import (
    READINESS_REFUSAL_REASONS,
    ReadinessRefusal,
    ReadinessRefusalReason,
    ReadinessService,
)

__all__ = [
    "READINESS_REFUSAL_REASONS",
    "ReadinessRefusal",
    "ReadinessRefusalReason",
    "ReadinessService",
]
