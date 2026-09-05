"""Crash-safe, revisioned JSON settings documents.

This module deliberately owns only physical document publication.  A domain
settings service owns validation, redaction, provider semantics, and the meaning
of a document.  The store consequently has no knowledge of any product feature
or document name.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from uuid import uuid4

from ..exceptions import XenixError

_ENVELOPE_MARKER: Final = "_xenix_settings_store"
_ENVELOPE_SCHEMA_VERSION: Final = 1
_MAX_DOCUMENT_ID_LENGTH: Final = 120


class SettingsStoreError(XenixError):
    """Base failure for physical settings document operations."""


class SettingsStoreLockedError(SettingsStoreError):
    """Another process already owns the settings-root writer fence."""


class SettingsDocumentError(SettingsStoreError):
    """A settings document is unreadable or has an unsupported envelope."""


class SettingsConflictError(SettingsStoreError):
    """A compare-and-swap command was based on an obsolete document revision."""

    def __init__(self, document_id: str, expected_revision: int, actual_revision: int) -> None:
        super().__init__(
            f"Settings document '{document_id}' changed before this command could be applied."
        )
        self.document_id = document_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class SettingsPublicationError(SettingsStoreError):
    """Atomic publication could not complete while preserving the old document."""


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    """An immutable view of one document at one per-document revision."""

    payload: Any
    revision: int


@dataclass(frozen=True, slots=True)
class SettingsChange:
    """Opaque post-commit notification; it intentionally carries no payload."""

    document_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class SettingsCasResult:
    """Result of one compare-and-swap command."""

    snapshot: SettingsSnapshot
    changed: bool


class SettingsRootLock:
    """A process-lifetime acquired lock for one settings root."""

    def close(self) -> None:
        raise NotImplementedError


class SettingsRootLockAdapter:
    """Injectable OS-fencing seam; production uses standard-library primitives."""

    def acquire(self, lock_path: Path, writer_id: str) -> SettingsRootLock:
        raise NotImplementedError


class _PlatformSettingsRootLock(SettingsRootLock):
    def __init__(self, file_handle: Any, *, windows: bool) -> None:
        self._file_handle = file_handle
        self._windows = windows
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._file_handle.seek(0)
            if self._windows:
                import msvcrt

                msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._file_handle.close()


class PlatformSettingsRootLockAdapter(SettingsRootLockAdapter):
    """Cross-platform non-blocking file fence using only the standard library."""

    def acquire(self, lock_path: Path, writer_id: str) -> SettingsRootLock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = lock_path.open("a+b")
        except OSError as exc:
            raise SettingsStoreLockedError("Settings writer fence could not be opened.") from exc

        windows = os.name == "nt"
        try:
            # msvcrt locks a byte range and requires that the locked byte exists.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if windows:
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # This is diagnostic-only ownership evidence.  The OS lock, not this
            # payload, grants authority to write.
            handle.seek(0)
            handle.write((writer_id + "\n").encode("ascii"))
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        except (ImportError, OSError) as exc:
            handle.close()
            raise SettingsStoreLockedError(
                "Another Xenix process already owns this settings root."
            ) from exc
        return _PlatformSettingsRootLock(handle, windows=windows)


class SettingsSubscription:
    """Thread-safe, payload-free change queue returned by :meth:`SettingsStore.watch`."""

    def __init__(self, document_id: str) -> None:
        self._document_id = document_id
        self._condition = threading.Condition()
        self._changes: deque[SettingsChange] = deque()
        self._closed = False

    @property
    def document_id(self) -> str:
        return self._document_id

    def next(self, timeout: float | None = None) -> SettingsChange | None:
        """Return the next observed revision, or ``None`` after timeout/close."""

        with self._condition:
            if not self._changes and not self._closed:
                self._condition.wait(timeout)
            if self._changes:
                return self._changes.popleft()
            return None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _publish(self, change: SettingsChange) -> None:
        with self._condition:
            if self._closed:
                return
            self._changes.append(change)
            self._condition.notify_all()


class SettingsStore:
    """One app-lifetime physical writer for revisioned JSON settings documents.

    A store fences the entire root because a desktop process is the only writer
    authority for its own configuration root.  Revisions are nevertheless
    independent per document; they must never be compared across document IDs.
    """

    def __init__(
        self,
        root: Path,
        *,
        lock_adapter: SettingsRootLockAdapter | None = None,
    ) -> None:
        self._root = Path(root)
        self._writer_id = uuid4().hex
        self._thread_lock = threading.RLock()
        self._subscriptions: dict[str, set[SettingsSubscription]] = {}
        adapter = lock_adapter or PlatformSettingsRootLockAdapter()
        self._root_lock = adapter.acquire(self._root / ".xenix-settings-store.lock", self._writer_id)
        self._closed = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def writer_id(self) -> str:
        return self._writer_id

    def close(self) -> None:
        with self._thread_lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = [subscription for group in self._subscriptions.values() for subscription in group]
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.close()
        self._root_lock.close()

    def __enter__(self) -> SettingsStore:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def load(self, document_id: str) -> SettingsSnapshot:
        """Read one immutable snapshot, treating an absent file as revision zero."""

        with self._thread_lock:
            self._require_open()
            return self._load_locked(document_id)

    def compare_and_swap(
        self,
        document_id: str,
        expected_revision: int,
        transform: Callable[[Any], Any],
    ) -> SettingsCasResult:
        """Apply one semantic command only if its source revision is still current."""

        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("Expected settings revision must be a non-negative integer.")
        if not callable(transform):
            raise TypeError("Settings transform must be callable.")

        change: SettingsChange | None = None
        subscribers: tuple[SettingsSubscription, ...] = ()
        with self._thread_lock:
            self._require_open()
            current = self._load_locked(document_id)
            if expected_revision != current.revision:
                raise SettingsConflictError(document_id, expected_revision, current.revision)

            # The transform cannot mutate the committed object or retain an alias
            # to future document state.
            candidate = _canonical_json_value(transform(current.payload))
            if candidate == _thaw_json_value(current.payload):
                return SettingsCasResult(snapshot=current, changed=False)

            next_snapshot = SettingsSnapshot(
                payload=_freeze_json_value(candidate),
                revision=current.revision + 1,
            )
            self._publish_locked(document_id, next_snapshot)
            change = SettingsChange(document_id=document_id, revision=next_snapshot.revision)
            subscribers = tuple(self._subscriptions.get(document_id, ()))

        # Publication is durable before observers see it; callbacks also run
        # outside the writer lock so a UI/domain refresh cannot deadlock CAS.
        for subscription in subscribers:
            subscription._publish(change)
        return SettingsCasResult(snapshot=next_snapshot, changed=True)

    def watch(self, document_id: str, after_revision: int) -> SettingsSubscription:
        """Subscribe without a missed-update window.

        If the document already advanced beyond ``after_revision``, the returned
        subscription contains the latest opaque revision immediately.  Future
        commits are registered while the same writer lock is held.
        """

        if not isinstance(after_revision, int) or isinstance(after_revision, bool) or after_revision < 0:
            raise ValueError("Settings revision must be a non-negative integer.")
        with self._thread_lock:
            self._require_open()
            current = self._load_locked(document_id)
            subscription = SettingsSubscription(document_id)
            self._subscriptions.setdefault(document_id, set()).add(subscription)
            if current.revision > after_revision:
                subscription._publish(SettingsChange(document_id, current.revision))
            return subscription

    def unwatch(self, subscription: SettingsSubscription) -> None:
        with self._thread_lock:
            group = self._subscriptions.get(subscription.document_id)
            if group is not None:
                group.discard(subscription)
                if not group:
                    self._subscriptions.pop(subscription.document_id, None)
        subscription.close()

    def _load_locked(self, document_id: str) -> SettingsSnapshot:
        path = self._document_path(document_id)
        if not path.exists():
            return SettingsSnapshot(payload=_freeze_json_value({}), revision=0)
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SettingsDocumentError(f"Settings document '{document_id}' could not be read.") from exc
        revision, payload = _decode_document(parsed)
        return SettingsSnapshot(payload=_freeze_json_value(payload), revision=revision)

    def _publish_locked(self, document_id: str, snapshot: SettingsSnapshot) -> None:
        path = self._document_path(document_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            _ENVELOPE_MARKER: {"schema_version": _ENVELOPE_SCHEMA_VERSION, "revision": snapshot.revision},
            "payload": _thaw_json_value(snapshot.payload),
        }
        try:
            serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
            temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                with temporary_path.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, path)
                _fsync_directory(path.parent)
            finally:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        except (OSError, TypeError, ValueError, UnicodeError) as exc:
            raise SettingsPublicationError(
                f"Settings document '{document_id}' could not be published safely."
            ) from exc

    def _document_path(self, document_id: str) -> Path:
        normalized = _validate_document_id(document_id)
        return self._root / normalized

    def _require_open(self) -> None:
        if self._closed:
            raise SettingsStoreError("SettingsStore is closed.")


def _validate_document_id(document_id: str) -> str:
    if not isinstance(document_id, str):
        raise TypeError("Settings document ID must be text.")
    normalized = document_id.strip()
    if (
        not normalized
        or len(normalized) > _MAX_DOCUMENT_ID_LENGTH
        or normalized != document_id
        or "/" in normalized
        or "\\" in normalized
        or normalized in {".", ".."}
        or not normalized.endswith(".json")
    ):
        raise ValueError("Settings document ID must be one simple .json file name.")
    return normalized


def _decode_document(value: Any) -> tuple[int, Any]:
    if not isinstance(value, dict) or _ENVELOPE_MARKER not in value:
        # Existing bare JSON documents are revision zero until their first
        # successful mutation.  Canonicalization also rejects non-JSON values.
        return 0, _canonical_json_value(value)

    if set(value) != {_ENVELOPE_MARKER, "payload"}:
        raise SettingsDocumentError("Settings document envelope has unsupported fields.")
    marker = value.get(_ENVELOPE_MARKER)
    if not isinstance(marker, dict) or set(marker) != {"schema_version", "revision"}:
        raise SettingsDocumentError("Settings document envelope is invalid.")
    if marker.get("schema_version") != _ENVELOPE_SCHEMA_VERSION:
        raise SettingsDocumentError("Settings document envelope schema is unsupported.")
    revision = marker.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise SettingsDocumentError("Settings document revision is invalid.")
    return revision, _canonical_json_value(value["payload"])


def _canonical_json_value(value: Any) -> Any:
    """Return a detached JSON value or fail before an unsafe publication."""

    try:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return json.loads(serialized)
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise SettingsDocumentError("Settings payload must be finite JSON data.") from exc


def _freeze_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json_value(item) for item in value)
    return value


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    # A frozen scalar is already immutable, but deepcopy keeps the public
    # boundary explicit if a future JSON-compatible type is introduced.
    return copy.deepcopy(value)


def _fsync_directory(path: Path) -> None:
    """Persist a rename on POSIX; Windows has no stdlib directory fsync equivalent."""

    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "PlatformSettingsRootLockAdapter",
    "SettingsCasResult",
    "SettingsChange",
    "SettingsConflictError",
    "SettingsDocumentError",
    "SettingsPublicationError",
    "SettingsRootLock",
    "SettingsRootLockAdapter",
    "SettingsSnapshot",
    "SettingsStore",
    "SettingsStoreError",
    "SettingsStoreLockedError",
    "SettingsSubscription",
]
