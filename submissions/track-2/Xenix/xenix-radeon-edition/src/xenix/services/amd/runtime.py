"""Private exact-runtime directory and generation admission gates.

The directory is deliberately process-local.  Durable installation lifecycle
belongs to SQLite; a live loopback binding is useful only while its exact
controller incarnation is still fenced in memory.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .placement import AmdRuntimeKey, LoopbackHttpBinding, RuntimeIncarnation


class AmdRuntimeError(RuntimeError):
    """Base failure for volatile managed runtime access."""


class AmdRuntimeUnavailableError(AmdRuntimeError):
    """No exact current binding can safely serve this operation."""


class AmdRuntimeRetiringError(AmdRuntimeError):
    """The exact generation is closed to new semantic operations."""


class AmdRuntimeFenceError(AmdRuntimeError):
    """A stale controller/incarnation attempted to alter a realization."""


class AmdRuntimeBusyError(AmdRuntimeError):
    """A lifecycle change requires a currently quiescent generation."""


class _GenerationPermit:
    def __init__(self, gate: _GenerationGate) -> None:
        self._gate = gate
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._gate._release()


class _GenerationGate:
    """One exact generation's admission state; its count never becomes durable."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._closed = False
        self._retirement_pending = False
        self._active_count = 0

    def acquire(self) -> _GenerationPermit:
        with self._condition:
            if self._closed or self._retirement_pending:
                raise AmdRuntimeRetiringError("Managed generation is retiring.")
            self._active_count += 1
            return _GenerationPermit(self)

    def begin_retirement(self, commit: Callable[[], None]) -> None:
        """Linearize durable retirement before publishing a closed gate."""

        with self._condition:
            if self._closed:
                return
            if self._retirement_pending:
                raise AmdRuntimeBusyError("Managed generation retirement is already being committed.")
            self._retirement_pending = True
            try:
                commit()
            except Exception:
                self._retirement_pending = False
                self._condition.notify_all()
                raise
            self._closed = True
            self._retirement_pending = False
            self._condition.notify_all()

    def wait_for_drain(self, timeout_seconds: float | None = None) -> bool:
        with self._condition:
            if self._active_count == 0:
                return True
            deadline = None if timeout_seconds is None else time.monotonic() + max(0.0, timeout_seconds)
            while self._active_count:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    @property
    def active_count(self) -> int:
        with self._condition:
            return self._active_count

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def _release(self) -> None:
        with self._condition:
            if self._active_count <= 0:
                raise AmdRuntimeError("Managed generation permit was released more than once.")
            self._active_count -= 1
            if self._active_count == 0:
                self._condition.notify_all()


@dataclass(slots=True)
class _RuntimeSlot:
    incarnation: RuntimeIncarnation
    gate: _GenerationGate
    binding: LoopbackHttpBinding | None = None
    binding_resolver: Callable[[AmdRuntimeKey], LoopbackHttpBinding] | None = None


class AmdRuntimeScope:
    """One exact binding snapshot with one generation admission permit."""

    def __init__(
        self,
        permit: _GenerationPermit,
        binding: LoopbackHttpBinding,
        incarnation: RuntimeIncarnation,
    ) -> None:
        self._permit = permit
        self.binding = binding
        self.incarnation = incarnation

    def close(self) -> None:
        self._permit.close()

    def __enter__(self) -> AmdRuntimeScope:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


