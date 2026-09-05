"""Protected, file-based runtime bearer-token handoff.

This module intentionally supports token-file handoff only on POSIX targets.
Those are the AMD execution targets, and refusing a platform that cannot prove
``0700`` directory and ``0600`` file protections is safer than offering a
best-effort secret store.  It creates no directory and never puts token text in
an exception or representation.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .errors import (
    TokenDirectoryError,
    TokenFileError,
    TokenHandoffPlatformError,
    TokenValidationError,
)


_MIN_TOKEN_BYTES: Final = 24
_MAX_TOKEN_BYTES: Final = 512
_TOKEN_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{24,512}\Z")
_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600
_TOKEN_PREFIX: Final = "xenix-runtime-token-"
_TOKEN_FILE_ATTEMPTS: Final = 8


@dataclass(frozen=True, slots=True)
class RuntimeBearerToken:
    """One opaque runtime token whose value is intentionally non-representable."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        _validate_token_text(self.value)

    @classmethod
    def generate(cls) -> RuntimeBearerToken:
        """Generate a fresh token from 32 bytes of operating-system entropy."""

        return cls(secrets.token_urlsafe(32))

    def authorization_header(self) -> str:
        """Return the intentionally explicit HTTP authorization value."""

        return f"Bearer {self.value}"

    def matches(self, candidate: RuntimeBearerToken | str) -> bool:
        """Compare a supplied token without exposing either value in diagnostics."""

        candidate_value = candidate.value if isinstance(candidate, RuntimeBearerToken) else candidate
        return isinstance(candidate_value, str) and secrets.compare_digest(self.value, candidate_value)

    def __repr__(self) -> str:
        return "RuntimeBearerToken(<redacted>)"

    def __str__(self) -> str:
        return "<redacted runtime bearer token>"


@dataclass(frozen=True, slots=True)
class BearerTokenHandoff:
    """A token and its private handoff file, both hidden from representations."""

    token_file: Path = field(repr=False)
    private_directory: Path = field(repr=False)
    token: RuntimeBearerToken = field(repr=False, compare=False)

    def verify(self) -> RuntimeBearerToken:
        """Read the handoff again and require the originally generated secret."""

        observed = read_bearer_token_handoff(self.token_file, private_directory=self.private_directory)
        if not self.token.matches(observed):
            raise TokenValidationError()
        return observed

    def remove(self) -> None:
        """Remove this exact protected handoff file after its owning runtime stops."""

        remove_bearer_token_handoff(self)

    def __repr__(self) -> str:
        return "BearerTokenHandoff(<redacted>)"

    def __str__(self) -> str:
        return "<redacted bearer token handoff>"


def create_bearer_token_handoff(private_directory: str | os.PathLike[str]) -> BearerTokenHandoff:
    """Create a fresh ``0600`` token file inside an existing private directory.

    The supplied directory must already exist, be owned by the current effective
    user, and be made exactly ``0700``.  The generated filename is not accepted
    from a caller, preventing path redirection through this API.
    """

    _require_posix_protection()
    directory = _absolute_path(private_directory, TokenDirectoryError)
    directory_fd = _open_private_directory(directory, enforce_mode=True)
    filename: str | None = None
    file_fd: int | None = None
    token = RuntimeBearerToken.generate()
    try:
        for _ in range(_TOKEN_FILE_ATTEMPTS):
            candidate = _TOKEN_PREFIX + secrets.token_hex(16)
            try:
                file_fd = os.open(
                    candidate,
                    _secure_file_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
                    _FILE_MODE,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            except OSError:
                raise TokenFileError() from None
            filename = candidate
            break
        if file_fd is None or filename is None:
            raise TokenFileError()

        try:
            os.fchmod(file_fd, _FILE_MODE)
            _require_private_file_stat(os.fstat(file_fd))
            _write_all(file_fd, token.value.encode("ascii") + b"\n")
            os.fsync(file_fd)
        except OSError:
            raise TokenFileError() from None
        finally:
            os.close(file_fd)
            file_fd = None
    except Exception:
        if filename is not None:
            _unlink_private_file(directory_fd, filename)
        raise
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)

    handoff = BearerTokenHandoff(
        token_file=directory / filename,
        private_directory=directory,
        token=token,
    )
    try:
        handoff.verify()
    except Exception:
        try:
            handoff.remove()
        except Exception:
            pass
        raise
    return handoff


