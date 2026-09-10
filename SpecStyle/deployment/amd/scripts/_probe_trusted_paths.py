"""Descriptor-anchored trusted path operations for the AMD probe."""

from __future__ import annotations

import os
import stat
from typing import Any


MAX_COMPONENTS = 64
SAFE_FLAGS = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | SAFE_FLAGS
READ_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | SAFE_FLAGS
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | SAFE_FLAGS
Chain = list[tuple[int, str, os.stat_result]]


class TrustedPathError(Exception): ...


def canonical_parts(raw: str) -> tuple[str, ...]:
    if type(raw) is not str or "\0" in raw or not raw.startswith("/"):
        raise TrustedPathError("invalid path")
    parts = tuple(raw[1:].split("/"))
    if not 1 <= len(parts) <= MAX_COMPONENTS or any(
        part in ("", ".", "..") for part in parts
    ):
        raise TrustedPathError("invalid path")
    return parts


def is_canonical_absolute(raw: object) -> bool:
    try:
        canonical_parts(raw)  # type: ignore[arg-type]
    except TrustedPathError:
        return False
    return True


def object_state(info: os.stat_result) -> tuple[Any, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
    )


def same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return object_state(left) == object_state(right)


def same_leaf(left: os.stat_result, right: os.stat_result) -> bool:
    return same_object(left, right) and (
        left.st_nlink,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (right.st_nlink, right.st_size, right.st_mtime_ns, right.st_ctime_ns)


def safe_root(info: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) & 0o022 == 0
    )


def trusted_transition(
    parent: os.stat_result, child: os.stat_result, euid: int
) -> bool:
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid not in (0, euid)
        or child.st_uid not in (0, euid)
    ):
        return False
    permissions = stat.S_IMODE(parent.st_mode)
    if permissions & 0o022 == 0:
        return True
    return parent.st_uid == 0 and permissions == 0o1777


def fixed_error(caught: Exception) -> TrustedPathError:
    if isinstance(caught, TrustedPathError):
        return caught
    return TrustedPathError("trusted path failed")


def close_once(fd: int, error: TrustedPathError | None) -> TrustedPathError | None:
    try:
        os.close(fd)
    except OSError:
        if error is None:
            error = TrustedPathError("close failed")
        else:
            error.add_note("cleanup close failed")
    return error


def close_chain(
    chain: Chain, error: TrustedPathError | None = None
) -> TrustedPathError | None:
    while chain:
        fd, _, _ = chain.pop()
        error = close_once(fd, error)
    return error


def open_chain(raw: str) -> tuple[Chain, int, str]:
    parts, euid = canonical_parts(raw), os.geteuid()
    directories, leaf = parts[:-1], parts[-1]
    chain: Chain = []
    child: int | None = None
    try:
        before = os.stat("/", follow_symlinks=False)
        child = os.open("/", DIRECTORY_FLAGS)
        opened, after = os.fstat(child), os.stat("/", follow_symlinks=False)
        if not same_object(before, opened) or not same_object(opened, after):
            raise TrustedPathError("root changed")
        if not safe_root(opened):
            raise TrustedPathError("unsafe root")
        chain.append((child, "", opened))
        child = None
        for name in directories:
            parent_fd, _, parent_info = chain[-1]
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            child = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
            opened = os.fstat(child)
            after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if not same_object(before, opened) or not same_object(opened, after):
                raise TrustedPathError("component changed")
            if not trusted_transition(parent_info, opened, euid):
                raise TrustedPathError("unsafe component")
            chain.append((child, name, opened))
            child = None
        return chain, euid, leaf
    except Exception as caught:
        error = fixed_error(caught)
        if child is not None:
            error = close_once(child, error)
        error = close_chain(chain, error)
        raise error from None


