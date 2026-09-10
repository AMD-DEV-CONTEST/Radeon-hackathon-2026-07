"""Strict, bounded JSON reads relative to a borrowed directory descriptor."""

from __future__ import annotations

import json
import math
import os
import stat
from typing import Any

from specstyle.errors import DomainError, InfrastructureError
from specstyle.production._fd_ownership import (
    _OwnedFileDescriptors,
    _duplicate_directory_fd,
)

MAX_CONFIG_BYTES = 16 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
_FIXED_FILENAMES = (
    "models.json",
    "weight_manifests.json",
    "license_approvals.json",
)


def _validate_root_fd(config_root_fd: object) -> int:
    if type(config_root_fd) is not int or config_root_fd < 0:
        raise DomainError("invalid production config root fd")
    try:
        root_stat = os.fstat(config_root_fd)
    except OSError as exc:
        raise InfrastructureError("production config root unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise InfrastructureError("production config root is not a directory")
    if root_stat.st_uid != os.geteuid() or root_stat.st_mode & 0o022:
        raise InfrastructureError("production config root is not trusted")
    return config_root_fd


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _open_config_file(root_fd: int, filename: str, owned: _OwnedFileDescriptors) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    def open_file() -> int:
        try:
            return os.open(filename, flags, dir_fd=root_fd)
        except (OSError, ValueError) as exc:
            raise InfrastructureError(
                f"production config file refused: {filename}"
            ) from exc

    return owned.acquire(open_file, f"config file {filename}")


def _validate_file_stat(file_stat: os.stat_result, filename: str) -> None:
    if not stat.S_ISREG(file_stat.st_mode):
        raise InfrastructureError(f"production config file is not regular: {filename}")
    if file_stat.st_uid != os.geteuid():
        raise InfrastructureError(f"production config file owner refused: {filename}")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise InfrastructureError(f"production config file mode refused: {filename}")


def _read_unchanged_file(
    root_fd: int,
    filename: str,
    remaining: int,
    owned: _OwnedFileDescriptors,
) -> bytes:
    file_fd = _open_config_file(root_fd, filename, owned)
    try:
        before = os.fstat(file_fd)
    except OSError as exc:
        raise InfrastructureError(
            f"production config metadata unavailable: {filename}"
        ) from exc
    _validate_file_stat(before, filename)
    if before.st_size > remaining:
        raise InfrastructureError("production config total size exceeds 16 MiB")
    chunks: list[bytes] = []
    bytes_read = 0
    while bytes_read <= before.st_size:
        request = min(_READ_CHUNK_BYTES, before.st_size - bytes_read + 1)
        try:
            chunk = os.read(file_fd, request)
        except OSError as exc:
            raise InfrastructureError(
                f"production config read failed: {filename}"
            ) from exc
        if not chunk:
            break
        chunks.append(chunk)
        bytes_read += len(chunk)
    try:
        after = os.fstat(file_fd)
    except OSError as exc:
        raise InfrastructureError(
            f"production config metadata unavailable: {filename}"
        ) from exc
    if bytes_read != before.st_size or _file_identity(before) != _file_identity(after):
        raise InfrastructureError(f"production config file changed: {filename}")
    return b"".join(chunks)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DomainError("duplicate production config JSON key")
        result[key] = value
    return result


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise DomainError("non-finite production config JSON number")
    return parsed


def _validate_unicode_scalars(value: object) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str:
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise DomainError("invalid production config Unicode scalar") from exc
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def _parse_json(payload: bytes, filename: str) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DomainError(f"production config is not strict UTF-8: {filename}") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                DomainError("non-finite production config JSON number")
            ),
            parse_float=_parse_finite_float,
        )
    except DomainError:
        raise
    except (
        json.JSONDecodeError,
        UnicodeError,
        ValueError,
        TypeError,
        RecursionError,
    ) as exc:
        raise DomainError(f"invalid production config JSON: {filename}") from exc
    _validate_unicode_scalars(value)
    if type(value) is not dict:
        raise DomainError(f"invalid production config document: {filename}")
    return value


def load_fixed_json_documents(config_root_fd: int, /) -> dict[str, dict[str, Any]]:
    """Read all fixed documents without closing the caller-owned root fd."""
    with _OwnedFileDescriptors("production config descriptors") as owned:
        owned_root_fd = owned.acquire(
            lambda: _duplicate_directory_fd(
                config_root_fd,
                "invalid production config root fd",
                "production config root unavailable",
            ),
            "config root",
        )
        root_fd = _validate_root_fd(owned_root_fd)
        remaining = MAX_CONFIG_BYTES
        documents: dict[str, dict[str, Any]] = {}
        for filename in _FIXED_FILENAMES:
            payload = _read_unchanged_file(root_fd, filename, remaining, owned)
            remaining -= len(payload)
            documents[filename] = _parse_json(payload, filename)
        return documents


def _load_json_document_from_owned_root(
    owned_root_fd: int,
    filename: str,
    max_bytes: int,
    owned: _OwnedFileDescriptors,
    /,
) -> dict[str, Any]:
    if (
        type(filename) is not str
        or not filename
        or "/" in filename
        or type(max_bytes) is not int
        or isinstance(max_bytes, bool)
        or max_bytes < 1
    ):
        raise DomainError("invalid production config document request")
    root_fd = _validate_root_fd(owned_root_fd)
    return _parse_json(
        _read_unchanged_file(root_fd, filename, max_bytes, owned),
        filename,
    )


def _load_json_document(
    config_root_fd: int, filename: str, max_bytes: int, /
) -> dict[str, Any]:
    with _OwnedFileDescriptors("production config descriptors") as owned:
        owned_root_fd = owned.acquire(
            lambda: _duplicate_directory_fd(
                config_root_fd,
                "invalid production config root fd",
                "production config root unavailable",
            ),
            "config root",
        )
        return _load_json_document_from_owned_root(
            owned_root_fd, filename, max_bytes, owned
        )
