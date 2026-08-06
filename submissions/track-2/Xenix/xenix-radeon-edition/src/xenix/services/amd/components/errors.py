"""Typed failures for the AMD target-side component helpers.

The messages are deliberately fixed and redacted.  Callers can branch on the
exception type or ``error_code`` without receiving a token, path, command, PID,
or target detail that could be persisted accidentally.
"""

from __future__ import annotations


class AmdComponentError(RuntimeError):
    """Base error for one target-side AMD component operation."""

    error_code = "amd_component_error"
    message = "AMD component operation failed."

    def __init__(self) -> None:
        super().__init__(self.message)


class TokenHandoffError(AmdComponentError):
    """A bearer-token handoff could not remain protected."""

    error_code = "token_handoff_error"
    message = "Protected token handoff failed."


class TokenHandoffPlatformError(TokenHandoffError):
    """The target cannot prove the required POSIX file protections."""

    error_code = "token_handoff_platform_unsupported"
    message = "Protected token handoff is unavailable on this target."


class TokenDirectoryError(TokenHandoffError):
    """The caller-supplied private directory is absent or unsafe."""

    error_code = "token_private_directory_invalid"
    message = "Protected token directory is invalid."


class TokenFileError(TokenHandoffError):
    """The handoff file is absent, malformed, or not private."""

    error_code = "token_handoff_file_invalid"
    message = "Protected token file is invalid."


class TokenValidationError(TokenHandoffError):
    """A token value or handoff read did not satisfy the token contract."""

    error_code = "token_validation_failed"
    message = "Runtime token validation failed."


class LoopbackBindingError(AmdComponentError):
    """A listener or authenticated loopback binding is unsafe."""

    error_code = "loopback_binding_invalid"
    message = "Loopback binding is invalid."


class ManagedProcessError(AmdComponentError):
    """Base failure for a fenced target-side managed process."""

    error_code = "managed_process_error"
    message = "Managed process operation failed."


class ManagedProcessPlatformError(ManagedProcessError):
    """The target cannot provide POSIX process fencing primitives."""

    error_code = "managed_process_platform_unsupported"
    message = "Managed process fencing is unavailable on this target."


class ManagedProcessSpecError(ManagedProcessError):
    """A launch spec would weaken the process or secret boundary."""

    error_code = "managed_process_spec_invalid"
    message = "Managed process specification is invalid."


class ManagedProcessLaunchError(ManagedProcessError):
    """A fenced managed process could not be started."""

    error_code = "managed_process_launch_failed"
    message = "Managed process could not be started safely."


class ManagedProcessFenceError(ManagedProcessError):
    """The observed process no longer proves the recorded identity."""

    error_code = "managed_process_fence_rejected"
    message = "Managed process identity could not be verified."


class ManagedProcessReapError(ManagedProcessError):
    """A managed process or its dedicated group could not be reaped safely."""

    error_code = "managed_process_reap_failed"
    message = "Managed process could not be reaped safely."


__all__ = [
    "AmdComponentError",
    "LoopbackBindingError",
    "ManagedProcessError",
    "ManagedProcessFenceError",
    "ManagedProcessLaunchError",
    "ManagedProcessPlatformError",
    "ManagedProcessReapError",
    "ManagedProcessSpecError",
    "TokenDirectoryError",
    "TokenFileError",
    "TokenHandoffError",
    "TokenHandoffPlatformError",
    "TokenValidationError",
]
