"""Base hierarchy for specstyle domain exceptions.

This module defines only inheritance: ``SpecStyleError`` derives from
``Exception``, while ``DomainError`` and ``InfrastructureError`` derive from
``SpecStyleError``. Error codes, contexts, and serialization are intentionally
deferred to a later task.
"""


class SpecStyleError(Exception):
    """Root of all specstyle exceptions."""


class DomainError(SpecStyleError):
    """Domain semantic error, such as a rule violation or invalid specification."""


class InfrastructureError(SpecStyleError):
    """Runtime infrastructure error involving GPU/ROCm, file I/O, or dependencies."""


class _GpuOutOfMemoryError(InfrastructureError):
    """Private structured marker for a genuine runtime GPU OOM."""

    __slots__ = ()
