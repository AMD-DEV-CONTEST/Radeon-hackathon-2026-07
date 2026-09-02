from __future__ import annotations

import hashlib
import stat
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from shared_contracts import ArtifactRef, ComponentName


DEFAULT_CHUNK_SIZE = 64 * 1024


class ArtifactUnavailable(Exception):
    """Base class for safe artifact-resolution failures."""


class ArtifactNotFound(ArtifactUnavailable):
    pass


class ArtifactCorrupt(ArtifactUnavailable):
    pass


class ArtifactMediaTypeRejected(ArtifactUnavailable):
    pass


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Server-only location metadata.

    ``path`` never crosses the domain contract or the HTTP boundary.
    ``cache_entry`` allows a corrupt, reproducible cache file to be removed
    without deleting a formal source asset.
    """

    ref: ArtifactRef
    path: Path
    cache_entry: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    ref: ArtifactRef
    path: Path


class ArtifactCatalog(Protocol):
    def get(
        self,
        owner: ComponentName,
        artifact_id: UUID,
    ) -> StoredArtifact | None: ...


class StaticArtifactCatalog:
    """Small immutable catalog used by local adapters and fixture tests."""

    def __init__(self, records: Iterable[StoredArtifact]) -> None:
        index: dict[tuple[ComponentName, UUID], StoredArtifact] = {}
        for record in records:
            key = (record.ref.owner, record.ref.artifact_id)
            if key in index:
                raise ValueError("duplicate artifact identity")
            index[key] = record
        self._index = index

    def get(
        self,
        owner: ComponentName,
        artifact_id: UUID,
    ) -> StoredArtifact | None:
        return self._index.get((owner, artifact_id))


def iter_file_range(
    path: Path,
    *,
    start: int,
    length: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Iterator[bytes]:
    """Yield exactly one file range without materializing the file."""

    if start < 0 or length < 0 or chunk_size <= 0:
        raise ValueError("invalid bounded file range")

    remaining = length
    with path.open("rb", buffering=0) as file:
        file.seek(start)
        while remaining:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                raise ArtifactCorrupt("artifact unavailable")
            remaining -= len(chunk)
            yield chunk


def _is_reparse_or_symlink(path: Path) -> bool:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _sniff_media_type(path: Path) -> str | None:
    with path.open("rb", buffering=0) as file:
        prefix = file.read(32)

    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        return "video/mp4"
    if prefix.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE":
        return "audio/wav"
    if prefix.startswith(b"ID3") or (
        len(prefix) >= 2
        and prefix[0] == 0xFF
        and prefix[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if (
        len(prefix) >= 12
        and prefix.startswith(b"RIFF")
        and prefix[8:12] == b"WEBP"
    ):
        return "image/webp"
    if prefix.lstrip().lower().startswith(
        (b"<!doctype html", b"<html", b"<script")
    ):
        return "text/html"
    return None


_SNIFFED_MIME_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "audio/wav",
        "audio/mpeg",
        "image/png",
        "image/jpeg",
        "image/webp",
    }
)


class ArtifactResolver:
    """Resolve an ArtifactRef to an authorized, immutable local file."""

    def __init__(
        self,
        *,
        owner_roots: Mapping[ComponentName | str, Path | str],
        catalog: ArtifactCatalog,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk size must be positive")
        self.chunk_size = chunk_size
        self._catalog = catalog
        self._roots: dict[ComponentName, Path] = {}
        for raw_owner, raw_root in owner_roots.items():
            try:
                owner = (
                    raw_owner
                    if isinstance(raw_owner, ComponentName)
                    else ComponentName(raw_owner)
                )
            except ValueError as exc:
                raise ValueError("unknown artifact owner") from exc
            root = Path(raw_root)
            if not root.is_absolute() or not root.is_dir():
                raise ValueError("artifact roots must be existing absolute directories")
            self._roots[owner] = root.resolve(strict=True)
        if not self._roots:
            raise ValueError("at least one artifact root is required")
        self._verified: dict[
            tuple[ComponentName, UUID],
            tuple[int, int, int, str],
        ] = {}

    def resolve_identity(
        self,
        owner: str,
        artifact_id: UUID,
    ) -> ResolvedArtifact:
        try:
            component = ComponentName(owner)
        except ValueError as exc:
            raise ArtifactNotFound("artifact unavailable") from exc
        record = self._catalog.get(component, artifact_id)
        if record is None:
            raise ArtifactNotFound("artifact unavailable")
        return self._resolve_record(record)

    def resolve(self, ref: ArtifactRef) -> ResolvedArtifact:
        record = self._catalog.get(ref.owner, ref.artifact_id)
        if record is None or record.ref != ref:
            raise ArtifactNotFound("artifact unavailable")
        return self._resolve_record(record)

    def _resolve_record(self, record: StoredArtifact) -> ResolvedArtifact:
        root = self._roots.get(record.ref.owner)
        if root is None:
            raise ArtifactNotFound("artifact unavailable")
        path = Path(record.path)
        try:
            if not path.is_absolute() or _is_reparse_or_symlink(path):
                raise ArtifactCorrupt("artifact unavailable")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise ArtifactCorrupt("artifact unavailable")
            metadata = resolved.stat()
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            raise ArtifactCorrupt("artifact unavailable") from exc

        identity = (record.ref.owner, record.ref.artifact_id)
        fingerprint = (
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            record.ref.sha256,
        )
        if self._verified.get(identity) == fingerprint:
            return ResolvedArtifact(ref=record.ref, path=resolved)

        if metadata.st_size != record.ref.bytes:
            self._reject_corrupt(record, resolved)

        detected_mime = _sniff_media_type(resolved)
        if (
            record.ref.mime in _SNIFFED_MIME_TYPES
            and detected_mime != record.ref.mime
        ):
            self._reject_media_type(record, resolved)

        digest = hashlib.sha256()
        for chunk in iter_file_range(
            resolved,
            start=0,
            length=metadata.st_size,
            chunk_size=self.chunk_size,
        ):
            digest.update(chunk)
        if digest.hexdigest() != record.ref.sha256:
            self._reject_corrupt(record, resolved)

        self._verified[identity] = fingerprint
        return ResolvedArtifact(ref=record.ref, path=resolved)

    def _reject_corrupt(self, record: StoredArtifact, path: Path) -> None:
        self._verified.pop((record.ref.owner, record.ref.artifact_id), None)
        if record.cache_entry:
            try:
                path.unlink()
            except OSError:
                pass
        raise ArtifactCorrupt("artifact unavailable")

    def _reject_media_type(self, record: StoredArtifact, path: Path) -> None:
        self._verified.pop((record.ref.owner, record.ref.artifact_id), None)
        if record.cache_entry:
            try:
                path.unlink()
            except OSError:
                pass
        raise ArtifactMediaTypeRejected("artifact media type is not allowed")
