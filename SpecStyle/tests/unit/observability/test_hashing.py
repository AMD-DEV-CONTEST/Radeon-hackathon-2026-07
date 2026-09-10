from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from specstyle.errors import DomainError, InfrastructureError
from specstyle.observability import hashing
from specstyle.observability.hashing import (
    MAX_HASH_CHUNK_SIZE,
    hash_bytes,
    hash_file,
    hash_stream,
)


class ReadSpy:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = iter(chunks)
        self.sizes: list[int] = []

    def read(self, size: int, /) -> bytes:
        self.sizes.append(size)
        return next(self.chunks, b"")


class BrokenRead:
    def read(self, size: int, /) -> bytes:
        raise OSError("private failure")


def test_hash_bytes_known_and_empty_vectors() -> None:
    assert str(hash_bytes(b"")) == hashlib.sha256(b"").hexdigest()
    assert str(hash_bytes(b"abc")) == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize("value", [bytearray(b"x"), memoryview(b"x"), "x"])
def test_hash_bytes_rejects_non_exact_bytes(value: object) -> None:
    with pytest.raises(DomainError):
        hash_bytes(value)  # type: ignore[arg-type]


def test_hash_stream_reads_offset_nonseekable_in_requested_chunks() -> None:
    stream = ReadSpy([b"bc", b"def", b""])
    assert (
        str(hash_stream(stream, chunk_size=3)) == hashlib.sha256(b"bcdef").hexdigest()
    )
    assert stream.sizes == [3, 3, 3]


@pytest.mark.parametrize("size", [True, 0, -1, MAX_HASH_CHUNK_SIZE + 1, 1.0])
def test_hash_stream_rejects_invalid_chunk_size(size: object) -> None:
    with pytest.raises(DomainError):
        hash_stream(ReadSpy([b""]), chunk_size=size)  # type: ignore[arg-type]


@pytest.mark.parametrize("chunks", [["bad"], [b"toolong"]])
def test_hash_stream_rejects_invalid_or_oversized_blocks(chunks: list[object]) -> None:
    stream = ReadSpy(chunks)  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        hash_stream(stream, chunk_size=3)


def test_hash_stream_wraps_read_error_without_secret() -> None:
    with pytest.raises(InfrastructureError) as raised:
        hash_stream(BrokenRead())
    assert "private failure" not in str(raised.value)


def test_hash_file_hashes_large_content_without_read_bytes(tmp_path: Path) -> None:
    payload = b"x" * 20_000
    (tmp_path / "large.bin").write_bytes(payload)
    assert (
        str(hash_file(tmp_path, "large.bin", chunk_size=257))
        == hashlib.sha256(payload).hexdigest()
    )


@pytest.mark.parametrize(
    "relative", ["", "/secret", "a/../b", "a//b", "a/", "a\\b", "C:/x", "//host/x"]
)
def test_hash_file_rejects_untrusted_relative_text_without_echoing_it(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(DomainError) as raised:
        hash_file(tmp_path, relative)
    if relative:
        assert relative not in str(raised.value)


def test_hash_file_rejects_symlink_directory_and_missing(tmp_path: Path) -> None:
    (tmp_path / "directory").mkdir()
    (tmp_path / "target").write_bytes(b"x")
    (tmp_path / "link").symlink_to(tmp_path / "target")
    for name in ("directory", "link", "missing"):
        with pytest.raises(DomainError):
            hash_file(tmp_path, name)


def test_hash_file_rejects_non_path_root_without_calling_stringification(
    tmp_path: Path,
) -> None:
    class Explosive:
        def __str__(self) -> str:
            raise AssertionError("must not stringify")

    with pytest.raises(DomainError):
        hash_file(Explosive(), "x")  # type: ignore[arg-type]


def test_hash_file_detects_change_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "changing.bin"
    file_path.write_bytes(b"abcdef")
    original_read = os.read
    changed = False

    def changing_read(fd: int, size: int) -> bytes:
        nonlocal changed
        data = original_read(fd, size)
        if data and not changed:
            changed = True
            file_path.write_bytes(b"changed content")
        return data

    monkeypatch.setattr(os, "read", changing_read)
    with pytest.raises(InfrastructureError, match="^file changed while hashing$"):
        hash_file(tmp_path, "changing.bin", chunk_size=1)
    assert changed


def test_hash_file_uses_dirfd_openat_not_path_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "leaf").write_bytes(b"safe")

    def forbidden_open(self: Path, *args: object, **kwargs: object) -> object:
        raise AssertionError("Path.open must not be used")

    monkeypatch.setattr(Path, "open", forbidden_open)
    assert str(hash_file(tmp_path, "leaf")) == hashlib.sha256(b"safe").hexdigest()


