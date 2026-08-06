"""Reusable, target-side AMD runtime component primitives.

Imports are pure: this package registers nothing, opens no listener, creates no
target directory, and starts no process.  Placement adapters explicitly choose
when to create a token handoff, validate a loopback binding, or launch a fenced
process.
"""

from .auth import (
    BearerTokenHandoff,
    RuntimeBearerToken,
    create_bearer_token_handoff,
    read_bearer_token_handoff,
    remove_bearer_token_handoff,
)
from .errors import (
    AmdComponentError,
    LoopbackBindingError,
    ManagedProcessError,
    ManagedProcessFenceError,
    ManagedProcessLaunchError,
    ManagedProcessPlatformError,
    ManagedProcessReapError,
    ManagedProcessSpecError,
    TokenDirectoryError,
    TokenFileError,
    TokenHandoffError,
    TokenHandoffPlatformError,
    TokenValidationError,
)
from .loopback import (
    LoopbackBinding,
    LoopbackListener,
    validate_loopback_binding,
    validate_loopback_host,
    validate_loopback_listener,
)
from .process import (
    ManagedProcess,
    ManagedProcessIdentity,
    ManagedProcessSpec,
    ManagedProcessState,
    ProcessStartIdentity,
    RedactedProcessStatus,
    command_fingerprint,
    launch_managed_process,
    verify_managed_process_fence,
)

__all__ = [
    "AmdComponentError",
    "BearerTokenHandoff",
    "LoopbackBinding",
    "LoopbackBindingError",
    "LoopbackListener",
    "ManagedProcess",
    "ManagedProcessError",
    "ManagedProcessFenceError",
    "ManagedProcessIdentity",
    "ManagedProcessLaunchError",
    "ManagedProcessPlatformError",
    "ManagedProcessReapError",
    "ManagedProcessSpec",
    "ManagedProcessSpecError",
    "ManagedProcessState",
    "ProcessStartIdentity",
    "RedactedProcessStatus",
    "RuntimeBearerToken",
    "TokenDirectoryError",
    "TokenFileError",
    "TokenHandoffError",
    "TokenHandoffPlatformError",
    "TokenValidationError",
    "command_fingerprint",
    "create_bearer_token_handoff",
    "launch_managed_process",
    "read_bearer_token_handoff",
    "remove_bearer_token_handoff",
    "validate_loopback_binding",
    "validate_loopback_host",
    "validate_loopback_listener",
    "verify_managed_process_fence",
]
