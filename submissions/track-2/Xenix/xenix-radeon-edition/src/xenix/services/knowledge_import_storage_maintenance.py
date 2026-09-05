from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import gc
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time
from typing import Any
from uuid import uuid4

import zstandard

from .knowledge_canonical import MAX_CANONICAL_ASSETS_BYTES
from .knowledge_content_store import (
    CANONICAL_SCHEMA_VERSION,
    MAX_CANONICAL_COMPRESSED_BYTES,
    MAX_CANONICAL_JSON_BYTES,
    MAX_CANONICAL_MANIFEST_BYTES,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SHARD_PATTERN = re.compile(r"^[0-9a-f]{2}$")
_SOURCE_STAGE_PATTERN = re.compile(r"^source-([0-9a-f]{32})\.tmp$")
_CANONICAL_STAGE_PATTERN = re.compile(r"^canonical-([0-9a-f]{32})$")
_CANONICAL_ASSET_PATTERN = re.compile(r"^[0-9a-f]{64}\.(?:jpg|png)$")
_TRASH_TOKEN_PATTERN = re.compile(
    r"^(source-cas|canonical-cas)-([0-9a-f]{64})-([0-9a-f]{32})$"
    r"|^(source-stage|canonical-stage)-([0-9a-f]{32})-([0-9a-f]{32})$"
)
_TRASH_DIRECTORY_NAME = ".import-trash"
_WINDOWS_REPARSE_POINT = 0x0400
_WINDOWS_SHARING_VIOLATIONS = frozenset({5, 32, 33})
_SHARING_RETRY_DELAYS = (0.02, 0.08)

_MANIFEST_FILE = "manifest.json"
_ENVELOPE_FILE = "canonical-envelope.json.zst"
_DOCUMENT_FILE = "docling-document.json.zst"
_CANONICAL_BASE_FILES = frozenset({_MANIFEST_FILE, _ENVELOPE_FILE, _DOCUMENT_FILE})
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "envelope_file",
        "envelope_sha256",
        "content_ir_file",
        "content_ir_sha256",
        "assets",
    }
)


class KnowledgeImportStorageMaintenanceError(RuntimeError):
    """Raised when cleanup cannot establish a safe ownership boundary."""


@dataclass(frozen=True)
class KnowledgeImportStorageCleanupResult:
    source_cas_quarantined: int = 0
    canonical_bundles_quarantined: int = 0
    source_staging_quarantined: int = 0
    canonical_staging_quarantined: int = 0
    trash_deleted: int = 0
    trash_remaining: int = 0


