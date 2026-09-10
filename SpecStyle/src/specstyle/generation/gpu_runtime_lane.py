"""Process-wide ownership for a complete GPU runtime lifecycle."""

from __future__ import annotations

import threading
from types import TracebackType

from specstyle.errors import DomainError

_LANE = threading.BoundedSemaphore(1)
_LEASE_SEAL = object()


class GpuRuntimeLaneLease:
    __slots__ = ("_closed", "_lock", "_seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("GPU runtime lane leases are issued only by acquire")

    def close(self) -> None:
        _validate_lease(self, require_open=False)
        with self._lock:
            if self._closed:
                return
            self._closed = True
            _LANE.release()

    def __enter__(self) -> GpuRuntimeLaneLease:
        _validate_lease(self, require_open=True)
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __copy__(self) -> GpuRuntimeLaneLease:
        raise TypeError("GPU runtime lane leases cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> GpuRuntimeLaneLease:
        raise TypeError("GPU runtime lane leases cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("GPU runtime lane leases cannot be serialized")


def _validate_lease(value: object, *, require_open: bool) -> None:
    if (
        type(value) is not GpuRuntimeLaneLease
        or getattr(value, "_seal", None) is not _LEASE_SEAL
        or type(getattr(value, "_closed", None)) is not bool
    ):
        raise DomainError("invalid GPU runtime lane lease")
    if require_open and value._closed:
        raise DomainError("GPU runtime lane lease is closed")


def acquire_gpu_runtime_lane() -> GpuRuntimeLaneLease:
    """Block until this process owns the full GPU runtime lifecycle."""
    _LANE.acquire()
    try:
        lease = object.__new__(GpuRuntimeLaneLease)
        lease._closed = False
        lease._lock = threading.Lock()
        lease._seal = _LEASE_SEAL
        _validate_lease(lease, require_open=True)
        return lease
    except BaseException:
        _LANE.release()
        raise


def try_acquire_gpu_runtime_lane() -> GpuRuntimeLaneLease | None:
    """Return a lease immediately, or ``None`` when another lifecycle owns it."""
    if not _LANE.acquire(blocking=False):
        return None
    try:
        lease = object.__new__(GpuRuntimeLaneLease)
        lease._closed = False
        lease._lock = threading.Lock()
        lease._seal = _LEASE_SEAL
        _validate_lease(lease, require_open=True)
        return lease
    except BaseException:
        _LANE.release()
        raise


__all__ = (
    "GpuRuntimeLaneLease",
    "acquire_gpu_runtime_lane",
    "try_acquire_gpu_runtime_lane",
)