def validate_chain(chain: Chain, euid: int) -> None:
    root_fd, _, root_info = chain[0]
    root_named, root_opened = os.stat("/", follow_symlinks=False), os.fstat(root_fd)
    if not same_object(root_info, root_named) or not same_object(
        root_named, root_opened
    ):
        raise TrustedPathError("root changed")
    if not safe_root(root_opened):
        raise TrustedPathError("unsafe root")
    for position in range(1, len(chain)):
        parent_fd, _, parent_saved = chain[position - 1]
        child_fd, name, child_saved = chain[position]
        parent_opened, child_opened = os.fstat(parent_fd), os.fstat(child_fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not same_object(parent_saved, parent_opened):
            raise TrustedPathError("parent changed")
        if not same_object(child_saved, child_opened) or not same_object(
            named, child_opened
        ):
            raise TrustedPathError("component changed")
        if not trusted_transition(parent_opened, child_opened, euid):
            raise TrustedPathError("unsafe component")


def exact_read(fd: int, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = os.read(fd, min(65536, size - len(data)))
        if not chunk:
            raise TrustedPathError("short read")
        data.extend(chunk)
    if os.read(fd, 1):
        raise TrustedPathError("long read")
    return bytes(data)


def baseline_info(info: os.stat_result, euid: int, maximum: int) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == euid
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) in (0o400, 0o600)
        and info.st_size <= maximum
    )


def evidence_info(info: os.stat_result, euid: int, size: int) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == euid
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_size == size
    )


def safe_evidence_parent(info: os.stat_result, euid: int) -> bool:
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == euid
        and stat.S_IMODE(info.st_mode) & 0o022 == 0
    )


def write_all(fd: int, data: bytes) -> None:
    sent = 0
    while sent < len(data):
        try:
            count = os.write(fd, data[sent:])
        except OSError:
            raise TrustedPathError("write failed") from None
        remaining = len(data) - sent
        if type(count) is not int or not 0 < count <= remaining:
            raise TrustedPathError("short write")
        sent += count


def read_baseline(raw: str, maximum: int) -> str:
    chain: Chain = []
    fd: int | None = None
    try:
        chain, euid, leaf = open_chain(raw)
        parent_fd, _, parent_info = chain[-1]
        before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        fd = os.open(leaf, READ_FLAGS, dir_fd=parent_fd)
        opened = os.fstat(fd)
        after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not same_leaf(before, opened) or not same_leaf(opened, after):
            raise TrustedPathError("leaf changed")
        if not trusted_transition(parent_info, opened, euid):
            raise TrustedPathError("unsafe leaf parent")
        if not baseline_info(opened, euid, maximum):
            raise TrustedPathError("unsafe baseline")
        data, ended = exact_read(fd, opened.st_size), os.fstat(fd)
        if not same_leaf(opened, ended):
            raise TrustedPathError("baseline changed")
        close_fd, fd = fd, None
        error = close_once(close_fd, None)
        if error is not None:
            raise error
        named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not same_leaf(ended, named):
            raise TrustedPathError("leaf changed")
        validate_chain(chain, euid)
        text = data.decode("utf-8")
        error = close_chain(chain)
        if error is not None:
            raise error
        return text
    except Exception as caught:
        error = fixed_error(caught)
        if fd is not None:
            close_fd, fd = fd, None
            error = close_once(close_fd, error)
        error = close_chain(chain, error)
        raise error from None


def write_evidence(raw: str, data: bytes, maximum: int) -> None:
    chain: Chain = []
    fd: int | None = None
    try:
        if type(data) is not bytes or len(data) > maximum:
            raise TrustedPathError("unsafe data")
        chain, euid, leaf = open_chain(raw)
        parent_fd, _, parent_info = chain[-1]
        if not safe_evidence_parent(parent_info, euid):
            raise TrustedPathError("unsafe evidence parent")
        try:
            os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise TrustedPathError("evidence exists")
        fd = os.open(leaf, CREATE_FLAGS, 0o600, dir_fd=parent_fd)
        opened = os.fstat(fd)
        named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not same_leaf(opened, named) or not evidence_info(opened, euid, 0):
            raise TrustedPathError("unsafe evidence")
        write_all(fd, data)
        os.fsync(fd)
        ended = os.fstat(fd)
        if not evidence_info(ended, euid, len(data)):
            raise TrustedPathError("unsafe evidence")
        close_fd, fd = fd, None
        error = close_once(close_fd, None)
        if error is not None:
            raise error
        os.fsync(parent_fd)
        named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not same_leaf(ended, named):
            raise TrustedPathError("evidence changed")
        validate_chain(chain, euid)
        error = close_chain(chain)
        if error is not None:
            raise error
    except Exception as caught:
        error = fixed_error(caught)
        if fd is not None:
            close_fd, fd = fd, None
            error = close_once(close_fd, error)
        error = close_chain(chain, error)
        raise error from None
