"""Project exceptions."""


class BuildGuardError(Exception):
    """Base application error."""


class ConfigurationError(BuildGuardError):
    """Configuration could not be loaded or validated."""


class EndpointSecurityError(BuildGuardError):
    """An LLM endpoint is outside the permitted local network."""


class MonitorUnavailableError(BuildGuardError):
    """A requested hardware monitor is unavailable."""


class ModelUnavailableError(BuildGuardError):
    """A configured local model cannot be loaded."""


class RagIndexError(BuildGuardError):
    """A local retrieval index is missing or invalid."""
