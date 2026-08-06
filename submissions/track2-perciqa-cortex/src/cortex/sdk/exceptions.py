from __future__ import annotations


class CortexSDKError(Exception):
    """Base class for cortex.sdk user-facing errors."""


class CortexPublishError(CortexSDKError):
    """Raised when publish() fails on the underlying node."""


class CortexQueryError(CortexSDKError):
    """Raised when query() fails on the underlying node."""


def map_node_error(exc: Exception) -> Exception:
    """Translate core/node exceptions to user-friendly SDK exceptions.

    Wrapped around every SDK call so agents get a single error taxonomy.
    """
    if isinstance(exc, CortexSDKError):
        return exc
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "publish" in name or "sign" in name or "publish" in msg:
        return CortexPublishError(str(exc))
    if "query" in name or "search" in name or "query" in msg or "search" in msg:
        return CortexQueryError(str(exc))
    return CortexSDKError(str(exc))
