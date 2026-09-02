from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePath, PureWindowsPath
import re
import stat
import tempfile
import time
from threading import Event, Lock
from typing import Any, Callable


PROJECT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
EPISODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ATOMIC_WRITE_LOCK = Lock()


class DramaCancelled(RuntimeError):
    """Raised at a cooperative cancellation boundary."""


class ProjectBusy(RuntimeError):
    """Raised when another process owns the same project."""


class CancellationToken:
    def __init__(self, callback: Callable[[], None] | None = None) -> None:
        self._event = Event()
        self._callback = callback

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self._event.is_set():
            raise DramaCancelled("drama job was cancelled")
        if self._callback is not None:
            self._callback()


def atomic_write_text(path: str | Path, text: str) -> Path:
    target = Path(path)
    with _ATOMIC_WRITE_LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(8):
                try:
                    os.replace(temporary, target)
                    break
                except PermissionError:
                    if os.name != "nt" or attempt == 7:
                        raise
                    # Windows virus scanners and readers can briefly retain a
                    # handle to the destination.  The write remains atomic;
                    # retry only the final rename with a bounded backoff.
                    time.sleep(0.01 * (attempt + 1))
            return target
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def atomic_write_json(path: str | Path, value: Any) -> Path:
    return atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2),
    )


def validate_project_key(value: str) -> str:
    if not PROJECT_KEY_PATTERN.fullmatch(value):
        raise ValueError("invalid project key")
    return value


def validate_episode_id(value: object) -> str:
    if not isinstance(value, str) or not EPISODE_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid episode identifier")
    return value


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    reparse = getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    )
    return path.is_symlink() or bool(reparse)


def safe_project_root(projects_root: str | Path, project_key: str) -> Path:
    root = Path(projects_root).resolve(strict=True)
    key = validate_project_key(project_key)
    candidate = root / key
    resolved_parent = candidate.parent.resolve(strict=True)
    if resolved_parent != root:
        raise ValueError("project path escaped runtime root")
    if (candidate.exists() or candidate.is_symlink()) and _is_link_or_reparse(candidate):
        raise ValueError("project root must not be a symlink or reparse point")
    return candidate


@dataclass(frozen=True, slots=True)
class ProjectPathCodec:
    project_root: Path
    legacy_roots: tuple[Path, ...] = ()

    def _windows_relative(self, value: str | Path) -> Path | None:
        raw = os.fspath(value)
        windows = PureWindowsPath(raw)
        if not windows.drive and not windows.is_absolute():
            if "\\" in raw:
                return Path(*windows.parts)
            return None

        for legacy_root in self.legacy_roots:
            legacy_windows = PureWindowsPath(os.fspath(legacy_root))
            if not legacy_windows.drive:
                continue
            try:
                relative = windows.relative_to(legacy_windows)
            except ValueError:
                continue
            return Path(*relative.parts)

        project_name = self.project_root.name.casefold()
        matching_indexes = [
            index
            for index, part in enumerate(windows.parts)
            if part.casefold() == project_name
        ]
        if not matching_indexes:
            raise ValueError("absolute path is outside known project roots")
        return Path(*windows.parts[matching_indexes[-1] + 1 :])

    def encode(self, value: str | Path) -> str:
        windows_relative = self._windows_relative(value)
        if windows_relative is not None:
            return self._bounded(windows_relative).relative_to(
                self.project_root.resolve(strict=False)
            ).as_posix()
        path = Path(value)
        if not path.is_absolute():
            normalized = PurePath(path)
            if ".." in normalized.parts:
                raise ValueError("relative path escaped project root")
            return normalized.as_posix()
        resolved = path.resolve(strict=False)
        root = self.project_root.resolve(strict=False)
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            for legacy_root in self.legacy_roots:
                try:
                    return resolved.relative_to(legacy_root.resolve(strict=False)).as_posix()
                except ValueError:
                    continue
        raise ValueError("path is outside the project root")

    def decode(self, value: str | Path) -> Path:
        windows_relative = self._windows_relative(value)
        if windows_relative is not None:
            return self._bounded(windows_relative)
        path = Path(value)
        if path.is_absolute():
            candidates = (self.project_root, *self.legacy_roots)
            resolved = path.resolve(strict=False)
            for candidate in candidates:
                try:
                    relative = resolved.relative_to(candidate.resolve(strict=False))
                    return self._bounded(relative)
                except ValueError:
                    continue
            raise ValueError("absolute path is outside known project roots")
        return self._bounded(path)

    def _bounded(self, relative: str | Path) -> Path:
        if ".." in PurePath(relative).parts:
            raise ValueError("path escaped project root")
        root = self.project_root.resolve(strict=False)
        candidate = (root / relative).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError("path escaped project root") from None
        current = root
        for part in Path(relative).parts:
            current = current / part
            if not current.exists():
                continue
            if _is_link_or_reparse(current):
                raise ValueError("path traversed a symlink or reparse point")
        return candidate


class ProjectLock(AbstractContextManager["ProjectLock"]):
    def __init__(self, project_root: str | Path) -> None:
        self.path = Path(project_root) / ".drama.lock"
        self._descriptor: int | None = None

    def __enter__(self) -> "ProjectLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.write(self._descriptor, str(os.getpid()).encode("ascii"))
            os.fsync(self._descriptor)
        except FileExistsError:
            raise ProjectBusy("project already has an active drama job") from None
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
        self.path.unlink(missing_ok=True)
