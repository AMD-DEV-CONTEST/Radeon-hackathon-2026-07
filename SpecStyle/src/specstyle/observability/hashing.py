"""SHA-256 calculation for constrained inputs."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path
from typing import Protocol, runtime_checkable

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError

DEFAULT_HASH_CHUNK_SIZE = 1_048_576
MAX_HASH_CHUNK_SIZE = 16_777_216
_CONTROL = frozenset(range(32)) | {127}
_PATH_ERRNOS = {
    errno.ENOENT,
    errno.ENOTDIR,
    errno.ELOOP,
    errno.ENAMETOOLONG,
    errno.EISDIR,
}
if hasattr(errno, "EMLINK"):
    _PATH_ERRNOS.add(errno.EMLINK)


@runtime_checkable
class BinaryReadable(Protocol):
    def read(self, size: int, /) -> bytes: ...


def _chunk_size(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_HASH_CHUNK_SIZE:
        raise DomainError("invalid hash chunk size")
    return value


def hash_bytes(data: bytes, /) -> Sha256:
    if type(data) is not bytes:
        raise DomainError("invalid hash bytes")
    return Sha256(hashlib.sha256(data).hexdigest())


def hash_stream(
    stream: BinaryReadable, /, *, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE
) -> Sha256:
    size = _chunk_size(chunk_size)
    digest = hashlib.sha256()
    while True:
        try:
            block = stream.read(size)
        except Exception as error:
            raise InfrastructureError("hash stream read failed") from error
        if type(block) is not bytes or len(block) > size:
            raise DomainError("invalid hash stream block")
        if not block:
            return Sha256(digest.hexdigest())
        digest.update(block)


def _contains_control(text: str) -> bool:
    return any(ord(character) in _CONTROL for character in text)


def _root_text(root: object) -> str:
    if not isinstance(root, Path):
        raise DomainError("hash path is invalid")
    text = str(root)
    if _contains_control(text):
        raise DomainError("hash path is invalid")
    return text


def _relative_text(relative_path: str | Path) -> tuple[str, ...]:
    if type(relative_path) is str:
        text = relative_path
    elif isinstance(relative_path, Path):
        text = str(relative_path)
    else:
        raise DomainError("hash path is invalid")
    if not text or _contains_control(text) or "\\" in text or text.startswith("/"):
        raise DomainError("hash path is invalid")
    if len(text) >= 2 and text[0].isalpha() and text[1] == ":":
        raise DomainError("hash path is invalid")
    parts = tuple(text.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise DomainError("hash path is invalid")
    return parts


def _secure_flags() -> tuple[int, int]:
    names = ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK")
    try:
        supports = getattr(os, "supports_dir_fd", ())
        supported = os.open in supports
        flags = tuple(getattr(os, name, 0) for name in names)
    except Exception:
        raise InfrastructureError("secure file hashing is unavailable") from None
    if os.name != "posix" or not supported or any(not flag for flag in flags):
        raise InfrastructureError("secure file hashing is unavailable")
    directory = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    leaf = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    return directory, leaf


def _path_error(error: OSError | ValueError) -> None:
    if isinstance(error, ValueError) or getattr(error, "errno", None) in _PATH_ERRNOS:
        raise DomainError("hash path is invalid") from None
    raise InfrastructureError("cannot access hash file") from None


def _open(path: str, flags: int, parent: int | None = None) -> int:
    try:
        return (
            os.open(path, flags)
            if parent is None
            else os.open(path, flags, dir_fd=parent)
        )
    except (OSError, ValueError) as error:
        _path_error(error)
    raise AssertionError("unreachable")


def _fstat(fd: int, directory: bool) -> os.stat_result:
    try:
        result = os.fstat(fd)
    except OSError as error:
        raise InfrastructureError("cannot access hash file") from error
    if (directory and not stat.S_ISDIR(result.st_mode)) or (
        not directory and not stat.S_ISREG(result.st_mode)
    ):
        raise DomainError("hash path is invalid") from None
    return result


def _same_stat(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns) == (
        second.st_dev,
        second.st_ino,
        second.st_size,
        second.st_mtime_ns,
    )


def _read_fd(fd: int, chunk_size: int, initial: os.stat_result) -> Sha256:
    digest = hashlib.sha256()
    total = 0
    while True:
        try:
            block = os.read(fd, chunk_size)
        except OSError as error:
            raise InfrastructureError("cannot read hash file") from error
        total += len(block)
        if not block:
            break
        digest.update(block)
    try:
        final = os.fstat(fd)
    except OSError as error:
        raise InfrastructureError("cannot read hash file") from error
    if total != initial.st_size or not _same_stat(initial, final):
        raise InfrastructureError("file changed while hashing")
    return Sha256(digest.hexdigest())


def _close(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def hash_file(
    allowed_root: Path,
    relative_path: str | Path,
    /,
    *,
    chunk_size: int = DEFAULT_HASH_CHUNK_SIZE,
) -> Sha256:
    """Safely hash a regular file beneath a trusted root via a POSIX openat chain."""
    size = _chunk_size(chunk_size)
    root = _root_text(allowed_root)
    parts = _relative_text(relative_path)
    directory_flags, leaf_flags = _secure_flags()
    parent: int | None = None
    leaf: int | None = None
    try:
        parent = _open(root, directory_flags)
        _fstat(parent, directory=True)
        for component in parts[:-1]:
            child = _open(component, directory_flags, parent)
            try:
                _fstat(child, directory=True)
            except Exception:
                _close(child)
                raise
            _close(parent)
            parent = child
        leaf = _open(parts[-1], leaf_flags, parent)
        return _read_fd(leaf, size, _fstat(leaf, directory=False))
    finally:
        _close(leaf)
        _close(parent)