@pytest.mark.skipif(os.name != "posix", reason="POSIX secure-open contract")
def test_hash_file_rejects_leaf_replaced_by_outside_symlink_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaf = tmp_path / "leaf"
    outside = tmp_path.parent / "outside-secret"
    leaf.write_bytes(b"safe")
    outside.write_bytes(b"private")
    real_open = os.open

    def replace_leaf(
        path: str | bytes, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if path == "leaf" and dir_fd is not None:
            leaf.unlink()
            leaf.symlink_to(outside)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(hashing.os, "open", replace_leaf)
    monkeypatch.setattr(
        hashing.os, "supports_dir_fd", os.supports_dir_fd | {replace_leaf}
    )
    with pytest.raises(DomainError) as raised:
        hash_file(tmp_path, "leaf")
    assert "outside-secret" not in str(raised.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX secure-open contract")
def test_hash_file_rejects_parent_replaced_by_symlink_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    outside = tmp_path.parent / "outside-dir"
    parent.mkdir()
    outside.mkdir()
    (parent / "leaf").write_bytes(b"safe")
    (outside / "leaf").write_bytes(b"private")
    real_open = os.open

    def replace_parent(
        path: str | bytes, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if path == "parent" and dir_fd is not None:
            (parent / "leaf").unlink()
            parent.rmdir()
            parent.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(hashing.os, "open", replace_parent)
    monkeypatch.setattr(
        hashing.os, "supports_dir_fd", os.supports_dir_fd | {replace_parent}
    )
    with pytest.raises(DomainError):
        hash_file(tmp_path, "parent/leaf")


@pytest.mark.skipif(os.name != "posix", reason="POSIX secure-open contract")
def test_hash_file_reads_opened_leaf_after_path_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaf = tmp_path / "leaf"
    outside = tmp_path.parent / "outside-replacement"
    leaf.write_bytes(b"original")
    outside.write_bytes(b"private")
    real_read = os.read
    calls = 0

    def replace_after_open(fd: int, size: int) -> bytes:
        nonlocal calls
        calls += 1
        block = real_read(fd, size)
        if calls == 1:
            leaf.unlink()
            leaf.symlink_to(outside)
        return block

    monkeypatch.setattr(hashing.os, "read", replace_after_open)
    assert (
        str(hash_file(tmp_path, "leaf", chunk_size=3))
        == hashlib.sha256(b"original").hexdigest()
    )
    assert calls > 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX secure-open contract")
def test_hash_file_detects_actual_mutation_of_opened_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaf = tmp_path / "leaf"
    leaf.write_bytes(b"abcdefgh")
    real_read = os.read
    mutated = False

    def mutate_opened_file(fd: int, size: int) -> bytes:
        nonlocal mutated
        block = real_read(fd, size)
        if block and not mutated:
            mutated = True
            with leaf.open("r+b") as writer:
                writer.seek(0)
                writer.write(b"changed!")
                writer.flush()
                os.fsync(writer.fileno())
        return block

    monkeypatch.setattr(hashing.os, "read", mutate_opened_file)
    with pytest.raises(InfrastructureError, match="^file changed while hashing$"):
        hash_file(tmp_path, "leaf", chunk_size=2)
    assert mutated


@pytest.mark.skipif(os.name != "posix", reason="POSIX secure-open contract")
def test_hash_file_rejects_fifo_and_control_characters_without_value_error(
    tmp_path: Path,
) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(DomainError, match="^hash path is invalid$"):
        hash_file(tmp_path, "pipe")
    for relative in ("bad\x00name", "bad\x1fname", "bad\x7fname"):
        with pytest.raises(DomainError, match="^hash path is invalid$"):
            hash_file(tmp_path, relative)
    with pytest.raises(DomainError, match="^hash path is invalid$"):
        hash_file(Path("\x00"), "leaf")


def test_hash_file_maps_open_permission_error_without_path_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "private-leaf").write_bytes(b"safe")
    real_open = os.open

    def denied(
        path: str | bytes, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if path == "private-leaf":
            raise PermissionError("private-leaf")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(hashing.os, "open", denied)
    monkeypatch.setattr(hashing.os, "supports_dir_fd", os.supports_dir_fd | {denied})
    with pytest.raises(
        InfrastructureError, match="^cannot access hash file$"
    ) as raised:
        hash_file(tmp_path, "private-leaf")
    assert "private-leaf" not in str(raised.value)


@pytest.mark.parametrize(
    ("mode", "flag"),
    [
        ("missing_supports", None),
        ("broken_supports", None),
        ("empty_supports", None),
        ("non_posix", None),
        *(
            ("missing_flag", name)
            for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK")
        ),
        *(
            ("zero_flag", name)
            for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK")
        ),
    ],
)
def test_hash_file_fails_closed_before_any_open_for_all_capability_defects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, flag: str | None
) -> None:
    (tmp_path / "leaf").write_bytes(b"safe")
    calls = {"os_open": 0, "path_open": 0}

    def counted_os_open(*args: object, **kwargs: object) -> int:
        calls["os_open"] += 1
        raise AssertionError("must not open")

    def counted_path_open(*args: object, **kwargs: object) -> int:
        calls["path_open"] += 1
        raise AssertionError("must not open")

    monkeypatch.setattr(hashing.os, "open", counted_os_open)
    monkeypatch.setattr(Path, "open", counted_path_open)
    if mode == "missing_supports":
        monkeypatch.delattr(hashing.os, "supports_dir_fd")
    elif mode == "broken_supports":

        class BrokenSupports:
            def __contains__(self, value: object) -> bool:
                raise RuntimeError("private support failure")

        monkeypatch.setattr(hashing.os, "supports_dir_fd", BrokenSupports())
    elif mode == "empty_supports":
        monkeypatch.setattr(hashing.os, "supports_dir_fd", set())
    elif mode == "non_posix":
        monkeypatch.setattr(
            hashing.os, "supports_dir_fd", os.supports_dir_fd | {counted_os_open}
        )
        monkeypatch.setattr(hashing.os, "name", "nt")
    elif mode == "missing_flag":
        monkeypatch.setattr(
            hashing.os, "supports_dir_fd", os.supports_dir_fd | {counted_os_open}
        )
        monkeypatch.delattr(hashing.os, flag)
    else:
        monkeypatch.setattr(
            hashing.os, "supports_dir_fd", os.supports_dir_fd | {counted_os_open}
        )
        monkeypatch.setattr(hashing.os, flag, 0)
    with pytest.raises(
        InfrastructureError, match="^secure file hashing is unavailable$"
    ):
        hash_file(tmp_path, "leaf")
    assert calls == {"os_open": 0, "path_open": 0}


def test_hash_file_closes_fds_promptly_for_long_parent_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a" / "b" / "c"
    target.mkdir(parents=True)
    (target / "leaf").write_bytes(b"safe")
    real_open, real_close = os.open, os.close
    active: set[int] = set()
    maximum = 0

    def tracked_open(
        path: str | bytes, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal maximum
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        active.add(fd)
        maximum = max(maximum, len(active))
        return fd

    def tracked_close(fd: int) -> None:
        active.discard(fd)
        real_close(fd)

    monkeypatch.setattr(hashing.os, "open", tracked_open)
    monkeypatch.setattr(hashing.os, "close", tracked_close)
    monkeypatch.setattr(
        hashing.os, "supports_dir_fd", os.supports_dir_fd | {tracked_open}
    )
    assert str(hash_file(tmp_path, "a/b/c/leaf")) == hashlib.sha256(b"safe").hexdigest()
    assert not active
    assert maximum <= 2


@pytest.mark.parametrize("mode", ["parent", "leaf", "read", "fstat"])
def test_hash_file_closes_opened_fds_after_every_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "leaf").write_bytes(b"safe")
    real_open, real_close, real_fstat = os.open, os.close, os.fstat
    active: set[int] = set()
    fstat_calls = 0

    def tracked_open(
        path: str | bytes,
        flags: int,
        mode_value: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == mode:
            raise OSError("private open failure")
        fd = real_open(path, flags, mode_value, dir_fd=dir_fd)
        active.add(fd)
        return fd

    def tracked_close(fd: int) -> None:
        active.discard(fd)
        real_close(fd)

    def broken_fstat(fd: int) -> os.stat_result:
        nonlocal fstat_calls
        fstat_calls += 1
        if mode == "fstat" and fstat_calls == 3:
            raise OSError("private stat failure")
        return real_fstat(fd)

    def broken_read(fd: int, size: int) -> bytes:
        raise OSError("private read failure")

    monkeypatch.setattr(hashing.os, "open", tracked_open)
    monkeypatch.setattr(hashing.os, "close", tracked_close)
    monkeypatch.setattr(hashing.os, "fstat", broken_fstat)
    monkeypatch.setattr(
        hashing.os, "supports_dir_fd", os.supports_dir_fd | {tracked_open}
    )
    if mode == "read":
        monkeypatch.setattr(hashing.os, "read", broken_read)
    with pytest.raises((DomainError, InfrastructureError)):
        hash_file(tmp_path, "parent/leaf")
    assert not active
