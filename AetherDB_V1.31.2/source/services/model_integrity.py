"""Content hashing with an optional process-local, metadata-bound cache."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path


_DIGEST_CACHE: dict[str, tuple[tuple[int, int, int, int, int], str]] = {}
_DIGEST_CACHE_LOCK = threading.Lock()


class ArtifactChangedDuringHashError(OSError):
    pass


def _signature(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
    )


def sha256_file(path: Path, *, use_cache: bool = False) -> str:
    resolved = path.resolve(strict=True)
    before = _signature(resolved)
    cache_key = str(resolved)
    if use_cache:
        with _DIGEST_CACHE_LOCK:
            cached = _DIGEST_CACHE.get(cache_key)
        if cached and cached[0] == before:
            return cached[1]

    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    after = _signature(resolved)
    if before != after:
        raise ArtifactChangedDuringHashError(
            "Model artifact changed while its checksum was being calculated"
        )
    value = digest.hexdigest()
    if use_cache:
        with _DIGEST_CACHE_LOCK:
            _DIGEST_CACHE[cache_key] = (after, value)
    return value
