"""Anonymous-inode CAS publication contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import errno
from io import BytesIO
import os
import stat
import threading
from types import SimpleNamespace

from PIL import Image
import pytest

from specstyle.errors import DomainError, InfrastructureError
from specstyle.observability.hashing import hash_bytes
from specstyle.workflow import _production_input_cas as cas
from specstyle.workflow._production_input_cas import _PROC_SUPER_MAGIC, store_style


_UNSUPPORTED_TMPFILE_ERRNOS = frozenset(
    (errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL, errno.EISDIR)
)


def _require_anonymous_tmpfile(parent: int) -> None:
    try:
        probe = cas._LinuxBackend().open_tmp(parent)
    except OSError as error:
        if error.errno not in _UNSUPPORTED_TMPFILE_ERRNOS:
            raise
        pytest.skip(f"filesystem does not support O_TMPFILE: errno={error.errno}")
    else:
        os.close(probe)


@dataclass
class _Node:
    ino: int
    mode: int
    uid: int = field(default_factory=os.geteuid)
    gid: int = field(default_factory=os.getegid)
    nlink: int = 0
    data: bytearray = field(default_factory=bytearray)
    mtime_ns: int = 1
    ctime_ns: int = 1
    entries: dict[str, "_Node"] | None = None
    proc: bool = False


class _MemoryBackend:
    platform = "linux"

    def __init__(self, direct_errno: int | None = None) -> None:
        self.events: list[str] = []
        self.direct_errno = direct_errno
        self.proc_errno: int | None = None
        self.proc_publish_on_error = False
        self.proc_magic = _PROC_SUPER_MAGIC
        self.proc_entry_matches = True
        self.publish_on_error = False
        self.invalid_winner = False
        self.swap_after_direct = False
        self.swap_on_open_proc = False
        self.close_after_real_close = False
        self.fail_operation: str | None = None
        self.write_result: object | None = None
        self.write_chunk: int | None = None
        self.fail_open_file_at: int | None = None
        self.open_file_calls = 0
        self.bump_tmp_link_on_direct_error = False
        self.corrupt_tmp_on_direct_error = False
        self.tmp_parent: int | None = None
        self._next_fd, self._next_ino = 20, 200
        root = self._directory(100)
        self.handles: dict[int, _Node] = {10: root}
        self.closed: list[int] = []
        self._lock = threading.Lock()

    def _directory(self, ino: int | None = None) -> _Node:
        return _Node(
            self._inode() if ino is None else ino,
            stat.S_IFDIR | 0o700,
            nlink=2,
            entries={},
        )

    def _inode(self) -> int:
        self._next_ino += 1
        return self._next_ino

    def _fd(self, node: _Node) -> int:
        self._next_fd += 1
        self.handles[self._next_fd] = node
        return self._next_fd

    def geteuid(self) -> int:
        return os.geteuid()

    def dup(self, fd: int) -> int:
        self.events.append("dup")
        return self._fd(self.handles[fd])

    def fstat(self, fd: int):
        return self._stat(self.handles[fd])

    def _stat(self, node: _Node):
        return SimpleNamespace(
            st_dev=1,
            st_ino=node.ino,
            st_mode=node.mode,
            st_nlink=node.nlink,
            st_uid=node.uid,
            st_gid=node.gid,
            st_size=len(node.data),
            st_mtime_ns=node.mtime_ns,
            st_ctime_ns=node.ctime_ns,
        )

    def mkdir(self, parent: int, name: str, mode: int) -> None:
        entries = self.handles[parent].entries
        assert entries is not None
        if name in entries:
            raise FileExistsError(errno.EEXIST, "exists")
        entries[name] = self._directory()
        self.events.append(f"mkdir:{name}")

    def open_dir(self, parent: int, name: str) -> int:
        entries = self.handles[parent].entries
        assert entries is not None
        return self._fd(entries[name])

    def stat_at(self, parent: int, name: str, *, follow: bool):
        node = self.handles[parent]
        if node.proc:
            target = self.handles[int(name)]
            if follow:
                result = self._stat(target)
                if not self.proc_entry_matches:
                    result.st_ino += 1
                return result
            return self._stat(_Node(self._inode(), stat.S_IFLNK | 0o777, nlink=1))
        assert node.entries is not None
        return self._stat(node.entries[name])

    def open_tmp(self, parent: int) -> int:
        self.events.append("open_tmp")
        self._fail("open_tmp")
        self.tmp_parent = parent
        return self._fd(_Node(self._inode(), stat.S_IFREG | 0o600))

    def fchmod(self, fd: int, mode: int) -> None:
        self._fail("fchmod")
        node = self.handles[fd]
        node.mode = stat.S_IFMT(node.mode) | mode
        node.ctime_ns += 1
        self.events.append("fchmod")

    def write(self, fd: int, data: memoryview) -> int:
        self._fail("write")
        if self.write_result is not None:
            return self.write_result  # type: ignore[return-value]
        count = (
            len(data) if self.write_chunk is None else min(self.write_chunk, len(data))
        )
        node = self.handles[fd]
        node.data.extend(data[:count])
        node.mtime_ns += 1
        node.ctime_ns += 1
        self.events.append("write")
        return count

    def pread(self, fd: int, size: int, offset: int) -> bytes:
        self.events.append("pread")
        self._fail("pread")
        return bytes(self.handles[fd].data[offset : offset + size])

    def fsync(self, fd: int) -> None:
        self.events.append("fsync")
        node = self.handles[fd]
        if stat.S_ISREG(node.mode) and node.nlink == 0:
            self._fail("tmp_fsync")
        if stat.S_ISDIR(node.mode) and node.entries is not None:
            if any(len(name) == 64 for name in node.entries):
                self._fail("dir_fsync_after_publish")

    def open_file(self, parent: int, name: str) -> int:
        self.open_file_calls += 1
        if self.fail_open_file_at == self.open_file_calls:
            raise OSError(errno.EIO, "readback failure")
        entries = self.handles[parent].entries
        assert entries is not None
        if name not in entries:
            raise FileNotFoundError(errno.ENOENT, "absent")
        return self._fd(entries[name])

    def _publish(self, tmp: int, parent: int, name: str, *, winner: bool) -> None:
        entries = self.handles[parent].entries
        assert entries is not None
        if name in entries:
            raise FileExistsError(errno.EEXIST, "winner")
        if winner:
            data = b"invalid" if self.invalid_winner else bytes(self.handles[tmp].data)
            node = _Node(self._inode(), stat.S_IFREG | 0o600, nlink=1)
            node.data.extend(data)
        else:
            node = self.handles[tmp]
            node.nlink = 1
            node.ctime_ns += 1
        entries[name] = node

    def direct_link(self, tmp: int, parent: int, name: str) -> None:
        with self._lock:
            self.events.append("direct_link")
            if self.direct_errno is None:
                self._publish(tmp, parent, name, winner=False)
                return
            if self.publish_on_error or self.direct_errno == errno.EEXIST:
                self._publish(tmp, parent, name, winner=True)
            if self.bump_tmp_link_on_direct_error:
                self.handles[tmp].nlink += 1
            if self.corrupt_tmp_on_direct_error:
                self.handles[tmp].data[0] ^= 0xFF
            if self.swap_after_direct:
                self._swap_prefix(parent)
            raise OSError(self.direct_errno, "direct failure")

    def _swap_prefix(self, parent: int) -> None:
        for node in self.handles.values():
            if (
                node.entries is not None
                and self.handles[parent] in node.entries.values()
            ):
                for name, child in node.entries.items():
                    if child is self.handles[parent]:
                        node.entries[name] = self._directory()
                        return

    def open_proc(self) -> int:
        self.events.append("open_proc")
        if self.swap_on_open_proc:
            assert self.tmp_parent is not None
            self._swap_prefix(self.tmp_parent)
        node = self._directory()
        node.proc = True
        return self._fd(node)

    def fstatfs_type(self, fd: int) -> int:
        assert self.handles[fd].proc
        return self.proc_magic

    def proc_link(self, proc: int, tmp: int, parent: int, name: str) -> None:
        del proc
        self.events.append("proc_link")
        if self.proc_errno is not None:
            if self.proc_publish_on_error:
                self._publish(tmp, parent, name, winner=True)
            raise OSError(self.proc_errno, "proc failure")
        self._publish(tmp, parent, name, winner=False)

    def close(self, fd: int) -> None:
        self.events.append("close")
        self.closed.append(fd)
        self.handles.pop(fd)
        if self.close_after_real_close:
            self.close_after_real_close = False
            raise OSError(errno.EIO, "close uncertainty")

    def _fail(self, operation: str) -> None:
        if self.fail_operation == operation:
            raise OSError(errno.EIO, f"{operation} failure")

    def canonical(self, digest: str) -> bytes | None:
        node = self.canonical_node(digest)
        return bytes(node.data) if node is not None else None

    def canonical_node(self, digest: str) -> _Node | None:
        root = self.handles[10]
        sha = root.entries.get("sha256") if root.entries is not None else None
        prefix = (
            sha.entries.get(digest[:2]) if sha and sha.entries is not None else None
        )
        return (
            prefix.entries.get(digest)
            if prefix and prefix.entries is not None
            else None
        )


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), "blue").save(output, "PNG")
    return output.getvalue()


def _store(backend: _MemoryBackend) -> tuple[str, bytes]:
    content = _png()
    digest = hash_bytes(content).value
    store_style(10, digest, content, (64, 64), _backend=backend)
    return digest, content


def test_direct_link_publishes_anonymous_inode_without_unlink() -> None:
    backend = _MemoryBackend()
    digest, content = _store(backend)
    assert backend.canonical(digest) == content
    assert backend.events.count("open_tmp") == 1
    assert backend.events.count("direct_link") == 1
    assert "open_proc" not in backend.events
    assert all("unlink" not in event for event in backend.events)


def test_partial_writes_are_completed_on_the_same_anonymous_inode() -> None:
    backend = _MemoryBackend()
    backend.write_chunk = 7
    digest, content = _store(backend)
    assert backend.canonical(digest) == content
    assert backend.events.count("write") > 1


def test_existing_valid_object_is_idempotent_without_republication() -> None:
    backend = _MemoryBackend()
    digest, content = _store(backend)
    store_style(10, digest, content, (64, 64), _backend=backend)
    assert backend.canonical(digest) == content
    assert backend.events.count("direct_link") == 1


@pytest.mark.parametrize("invalid", ("content", "mode", "owner", "links"))
def test_existing_invalid_object_fails_closed_without_republication(
    invalid: str,
) -> None:
    backend = _MemoryBackend()
    digest, content = _store(backend)
    node = backend.canonical_node(digest)
    assert node is not None
    if invalid == "content":
        node.data[0] ^= 0xFF
    elif invalid == "mode":
        node.mode = stat.S_IFREG | 0o666
    elif invalid == "owner":
        node.uid += 1
    else:
        node.nlink = 2
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        store_style(10, digest, content, (64, 64), _backend=backend)
    assert backend.events.count("direct_link") == 1


@pytest.mark.parametrize("invalid", ("type", "mode", "owner"))
def test_untrusted_root_is_a_fixed_domain_failure(invalid: str) -> None:
    backend = _MemoryBackend()
    root = backend.handles[10]
    if invalid == "type":
        root.mode = stat.S_IFREG | 0o700
    elif invalid == "mode":
        root.mode = stat.S_IFDIR | 0o755
    else:
        root.uid += 1
    with pytest.raises(DomainError, match="^invalid production job input$"):
        _store(backend)
    assert "open_tmp" not in backend.events


def test_linux_backend_opens_otmpfile_readwrite_without_exclusive(monkeypatch) -> None:
    observed: list[tuple[object, int, int, int]] = []
    monkeypatch.setattr(cas.os, "O_TMPFILE", 0x400000, raising=False)

    def open_(path: object, flags: int, mode: int, *, dir_fd: int) -> int:
        observed.append((path, flags, mode, dir_fd))
        return 99

    monkeypatch.setattr(cas.os, "open", open_)
    assert cas._LinuxBackend().open_tmp(7) == 99
    path, flags, mode, parent = observed[0]
    assert (path, mode, parent) == (".", 0o600, 7)
    assert flags & 0x400000 and flags & os.O_RDWR and flags & os.O_CLOEXEC
    assert not flags & os.O_EXCL


def test_linux_backend_uses_exact_direct_and_proc_linkat_flags(monkeypatch) -> None:
    observed: list[tuple[int, str, int, str, int]] = []
    monkeypatch.setattr(cas, "_linkat", lambda *args: observed.append(args))
    backend = cas._LinuxBackend()
    backend.direct_link(11, 12, "a" * 64)
    backend.proc_link(13, 11, 12, "a" * 64)
    assert observed == [
        (11, "", 12, "a" * 64, cas._AT_EMPTY_PATH),
        (13, "11", 12, "a" * 64, cas._AT_SYMLINK_FOLLOW),
    ]


def test_linux_backend_declares_fstatfs_ctypes_signature(monkeypatch) -> None:
    class _Fstatfs:
        argtypes = None
        restype = None

        def __call__(self, fd: int, pointer: object) -> int:
            del fd
            pointer._obj.f_type = _PROC_SUPER_MAGIC  # type: ignore[attr-defined]
            return 0

    fstatfs = _Fstatfs()
    monkeypatch.setattr(
        cas.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(fstatfs=fstatfs)
    )
    assert cas._LinuxBackend().fstatfs_type(9) == _PROC_SUPER_MAGIC
    assert fstatfs.argtypes == [cas.ctypes.c_int, cas.ctypes.POINTER(cas._StatFs)]
    assert fstatfs.restype is cas.ctypes.c_int


def test_cas_source_has_no_named_stage_or_unlink() -> None:
    source = open(cas.__file__, encoding="utf-8").read()
    assert "os.unlink" not in source
    assert "os.link(" not in source
    assert "secrets." not in source
    assert "O_CREAT" not in source


@pytest.mark.parametrize(
    "allowed", (errno.ENOENT, errno.EPERM, errno.EACCES, errno.EINVAL, errno.EOPNOTSUPP)
)
def test_allowed_direct_failure_uses_verified_proc_fallback(allowed: int) -> None:
    backend = _MemoryBackend(allowed)
    digest, content = _store(backend)
    assert backend.canonical(digest) == content
    assert backend.events.count("open_proc") == 1
    assert backend.events.count("proc_link") == 1


@pytest.mark.parametrize("refused", (errno.ENOSYS, errno.EIO, errno.ENOSPC))
def test_uncertain_direct_failure_never_falls_back_or_unlinks(refused: int) -> None:
    backend = _MemoryBackend(refused)
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert "open_proc" not in backend.events
    assert all("unlink" not in event for event in backend.events)


@pytest.mark.parametrize(
    "operation", ("open_tmp", "fchmod", "write", "pread", "tmp_fsync")
)
def test_anonymous_inode_faults_fail_closed_without_unlink(operation: str) -> None:
    backend = _MemoryBackend()
    backend.fail_operation = operation
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert all("unlink" not in event for event in backend.events)


@pytest.mark.parametrize("result", (0, -1, 999999, True, 1.5, "1"))
def test_anonymous_write_rejects_invalid_counts(result: object) -> None:
    backend = _MemoryBackend()
    backend.write_result = result
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert all("unlink" not in event for event in backend.events)


def test_directory_fsync_failure_after_publish_fails_closed() -> None:
    backend = _MemoryBackend()
    backend.fail_operation = "dir_fsync_after_publish"
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert backend.events.count("direct_link") == 1
    assert all("unlink" not in event for event in backend.events)


def test_fresh_readback_open_failure_is_not_treated_as_success() -> None:
    backend = _MemoryBackend()
    backend.fail_open_file_at = 3
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert all("unlink" not in event for event in backend.events)


def test_eexist_accepts_only_a_valid_fsynced_winner() -> None:
    backend = _MemoryBackend(errno.EEXIST)
    digest, content = _store(backend)
    assert backend.canonical(digest) == content
    assert backend.events.count("open_proc") == 0
    assert backend.events.count("fsync") >= 3


def test_eexist_invalid_winner_fails_closed_without_unlink() -> None:
    backend = _MemoryBackend(errno.EEXIST)
    backend.invalid_winner = True
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert all("unlink" not in event for event in backend.events)


def test_uncertain_published_link_is_reconciled_without_retry() -> None:
    backend = _MemoryBackend(errno.EIO)
    backend.publish_on_error = True
    digest, content = _store(backend)
    assert backend.canonical(digest) == content
    assert backend.events.count("direct_link") == 1
    assert "proc_link" not in backend.events


def test_allowed_error_with_changed_tmp_link_count_cannot_fallback() -> None:
    backend = _MemoryBackend(errno.EPERM)
    backend.bump_tmp_link_on_direct_error = True
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert "open_proc" not in backend.events


def test_allowed_error_with_changed_tmp_content_cannot_fallback() -> None:
    backend = _MemoryBackend(errno.EPERM)
    backend.corrupt_tmp_on_direct_error = True
    content = _png()
    digest = hash_bytes(content).value
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        store_style(10, digest, content, (64, 64), _backend=backend)
    assert "proc_link" not in backend.events
    assert backend.canonical(digest) is None


@pytest.mark.parametrize("failure", (errno.EEXIST, errno.EIO, errno.ENOSPC))
def test_proc_link_failure_only_reconciles_without_retry(failure: int) -> None:
    backend = _MemoryBackend(errno.EPERM)
    backend.proc_errno = failure
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert backend.events.count("proc_link") == 1
    assert all("unlink" not in event for event in backend.events)


def test_proc_eexist_accepts_a_valid_concurrent_winner() -> None:
    backend = _MemoryBackend(errno.EPERM)
    backend.proc_errno = errno.EEXIST
    backend.proc_publish_on_error = True
    digest, content = _store(backend)
    assert backend.canonical(digest) == content
    assert backend.events.count("proc_link") == 1


def test_proc_eexist_rejects_an_invalid_concurrent_winner() -> None:
    backend = _MemoryBackend(errno.EPERM)
    backend.proc_errno = errno.EEXIST
    backend.proc_publish_on_error = True
    backend.invalid_winner = True
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)


@pytest.mark.parametrize("kind", ("magic", "entry"))
def test_proc_fallback_requires_verified_procfs_identity(kind: str) -> None:
    backend = _MemoryBackend(errno.EPERM)
    if kind == "magic":
        backend.proc_magic = 0
    else:
        backend.proc_entry_matches = False
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert "proc_link" not in backend.events


def test_directory_swap_blocks_proc_fallback() -> None:
    backend = _MemoryBackend(errno.EPERM)
    backend.swap_after_direct = True
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert "open_proc" not in backend.events


def test_directory_swap_after_proc_open_blocks_link() -> None:
    backend = _MemoryBackend(errno.EPERM)
    backend.swap_on_open_proc = True
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert "proc_link" not in backend.events


def test_close_after_real_close_is_not_retried() -> None:
    backend = _MemoryBackend()
    backend.close_after_real_close = True
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert len(backend.closed) == len(set(backend.closed))


def test_non_linux_platform_is_a_fixed_failure_before_io() -> None:
    backend = _MemoryBackend()
    backend.platform = "darwin"
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        _store(backend)
    assert backend.events == []


def test_two_publishers_converge_on_one_valid_winner() -> None:
    backend = _MemoryBackend()
    failures: list[InfrastructureError] = []

    def publish() -> None:
        try:
            _store(backend)
        except InfrastructureError as error:
            failures.append(error)

    threads = [threading.Thread(target=publish) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []


@pytest.mark.parametrize("code", sorted(_UNSUPPORTED_TMPFILE_ERRNOS))
def test_anonymous_tmpfile_probe_skips_only_unsupported_errors(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    def unsupported(_self: object, _parent: int) -> int:
        raise OSError(code, "unsupported")

    monkeypatch.setattr(cas._LinuxBackend, "open_tmp", unsupported)

    with pytest.raises(pytest.skip.Exception):
        _require_anonymous_tmpfile(10)


def test_anonymous_tmpfile_probe_propagates_other_os_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bad_descriptor(_self: object, _parent: int) -> int:
        raise OSError(errno.EBADF, "bad descriptor")

    monkeypatch.setattr(cas._LinuxBackend, "open_tmp", bad_descriptor)

    with pytest.raises(OSError, match="bad descriptor") as captured:
        _require_anonymous_tmpfile(10)

    assert captured.value.errno == errno.EBADF


@pytest.mark.skipif(os.uname().sysname != "Linux", reason="requires Linux O_TMPFILE")
def test_real_linux_anonymous_publish_smoke(tmp_path) -> None:
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _require_anonymous_tmpfile(fd)
        content = _png()
        store_style(fd, hash_bytes(content).value, content, (64, 64))
    finally:
        os.close(fd)