def read_bearer_token_handoff(
    token_file: str | os.PathLike[str],
    *,
    private_directory: str | os.PathLike[str] | None = None,
) -> RuntimeBearerToken:
    """Read a protected handoff after validating its directory, mode, and shape."""

    _require_posix_protection()
    path = _absolute_path(token_file, TokenFileError)
    directory = _handoff_directory(path, private_directory)
    filename = _handoff_filename(path, directory)
    directory_fd = _open_private_directory(directory, enforce_mode=False)
    file_fd: int | None = None
    try:
        try:
            before = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
            _require_private_file_stat(before)
            file_fd = os.open(filename, _secure_file_open_flags(os.O_RDONLY), dir_fd=directory_fd)
            after = os.fstat(file_fd)
            _require_private_file_stat(after)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise TokenFileError()
            payload = _read_small_file(file_fd)
        except TokenFileError:
            raise
        except OSError:
            raise TokenFileError() from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)

    return _decode_token_payload(payload)


def remove_bearer_token_handoff(handoff: BearerTokenHandoff) -> None:
    """Delete only the exact verified file represented by a handoff object."""

    if not isinstance(handoff, BearerTokenHandoff):
        raise TokenFileError()
    handoff.verify()
    _require_posix_protection()
    filename = _handoff_filename(handoff.token_file, handoff.private_directory)
    directory_fd = _open_private_directory(handoff.private_directory, enforce_mode=False)
    try:
        try:
            file_stat = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
            _require_private_file_stat(file_stat)
            os.unlink(filename, dir_fd=directory_fd)
        except TokenFileError:
            raise
        except OSError:
            raise TokenFileError() from None
    finally:
        os.close(directory_fd)


def _validate_token_text(value: object) -> None:
    if not isinstance(value, str):
        raise TokenValidationError()
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise TokenValidationError() from None
    if not _MIN_TOKEN_BYTES <= len(encoded) <= _MAX_TOKEN_BYTES or not _TOKEN_PATTERN.fullmatch(value):
        raise TokenValidationError()


def _require_posix_protection() -> None:
    if os.name != "posix" or not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "fchmod", "geteuid")):
        raise TokenHandoffPlatformError()


def _absolute_path(
    value: str | os.PathLike[str],
    error_type: type[TokenDirectoryError] | type[TokenFileError],
) -> Path:
    try:
        path = Path(value)
    except (TypeError, ValueError):
        raise error_type() from None
    if not path.is_absolute():
        raise error_type()
    return path


def _open_private_directory(directory: Path, *, enforce_mode: bool) -> int:
    try:
        descriptor = os.open(
            directory,
            _secure_directory_open_flags(),
        )
    except (OSError, ValueError):
        raise TokenDirectoryError() from None
    try:
        directory_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.geteuid():
            raise TokenDirectoryError()
        if enforce_mode:
            os.fchmod(descriptor, _DIRECTORY_MODE)
            directory_stat = os.fstat(descriptor)
        if stat.S_IMODE(directory_stat.st_mode) != _DIRECTORY_MODE:
            raise TokenDirectoryError()
        return descriptor
    except TokenDirectoryError:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        raise TokenDirectoryError() from None


def _secure_directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _secure_file_open_flags(base_flags: int) -> int:
    return base_flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _require_private_file_stat(file_stat: os.stat_result) -> None:
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.geteuid()
        or stat.S_IMODE(file_stat.st_mode) != _FILE_MODE
    ):
        raise TokenFileError()


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("token write failed")
        offset += written


def _read_small_file(descriptor: int) -> bytes:
    payload = os.read(descriptor, _MAX_TOKEN_BYTES + 2)
    if len(payload) > _MAX_TOKEN_BYTES + 1:
        raise TokenFileError()
    if os.read(descriptor, 1):
        raise TokenFileError()
    return payload


def _decode_token_payload(payload: bytes) -> RuntimeBearerToken:
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise TokenValidationError()
    try:
        return RuntimeBearerToken(payload[:-1].decode("ascii"))
    except UnicodeDecodeError:
        raise TokenValidationError() from None


def _handoff_directory(
    token_path: Path,
    private_directory: str | os.PathLike[str] | None,
) -> Path:
    if private_directory is None:
        return token_path.parent
    directory = _absolute_path(private_directory, TokenDirectoryError)
    if token_path.parent != directory:
        raise TokenFileError()
    return directory


def _handoff_filename(token_path: Path, directory: Path) -> str:
    if token_path.parent != directory or token_path.name in {"", ".", ".."}:
        raise TokenFileError()
    return token_path.name


def _unlink_private_file(directory_fd: int, filename: str) -> None:
    try:
        os.unlink(filename, dir_fd=directory_fd)
    except OSError:
        pass


__all__ = [
    "BearerTokenHandoff",
    "RuntimeBearerToken",
    "create_bearer_token_handoff",
    "read_bearer_token_handoff",
    "remove_bearer_token_handoff",
]
