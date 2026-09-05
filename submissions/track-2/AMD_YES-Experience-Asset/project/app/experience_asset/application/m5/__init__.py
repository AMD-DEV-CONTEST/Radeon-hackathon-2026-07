"""Isolated E6/M5 application contracts and services.

The package deliberately has no API, migration, repository, or production
workflow wiring until E5 is merged and its read-only handoff is available.
"""

from typing import TYPE_CHECKING, Any

from .contracts import (
    ApprovalRequestV1,
    M5ContextProjectionV1,
    M5EvidenceIndexV1,
    M5RelationProjectionV1,
    PrivacyActionV1,
    PrivacyCategoryV1,
    PrivacyFindingProposalV1,
    PrivacyProposalSourceV1,
    PrivacyResolutionResultV1,
    PrivacyReviewStatusV1,
    PrivacyReviewV1,
    RelationOutcomeV1,
    RouteReadinessMatrixV1,
)

if TYPE_CHECKING:
    from .service import M5IsolatedService


def __getattr__(name: str) -> Any:
    """Load the service lazily so policy-first imports cannot form a cycle."""

    if name == "M5IsolatedService":
        from .service import M5IsolatedService

        return M5IsolatedService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ApprovalRequestV1",
    "M5ContextProjectionV1",
    "M5EvidenceIndexV1",
    "M5IsolatedService",
    "M5RelationProjectionV1",
    "PrivacyActionV1",
    "PrivacyCategoryV1",
    "PrivacyFindingProposalV1",
    "PrivacyProposalSourceV1",
    "PrivacyResolutionResultV1",
    "PrivacyReviewStatusV1",
    "PrivacyReviewV1",
    "RelationOutcomeV1",
    "RouteReadinessMatrixV1",
]