class KnowledgeImportStorageMaintenance:
    """Reclaim definite crash orphans from one Knowledge content root.

    The caller supplies the live SQLite references and must run this startup-only
    operation before an import worker can publish into the same root.  Recognition
    is deliberately closed: unfamiliar layouts, unsafe references, and link-like
    entries are retained instead of being guessed into this cleanup authority.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = _absolute_path(root)
        self._objects_root = self._root / "objects"
        self._source_root = self._objects_root / "source"
        self._canonical_root = self._objects_root / "canonical"
        self._staging_root = self._root / "staging"
        self._trash_root = self._root / _TRASH_DIRECTORY_NAME

    def cleanup(
        self,
        *,
        referenced_source_paths: Iterable[str | os.PathLike[str]],
        referenced_canonical_paths: Iterable[str | os.PathLike[str]],
    ) -> KnowledgeImportStorageCleanupResult:
        """Atomically detach definite orphans, then best-effort delete private trash."""

        self._validate_root_topology()
        source_references = self._validated_source_references(referenced_source_paths)
        canonical_references = self._validated_canonical_references(
            referenced_canonical_paths
        )
        self._validate_trash_topology()

        if not self._root.exists():
            return KnowledgeImportStorageCleanupResult()

        trash_deleted = self._delete_recognized_trash()
        source_cas_quarantined = 0
        canonical_bundles_quarantined = 0
        source_staging_quarantined = 0
        canonical_staging_quarantined = 0

        for digest, path in self._iter_cas_directories(self._source_root):
            if path in source_references or not _is_recognized_source_cas(path, digest):
                continue
            if self._quarantine(path, kind="source-cas", identity=digest):
                source_cas_quarantined += 1

        for digest, path in self._iter_cas_directories(self._canonical_root):
            if path in canonical_references or not _is_recognized_canonical_bundle(
                path, digest
            ):
                continue
            if self._quarantine(path, kind="canonical-cas", identity=digest):
                canonical_bundles_quarantined += 1

        for path in _safe_children(self._staging_root) or ():
            source_match = _SOURCE_STAGE_PATTERN.fullmatch(path.name)
            if source_match and _is_safe_regular_file(path):
                if self._quarantine(
                    path,
                    kind="source-stage",
                    identity=source_match.group(1),
                ):
                    source_staging_quarantined += 1
                continue

            canonical_match = _CANONICAL_STAGE_PATTERN.fullmatch(path.name)
            if canonical_match and _is_recognized_canonical_staging(path):
                if self._quarantine(
                    path,
                    kind="canonical-stage",
                    identity=canonical_match.group(1),
                ):
                    canonical_staging_quarantined += 1

        trash_deleted += self._delete_recognized_trash()
        return KnowledgeImportStorageCleanupResult(
            source_cas_quarantined=source_cas_quarantined,
            canonical_bundles_quarantined=canonical_bundles_quarantined,
            source_staging_quarantined=source_staging_quarantined,
            canonical_staging_quarantined=canonical_staging_quarantined,
            trash_deleted=trash_deleted,
            trash_remaining=len(self._recognized_trash_entries()),
        )

    def _validated_source_references(
        self,
        values: Iterable[str | os.PathLike[str]],
    ) -> set[Path]:
        references: set[Path] = set()
        for value in _materialize_references(values):
            relative, absolute = self._contained_reference(value)
            parts = relative.parts
            if len(parts) != 6 or parts[:2] != ("objects", "source"):
                raise KnowledgeImportStorageMaintenanceError(
                    "Knowledge source reference has an unknown shape."
                )
            digest = parts[4]
            if (
                not _SHARD_PATTERN.fullmatch(parts[2])
                or not _SHARD_PATTERN.fullmatch(parts[3])
                or not _SHA256_PATTERN.fullmatch(digest)
                or parts[2] != digest[:2]
                or parts[3] != digest[2:4]
                or not _is_source_file_name(parts[5])
            ):
                raise KnowledgeImportStorageMaintenanceError(
                    "Knowledge source reference has an unknown shape."
                )
            references.add(absolute.parent)
        return references

    def _validated_canonical_references(
        self,
        values: Iterable[str | os.PathLike[str]],
    ) -> set[Path]:
        references: set[Path] = set()
        for value in _materialize_references(values):
            relative, absolute = self._contained_reference(value)
            parts = relative.parts
            if len(parts) != 5 or parts[:2] != ("objects", "canonical"):
                raise KnowledgeImportStorageMaintenanceError(
                    "Knowledge canonical reference has an unknown shape."
                )
            digest = parts[4]
            if (
                not _SHARD_PATTERN.fullmatch(parts[2])
                or not _SHARD_PATTERN.fullmatch(parts[3])
                or not _SHA256_PATTERN.fullmatch(digest)
                or parts[2] != digest[:2]
                or parts[3] != digest[2:4]
            ):
                raise KnowledgeImportStorageMaintenanceError(
                    "Knowledge canonical reference has an unknown shape."
                )
            references.add(absolute)
        return references

    def _contained_reference(
        self,
        value: str | os.PathLike[str],
    ) -> tuple[Path, Path]:
        try:
            raw = os.fspath(value)
        except TypeError as exc:
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge storage reference must be path-like."
            ) from exc
        if not isinstance(raw, str) or not raw.strip():
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge storage reference must be a non-empty path."
            )
        candidate = Path(raw).expanduser()
        if ".." in candidate.parts:
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge storage reference contains path traversal."
            )
        absolute = _absolute_path(
            candidate if candidate.is_absolute() else self._root / candidate
        )
        try:
            relative_text = os.path.relpath(absolute, self._root)
        except ValueError as exc:
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge storage reference is outside the owned root."
            ) from exc
        relative = Path(relative_text)
        if relative == Path(".") or relative.parts[0] == "..":
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge storage reference is outside the owned root."
            )
        current = self._root
        for part in relative.parts:
            current /= part
            if _is_link_like(current):
                raise KnowledgeImportStorageMaintenanceError(
                    "Knowledge storage reference crosses a link-like path."
                )
        return relative, absolute

    def _iter_cas_directories(self, base: Path) -> Iterable[tuple[str, Path]]:
        for first in _safe_children(base) or ():
            if not _SHARD_PATTERN.fullmatch(first.name):
                continue
            for second in _safe_children(first) or ():
                if not _SHARD_PATTERN.fullmatch(second.name):
                    continue
                for candidate in _safe_children(second) or ():
                    digest = candidate.name
                    if (
                        _SHA256_PATTERN.fullmatch(digest)
                        and first.name == digest[:2]
                        and second.name == digest[2:4]
                        and _is_safe_directory(candidate)
                    ):
                        yield digest, candidate

    def _validate_root_topology(self) -> None:
        current = self._root
        while True:
            if _is_link_like(current):
                raise KnowledgeImportStorageMaintenanceError(
                    "Knowledge storage root crosses a link-like path."
                )
            if current.parent == current:
                break
            current = current.parent
        if self._root.exists() and not _is_safe_directory(self._root):
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge storage root is not a safe directory."
            )

    def _validate_trash_topology(self) -> None:
        if not self._trash_root.exists() and not _is_link_like(self._trash_root):
            return
        if not _is_safe_directory(self._trash_root):
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge Import trash is not a safe directory."
            )

    def _ensure_trash_root(self) -> None:
        self._validate_trash_topology()
        if not self._trash_root.exists():
            try:
                self._trash_root.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                pass
            except OSError as exc:
                raise KnowledgeImportStorageMaintenanceError(
                    "Knowledge Import trash could not be created."
                ) from exc
        self._validate_trash_topology()

    def _quarantine(self, path: Path, *, kind: str, identity: str) -> bool:
        if _is_link_like(path) or not _is_direct_child_of_owned_tree(path, self._root):
            return False
        self._ensure_trash_root()
        token = f"{kind}-{identity}-{uuid4().hex}"
        if not _TRASH_TOKEN_PATTERN.fullmatch(token):
            raise KnowledgeImportStorageMaintenanceError(
                "Knowledge Import trash token is invalid."
            )
        target = self._trash_root / token
        try:
            return _replace_with_retries(path, target)
        except OSError:
            return False

    def _recognized_trash_entries(self) -> tuple[Path, ...]:
        entries: list[Path] = []
        for path in _safe_children(self._trash_root) or ():
            match = _TRASH_TOKEN_PATTERN.fullmatch(path.name)
            if not match:
                continue
            kind = match.group(1) or match.group(4)
            identity = match.group(2) or match.group(5)
            if kind == "source-cas" and _is_recognized_source_cas(path, identity):
                entries.append(path)
            elif kind == "canonical-cas" and _is_recognized_canonical_bundle(
                path, identity
            ):
                entries.append(path)
            elif kind == "source-stage" and _is_safe_regular_file(path):
                entries.append(path)
            elif kind == "canonical-stage" and _is_recognized_canonical_staging(path):
                entries.append(path)
        return tuple(entries)

    def _delete_recognized_trash(self) -> int:
        deleted = 0
        for path in self._recognized_trash_entries():
            if _remove_with_retries(path):
                deleted += 1
        return deleted


def _materialize_references(
    values: Iterable[str | os.PathLike[str]],
) -> tuple[str | os.PathLike[str], ...]:
    if isinstance(values, (str, os.PathLike)):
        raise KnowledgeImportStorageMaintenanceError(
            "Knowledge storage references must be an iterable of paths."
        )
    try:
        return tuple(values)
    except TypeError as exc:
        raise KnowledgeImportStorageMaintenanceError(
            "Knowledge storage references must be iterable."
        ) from exc


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


def _is_direct_child_of_owned_tree(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] in {"objects", "staging"}


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(metadata.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    try:
        if bool(is_junction and is_junction()):
            return True
    except OSError:
        return True
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return os.name == "nt" and bool(attributes & _WINDOWS_REPARSE_POINT)


def _is_safe_directory(path: Path) -> bool:
    if _is_link_like(path):
        return False
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _is_safe_regular_file(path: Path) -> bool:
    if _is_link_like(path):
        return False
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _safe_children(path: Path) -> tuple[Path, ...] | None:
    if not _is_safe_directory(path):
        return None
    try:
        return tuple(sorted(path.iterdir(), key=lambda child: child.name))
    except OSError:
        return None


def _is_source_file_name(value: str) -> bool:
    if value == "source":
        return True
    if not value.startswith("source."):
        return False
    suffix = value.removeprefix("source")
    return (
        len(suffix) <= 12
        and suffix == suffix.casefold()
        and suffix[1:].isalnum()
    )


def _is_recognized_source_cas(path: Path, digest: str) -> bool:
    if not _SHA256_PATTERN.fullmatch(digest):
        return False
    children = _safe_children(path)
    if children is None or len(children) != 1:
        return False
    source = children[0]
    if not _is_source_file_name(source.name) or not _is_safe_regular_file(source):
        return False
    try:
        return _sha256_file(source) == digest
    except OSError:
        return False


def _is_recognized_canonical_bundle(path: Path, digest: str) -> bool:
    if not _SHA256_PATTERN.fullmatch(digest):
        return False
    children = _safe_children(path)
    if children is None:
        return False
    child_names = {child.name for child in children}
    if not _CANONICAL_BASE_FILES.issubset(child_names) or not child_names.issubset(
        _CANONICAL_BASE_FILES | {"assets"}
    ):
        return False
    try:
        manifest = json.loads(
            _read_regular_bounded(path / _MANIFEST_FILE, MAX_CANONICAL_MANIFEST_BYTES)
        )
        if (
            not isinstance(manifest, dict)
            or set(manifest) != _MANIFEST_KEYS
            or manifest.get("schema_version") != CANONICAL_SCHEMA_VERSION
            or manifest.get("envelope_file") != _ENVELOPE_FILE
            or manifest.get("content_ir_file") != _DOCUMENT_FILE
            or manifest.get("envelope_sha256") != digest
        ):
            return False
        content_digest = manifest.get("content_ir_sha256")
        if not isinstance(content_digest, str) or not _SHA256_PATTERN.fullmatch(
            content_digest
        ):
            return False
        envelope_bytes = _decompress_bounded(
            _read_regular_bounded(
                path / _ENVELOPE_FILE,
                MAX_CANONICAL_COMPRESSED_BYTES,
            )
        )
        document_bytes = _decompress_bounded(
            _read_regular_bounded(
                path / _DOCUMENT_FILE,
                MAX_CANONICAL_COMPRESSED_BYTES,
            )
        )
        if _sha256_bytes(envelope_bytes) != digest:
            return False
        if _sha256_bytes(document_bytes) != content_digest:
            return False
        envelope = json.loads(envelope_bytes)
        document = json.loads(document_bytes)
        content_ir = envelope.get("content_ir") if isinstance(envelope, dict) else None
        if (
            not isinstance(document, dict)
            or not isinstance(content_ir, dict)
            or envelope.get("schema_version") != CANONICAL_SCHEMA_VERSION
            or content_ir.get("kind") != "DoclingDocument"
            or content_ir.get("relative_path") != _DOCUMENT_FILE
            or content_ir.get("sha256") != content_digest
        ):
            return False
        assets = _validated_asset_descriptors(manifest.get("assets"))
        if envelope.get("assets") != assets:
            return False
        return _stored_assets_match(path, assets)
    except (OSError, ValueError, json.JSONDecodeError, zstandard.ZstdError):
        return False


def _validated_asset_descriptors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("asset descriptors")
    descriptors: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_size = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "relative_path",
            "media_type",
            "sha256",
            "size",
        }:
            raise ValueError("asset descriptor")
        relative_path = item.get("relative_path")
        media_type = item.get("media_type")
        digest = item.get("sha256")
        size = item.get("size")
        if (
            not isinstance(relative_path, str)
            or not isinstance(media_type, str)
            or not isinstance(digest, str)
            or type(size) is not int
            or size < 1
            or not _SHA256_PATTERN.fullmatch(digest)
        ):
            raise ValueError("asset descriptor fields")
        relative = PurePosixPath(relative_path)
        if (
            relative.as_posix() != relative_path
            or relative.is_absolute()
            or len(relative.parts) != 2
            or relative.parts[0] != "assets"
            or not relative.parts[1].startswith(f"{digest}.")
            or relative.parts[1].split(".")[-1] not in {"jpg", "png"}
            or media_type not in {"image/jpeg", "image/png"}
            or relative_path in seen
        ):
            raise ValueError("asset descriptor identity")
        total_size += size
        if total_size > MAX_CANONICAL_ASSETS_BYTES:
            raise ValueError("asset total size")
        seen.add(relative_path)
        descriptors.append(
            {
                "relative_path": relative_path,
                "media_type": media_type,
                "sha256": digest,
                "size": size,
            }
        )
    if descriptors != sorted(descriptors, key=lambda item: item["relative_path"]):
        raise ValueError("asset descriptor order")
    return descriptors


def _stored_assets_match(path: Path, assets: list[dict[str, Any]]) -> bool:
    assets_root = path / "assets"
    children = _safe_children(assets_root)
    if children is None:
        return not assets and not assets_root.exists() and not _is_link_like(assets_root)
    expected_names = {
        PurePosixPath(str(descriptor["relative_path"])).parts[1]
        for descriptor in assets
    }
    if {child.name for child in children} != expected_names:
        return False
    descriptors_by_name = {
        PurePosixPath(str(descriptor["relative_path"])).parts[1]: descriptor
        for descriptor in assets
    }
    for child in children:
        descriptor = descriptors_by_name[child.name]
        if not _is_safe_regular_file(child):
            return False
        try:
            if child.stat().st_size != descriptor["size"]:
                return False
            if _sha256_file(child) != descriptor["sha256"]:
                return False
        except OSError:
            return False
    return True


def _is_recognized_canonical_staging(path: Path) -> bool:
    children = _safe_children(path)
    if children is None:
        return False
    for child in children:
        if child.name == "assets":
            assets = _safe_children(child)
            if assets is None or any(
                not _CANONICAL_ASSET_PATTERN.fullmatch(asset.name)
                or not _is_safe_regular_file(asset)
                for asset in assets
            ):
                return False
        elif child.name not in _CANONICAL_BASE_FILES or not _is_safe_regular_file(child):
            return False
    return True


def _read_regular_bounded(path: Path, maximum_bytes: int) -> bytes:
    if not _is_safe_regular_file(path):
        raise ValueError("unsafe file")
    size = path.stat().st_size
    if size < 1 or size > maximum_bytes:
        raise ValueError("file size")
    with path.open("rb") as stream:
        payload = stream.read(maximum_bytes + 1)
    if len(payload) != size or len(payload) > maximum_bytes:
        raise ValueError("file size")
    return payload


def _decompress_bounded(payload: bytes) -> bytes:
    value = zstandard.ZstdDecompressor().decompress(
        payload,
        max_output_size=MAX_CANONICAL_JSON_BYTES,
    )
    if len(value) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical payload too large")
    return value


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_with_retries(source: Path, target: Path) -> bool:
    for attempt in range(len(_SHARING_RETRY_DELAYS) + 1):
        try:
            os.replace(source, target)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            if not _is_windows_sharing_violation(exc) or attempt >= len(
                _SHARING_RETRY_DELAYS
            ):
                raise
            _discard_exception_traceback(exc)
            gc.collect()
            time.sleep(_SHARING_RETRY_DELAYS[attempt])
    return False


def _remove_with_retries(path: Path) -> bool:
    for attempt in range(len(_SHARING_RETRY_DELAYS) + 1):
        try:
            if _is_link_like(path):
                return False
            if _is_safe_directory(path):
                shutil.rmtree(path)
            elif _is_safe_regular_file(path):
                path.unlink()
            else:
                return not path.exists() and not _is_link_like(path)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            retryable = _is_windows_sharing_violation(exc)
            _discard_exception_traceback(exc)
            if not retryable or attempt >= len(_SHARING_RETRY_DELAYS):
                return False
            gc.collect()
            time.sleep(_SHARING_RETRY_DELAYS[attempt])
    return False


def _is_windows_sharing_violation(exc: OSError) -> bool:
    return (
        getattr(exc, "winerror", None) in _WINDOWS_SHARING_VIOLATIONS
        or isinstance(exc, PermissionError)
    )


def _discard_exception_traceback(exc: Exception) -> None:
    exc.__traceback__ = None
    exc.__cause__ = None
    exc.__context__ = None
