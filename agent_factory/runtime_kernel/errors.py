from __future__ import annotations


class RuntimeKernelError(Exception):
    """Base error for RuntimeKernel."""


class PatternValidationError(RuntimeKernelError):
    """Raised when a graph pattern spec is invalid."""


class NodeExecutionError(RuntimeKernelError):
    """Raised when a node implementation fails."""


class CheckpointError(RuntimeKernelError):
    """Raised when checkpoint operations fail."""
