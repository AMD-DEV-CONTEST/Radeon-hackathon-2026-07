"""EXP-001B secure atomic bundle publish (section 13.11).

Implements a trusted root fd, same-filesystem staging, ``O_NOFOLLOW/O_EXCL``,
a short-write loop, fsync, post-write readback, atomic publication through
Linux ``renameat2(RENAME_NOREPLACE)`` or macOS
``renameatx_np(RENAME_EXCL)``, stale staging retention, and ``ExportBundle``.
It does not use Path conveniences, ``resolve``, ``shutil``, or a plain rename
fallback, and it does not rerun verifiers or modify gates.

The online flow closes only its own file descriptors and never removes staging
by name. Unpublished random 0700 staging directories are left for trusted
recovery or offline GC, avoiding same-name replacement races between POSIX
stat and unlink/rmdir operations.

Only the frozen public/prepared ABI is imported from ``manifest``. Canonical
parsing is implemented inline here without a direct ``qa_report`` dependency,
preserving the section 13.2 ABI boundary.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from threading import Lock, RLock

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.manifest import ExportRequest, _PreparedExport, _prepare_export
from specstyle.observability.hashing import hash_bytes

_BUNDLE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)
_ALWAYS_ON_DIRS = (
    ("approved",),
    ("approved", "xhs_grid"),
    ("approved", "talking_head_cover"),
    ("approved", "background_sequence"),
    ("rejected",),
    ("manual_review",),
)
_RENAME_EXCL = 0x00000004
_RENAME_NOREPLACE = 1
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_WRITE_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_STAGED_SEAL = object()
_STAGED_OPEN = "open"
_STAGED_UNKNOWN = "unknown"
_STAGED_PUBLISHED = "published"
_STAGED_CLOSED = "closed"


class _ExportTargetExists(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class ExportedFile:
    relative_path: str
    sha256: Sha256
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ExportBundle:
    bundle_name: str
    root_device: int
    root_inode: int
    manifest_sha256: Sha256
    payload_sha256: Sha256
    bundle_sha256: Sha256
    files: tuple[ExportedFile, ...]


@dataclass(frozen=True, slots=True)
class _NodeIdentity:
    st_dev: int
    st_ino: int


@dataclass(frozen=True, slots=True)
class _RootIdentity:
    st_dev: int
    st_ino: int
    st_uid: int
    st_gid: int
    st_mode: int


@dataclass(frozen=True, slots=True)
class _NodeSnapshot:
    st_dev: int
    st_ino: int
    st_mode: int
    st_nlink: int
    st_uid: int
    st_gid: int
    st_size: int
    st_mtime_ns: int
    st_ctime_ns: int


class _BundleLockHolder:
    __slots__ = ("lock", "refs")

    def __init__(self) -> None:
        self.lock = RLock()
        self.refs = 0


_BUNDLE_LOCKS_GUARD = Lock()
_BUNDLE_LOCKS: dict[tuple[int, int, str], _BundleLockHolder] = {}


class _StagedBundle:
    """Seal-protected ownership of one verified, unpublished staging tree."""

    __slots__ = (
        "_seal",
        "_lock",
        "_state",
        "_root_fd",
        "_staging_fd",
        "_root_identity",
        "_staging_identity",
        "_inventory_snapshot",
        "_staging_name",
        "_bundle_name",
        "_prepared",
    )

    def __init__(
        self,
        seal: object,
        *,
        root_fd: int,
        staging_fd: int,
        root_identity: _RootIdentity,
        staging_identity: _NodeSnapshot,
        inventory_snapshot: dict[str, _NodeSnapshot],
        staging_name: str,
        bundle_name: str,
        prepared: _PreparedExport,
    ) -> None:
        if seal is not _STAGED_SEAL:
            raise DomainError("invalid staged export") from None
        self._seal = seal
        self._lock = Lock()
        self._state = _STAGED_OPEN
        self._root_fd = root_fd
        self._staging_fd = staging_fd
        self._root_identity = root_identity
        self._staging_identity = staging_identity
        self._inventory_snapshot = inventory_snapshot.copy()
        self._staging_name = staging_name
        self._bundle_name = bundle_name
        self._prepared = prepared

    def close(self) -> None:
        with self._lock:
            if self._state == _STAGED_CLOSED:
                return
            close_error = _finish_staged_locked(self)
        if close_error is not None:
            raise InfrastructureError("export close failed") from close_error


def _invalid_target() -> None:
    raise DomainError("invalid export target") from None


def _target_exists() -> None:
    raise _ExportTargetExists("export target exists") from None


def _invalid_staged() -> None:
    raise DomainError("invalid staged export") from None


def _hash_mismatch() -> None:
    raise DomainError("export hash mismatch") from None


def _write_failed(cause: BaseException) -> None:
    raise InfrastructureError("export write failed") from cause


def _readback_failed(cause: BaseException) -> None:
    raise InfrastructureError("export readback failed") from cause


def _sync_failed(cause: BaseException) -> None:
    raise InfrastructureError("export sync failed") from cause


def _publication_unavailable(cause: BaseException | None) -> None:
    raise InfrastructureError("secure atomic publication unavailable") from cause


def _publication_verification_failed(cause: BaseException | None = None) -> None:
    raise InfrastructureError("export publication verification failed") from cause


def _validate_bundle_name(bundle_name: object) -> str:
    if type(bundle_name) is not str or _BUNDLE_NAME_RE.fullmatch(bundle_name) is None:
        _invalid_target()
    return bundle_name


def _dup_root_fd(target_root_fd: object) -> int:
    if type(target_root_fd) is bool or type(target_root_fd) is not int:
        _invalid_target()
    try:
        dup = os.dup(target_root_fd)
    except OSError:
        _invalid_target()
    os.set_inheritable(dup, False)
    try:
        st = os.fstat(dup)
    except OSError:
        os.close(dup)
        _invalid_target()
    if not stat.S_ISDIR(st.st_mode):
        os.close(dup)
        _invalid_target()
    return dup


def _node_identity(st: os.stat_result) -> _NodeIdentity:
    return _NodeIdentity(st.st_dev, st.st_ino)


def _node_snapshot(st: os.stat_result) -> _NodeSnapshot:
    return _NodeSnapshot(
        st.st_dev,
        st.st_ino,
        st.st_mode,
        st.st_nlink,
        st.st_uid,
        st.st_gid,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
    )


def _is_same_directory(st: os.stat_result, expected: _NodeIdentity) -> bool:
    return (
        stat.S_ISDIR(st.st_mode)
        and st.st_dev == expected.st_dev
        and st.st_ino == expected.st_ino
    )


def _trusted_root_identity(st: os.stat_result) -> _RootIdentity:
    mode = stat.S_IMODE(st.st_mode)
    if (
        not stat.S_ISDIR(st.st_mode)
        or st.st_uid != os.geteuid()
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        _invalid_target()
    return _RootIdentity(st.st_dev, st.st_ino, st.st_uid, st.st_gid, mode)


def _confirm_root(
    root_fd: int, expected: _RootIdentity, *, staged_drift: bool
) -> _RootIdentity:
    try:
        root_st = os.fstat(root_fd)
    except OSError:
        if staged_drift:
            _invalid_staged()
        _invalid_target()
    current = _trusted_root_identity(root_st)
    if current != expected:
        if staged_drift:
            _invalid_staged()
        _invalid_target()
    return current


@contextmanager
def _bundle_name_lock(root_identity: _RootIdentity, bundle_name: str) -> Iterator[None]:
    key = (root_identity.st_dev, root_identity.st_ino, bundle_name)
    with _BUNDLE_LOCKS_GUARD:
        holder = _BUNDLE_LOCKS.get(key)
        if holder is None:
            holder = _BundleLockHolder()
            _BUNDLE_LOCKS[key] = holder
        holder.refs += 1
    try:
        with holder.lock:
            yield
    finally:
        with _BUNDLE_LOCKS_GUARD:
            holder.refs -= 1
            if holder.refs == 0 and _BUNDLE_LOCKS.get(key) is holder:
                del _BUNDLE_LOCKS[key]


def _finish_staged_locked(staged: _StagedBundle) -> OSError | None:
    """Consume owned descriptors; namespace cleanup is deliberately offline-only."""
    root_fd, staging_fd = staged._root_fd, staged._staging_fd
    staged._state = _STAGED_CLOSED
    staged._root_fd = staged._staging_fd = -1
    close_error: OSError | None = None
    for fd in (staging_fd, root_fd):
        try:
            os.close(fd)
        except OSError as cause:
            close_error = close_error or cause
    return close_error


def _libc():
    try:
        if sys.platform == "darwin":
            return ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
        return ctypes.CDLL("libc.so.6", use_errno=True)
    except OSError as cause:
        _publication_unavailable(cause)


def _native_rename(from_fd: int, from_name: str, to_fd: int, to_name: str) -> None:
    libc = _libc()
    from_bytes = from_name.encode("utf-8")
    to_bytes = to_name.encode("utf-8")
    if sys.platform == "darwin":
        fn = getattr(libc, "renameatx_np", None)
        if fn is None:
            _publication_unavailable(None)
        fn.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        fn.restype = ctypes.c_int
        ret = fn(from_fd, from_bytes, to_fd, to_bytes, _RENAME_EXCL)
    else:
        fn = getattr(libc, "renameat2", None)
        if fn is None:
            _publication_unavailable(None)
        fn.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        fn.restype = ctypes.c_int
        ret = fn(from_fd, from_bytes, to_fd, to_bytes, _RENAME_NOREPLACE)
    if ret != 0:
        err = ctypes.get_errno()
        if err in (errno.EEXIST, errno.ENOTEMPTY):
            _target_exists()
        caps = {
            errno.ENOSYS,
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if err in caps:
            _publication_unavailable(OSError(err, os.strerror(err)))
        raise InfrastructureError("export publish failed") from OSError(
            err, os.strerror(err)
        )


def _create_staging(root_dup: int, root_st: os.stat_result) -> tuple[int, str]:
    while True:
        name = f".specstyle-export-{os.urandom(16).hex()}.tmp"
        try:
            os.mkdir(name, 0o700, dir_fd=root_dup)
        except FileExistsError:
            continue
        except OSError as cause:
            _write_failed(cause)
        fd = _open_dir(root_dup, name)
        try:
            st = os.fstat(fd)
        except OSError as cause:
            os.close(fd)
            _readback_failed(cause)
        if st.st_dev != root_st.st_dev:
            os.close(fd)
            _publication_unavailable(None)
        return fd, name


def _populate_staging(
    staging_fd: int,
    prepared: _PreparedExport,
    dir_ids: dict[str, _NodeIdentity],
    file_ids: dict[str, _NodeIdentity],
) -> None:
    for parts in _ALWAYS_ON_DIRS:
        _mkdir_rel(staging_fd, parts, dir_ids)
    for prepared_file in (*prepared.payload_files, prepared.manifest_file):
        for parents in _dir_parents(prepared_file.relative_path):
            _mkdir_rel(staging_fd, parents, dir_ids)
        _write_file(
            staging_fd,
            prepared_file.relative_path,
            prepared_file.content,
            file_ids,
        )
    for prepared_file in (*prepared.payload_files, prepared.manifest_file):
        parents = tuple(prepared_file.relative_path.split("/")[:-1])
        if parents:
            _fsync_dir(staging_fd, parents)
    for parts in _ALWAYS_ON_DIRS:
        _fsync_dir(staging_fd, parts)
    _fsync_dir(staging_fd, ())


def _stage_bundle(
    request: ExportRequest, target_root_fd: int, bundle_name: str, /
) -> _StagedBundle:
    bundle_name = _validate_bundle_name(bundle_name)
    root_fd = _dup_root_fd(target_root_fd)
    staging_fd = -1
    staging_name = ""
    dir_ids: dict[str, _NodeIdentity] = {}
    file_ids: dict[str, _NodeIdentity] = {}
    try:
        root_st = os.fstat(root_fd)
        root_identity = _trusted_root_identity(root_st)
        prepared = _prepare_export(request)
        with _bundle_name_lock(root_identity, bundle_name):
            _confirm_root(root_fd, root_identity, staged_drift=False)
            staging_fd, staging_name = _create_staging(root_fd, root_st)
            _confirm_root(root_fd, root_identity, staged_drift=False)
        _populate_staging(staging_fd, prepared, dir_ids, file_ids)
        _readback(staging_fd, prepared, set(dir_ids) | set(file_ids))
        with _bundle_name_lock(root_identity, bundle_name):
            _confirm_root(root_fd, root_identity, staged_drift=False)
            try:
                inventory_snapshot = _snapshot_inventory(staging_fd)
                staging_identity = _node_snapshot(os.fstat(staging_fd))
                named_identity = _node_snapshot(
                    os.stat(staging_name, dir_fd=root_fd, follow_symlinks=False)
                )
            except OSError as cause:
                _readback_failed(cause)
            if named_identity != staging_identity:
                _hash_mismatch()
            _verify_snapshot_layout(inventory_snapshot, prepared, staging_identity)
            _confirm_root(root_fd, root_identity, staged_drift=False)
            return _StagedBundle(
                _STAGED_SEAL,
                root_fd=root_fd,
                staging_fd=staging_fd,
                root_identity=root_identity,
                staging_identity=staging_identity,
                inventory_snapshot=inventory_snapshot,
                staging_name=staging_name,
                bundle_name=bundle_name,
                prepared=prepared,
            )
    except BaseException:
        if staging_fd >= 0:
            _close_quietly(staging_fd)
        _close_quietly(root_fd)
        raise


def _open_dir(parent_fd: int, name: str) -> int:
    try:
        return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as cause:
        _readback_failed(cause)


def _open_parent_chain(root_fd: int, parts: tuple[str, ...]) -> tuple[list[int], int]:
    """Open parent components from a held dirfd with O_NOFOLLOW.

    Return ``(opened, leaf_parent)``.
    """
    parent = root_fd
    opened: list[int] = []
    for component in parts:
        try:
            child = os.open(component, _DIR_FLAGS, dir_fd=parent)
        except OSError:
            _close_fds(opened)
            raise
        opened.append(child)
        parent = child
    return opened, parent


def _close_fds(opened: list[int]) -> None:
    for fd in reversed(opened):
        _close_quietly(fd)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _mkdir_rel(
    staging_fd: int, parts: tuple[str, ...], dir_ids: dict[str, _NodeIdentity]
) -> None:
    parent = staging_fd
    opened: list[int] = []
    prefix: list[str] = []
    try:
        for component in parts:
            prefix.append(component)
            rel = "/".join(prefix)
            try:
                os.mkdir(component, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            except OSError as cause:
                _write_failed(cause)
            try:
                child = os.open(component, _DIR_FLAGS, dir_fd=parent)
            except OSError as cause:
                _write_failed(cause)
            try:
                st = os.fstat(child)
            except OSError as cause:
                os.close(child)
                _write_failed(cause)
            if not stat.S_ISDIR(st.st_mode):
                os.close(child)
                _write_failed(InfrastructureError("directory became non-dir"))
            dir_ids[rel] = _NodeIdentity(st.st_dev, st.st_ino)
            opened.append(child)
            parent = child
    finally:
        _close_fds(opened)


def _dir_parents(rel_path: str) -> list[tuple[str, ...]]:
    parts = tuple(rel_path.split("/"))
    return [parts[: i + 1] for i in range(len(parts) - 1)]


def _write_file(
    staging_fd: int, rel_path: str, content: bytes, file_ids: dict[str, _NodeIdentity]
) -> None:
    parts = tuple(rel_path.split("/"))
    try:
        opened, parent = _open_parent_chain(staging_fd, parts[:-1])
    except OSError as cause:
        _write_failed(cause)
    try:
        try:
            fd = os.open(parts[-1], _FILE_WRITE_FLAGS, 0o600, dir_fd=parent)
        except OSError as cause:
            _write_failed(cause)
        try:
            written = 0
            total = len(content)
            while written < total:
                try:
                    chunk = os.write(fd, content[written:])
                except OSError as cause:
                    _write_failed(cause)
                if type(chunk) is not int or chunk <= 0:
                    _write_failed(InfrastructureError("short write returned zero"))
                written += chunk
            try:
                os.fsync(fd)
            except OSError as cause:
                _sync_failed(cause)
            try:
                st = os.fstat(fd)
            except OSError as cause:
                _write_failed(cause)
            if not stat.S_ISREG(st.st_mode):
                _write_failed(InfrastructureError("file became non-regular"))
            file_ids[rel_path] = _NodeIdentity(st.st_dev, st.st_ino)
        finally:
            os.close(fd)
    finally:
        _close_fds(opened)


def _fsync_dir(staging_fd: int, parts: tuple[str, ...]) -> None:
    if not parts:
        try:
            os.fsync(staging_fd)
        except OSError as cause:
            _sync_failed(cause)
        return
    parent = staging_fd
    opened: list[int] = []
    try:
        for component in parts:
            child = _open_dir(parent, component)
            opened.append(child)
            parent = child
        for fd in reversed(opened):
            try:
                os.fsync(fd)
            except OSError as cause:
                _sync_failed(cause)
    finally:
        _close_fds(opened)


def _readback_file(staging_fd: int, rel_path: str, expected: bytes) -> None:
    parts = tuple(rel_path.split("/"))
    try:
        opened, parent = _open_parent_chain(staging_fd, parts[:-1])
    except OSError as cause:
        _readback_failed(cause)
    try:
        try:
            before = _node_snapshot(
                os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            )
            fd = os.open(parts[-1], _FILE_READ_FLAGS, dir_fd=parent)
        except OSError as cause:
            _readback_failed(cause)
        try:
            opened_identity = _node_snapshot(os.fstat(fd))
            if not stat.S_ISREG(opened_identity.st_mode) or opened_identity != before:
                _hash_mismatch()
            data = _read_exact_size(fd, opened_identity.st_size)
            held_after = _node_snapshot(os.fstat(fd))
            named_after = _node_snapshot(
                os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            )
            if held_after != opened_identity or named_after != opened_identity:
                _hash_mismatch()
            if data != expected or hash_bytes(data) != hash_bytes(expected):
                _hash_mismatch()
        except OSError as cause:
            _readback_failed(cause)
        finally:
            os.close(fd)
    finally:
        _close_fds(opened)


def _read_exact_size(fd: int, size_bytes: int) -> bytes:
    data = b""
    while len(data) < size_bytes:
        try:
            block = os.read(fd, min(1 << 20, size_bytes - len(data)))
        except OSError as cause:
            _readback_failed(cause)
        if not block:
            _readback_failed(InfrastructureError("short read"))
        data += block
    try:
        if os.read(fd, 1):
            _hash_mismatch()
    except OSError as cause:
        _readback_failed(cause)
    return data


def _readback_png(content: bytes, resolution: tuple[int, int]) -> None:
    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        if image.mode != "RGB":
            _hash_mismatch()
        if getattr(image, "n_frames", 1) != 1:
            _hash_mismatch()
        if image.info != {}:
            _hash_mismatch()
        if (image.width, image.height) != resolution:
            _hash_mismatch()


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in seen:
            raise DomainError("export invariant violation")
        seen.add(key)
        result[key] = value
    return result


def _parse_strict(data: bytes) -> object:
    if type(data) is not bytes:
        raise DomainError("export invariant violation")
    try:
        return json.loads(
            data,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                DomainError("export invariant violation")
            ),
        )
    except UnicodeDecodeError:
        raise DomainError("export invariant violation") from None
    except json.JSONDecodeError:
        raise DomainError("export invariant violation") from None


def _canonical_json_bytes(primitive: object) -> bytes:
    def normalize(value: object) -> object:
        if type(value) is float:
            return 0.0 if value == 0.0 else value
        if type(value) is dict:
            return {k: normalize(v) for k, v in value.items()}
        if type(value) is list:
            return [normalize(v) for v in value]
        return value

    return json.dumps(
        normalize(primitive),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _assert_canonical_round_trip(data: bytes) -> None:
    parsed = _parse_strict(data)
    if _canonical_json_bytes(parsed) != data:
        raise DomainError("export invariant violation")


def _expected_layout(
    prepared: _PreparedExport,
) -> tuple[set[str], dict[str, int]]:
    directories = {"/".join(parts) for parts in _ALWAYS_ON_DIRS}
    files: dict[str, int] = {}
    for prepared_file in (*prepared.payload_files, prepared.manifest_file):
        files[prepared_file.relative_path] = prepared_file.size_bytes
        directories.update(
            "/".join(parts) for parts in _dir_parents(prepared_file.relative_path)
        )
    return directories, files


def _snapshot_inventory(root_fd: int) -> dict[str, _NodeSnapshot]:
    result: dict[str, _NodeSnapshot] = {}
    _snapshot_children(root_fd, "", result)
    return result


def _snapshot_children(
    parent_fd: int, prefix: str, result: dict[str, _NodeSnapshot]
) -> None:
    try:
        names = sorted(os.listdir(parent_fd))
    except OSError as cause:
        _readback_failed(cause)
    for name in names:
        relative_path = name if not prefix else f"{prefix}/{name}"
        try:
            before_st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as cause:
            _readback_failed(cause)
        before = _node_snapshot(before_st)
        result[relative_path] = before
        if not stat.S_ISDIR(before.st_mode):
            continue
        child_fd = _open_dir(parent_fd, name)
        try:
            try:
                opened = _node_snapshot(os.fstat(child_fd))
            except OSError as cause:
                _readback_failed(cause)
            if opened != before:
                _hash_mismatch()
            _snapshot_children(child_fd, relative_path, result)
            try:
                held_after = _node_snapshot(os.fstat(child_fd))
                named_after = _node_snapshot(
                    os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                )
            except OSError as cause:
                _readback_failed(cause)
            if held_after != before or named_after != before:
                _hash_mismatch()
        finally:
            _close_quietly(child_fd)


def _verify_snapshot_layout(
    snapshot: dict[str, _NodeSnapshot],
    prepared: _PreparedExport,
    final: _NodeSnapshot,
) -> None:
    directories, files = _expected_layout(prepared)
    if set(snapshot) != directories | set(files):
        _hash_mismatch()
    for path in directories:
        node = snapshot[path]
        if (
            not stat.S_ISDIR(node.st_mode)
            or stat.S_IMODE(node.st_mode) != 0o700
            or node.st_dev != final.st_dev
            or (node.st_uid, node.st_gid) != (final.st_uid, final.st_gid)
        ):
            _hash_mismatch()
    for path, size_bytes in files.items():
        node = snapshot[path]
        if (
            not stat.S_ISREG(node.st_mode)
            or stat.S_IMODE(node.st_mode) != 0o600
            or node.st_nlink != 1
            or node.st_size != size_bytes
            or node.st_dev != final.st_dev
            or (node.st_uid, node.st_gid) != (final.st_uid, final.st_gid)
        ):
            _hash_mismatch()


def _bundle_from_prepared(
    prepared: _PreparedExport,
    bundle_name: str,
    root_identity: _RootIdentity,
) -> ExportBundle:
    files = tuple(
        sorted(
            (
                ExportedFile(f.relative_path, f.sha256, f.size_bytes)
                for f in (*prepared.payload_files, prepared.manifest_file)
            ),
            key=lambda exported: exported.relative_path,
        )
    )
    return ExportBundle(
        bundle_name,
        root_identity.st_dev,
        root_identity.st_ino,
        prepared.manifest_file.sha256,
        prepared.payload_sha256,
        prepared.bundle_sha256,
        files,
    )


def _inspect_final_bundle(
    prepared: _PreparedExport, target_root_fd: int, bundle_name: str, /
) -> ExportBundle | None:
    bundle_name = _validate_bundle_name(bundle_name)
    root_fd = _dup_root_fd(target_root_fd)
    try:
        root_st = os.fstat(root_fd)
        root_identity = _trusted_root_identity(root_st)
        with _bundle_name_lock(root_identity, bundle_name):
            _confirm_root(root_fd, root_identity, staged_drift=False)
            try:
                initial_st = os.stat(bundle_name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                _confirm_root(root_fd, root_identity, staged_drift=False)
                return None
            except OSError as cause:
                _readback_failed(cause)
            initial = _node_snapshot(initial_st)
            if (
                not stat.S_ISDIR(initial.st_mode)
                or stat.S_IMODE(initial.st_mode) != 0o700
                or initial.st_dev != root_st.st_dev
            ):
                _hash_mismatch()
            try:
                final_fd = _open_dir(root_fd, bundle_name)
            except InfrastructureError:
                _hash_mismatch()
            try:
                inspected = _inspect_open_final(
                    prepared,
                    root_fd,
                    final_fd,
                    bundle_name,
                    initial,
                    root_identity,
                )
                _confirm_root(root_fd, root_identity, staged_drift=False)
                return inspected
            finally:
                _close_quietly(final_fd)
    finally:
        _close_quietly(root_fd)


def _inspect_open_final(
    prepared: _PreparedExport,
    root_fd: int,
    final_fd: int,
    bundle_name: str,
    initial: _NodeSnapshot,
    root_identity: _RootIdentity,
) -> ExportBundle:
    """Inspect one exact S0→readback→S1 snapshot under the target-name lock.

    Direct same-UID writes after S1 are outside this process-local lock contract.
    """
    try:
        opened = _node_snapshot(os.fstat(final_fd))
        if opened != initial:
            _hash_mismatch()
        before = _snapshot_inventory(final_fd)
        _verify_snapshot_layout(before, prepared, opened)
        _readback(final_fd, prepared, set(before))
        after = _snapshot_inventory(final_fd)
        _verify_snapshot_layout(after, prepared, opened)
        held_after = _node_snapshot(os.fstat(final_fd))
        named_after = _node_snapshot(
            os.stat(bundle_name, dir_fd=root_fd, follow_symlinks=False)
        )
    except InfrastructureError:
        _hash_mismatch()
    except OSError:
        _hash_mismatch()
    if before != after or held_after != opened or named_after != opened:
        _hash_mismatch()
    return _bundle_from_prepared(prepared, bundle_name, root_identity)


def _require_open_staged(candidate: object) -> _StagedBundle:
    if (
        type(candidate) is not _StagedBundle
        or getattr(candidate, "_seal", None) is not _STAGED_SEAL
    ):
        _invalid_staged()
    return candidate


def _verify_staged_for_commit(staged: _StagedBundle) -> None:
    _confirm_root(staged._root_fd, staged._root_identity, staged_drift=True)
    try:
        staging_st = os.fstat(staged._staging_fd)
        named_st = os.stat(
            staged._staging_name,
            dir_fd=staged._root_fd,
            follow_symlinks=False,
        )
    except OSError:
        _invalid_staged()
    if not _is_same_directory(staging_st, staged._staging_identity):
        _invalid_staged()
    if not _is_same_directory(named_st, staged._staging_identity):
        _invalid_staged()
    current_root = _node_snapshot(staging_st)
    if current_root != staged._staging_identity:
        _hash_mismatch()
    if _node_snapshot(named_st) != staged._staging_identity:
        _hash_mismatch()
    before = _snapshot_inventory(staged._staging_fd)
    if before != staged._inventory_snapshot:
        _hash_mismatch()
    _verify_snapshot_layout(before, staged._prepared, current_root)
    _readback(staged._staging_fd, staged._prepared, set(before))
    after = _snapshot_inventory(staged._staging_fd)
    try:
        held_after = _node_snapshot(os.fstat(staged._staging_fd))
        named_after = _node_snapshot(
            os.stat(
                staged._staging_name,
                dir_fd=staged._root_fd,
                follow_symlinks=False,
            )
        )
    except OSError:
        _invalid_staged()
    if before != after or after != staged._inventory_snapshot:
        _hash_mismatch()
    if held_after != current_root or named_after != current_root:
        _hash_mismatch()
    _confirm_root(staged._root_fd, staged._root_identity, staged_drift=True)


def _raise_close_error(close_error: OSError | None) -> None:
    if close_error is not None:
        raise InfrastructureError("export close failed") from close_error


def _converge_existing_locked(staged: _StagedBundle) -> ExportBundle:
    try:
        inspected = _inspect_final_bundle(
            staged._prepared,
            staged._root_fd,
            staged._bundle_name,
        )
        if inspected is None:
            _hash_mismatch()
    except BaseException:
        _finish_staged_locked(staged)
        raise
    _confirm_root(staged._root_fd, staged._root_identity, staged_drift=True)
    close_error = _finish_staged_locked(staged)
    _raise_close_error(close_error)
    return inspected


def _open_published_final(staged: _StagedBundle) -> tuple[int, _NodeSnapshot]:
    final_fd = -1
    try:
        final_fd = _open_dir(staged._root_fd, staged._bundle_name)
        held_st = os.fstat(staged._staging_fd)
        opened_st = os.fstat(final_fd)
        named_st = os.stat(
            staged._bundle_name,
            dir_fd=staged._root_fd,
            follow_symlinks=False,
        )
    except (InfrastructureError, OSError) as cause:
        if final_fd >= 0:
            _close_quietly(final_fd)
        _publication_verification_failed(cause)
    held = _node_snapshot(held_st)
    opened = _node_snapshot(opened_st)
    named = _node_snapshot(named_st)
    if not _is_same_directory(opened_st, staged._staging_identity):
        _close_quietly(final_fd)
        _publication_verification_failed()
    if opened != held or named != held:
        _close_quietly(final_fd)
        _publication_verification_failed()
    return final_fd, held


def _verify_published_final(
    staged: _StagedBundle, final_fd: int, opened: _NodeSnapshot
) -> None:
    try:
        before = _snapshot_inventory(final_fd)
        if before != staged._inventory_snapshot:
            _hash_mismatch()
        _verify_snapshot_layout(before, staged._prepared, opened)
        _readback(final_fd, staged._prepared, set(before))
        after = _snapshot_inventory(final_fd)
        held_after = _node_snapshot(os.fstat(final_fd))
        stage_after = _node_snapshot(os.fstat(staged._staging_fd))
        named_after = _node_snapshot(
            os.stat(
                staged._bundle_name,
                dir_fd=staged._root_fd,
                follow_symlinks=False,
            )
        )
    except (DomainError, InfrastructureError, OSError) as cause:
        _publication_verification_failed(cause)
    if before != after or after != staged._inventory_snapshot:
        _publication_verification_failed()
    if held_after != opened or stage_after != opened or named_after != opened:
        _publication_verification_failed()


def _publish_open_staged(
    staged: _StagedBundle, *, accept_exact_existing: bool
) -> ExportBundle:
    result = _bundle_from_prepared(
        staged._prepared, staged._bundle_name, staged._root_identity
    )
    try:
        _native_rename(
            staged._root_fd,
            staged._staging_name,
            staged._root_fd,
            staged._bundle_name,
        )
    except _ExportTargetExists:
        if accept_exact_existing:
            return _converge_existing_locked(staged)
        _finish_staged_locked(staged)
        raise
    except BaseException:
        _finish_staged_locked(staged)
        raise
    staged._state = _STAGED_UNKNOWN
    final_fd, opened = _open_published_final(staged)
    try:
        try:
            os.fsync(staged._root_fd)
        except OSError as cause:
            raise InfrastructureError(
                "export published but directory fsync failed"
            ) from cause
        _verify_published_final(staged, final_fd, opened)
        _confirm_root(staged._root_fd, staged._root_identity, staged_drift=True)
        staged._state = _STAGED_PUBLISHED
    finally:
        _close_quietly(final_fd)
    close_error = _finish_staged_locked(staged)
    _raise_close_error(close_error)
    return result


def _commit_staged_bundle(
    staged: _StagedBundle, *, accept_exact_existing: bool
) -> ExportBundle:
    candidate = _require_open_staged(staged)
    if type(accept_exact_existing) is not bool:
        _invalid_staged()
    with candidate._lock:
        if candidate._state != _STAGED_OPEN:
            _invalid_staged()
        with _bundle_name_lock(candidate._root_identity, candidate._bundle_name):
            try:
                _verify_staged_for_commit(candidate)
                return _publish_open_staged(
                    candidate, accept_exact_existing=accept_exact_existing
                )
            except BaseException:
                if candidate._state != _STAGED_CLOSED:
                    _finish_staged_locked(candidate)
                raise


def export_bundle(
    request: ExportRequest, target_root_fd: int, bundle_name: str, /
) -> ExportBundle:
    staged = _stage_bundle(request, target_root_fd, bundle_name)
    return _commit_staged_bundle(staged, accept_exact_existing=False)


def _readback(staging_fd, prepared, expected: set[str]) -> None:
    manifest = prepared.manifest_file
    _readback_file(staging_fd, manifest.relative_path, manifest.content)
    _assert_canonical_round_trip(manifest.content)
    res_by_path = _resolution_by_path(manifest.content)
    for f in prepared.payload_files:
        _readback_file(staging_fd, f.relative_path, f.content)
        if f.relative_path.endswith(".json") or f.relative_path.endswith(".yaml"):
            _assert_canonical_round_trip(f.content)
        if f.relative_path.endswith(".png"):
            resolution = res_by_path.get(f.relative_path)
            if resolution is None:
                _hash_mismatch()
            _readback_png(f.content, resolution)
    _verify_inventory(staging_fd, expected)


def _resolution_by_path(manifest_bytes: bytes) -> dict[str, tuple[int, int]]:
    manifest = _parse_strict(manifest_bytes)
    if type(manifest) is not dict:
        _hash_mismatch()
    result: dict[str, tuple[int, int]] = {}
    cohorts = manifest.get("cohorts")
    if type(cohorts) is not list:
        _hash_mismatch()
    for cohort in cohorts:
        if type(cohort) is not dict:
            _hash_mismatch()
        profile = cohort.get("output_profile")
        items = cohort.get("items")
        if type(profile) is not str or type(items) is not list:
            _hash_mismatch()
        for index, item in enumerate(items):
            if type(item) is not dict:
                _hash_mismatch()
            final = item.get("final_artifact")
            initial = item.get("initial_attempt")
            if type(final) is not dict or type(initial) is not dict:
                _hash_mismatch()
            path = final.get("relative_path")
            graph = initial.get("graph")
            if type(path) is not str or type(graph) is not dict:
                _hash_mismatch()
            _validate_readback_sequence(profile, items, item, graph, path, index)
            if path in result:
                _hash_mismatch()
            result[path] = _final_graph_resolution(graph)
    return result


def _validate_readback_sequence(
    profile: str,
    items: list[object],
    item: dict[str, object],
    graph: dict[str, object],
    path: str,
    index: int,
) -> None:
    if graph.get("output_profile") != profile:
        _hash_mismatch()
    sequence = item.get("sequence_index")
    contract = graph.get("render_contract")
    semantics = contract.get("sequence_semantics") if type(contract) is dict else None
    if profile == "background_sequence":
        if (
            type(sequence) is not int
            or isinstance(sequence, bool)
            or sequence != index
            or not path.rsplit("/", 1)[-1].startswith(f"{sequence:06d}_")
        ):
            _hash_mismatch()
        if semantics == "single_item_sequence_index_zero" and (
            len(items) != 1 or sequence != 0
        ):
            _hash_mismatch()
    elif sequence is not None or semantics == "single_item_sequence_index_zero":
        _hash_mismatch()


def _final_graph_resolution(graph: dict[str, object]) -> tuple[int, int]:
    resolution = graph.get("resolution")
    if not _valid_resolution(resolution):
        _hash_mismatch()
    contract = graph.get("render_contract")
    if contract is None:
        return (resolution[0], resolution[1])
    base_keys = {
        "background",
        "final_resolution",
        "fit",
        "overlay",
        "resampling",
        "sequence_semantics",
    }
    if type(contract) is not dict or set(contract) not in (
        base_keys,
        base_keys | {"native_resolution"},
    ):
        _hash_mismatch()
    background = contract["background"]
    final = contract["final_resolution"]
    native = contract.get("native_resolution")
    if (
        not _valid_resolution(final)
        or (native is not None and not _valid_resolution(native))
        or (native is not None and native != resolution)
        or (contract["fit"] == "contain_pad_center" and native is None)
        or type(background) is not list
        or len(background) != 3
        or any(type(item) is not int or not 0 <= item <= 255 for item in background)
        or contract["fit"] not in ("contain_pad", "contain_pad_center", "cover_center")
        or contract["overlay"] != "disabled"
        or contract["resampling"] != "lanczos"
        or contract["sequence_semantics"]
        not in {"single_static", "single_item_sequence_index_zero"}
    ):
        _hash_mismatch()
    return (final[0], final[1])


def _valid_resolution(value: object) -> bool:
    return (
        type(value) is list
        and len(value) == 2
        and all(type(item) is int and item > 0 for item in value)
    )


def _verify_inventory(staging_fd: int, expected: set[str]) -> None:
    seen: set[str] = set()
    _walk(staging_fd, "", seen)
    if seen != expected:
        _hash_mismatch()


def _walk(fd: int, prefix: str, seen: set[str]) -> None:
    try:
        names = os.listdir(fd)
    except OSError as cause:
        _readback_failed(cause)
    for name in names:
        rel = f"{prefix}{name}" if not prefix else f"{prefix}/{name}"
        try:
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except OSError as cause:
            _readback_failed(cause)
        seen.add(rel)
        if stat.S_ISDIR(st.st_mode):
            child = _open_dir(fd, name)
            try:
                _walk(child, rel, seen)
            finally:
                os.close(child)
