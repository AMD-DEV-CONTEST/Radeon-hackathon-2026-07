from policyseal.domain.enums import ContentCategory


class PolicySealError(Exception):
    """Base class for expected PolicySeal domain failures."""


class InvalidContextError(PolicySealError):
    """Raised when a disclosure context is incomplete or inconsistent."""


class InvalidDecisionError(PolicySealError):
    """Raised when a policy decision lacks required evidence."""


class UnsupportedDocumentError(PolicySealError):
    """Raised when a document cannot be processed safely in P0."""


class UnsafeOutputError(PolicySealError):
    """Raised when residual validation cannot prove an output safe."""


class ResidualOutputError(UnsafeOutputError):
    """A non-waivable output finding represented without the matched raw value."""

    def __init__(
        self,
        message: str,
        *,
        category: ContentCategory,
        location: str,
        rule_id: str,
        evidence_ids: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.category = category
        self.location = location
        self.rule_id = rule_id
        self.evidence_ids = evidence_ids


class ImmutableRevisionError(PolicySealError):
    """Raised when code attempts to alter an immutable source or revision."""


class StorageConflictError(PolicySealError):
    """Raised when persistent data violates a PolicySeal storage invariant."""


class InvalidStateTransition(PolicySealError):
    """Raised when a revision attempts an unlisted state transition."""


class ApprovalDenied(PolicySealError):
    """Raised when an approval is missing, expired, self-issued, or no longer exact."""


class ExportDenied(PolicySealError):
    """Raised when a revision or simulation is not eligible for download."""


class AnalysisFailed(PolicySealError):
    """Raised when a disclosure revision cannot complete its controlled analysis."""
