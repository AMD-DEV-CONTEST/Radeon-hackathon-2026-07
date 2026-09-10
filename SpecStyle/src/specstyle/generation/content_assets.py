"""Fail-closed resolver for allowlisted, content-addressed style PNGs."""

from __future__ import annotations

from io import BytesIO
import os
import stat
import sys
import threading
from types import TracebackType
import warnings

from PIL import Image, UnidentifiedImageError

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.observability.hashing import hash_bytes

_MAX_BYTES = 32 * 1024 * 1024
_READ_SIZE = 1024 * 1024


def _rebuild_reference(value: object) -> AssetRef:
    if (
        type(value) is not AssetRef
        or type(value.asset_id) is not AssetId
        or type(value.sha256) is not Sha256
    ):
        raise DomainError("invalid style asset reference")
    return AssetRef(AssetId(value.asset_id.value), Sha256(value.sha256.value))


def _validate_inputs(
    root_fd: object, allowed_refs: object, target_size: object
) -> tuple[int, tuple[AssetRef, ...], tuple[int, int]]:
    if type(root_fd) is not int or root_fd < 0:
        raise DomainError("invalid style asset root")
    if type(allowed_refs) is not tuple or not allowed_refs:
        raise DomainError("allowed style references must be a nonempty tuple")
    references = tuple(_rebuild_reference(item) for item in allowed_refs)
    if len(set(references)) != len(references):
        raise DomainError("allowed style references must be unique")
    if (
        type(target_size) is not tuple
        or len(target_size) != 2
        or any(type(item) is not int for item in target_size)
        or any(not 64 <= item <= 4096 or item % 8 for item in target_size)
    ):
        raise DomainError("invalid style asset target size")
    return root_fd, references, target_size


def _trusted(stat_result: os.stat_result, *, directory: bool) -> bool:
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_kind(stat_result.st_mode) or stat_result.st_uid != os.geteuid():
        return False
    if directory:
        return not stat_result.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    return stat.S_IMODE(stat_result.st_mode) in {0o400, 0o600}


def _duplicate_trusted_root(root_fd: int) -> int:
    try:
        duplicate = os.dup(root_fd)
    except OSError as error:
        raise InfrastructureError("style asset root unavailable") from error
    try:
        root_stat = os.fstat(duplicate)
        if not _trusted(root_stat, directory=True):
            raise InfrastructureError("style asset root is not trusted")
        return duplicate
    except OSError as error:
        failure = InfrastructureError("style asset root unavailable")
        _finish_internal_cleanup((duplicate,), failure)
        raise failure from error
    except BaseException as error:
        _finish_internal_cleanup((duplicate,), error)
        raise


def _open_trusted_directory(parent_fd: int, component: str) -> int:
    try:
        fd = os.open(
            component,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        node_stat = os.fstat(fd)
        if not _trusted(node_stat, directory=True):
            raise InfrastructureError("style asset path is not trusted")
        return fd
    except InfrastructureError as error:
        _finish_internal_cleanup((fd,) if "fd" in locals() else (), error)
        raise
    except (OSError, ValueError) as error:
        failure = InfrastructureError("style asset path refused")
        _finish_internal_cleanup((fd,) if "fd" in locals() else (), failure)
        raise failure from error
    except BaseException as error:
        _finish_internal_cleanup((fd,) if "fd" in locals() else (), error)
        raise


def _open_asset_file(parent_fd: int, digest: str) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        return os.open(digest, flags, dir_fd=parent_fd)
    except (OSError, ValueError) as error:
        raise InfrastructureError("style asset path refused") from error


def _file_snapshot(node_stat: os.stat_result) -> tuple[int, ...]:
    return (
        node_stat.st_dev,
        node_stat.st_ino,
        node_stat.st_mode,
        node_stat.st_nlink,
        node_stat.st_uid,
        node_stat.st_gid,
        node_stat.st_size,
        node_stat.st_mtime_ns,
        node_stat.st_ctime_ns,
    )


def _read_unchanged_regular_file(fd: int) -> bytes:
    try:
        before = os.fstat(fd)
        if (
            not _trusted(before, directory=False)
            or before.st_nlink != 1
            or not 1 <= before.st_size <= _MAX_BYTES
        ):
            raise InfrastructureError("style asset file is not trusted")
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(_READ_SIZE, remaining))
            if not chunk or len(chunk) > remaining:
                raise InfrastructureError("style asset file changed during read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise InfrastructureError("style asset file changed during read")
        after = os.fstat(fd)
        if _file_snapshot(before) != _file_snapshot(after):
            raise InfrastructureError("style asset file changed during read")
        return b"".join(chunks)
    except InfrastructureError:
        raise
    except OSError as error:
        raise InfrastructureError("style asset file unreadable") from error


def _metadata_absent(image: Image.Image) -> bool:
    return not image.info and not getattr(image, "text", {})


def _validate_png(content: bytes, target_size: tuple[int, int]) -> None:
    image: Image.Image | None = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(content))
            if (
                image.format != "PNG"
                or getattr(image, "n_frames", 1) != 1
                or image.mode != "RGB"
                or image.size != target_size
                or not _metadata_absent(image)
            ):
                raise InfrastructureError("style asset PNG contract violation")
            image.load()
            if not _metadata_absent(image):
                raise InfrastructureError("style asset PNG contract violation")
    except InfrastructureError:
        raise
    except MemoryError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise InfrastructureError("style asset PNG contract violation") from error
    except Exception as error:
        raise InfrastructureError("style asset validation failed") from error
    finally:
        if image is not None:
            try:
                image.close()
            except Exception as error:
                if sys.exc_info()[0] is None:
                    raise InfrastructureError(
                        "style asset validation failed"
                    ) from error


