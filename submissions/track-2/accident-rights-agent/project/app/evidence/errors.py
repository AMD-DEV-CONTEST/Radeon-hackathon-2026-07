"""Evidence-layer exceptions with safe, user-facing messages."""


class EvidenceError(RuntimeError):
    """Base error for deterministic evidence processing."""


class InvalidCaseId(EvidenceError):
    """A case identifier is unsafe or malformed."""


class UnsupportedEvidence(EvidenceError):
    """A source file is unsupported or its signature is inconsistent."""


class EvidenceTooLarge(EvidenceError):
    """A source exceeds the configured intake limit."""


class DependencyUnavailable(EvidenceError):
    """An optional parser dependency is not installed."""


class ModelResponseError(EvidenceError):
    """The local model response cannot be validated."""
