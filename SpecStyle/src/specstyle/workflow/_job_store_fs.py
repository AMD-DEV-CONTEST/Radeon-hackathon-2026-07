"""Descriptor-rooted filesystem primitives for JobStore.

This module knows files, descriptors and atomic rename syscalls.  It does not
interpret workflow bytes or transaction marker phases.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import stat
import sys
from dataclasses import dataclass

READ_CHUNK = 64 * 1024
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC


class CorruptStore(Exception):
    """The namespace or an inode violates the trusted-store contract."""


class StoreIO(Exception):
    """A required filesystem operation failed or is unsupported."""


class DestinationExists(StoreIO):
    """A no-replace publication found an existing destination."""


class RenameUncertain(StoreIO):
    """An atomic rename syscall failed with an outcome that must be reread."""


@dataclass(frozen=True, slots=True)
class Identity:
    dev: int
    ino: int
    uid: int
    mode: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int

    def same_inode(self, other: Identity) -> bool:
        return self.dev == other.dev and self.ino == other.ino


@dataclass(frozen=True, slots=True)
class FileRecord:
    data: bytes
    identity: Identity


def _identity(result: os.stat_result) -> Identity:
    return Identity(
        result.st_dev,
        result.st_ino,
        result.st_uid,
        result.st_mode,
        result.st_nlink,
        result.st_size,
        result.st_mtime_ns,
        result.st_ctime_ns,
    )


def validate_directory(result: os.stat_result, root_dev: int) -> Identity:
    if (
        not stat.S_ISDIR(result.st_mode)
        or result.st_dev != root_dev
        or result.st_uid != os.geteuid()
        or stat.S_IMODE(result.st_mode) & 0o022
    ):
        raise CorruptStore
    return _identity(result)


def validate_file(
    result: os.stat_result, root_dev: int, minimum: int, maximum: int
) -> Identity:
    if (
        not stat.S_ISREG(result.st_mode)
        or result.st_dev != root_dev
        or result.st_uid != os.geteuid()
        or result.st_nlink != 1
        or stat.S_IMODE(result.st_mode) & 0o022
        or not minimum <= result.st_size <= maximum
    ):
        raise CorruptStore
    return _identity(result)


def duplicate_fd(fd: int) -> int:
    try:
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 0)
    except OSError as cause:
        raise StoreIO from cause


def close_owned(fd: int, primary: BaseException | None = None) -> None:
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError as cause:
        if primary is None:
            raise StoreIO from cause


def close_quietly(fd: int) -> None:
    try:
        close_owned(fd, sys.exception())
    except StoreIO:
        pass


def directory_names(fd: int) -> tuple[str, ...]:
    try:
        with os.scandir(fd) as entries:
            names = tuple(entry.name for entry in entries)
    except OSError as cause:
        raise StoreIO from cause
    if any(type(name) is not str for name in names):
        raise CorruptStore
    return names


def named_identity(parent_fd: int, name: str, root_dev: int) -> Identity:
    try:
        result = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise
    except OSError as cause:
        raise CorruptStore from cause
    return validate_directory(result, root_dev)


def open_directory(
    parent_fd: int, name: str, root_dev: int, *, missing_ok: bool = False
) -> tuple[int, Identity] | None:
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    except OSError as cause:
        raise CorruptStore from cause
    fd = -1
    try:
        expected = validate_directory(before, root_dev)
        fd = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
        opened = validate_directory(os.fstat(fd), root_dev)
        after = named_identity(parent_fd, name, root_dev)
        if not expected.same_inode(opened) or not expected.same_inode(after):
            raise CorruptStore
        return fd, opened
    except FileNotFoundError:
        close_quietly(fd)
        if missing_ok:
            return None
        raise
    except BaseException:
        close_quietly(fd)
        raise


def open_or_create_directory(
    parent_fd: int, name: str, root_dev: int
) -> tuple[int, Identity]:
    opened = open_directory(parent_fd, name, root_dev, missing_ok=True)
    if opened is not None:
        return opened
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        fsync_directory(parent_fd)
    except FileExistsError:
        pass
    except OSError as cause:
        raise StoreIO from cause
    opened = open_directory(parent_fd, name, root_dev, missing_ok=True)
    if opened is None:
        raise CorruptStore
    return opened


def _read_exact(fd: int, size: int) -> bytes:
    parts: list[bytes] = []
    remaining = size
    while remaining:
        amount = min(remaining, READ_CHUNK)
        try:
            part = os.read(fd, amount)
        except OSError as cause:
            raise StoreIO from cause
        if type(part) is not bytes or not part or len(part) > amount:
            raise CorruptStore
        parts.append(part)
        remaining -= len(part)
    try:
        if os.read(fd, 1):
            raise CorruptStore
    except OSError as cause:
        raise StoreIO from cause
    return b"".join(parts)


def read_file(
    directory_fd: int,
    name: str,
    minimum: int,
    maximum: int,
    root_dev: int,
    *,
    missing_ok: bool = False,
) -> FileRecord | None:
    try:
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise CorruptStore from None
    except OSError as cause:
        raise CorruptStore from cause
    before = validate_file(named, root_dev, minimum, maximum)
    try:
        fd = os.open(name, READ_FLAGS, dir_fd=directory_fd)
    except OSError as cause:
        raise CorruptStore from cause
    try:
        opened = validate_file(os.fstat(fd), root_dev, minimum, maximum)
        if not before.same_inode(opened):
            raise CorruptStore
        data = _read_exact(fd, opened.size)
        after = validate_file(
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False),
            root_dev,
            minimum,
            maximum,
        )
        if opened != after:
            raise CorruptStore
        return FileRecord(data, opened)
    except OSError as cause:
        raise CorruptStore from cause
    finally:
        close_owned(fd, sys.exception())


def inspect_file(
    directory_fd: int,
    name: str,
    minimum: int,
    maximum: int,
    root_dev: int,
    *,
    missing_ok: bool = False,
) -> Identity | None:
    try:
        result = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise CorruptStore from None
    except OSError as cause:
        raise CorruptStore from cause
    return validate_file(result, root_dev, minimum, maximum)


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        try:
            written = os.write(fd, data[offset:])
        except OSError as cause:
            raise StoreIO from cause
        if type(written) is not int or not 0 < written <= len(data) - offset:
            raise StoreIO
        offset += written


def write_slot(
    directory_fd: int, name: str, data: bytes, maximum: int, root_dev: int
) -> Identity:
    fd = -1
    try:
        fd = os.open(name, WRITE_FLAGS, 0o600, dir_fd=directory_fd)
        validate_file(os.fstat(fd), root_dev, 0, maximum)
        os.ftruncate(fd, 0)
        _write_all(fd, data)
        os.fsync(fd)
        identity = validate_file(os.fstat(fd), root_dev, len(data), len(data))
        named = validate_file(
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False),
            root_dev,
            len(data),
            len(data),
        )
        if not identity.same_inode(named):
            raise CorruptStore
        return identity
    except (CorruptStore, StoreIO):
        raise
    except OSError as cause:
        raise StoreIO from cause
    finally:
        close_owned(fd, sys.exception())


def fsync_directory(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError as cause:
        raise StoreIO from cause


def _atomic_backend():
    libc = ctypes.CDLL(None, use_errno=True)
    if hasattr(libc, "renameat2"):
        return libc.renameat2, 1, 2
    if hasattr(libc, "renameatx_np"):
        return libc.renameatx_np, 4, 2
    return None


def _rename(directory_fd: int, old: str, new: str, flag_index: int) -> None:
    backend = _atomic_backend()
    if backend is None:
        raise StoreIO
    function, noreplace, exchange = backend
    flags = noreplace if flag_index == 0 else exchange
    result = function(
        directory_fd, os.fsencode(old), directory_fd, os.fsencode(new), flags
    )
    if result == 0:
        return
    number = ctypes.get_errno()
    if flag_index == 0 and number == errno.EEXIST:
        raise DestinationExists
    raise RenameUncertain from OSError(number, os.strerror(number))


def rename_noreplace(directory_fd: int, old: str, new: str) -> None:
    _rename(directory_fd, old, new, 0)


def rename_exchange(directory_fd: int, old: str, new: str) -> None:
    _rename(directory_fd, old, new, 1)