def _close_internal_fds(fds: tuple[int, ...]) -> OSError | None:
    first_error: OSError | None = None
    for fd in fds:
        try:
            os.close(fd)
        except OSError as error:
            if first_error is None:
                first_error = error
    return first_error


def _finish_internal_cleanup(
    fds: tuple[int, ...], primary: BaseException | None
) -> None:
    close_error = _close_internal_fds(fds)
    if close_error is None:
        return
    if primary is not None:
        primary.add_note("style asset cleanup failed")
        return
    raise InfrastructureError("style asset cleanup failed") from close_error


def _resolve(root_fd: int, reference: AssetRef, target_size: tuple[int, int]) -> bytes:
    directory_fds: list[int] = []
    file_fd = -1
    digest = reference.sha256.value
    try:
        current = root_fd
        for component in ("sha256", digest[:2]):
            current = _open_trusted_directory(current, component)
            directory_fds.append(current)
        file_fd = _open_asset_file(current, digest)
        content = _read_unchanged_regular_file(file_fd)
        if hash_bytes(content) != reference.sha256:
            raise InfrastructureError("style asset hash mismatch")
        _validate_png(content, target_size)
        return content
    finally:
        fds = ((file_fd,) if file_fd >= 0 else ()) + tuple(reversed(directory_fds))
        _finish_internal_cleanup(fds, sys.exception())


class ContentAddressedStyleResolver:
    """Callable owner of a duplicated, trusted style asset root descriptor."""

    __slots__ = ("_allowed_refs", "_closed", "_lock", "_root_fd", "_target_size")

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("use open_content_addressed_style_resolver")

    def __call__(self, reference: AssetRef, /) -> bytes:
        rebuilt = _rebuild_reference(reference)
        with self._lock:
            if self._closed:
                raise InfrastructureError("style asset resolver is closed")
            if rebuilt not in self._allowed_refs:
                raise DomainError("style asset reference is not allowed")
            return _resolve(self._root_fd, rebuilt, self._target_size)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            root_fd = self._root_fd
            self._root_fd = -1
            try:
                os.close(root_fd)
            except OSError as error:
                raise InfrastructureError(
                    "style asset resolver close failed"
                ) from error

    def __enter__(self) -> ContentAddressedStyleResolver:
        with self._lock:
            if self._closed:
                raise InfrastructureError("style asset resolver is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> None:
        try:
            self.close()
        except InfrastructureError:
            if exc_value is None:
                raise
            exc_value.add_note("style asset resolver cleanup failed")

    def __copy__(self) -> ContentAddressedStyleResolver:
        raise TypeError("style asset resolvers cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> ContentAddressedStyleResolver:
        raise TypeError("style asset resolvers cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("style asset resolvers cannot be serialized")


def open_content_addressed_style_resolver(
    root_fd: int,
    allowed_refs: tuple[AssetRef, ...],
    target_size: tuple[int, int],
    /,
) -> ContentAddressedStyleResolver:
    """Issue a resolver that owns a duplicate, never the caller's root fd."""
    validated_fd, references, size = _validate_inputs(
        root_fd, allowed_refs, target_size
    )
    duplicate = _duplicate_trusted_root(validated_fd)
    try:
        resolver = object.__new__(ContentAddressedStyleResolver)
        resolver._root_fd = duplicate
        resolver._allowed_refs = frozenset(references)
        resolver._target_size = size
        resolver._lock = threading.Lock()
        resolver._closed = False
        return resolver
    except BaseException as error:
        _finish_internal_cleanup((duplicate,), error)
        raise
