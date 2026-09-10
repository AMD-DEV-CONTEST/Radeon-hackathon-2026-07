"""Private durable monotonic journal for a formal Production batch."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import threading

from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow.production_batch import ProductionBatchPhase

__all__ = ("ProductionBatchJournal",)

_SCHEMA = "specstyle.production.batch_journal.v1"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", re.ASCII)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_PHASES = tuple(ProductionBatchPhase)


def _invalid() -> None:
    raise DomainError("invalid production batch journal") from None


def _drift() -> None:
    raise DomainError("production batch journal drift") from None


def _unavailable() -> None:
    raise InfrastructureError("production batch journal unavailable") from None


def _sync(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        _unavailable()


def _secure_directory(fd: int) -> None:
    try:
        observed = os.fstat(fd)
    except OSError:
        _unavailable()
    if (
        not stat.S_ISDIR(observed.st_mode)
        or observed.st_uid != os.geteuid()
        or stat.S_IMODE(observed.st_mode) != 0o700
    ):
        _invalid()


def _open_directory(parent_fd: int, name: str, *, create: bool) -> int:
    if _NAME.fullmatch(name) is None:
        _invalid()
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            _invalid()
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            _sync(parent_fd)
            fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except (FileExistsError, OSError):
            _invalid()
    except OSError:
        _invalid()
    try:
        _secure_directory(fd)
    except Exception:
        os.close(fd)
        raise
    return fd


def _read(fd: int, name: str) -> bytes | None:
    try:
        file_fd = os.open(name, _READ_FLAGS, dir_fd=fd)
    except FileNotFoundError:
        return None
    except OSError:
        _invalid()
    try:
        observed = os.fstat(file_fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != os.geteuid()
            or stat.S_IMODE(observed.st_mode) != 0o600
            or not 1 <= observed.st_size <= 4096
        ):
            _invalid()
        content = os.read(file_fd, observed.st_size + 1)
        if len(content) != observed.st_size:
            _invalid()
        return content
    except OSError:
        _invalid()
    finally:
        os.close(file_fd)


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(fd, content[offset:])
        except OSError:
            _unavailable()
        if written <= 0:
            _unavailable()
        offset += written


def _publish(fd: int, name: str, content: bytes) -> None:
    temporary = f".checkpoint-{secrets.token_hex(16)}.tmp"
    file_fd = -1
    try:
        file_fd = os.open(temporary, _WRITE_FLAGS, 0o600, dir_fd=fd)
        _write_all(file_fd, content)
        _sync(file_fd)
        os.close(file_fd)
        file_fd = -1
        os.link(
            temporary,
            name,
            src_dir_fd=fd,
            dst_dir_fd=fd,
            follow_symlinks=False,
        )
        _sync(fd)
        os.unlink(temporary, dir_fd=fd)
        _sync(fd)
    except FileExistsError:
        try:
            os.unlink(temporary, dir_fd=fd)
        except OSError:
            pass
    except OSError:
        _unavailable()
    finally:
        if file_fd >= 0:
            os.close(file_fd)


def _document(
    batch_id: Identifier,
    phase: ProductionBatchPhase,
    binding: Sha256,
) -> bytes:
    return json.dumps(
        {
            "batch_id": batch_id.value,
            "binding_sha256": binding.value,
            "phase": phase.value,
            "schema_version": _SCHEMA,
            "sequence": _PHASES.index(phase),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _file_name(phase: ProductionBatchPhase) -> str:
    return f"{_PHASES.index(phase):02d}_{phase.value}.json"


class ProductionBatchJournal:
    """Append immutable phase checkpoints and accept byte-exact replay."""

    __slots__ = ("_root_fd", "_lock")

    def __init__(self, root_fd: int) -> None:
        if type(root_fd) is not int or isinstance(root_fd, bool):
            _invalid()
        try:
            duplicate = os.dup(root_fd)
            os.set_inheritable(duplicate, False)
        except OSError:
            _invalid()
        try:
            _secure_directory(duplicate)
        except Exception:
            os.close(duplicate)
            raise
        self._root_fd = duplicate
        self._lock = threading.Lock()

    def record(
        self,
        batch_id: Identifier,
        phase: ProductionBatchPhase,
        binding_sha256: Sha256,
    ) -> None:
        if (
            type(batch_id) is not Identifier
            or _NAME.fullmatch(batch_id.value) is None
            or type(phase) is not ProductionBatchPhase
            or type(binding_sha256) is not Sha256
        ):
            _invalid()
        expected = _document(batch_id, phase, binding_sha256)
        with self._lock:
            batches_fd = _open_directory(self._root_fd, "batches", create=True)
            try:
                batch_fd = _open_directory(batches_fd, batch_id.value, create=True)
                try:
                    self._record_open(batch_fd, phase, expected)
                finally:
                    os.close(batch_fd)
            finally:
                os.close(batches_fd)

    def _record_open(
        self, batch_fd: int, phase: ProductionBatchPhase, expected: bytes
    ) -> None:
        index = _PHASES.index(phase)
        if any(_read(batch_fd, _file_name(item)) is None for item in _PHASES[:index]):
            _invalid()
        name = _file_name(phase)
        existing = _read(batch_fd, name)
        if existing is not None:
            if existing != expected:
                _drift()
            return
        _publish(batch_fd, name, expected)
        if _read(batch_fd, name) != expected:
            _drift()

    def close(self) -> None:
        with self._lock:
            if self._root_fd < 0:
                return
            fd, self._root_fd = self._root_fd, -1
            try:
                os.close(fd)
            except OSError:
                _unavailable()
