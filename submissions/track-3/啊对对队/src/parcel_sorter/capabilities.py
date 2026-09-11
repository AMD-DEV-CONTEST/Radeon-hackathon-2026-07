"""Runtime capability gates for parcel handling.

The catalog deliberately contains evaluation-only profiles that require a
different end effector.  Keeping the capability check in one small module
prevents an unsupported profile from silently being evaluated with parallel
jaws and reported as a robot result.
"""

from __future__ import annotations

from typing import Collection


SUPPORTED_HANDLING_CLASSES = frozenset({"parallel_jaw"})


def runtime_supported_handling_classes(
    *,
    tri_suction_enabled: bool,
) -> frozenset[str]:
    """Resolve support from the end effector physically present in the scene."""

    supported = {"parallel_jaw"}
    if tri_suction_enabled:
        supported.add("suction_required")
    return frozenset(supported)


class UnsupportedHandlingClassError(ValueError):
    """Raised when a profile requires an end effector not present in the scene."""


def require_supported_handling(
    handling_class: str,
    *,
    supported: Collection[str] = SUPPORTED_HANDLING_CLASSES,
) -> None:
    """Fail before simulation setup when the selected end effector is unavailable."""

    if handling_class not in supported:
        supported_text = ", ".join(sorted(supported)) or "none"
        raise UnsupportedHandlingClassError(
            f"handling class '{handling_class}' is not implemented by this runtime; "
            f"supported classes: {supported_text}"
        )
