"""Private ownership helpers for duplicated production file descriptors."""

from __future__ import annotations

from collections.abc import Callable
import fcntl
import os

from specstyle.errors import DomainError, InfrastructureError


class _OwnedFileDescriptors:
    __slots__ = ("_label", "_owned")

    def __init__(self, label: str) -> None:
        self._label = label
        self._owned: list[tuple[int, str]] = []

    def __enter__(self) -> _OwnedFileDescriptors:
        return self

    def _register(self, fd: int, label: str, /) -> int:
        self._owned.append((fd, label))
        return fd

    def acquire(self, opener: Callable[[], int], label: str, /) -> int:
        fd = opener()
        try:
            return self._register(fd, label)
        except BaseException as primary:
            try:
                os.close(fd)
            except BaseException as cleanup:
                primary.add_note(self._failure_note(label, cleanup))
            raise

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        primary: BaseException | None,
        _traceback: object,
    ) -> bool:
        failures: list[tuple[str, BaseException]] = []
        for fd, label in reversed(self._owned):
            try:
                os.close(fd)
            except BaseException as exc:
                failures.append((label, exc))
        self._owned.clear()
        if not failures:
            return False
        if primary is not None:
            for label, failure in failures:
                primary.add_note(self._failure_note(label, failure))
            return False
        for label, failure in failures:
            if not isinstance(failure, OSError):
                self._add_other_failure_notes(failure, label, failures)
                raise failure
        error = InfrastructureError(f"{self._label} close failed")
        for label, failure in failures:
            error.add_note(self._failure_note(label, failure))
        raise error from failures[0][1]

    def _failure_note(self, label: str, failure: BaseException) -> str:
        return f"{self._label} close failed for {label}: {failure}"

    def _add_other_failure_notes(
        self,
        selected: BaseException,
        selected_label: str,
        failures: list[tuple[str, BaseException]],
    ) -> None:
        skipped_selected = False
        for label, failure in failures:
            if not skipped_selected and label == selected_label and failure is selected:
                skipped_selected = True
                continue
            selected.add_note(self._failure_note(label, failure))


def _duplicate_directory_fd(
    root_fd: object, invalid_message: str, unavailable_message: str, /
) -> int:
    if type(root_fd) is not int or root_fd < 0:
        raise DomainError(invalid_message)
    try:
        return fcntl.fcntl(root_fd, fcntl.F_DUPFD_CLOEXEC, 0)
    except (OSError, OverflowError) as exc:
        raise InfrastructureError(unavailable_message) from exc