class AmdRuntimeDirectory:
    """Exact multi-installation directory used privately by AMD capability adapters."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._slots: dict[AmdRuntimeKey, _RuntimeSlot] = {}

    def activate(self, key: AmdRuntimeKey, incarnation: RuntimeIncarnation) -> None:
        """Fence an exact generation to a controller incarnation without a binding."""

        with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                self._slots[key] = _RuntimeSlot(incarnation=incarnation, gate=_GenerationGate())
                return
            if slot.gate.closed:
                raise AmdRuntimeRetiringError("A retiring managed generation cannot be reactivated.")
            if slot.incarnation == incarnation:
                return
            if slot.gate.active_count:
                raise AmdRuntimeBusyError("Managed generation has an active operation.")
            slot.incarnation = incarnation
            slot.binding = None

    def publish_binding(
        self,
        key: AmdRuntimeKey,
        *,
        incarnation: RuntimeIncarnation,
        binding: LoopbackHttpBinding,
        binding_resolver: Callable[[AmdRuntimeKey], LoopbackHttpBinding],
    ) -> None:
        """Publish a binding together with its live identity verifier.

        A loopback URL alone is never a sufficient authority for a Private
        placement: a dead SSH forward can be followed by an unrelated local
        listener reusing the same port.  The verifier is intentionally kept
        only in process memory and is run for every capability operation.
        """

        if not callable(binding_resolver):
            raise TypeError("Managed runtime binding resolver must be callable.")
        with self._lock:
            slot = self._require_slot(key)
            self._require_incarnation(slot, incarnation)
            if slot.gate.closed:
                raise AmdRuntimeRetiringError("A retiring managed generation cannot publish a binding.")
            slot.binding = binding
            slot.binding_resolver = binding_resolver

    def clear_binding(self, key: AmdRuntimeKey, *, incarnation: RuntimeIncarnation) -> None:
        """Forget one volatile binding only when its exact owner is still current."""

        with self._lock:
            slot = self._require_slot(key)
            self._require_incarnation(slot, incarnation)
            slot.binding = None
            slot.binding_resolver = None

    def acquire(self, key: AmdRuntimeKey) -> AmdRuntimeScope:
        """Acquire one verified scope over a complete capability operation.

        The placement-owned verifier runs outside the directory lock because
        it may perform bounded SSH/process observation.  The permit is held
        while that happens, then the closed gate is checked again before the
        caller receives a binding.  Thus retirement cannot admit a request
        whose live binding was only validated after retirement committed.
        """

        with self._lock:
            slot = self._require_slot(key)
            if slot.gate.closed:
                raise AmdRuntimeRetiringError("Managed generation is retiring.")
            if slot.binding is None or slot.binding_resolver is None:
                raise AmdRuntimeUnavailableError("Managed runtime binding is unavailable.")
            permit = slot.gate.acquire()
            incarnation = slot.incarnation
            resolver = slot.binding_resolver

        try:
            binding = resolver(key)
            if not isinstance(binding, LoopbackHttpBinding):
                raise AmdRuntimeUnavailableError("Managed runtime binding is unavailable.")
        except AmdRuntimeError:
            permit.close()
            self._forget_failed_binding(key, incarnation)
            raise
        except Exception as exc:
            permit.close()
            self._forget_failed_binding(key, incarnation)
            raise AmdRuntimeUnavailableError("Managed runtime binding is unavailable.") from exc

        with self._lock:
            current = self._require_slot(key)
            self._require_incarnation(current, incarnation)
            if current.gate.closed:
                permit.close()
                raise AmdRuntimeRetiringError("Managed generation is retiring.")
            # A successful verifier is allowed to refresh an ephemeral
            # loopback forwarding endpoint, but never to change its owner.
            current.binding = binding
            return AmdRuntimeScope(permit, binding, incarnation)

    def retire(self, key: AmdRuntimeKey, *, commit_retiring: Callable[[], None]) -> None:
        """Close exact admission only after the caller persists forward retirement."""

        with self._lock:
            slot = self._require_slot(key)
            slot.gate.begin_retirement(commit_retiring)
            slot.binding = None
            slot.binding_resolver = None

    def wait_for_drain(self, key: AmdRuntimeKey, timeout_seconds: float | None = None) -> bool:
        with self._lock:
            slot = self._require_slot(key)
            gate = slot.gate
        return gate.wait_for_drain(timeout_seconds)

    def remove_retired(
        self,
        key: AmdRuntimeKey,
        *,
        incarnation: RuntimeIncarnation,
    ) -> None:
        """Forget a runtime slot only after its closed gate has drained exactly."""

        with self._lock:
            slot = self._require_slot(key)
            self._require_incarnation(slot, incarnation)
            if not slot.gate.closed or slot.gate.active_count:
                raise AmdRuntimeBusyError("Managed generation has not completed retirement drain.")
            self._slots.pop(key, None)

    def _require_slot(self, key: AmdRuntimeKey) -> _RuntimeSlot:
        slot = self._slots.get(key)
        if slot is None:
            raise AmdRuntimeUnavailableError("Managed runtime is unavailable.")
        return slot

    def _forget_failed_binding(self, key: AmdRuntimeKey, incarnation: RuntimeIncarnation) -> None:
        """Forget a stale volatile endpoint only if its owner is unchanged."""

        with self._lock:
            slot = self._slots.get(key)
            if slot is not None and slot.incarnation == incarnation:
                slot.binding = None

    @staticmethod
    def _require_incarnation(slot: _RuntimeSlot, incarnation: RuntimeIncarnation) -> None:
        if slot.incarnation != incarnation:
            raise AmdRuntimeFenceError("Managed runtime controller fence no longer matches.")


__all__ = [
    "AmdRuntimeBusyError",
    "AmdRuntimeDirectory",
    "AmdRuntimeError",
    "AmdRuntimeFenceError",
    "AmdRuntimeRetiringError",
    "AmdRuntimeScope",
    "AmdRuntimeUnavailableError",
]
