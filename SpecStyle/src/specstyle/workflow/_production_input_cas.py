"""Linux anonymous-inode publication for normalized production style assets."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import os
import re
import stat
import sys
from typing import Any

from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.content_assets import _validate_png

_MAX_BYTES = 32 * 1024 * 1024
_READ_BYTES = 1024 * 1024
_PROC_SUPER_MAGIC = 0x9FA0
_AT_SYMLINK_FOLLOW = 0x400
_AT_EMPTY_PATH = 0x1000
_FALLBACK_ERRNOS = {
    errno.ENOENT,
    errno.EPERM,
    errno.EACCES,
    errno.EINVAL,
    errno.EOPNOTSUPP,
}
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _domain() -> DomainError:
    return DomainError("invalid production job input")


def _infra() -> InfrastructureError:
    return InfrastructureError("production job input unavailable")


class _StatFs(ctypes.Structure):
    _fields_ = [
        ("f_type", ctypes.c_long),
        ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong),
        ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong),
        ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong),
        ("f_fsid", ctypes.c_int * 2),
        ("f_namelen", ctypes.c_long),
        ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long),
        ("f_spare", ctypes.c_long * 4),
    ]


class _LinuxBackend:
    platform = sys.platform

    def geteuid(self) -> int:
        return os.geteuid()

    def dup(self, fd: int) -> int:
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 0)

    def fstat(self, fd: int) -> os.stat_result:
        return os.fstat(fd)

    def mkdir(self, parent: int, name: str, mode: int) -> None:
        os.mkdir(name, mode, dir_fd=parent)

    def open_dir(self, parent: int, name: str) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        return os.open(name, flags, dir_fd=parent)

    def stat_at(self, parent: int, name: str, *, follow: bool) -> os.stat_result:
        return os.stat(name, dir_fd=parent, follow_symlinks=follow)

    def open_tmp(self, parent: int) -> int:
        flag = getattr(os, "O_TMPFILE", None)
        if flag is None:
            raise OSError(errno.ENOSYS, "anonymous files unsupported")
        return os.open(".", flag | os.O_RDWR | os.O_CLOEXEC, 0o600, dir_fd=parent)

    def fchmod(self, fd: int, mode: int) -> None:
        os.fchmod(fd, mode)

    def write(self, fd: int, data: memoryview) -> int:
        return os.write(fd, data)

    def pread(self, fd: int, size: int, offset: int) -> bytes:
        return os.pread(fd, size, offset)

    def fsync(self, fd: int) -> None:
        os.fsync(fd)

    def open_file(self, parent: int, name: str) -> int:
        return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)

    def direct_link(self, tmp: int, parent: int, name: str) -> None:
        _linkat(tmp, "", parent, name, _AT_EMPTY_PATH)

    def open_proc(self) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        return os.open("/proc/self/fd", flags)

    def fstatfs_type(self, fd: int) -> int:
        libc = ctypes.CDLL(None, use_errno=True)
        fstatfs = libc.fstatfs
        fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_StatFs)]
        fstatfs.restype = ctypes.c_int
        value = _StatFs()
        if fstatfs(fd, ctypes.byref(value)) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        return int(value.f_type)

    def proc_link(self, proc: int, tmp: int, parent: int, name: str) -> None:
        _linkat(proc, str(tmp), parent, name, _AT_SYMLINK_FOLLOW)

    def close(self, fd: int) -> None:
        os.close(fd)


def _linkat(old_dir: int, old: str, new_dir: int, new: str, flags: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    linkat = libc.linkat
    linkat.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    linkat.restype = ctypes.c_int
    if linkat(old_dir, old.encode("ascii"), new_dir, new.encode("ascii"), flags) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _file_snapshot(value: Any) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _dir_identity(value: Any) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid)


def _trusted_dir(value: Any, backend: Any, device: int | None = None) -> bool:
    return (
        stat.S_ISDIR(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o700
        and value.st_uid == backend.geteuid()
        and (device is None or value.st_dev == device)
    )


@dataclass(frozen=True, slots=True)
class _Binding:
    parent: int | None
    name: str | None
    fd: int
    identity: tuple[int, ...]


def _binding(
    parent: int | None, name: str | None, fd: int, backend: Any, device: int
) -> _Binding:
    value = backend.fstat(fd)
    if not _trusted_dir(value, backend, device):
        raise _domain()
    if parent is not None and name is not None:
        named = backend.stat_at(parent, name, follow=False)
        if _dir_identity(named) != _dir_identity(value):
            raise _infra()
    return _Binding(parent, name, fd, _dir_identity(value))


def _bindings_stable(bindings: list[_Binding], backend: Any) -> bool:
    try:
        for item in bindings:
            if _dir_identity(backend.fstat(item.fd)) != item.identity:
                return False
            if item.parent is not None and item.name is not None:
                named = backend.stat_at(item.parent, item.name, follow=False)
                if _dir_identity(named) != item.identity:
                    return False
    except OSError:
        return False
    return True


def _open_tree(
    root_fd: int, backend: Any, fds: list[int]
) -> tuple[int, int, list[_Binding]]:
    root = backend.dup(root_fd)
    fds.append(root)
    root_stat = backend.fstat(root)
    if not _trusted_dir(root_stat, backend):
        raise _domain()
    device = root_stat.st_dev
    bindings = [_Binding(None, None, root, _dir_identity(root_stat))]
    current = root
    for name in ("sha256",):
        current = _open_component(current, name, device, backend, fds)
        bindings.append(_binding(bindings[-1].fd, name, current, backend, device))
    return current, device, bindings


def _open_component(
    parent: int, name: str, device: int, backend: Any, fds: list[int]
) -> int:
    try:
        backend.mkdir(parent, name, 0o700)
    except FileExistsError:
        pass
    except OSError:
        raise _infra() from None
    else:
        try:
            backend.fsync(parent)
        except OSError:
            raise _infra() from None
    try:
        child = backend.open_dir(parent, name)
    except OSError:
        raise _infra() from None
    fds.append(child)
    return child


def _open_prefix(
    parent: int,
    digest: str,
    device: int,
    backend: Any,
    fds: list[int],
    bindings: list[_Binding],
) -> int:
    child = _open_component(parent, digest[:2], device, backend, fds)
    bindings.append(_binding(parent, digest[:2], child, backend, device))
    return child


def _validate_tmp(fd: int, backend: Any, device: int, size: int, links: int) -> Any:
    value = backend.fstat(fd)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_uid != backend.geteuid()
        or value.st_dev != device
        or value.st_nlink != links
        or value.st_size != size
    ):
        raise _infra()
    return value


def _write_all(fd: int, content: bytes, backend: Any) -> None:
    remaining = memoryview(content)
    while remaining:
        try:
            count = backend.write(fd, remaining)
        except OSError:
            raise _infra() from None
        if type(count) is not int or not 0 < count <= len(remaining):
            raise _infra()
        remaining = remaining[count:]


def _read_all(fd: int, backend: Any, limit: int) -> bytes:
    before = backend.fstat(fd)
    if not 1 <= before.st_size <= limit:
        raise _infra()
    offset, remaining, parts = 0, before.st_size, []
    while remaining:
        try:
            part = backend.pread(fd, min(remaining, _READ_BYTES), offset)
        except OSError:
            raise _infra() from None
        if not part or len(part) > remaining:
            raise _infra()
        parts.append(part)
        offset += len(part)
        remaining -= len(part)
    if backend.pread(fd, 1, offset) or _file_snapshot(before) != _file_snapshot(
        backend.fstat(fd)
    ):
        raise _infra()
    return b"".join(parts)


def _validate_content(
    fd: int, digest: str, target: tuple[int, int], backend: Any
) -> bytes:
    content = _read_all(fd, backend, _MAX_BYTES)
    if hashlib.sha256(content).hexdigest() != digest:
        raise _infra()
    try:
        _validate_png(content, target)
    except (DomainError, InfrastructureError):
        raise _infra() from None
    return content


def _open_optional(
    parent: int, digest: str, backend: Any, fds: list[int]
) -> int | None:
    try:
        fd = backend.open_file(parent, digest)
    except FileNotFoundError:
        return None
    except OSError:
        raise _infra() from None
    fds.append(fd)
    return fd


def _validate_canonical(
    fd: int, digest: str, target: tuple[int, int], backend: Any, device: int
) -> bytes:
    value = backend.fstat(fd)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_IMODE(value.st_mode) not in (0o400, 0o600)
        or value.st_uid != backend.geteuid()
        or value.st_dev != device
        or value.st_nlink != 1
    ):
        raise _infra()
    return _validate_content(fd, digest, target, backend)


def _fresh_readback(
    parent: int,
    digest: str,
    target: tuple[int, int],
    backend: Any,
    device: int,
    fds: list[int],
) -> bytes:
    fd = _open_optional(parent, digest, backend, fds)
    if fd is None:
        raise _infra()
    return _validate_canonical(fd, digest, target, backend, device)


def _reconcile(
    parent: int,
    digest: str,
    target: tuple[int, int],
    backend: Any,
    device: int,
    bindings: list[_Binding],
    fds: list[int],
) -> bool:
    fd = _open_optional(parent, digest, backend, fds)
    if fd is None:
        return False
    _validate_canonical(fd, digest, target, backend, device)
    try:
        backend.fsync(fd)
        backend.fsync(parent)
    except OSError:
        raise _infra() from None
    _fresh_readback(parent, digest, target, backend, device, fds)
    if not _bindings_stable(bindings, backend):
        raise _infra()
    return True


def _finalize(
    tmp: int,
    parent: int,
    digest: str,
    target: tuple[int, int],
    size: int,
    backend: Any,
    device: int,
    bindings: list[_Binding],
    fds: list[int],
) -> None:
    tmp_stat = _validate_tmp(tmp, backend, device, size, 1)
    fd = _open_optional(parent, digest, backend, fds)
    if fd is None:
        raise _infra()
    final_stat = backend.fstat(fd)
    if (tmp_stat.st_dev, tmp_stat.st_ino) != (final_stat.st_dev, final_stat.st_ino):
        raise _infra()
    _validate_canonical(fd, digest, target, backend, device)
    if not _bindings_stable(bindings, backend):
        raise _infra()
    try:
        backend.fsync(parent)
    except OSError:
        raise _infra() from None
    _fresh_readback(parent, digest, target, backend, device, fds)
    if not _bindings_stable(bindings, backend):
        raise _infra()


def _proc_verified(proc: int, tmp: int, backend: Any) -> None:
    if backend.fstatfs_type(proc) != _PROC_SUPER_MAGIC:
        raise _infra()
    link = backend.stat_at(proc, str(tmp), follow=False)
    target = backend.stat_at(proc, str(tmp), follow=True)
    current = backend.fstat(tmp)
    if not stat.S_ISLNK(link.st_mode) or (target.st_dev, target.st_ino) != (
        current.st_dev,
        current.st_ino,
    ):
        raise _infra()


def _fallback(
    tmp: int,
    parent: int,
    digest: str,
    target: tuple[int, int],
    size: int,
    backend: Any,
    device: int,
    bindings: list[_Binding],
    fds: list[int],
) -> None:
    try:
        proc = backend.open_proc()
    except OSError:
        raise _infra() from None
    fds.append(proc)
    try:
        _proc_verified(proc, tmp, backend)
        _validate_tmp(tmp, backend, device, size, 0)
        _validate_content(tmp, digest, target, backend)
        if not _bindings_stable(bindings, backend):
            raise _infra()
        if _open_optional(parent, digest, backend, fds) is not None:
            raise _infra()
        backend.proc_link(proc, tmp, parent, digest)
    except OSError:
        if not _reconcile(parent, digest, target, backend, device, bindings, fds):
            raise _infra() from None
    else:
        _finalize(tmp, parent, digest, target, size, backend, device, bindings, fds)


def _publish(
    tmp: int,
    parent: int,
    digest: str,
    target: tuple[int, int],
    size: int,
    backend: Any,
    device: int,
    bindings: list[_Binding],
    fds: list[int],
) -> None:
    try:
        backend.direct_link(tmp, parent, digest)
    except OSError as error:
        if _reconcile(parent, digest, target, backend, device, bindings, fds):
            return
        if error.errno not in _FALLBACK_ERRNOS:
            raise _infra() from None
        _validate_tmp(tmp, backend, device, size, 0)
        _validate_content(tmp, digest, target, backend)
        if not _bindings_stable(bindings, backend):
            raise _infra()
        if _open_optional(parent, digest, backend, fds) is not None:
            raise _infra()
        _fallback(tmp, parent, digest, target, size, backend, device, bindings, fds)
    else:
        _finalize(tmp, parent, digest, target, size, backend, device, bindings, fds)


def _validate_inputs(
    root_fd: object, digest: object, content: object, target: object, backend: Any
) -> tuple[int, str, bytes, tuple[int, int]]:
    if backend.platform != "linux":
        raise _infra()
    if type(root_fd) is not int or root_fd < 0:
        raise _domain()
    if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
        raise _domain()
    if type(content) is not bytes or not 1 <= len(content) <= _MAX_BYTES:
        raise _domain()
    if (
        type(target) is not tuple
        or len(target) != 2
        or any(type(item) is not int for item in target)
        or any(not 64 <= item <= 4096 or item % 8 for item in target)
    ):
        raise _domain()
    return root_fd, digest, content, target


def _finish_close(fds: list[int], backend: Any, primary: BaseException | None) -> None:
    failed = False
    for fd in reversed(fds):
        try:
            backend.close(fd)
        except OSError:
            failed = True
    if not failed:
        return
    if primary is not None:
        primary.add_note("production job input cleanup failed")
        return
    raise _infra()


def _prepare_tmp(
    parent: int,
    digest: str,
    content: bytes,
    target: tuple[int, int],
    backend: Any,
    device: int,
    bindings: list[_Binding],
    fds: list[int],
) -> int:
    try:
        tmp = backend.open_tmp(parent)
        fds.append(tmp)
        backend.fchmod(tmp, 0o600)
    except OSError:
        raise _infra() from None
    _validate_tmp(tmp, backend, device, 0, 0)
    _write_all(tmp, content, backend)
    _validate_tmp(tmp, backend, device, len(content), 0)
    _validate_content(tmp, digest, target, backend)
    try:
        backend.fsync(tmp)
    except OSError:
        raise _infra() from None
    if not _bindings_stable(bindings, backend):
        raise _infra()
    return tmp


def store_style(
    root_fd: object,
    digest: object,
    content: object,
    target: object,
    *,
    _backend: Any | None = None,
) -> None:
    backend = _LinuxBackend() if _backend is None else _backend
    root_fd, digest, content, target = _validate_inputs(
        root_fd, digest, content, target, backend
    )
    fds: list[int] = []
    try:
        sha, device, bindings = _open_tree(root_fd, backend, fds)
        parent = _open_prefix(sha, digest, device, backend, fds, bindings)
        if _reconcile(parent, digest, target, backend, device, bindings, fds):
            return
        tmp = _prepare_tmp(
            parent, digest, content, target, backend, device, bindings, fds
        )
        _publish(
            tmp,
            parent,
            digest,
            target,
            len(content),
            backend,
            device,
            bindings,
            fds,
        )
    except (DomainError, InfrastructureError):
        raise
    except Exception:
        raise _infra() from None
    finally:
        _finish_close(fds, backend, sys.exception())
