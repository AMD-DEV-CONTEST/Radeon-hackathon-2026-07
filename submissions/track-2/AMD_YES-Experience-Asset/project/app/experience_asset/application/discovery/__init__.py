"""Ticket 05 — one explicit search returning zero or one validated candidate.

The service owns "search once and get an answer": reserving one attempt against
the record ticket 01 froze, making one batch call, validating the proposal
against stored projections, and persisting a candidate or a semantic no-match.
Ticket 06 owns what happens when the same search runs twice, runs twice at once,
or dies halfway.
"""

from .service import (
    DISCOVERY_INTENT_VERSION,
    DISCOVERY_MAX_ELIGIBLE,
    DiscoveryResult,
    DiscoveryService,
    DiscoveryUnavailable,
)
from .validation import BOUNDARY_ROLES, ProposalRejected, validate_relation_proposal

__all__ = [
    "BOUNDARY_ROLES",
    "DISCOVERY_INTENT_VERSION",
    "DISCOVERY_MAX_ELIGIBLE",
    "DiscoveryResult",
    "DiscoveryService",
    "DiscoveryUnavailable",
    "ProposalRejected",
    "validate_relation_proposal",
]
