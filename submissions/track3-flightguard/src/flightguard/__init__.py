"""FlightGuard package.

The fault-injection API depends on PyTorch, while audit and search utilities are
deliberately usable in a lightweight CPU-only environment.  Keep the historical
top-level names available without importing PyTorch until one of them is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .faults import FaultBatch, ReplayFaultInjector, ReplayTrace

__all__ = ["FaultBatch", "ReplayFaultInjector", "ReplayTrace"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .faults import FaultBatch, ReplayFaultInjector, ReplayTrace

        return {
            "FaultBatch": FaultBatch,
            "ReplayFaultInjector": ReplayFaultInjector,
            "ReplayTrace": ReplayTrace,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
