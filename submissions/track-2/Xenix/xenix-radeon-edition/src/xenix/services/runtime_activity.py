from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


class UpdateAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActivitySnapshot:
    accepting_work: bool
    active_count: int
    labels: tuple[str, ...]


class ApplicationActivityCoordinator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._accepting_work = True
        self._active: dict[int, str] = {}
        self._next_id = 0

    @contextmanager
    def work(self, label: str) -> Iterator[None]:
        with self._lock:
            if not self._accepting_work:
                raise UpdateAdmissionError("Xenix is preparing to apply an update and is not accepting new work.")
            self._next_id += 1
            lease_id = self._next_id
            self._active[lease_id] = label
        try:
            yield
        finally:
            with self._lock:
                self._active.pop(lease_id, None)

    def snapshot(self) -> ActivitySnapshot:
        with self._lock:
            return ActivitySnapshot(
                accepting_work=self._accepting_work,
                active_count=len(self._active),
                labels=tuple(sorted(self._active.values())),
            )

    def begin_update(self) -> None:
        with self._lock:
            if not self._accepting_work:
                raise UpdateAdmissionError("An update handoff is already in progress.")
            if self._active:
                labels = ", ".join(sorted(set(self._active.values())))
                raise UpdateAdmissionError(f"Active work must finish before updating: {labels}.")
            self._accepting_work = False

    def cancel_update(self) -> None:
        with self._lock:
            self._accepting_work = True


activity_coordinator = ApplicationActivityCoordinator()
