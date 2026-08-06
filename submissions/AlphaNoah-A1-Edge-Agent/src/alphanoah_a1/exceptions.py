"""Domain exceptions for explicit, auditable failure handling."""


class AlphaNoahError(Exception):
    """Base class for expected runtime failures."""


class ObjectNotFoundError(AlphaNoahError):
    """Raised when a requested domain object does not exist."""


class InvalidStateTransition(AlphaNoahError):
    """Raised when an operation attempts an illegal state transition."""


class ConcurrentUpdateError(AlphaNoahError):
    """Raised when persisted state changed before a transition was committed."""


class InvalidAnalysisOutput(AlphaNoahError):
    """Raised when rule/model analysis output does not match the Skill contract."""


class AnalysisProviderError(AlphaNoahError):
    """Base class for expected failures at an AnalysisProvider boundary."""

    failure_type = "provider"

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class ProviderInputError(AnalysisProviderError):
    """Raised when an Event cannot fit the bounded provider input contract."""

    failure_type = "input"


class ProviderTransportError(AnalysisProviderError):
    """Raised when a provider request cannot return a bounded response."""

    failure_type = "transport"


class ProviderOutputError(AnalysisProviderError):
    """Raised when a provider response violates the analysis contract."""

    failure_type = "output"


class ProviderInternalError(AnalysisProviderError):
    """Raised when a provider fails outside a known input/transport/output case."""

    failure_type = "internal"


class InvalidEventInput(AlphaNoahError):
    """Raised when an Event input does not match the ingestion contract."""


class HumanActorRequired(AlphaNoahError):
    """Raised when a human-only action is attributed to a non-human actor."""


class DuplicateSubmissionError(AlphaNoahError):
    """Raised when an idempotency key has already been accepted."""


class SkillResolutionError(AlphaNoahError):
    """Base class for deterministic Skill resolution failures."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class SkillNotFoundError(SkillResolutionError):
    """Raised when no active Skill is eligible for an Event."""


class SkillConflictError(SkillResolutionError):
    """Raised when multiple equally specific Skills are eligible."""
