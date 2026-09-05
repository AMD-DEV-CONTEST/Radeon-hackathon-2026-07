from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import zstandard

from ..config import AppPaths
from ..exceptions import ValidationError
from .knowledge_canonical import CanonicalAsset, MAX_CANONICAL_ASSETS_BYTES
from .storage.layout import knowledge_objects_root, knowledge_root, knowledge_staging_root

CANONICAL_SCHEMA_VERSION = 2
MAX_CANONICAL_JSON_BYTES = 256 * 1024 * 1024
MAX_CANONICAL_COMPRESSED_BYTES = 256 * 1024 * 1024
MAX_CANONICAL_MANIFEST_BYTES = 1024 * 1024
_MANIFEST_FILE = "manifest.json"
_ENVELOPE_FILE = "canonical-envelope.json.zst"
_DOCUMENT_FILE = "docling-document.json.zst"
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


@dataclass(frozen=True)
class StoredKnowledgeSource:
    sha256: str
    path: Path
    size: int


@dataclass(frozen=True)
class StoredCanonicalBundle:
    envelope_sha256: str
    content_ir_sha256: str
    relative_path: str
    path: Path


@dataclass(frozen=True)
class CanonicalBundle:
    envelope: dict[str, Any]
    docling_document: dict[str, Any]
    stored: StoredCanonicalBundle


@dataclass(frozen=True)
class CanonicalBundleIdentity:
    document_id: str
    import_id: str | None
    canonical_generation_id: str
    source_artifact_id: str | None
    library_id: str
    source_sha256: str
    source_format: str


@dataclass(frozen=True)
class _CanonicalBundleMaterial:
    envelope_bytes: bytes
    document_bytes: bytes
    envelope_sha256: str
    content_ir_sha256: str
    assets: tuple[CanonicalAsset, ...]
    asset_descriptors: tuple[dict[str, Any], ...]


class KnowledgeContentStore:
    """Own immutable source snapshots and verified canonical bundles.

    SQLite stores only contained paths relative to the Knowledge root.  A bundle is
    addressed by the deterministic envelope bytes; the envelope in turn binds the
    exact DoclingDocument JSON hash.  Existing targets are always reopened and
    verified instead of being trusted merely because a path exists.
    """

    def __init__(self, paths: AppPaths) -> None:
        self._root = knowledge_root(paths).resolve()
        self._objects = knowledge_objects_root(paths).resolve()
        self._staging = knowledge_staging_root(paths).resolve()
        self._objects.mkdir(parents=True, exist_ok=True)
        self._staging.mkdir(parents=True, exist_ok=True)

    def snapshot_source(
        self,
        source_path: Path,
        *,
        maximum_bytes: int | None = None,
    ) -> StoredKnowledgeSource:
        if maximum_bytes is not None and maximum_bytes < 1:
            raise ValueError("Knowledge source byte limit must be positive.")
        source = source_path.expanduser().resolve()
        if not source.is_file():
            raise ValidationError("Knowledge source must be an existing local file.")
        staged = self._staging / f"source-{uuid4().hex}.tmp"
        digest_builder = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as source_stream, staged.open("xb") as target_stream:
                for block in iter(lambda: source_stream.read(1024 * 1024), b""):
                    size += len(block)
                    if maximum_bytes is not None and size > maximum_bytes:
                        raise ValidationError(
                            "Knowledge source size is outside the supported range.",
                            error_code="knowledge_source_size_unsupported",
                        )
                    digest_builder.update(block)
                    target_stream.write(block)
                target_stream.flush()
                os.fsync(target_stream.fileno())
            digest = digest_builder.hexdigest()
            suffix = _safe_source_suffix(source.suffix)
            target = self._source_directory(digest) / f"source{suffix}"
            if target.exists():
                self._verify_source(target, expected_sha256=digest, expected_size=size)
                staged.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                self._atomic_publish_file(staged, target)
                self._verify_source(target, expected_sha256=digest, expected_size=size)
            return StoredKnowledgeSource(sha256=digest, path=target, size=size)
        finally:
            staged.unlink(missing_ok=True)

    def verify_source_snapshot(
        self,
        source_path: Path,
        *,
        expected_sha256: str,
    ) -> StoredKnowledgeSource:
        """Re-establish CAS location and byte identity before every parse/resume."""

        _require_sha256(expected_sha256)
        candidate = source_path.expanduser()
        expected_directory = self._source_directory(expected_sha256)
        try:
            if (
                candidate.name != "source"
                and not candidate.name.startswith("source.")
            ):
                raise ValueError("source name")
            if candidate.parent.resolve() != expected_directory.resolve():
                raise ValueError("source directory")
            self._reject_link_like_path(candidate, stop=self._root)
            resolved = candidate.resolve(strict=True)
            if resolved.parent != expected_directory.resolve(strict=True):
                raise ValueError("resolved source directory")
            size = resolved.stat().st_size
            self._verify_source(
                resolved,
                expected_sha256=expected_sha256,
                expected_size=size,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValidationError(
                "Knowledge source snapshot failed integrity validation.",
                error_code="knowledge_source_integrity_failed",
            ) from exc
        return StoredKnowledgeSource(
            sha256=expected_sha256,
            path=resolved,
            size=size,
        )

    def write_canonical_bundle(
        self,
        *,
        envelope: dict[str, Any],
        docling_document: dict[str, Any],
        assets: Sequence[CanonicalAsset] = (),
    ) -> StoredCanonicalBundle:
        material = _prepare_canonical_bundle(
            envelope=envelope,
            docling_document=docling_document,
            assets=assets,
        )
        target = self._canonical_directory(material.envelope_sha256)
        relative_path = target.relative_to(self._root).as_posix()
        stored = StoredCanonicalBundle(
            envelope_sha256=material.envelope_sha256,
            content_ir_sha256=material.content_ir_sha256,
            relative_path=relative_path,
            path=target,
        )
        if target.exists():
            self.read_canonical_bundle(
                relative_path,
                expected_envelope_sha256=material.envelope_sha256,
                expected_content_ir_sha256=material.content_ir_sha256,
            )
            return stored

        staged = self._staging / f"canonical-{uuid4().hex}"
        try:
            _write_canonical_directory(staged, material)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staged, target)
            except OSError:
                if not target.exists():
                    raise
            self.read_canonical_bundle(
                relative_path,
                expected_envelope_sha256=material.envelope_sha256,
                expected_content_ir_sha256=material.content_ir_sha256,
            )
            return stored
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)

    def stage_canonical_bundle(
        self,
        stage: Path,
        *,
        envelope: dict[str, Any],
        docling_document: dict[str, Any],
        assets: Sequence[CanonicalAsset] = (),
    ) -> StoredCanonicalBundle:
        """Write a worker result only inside its private task directory."""

        relative_path = self._task_canonical_relative_path(stage)
        if stage.exists():
            raise ValidationError("Knowledge task output already exists.")
        material = _prepare_canonical_bundle(
            envelope=envelope,
            docling_document=docling_document,
            assets=assets,
        )
        try:
            _write_canonical_directory(stage, material)
            bundle = self.read_canonical_bundle(
                relative_path,
                expected_envelope_sha256=material.envelope_sha256,
                expected_content_ir_sha256=material.content_ir_sha256,
            )
            return bundle.stored
        except Exception:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            raise

    def publish_staged_canonical_bundle(
        self,
        relative_path: str,
        *,
        import_id: str,
        expected_envelope_sha256: str,
        expected_content_ir_sha256: str,
        expected_identity: CanonicalBundleIdentity,
    ) -> CanonicalBundle:
        """Admit one validated worker output into immutable CAS.

        Only the parent write coordinator calls this method. The child process can
        create a private task directory but cannot choose or mutate the published
        CAS location.
        """

        expected_relative = f"tasks/imports/{import_id}/canonical"
        if relative_path != expected_relative:
            raise ValidationError(
                "Knowledge worker output is outside its private task directory.",
                error_code="knowledge_canonical_integrity_failed",
            )
        staged = self._contained_path(relative_path)
        self._task_canonical_relative_path(staged)
        self.read_canonical_bundle(
            relative_path,
            expected_envelope_sha256=expected_envelope_sha256,
            expected_content_ir_sha256=expected_content_ir_sha256,
            expected_identity=expected_identity,
        )
        target = self._canonical_directory(expected_envelope_sha256)
        target_relative = target.relative_to(self._root).as_posix()
        if target.exists():
            bundle = self.read_canonical_bundle(
                target_relative,
                expected_envelope_sha256=expected_envelope_sha256,
                expected_content_ir_sha256=expected_content_ir_sha256,
                expected_identity=expected_identity,
            )
            shutil.rmtree(staged, ignore_errors=True)
            return bundle
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(staged, target)
        except OSError:
            if not target.exists():
                raise
            shutil.rmtree(staged, ignore_errors=True)
        return self.read_canonical_bundle(
            target_relative,
            expected_envelope_sha256=expected_envelope_sha256,
            expected_content_ir_sha256=expected_content_ir_sha256,
            expected_identity=expected_identity,
        )

    def discard_staged_canonical_bundle(self, import_id: str) -> None:
        if (
            len(import_id) != 32
            or any(character not in "0123456789abcdef" for character in import_id)
        ):
            return
        staged = self._root / "tasks" / "imports" / import_id / "canonical"
        self._task_canonical_relative_path(staged)
        shutil.rmtree(staged, ignore_errors=True)

    def read_canonical_bundle(
        self,
        relative_path: str,
        *,
        expected_envelope_sha256: str | None = None,
        expected_content_ir_sha256: str | None = None,
        expected_identity: CanonicalBundleIdentity | None = None,
    ) -> CanonicalBundle:
        directory = self._contained_path(relative_path)
        if not directory.is_dir():
            raise ValidationError(
                "Knowledge canonical content is unavailable.",
                error_code="knowledge_canonical_unavailable",
            )
        try:
            manifest = json.loads(
                _read_bounded(directory / _MANIFEST_FILE, MAX_CANONICAL_MANIFEST_BYTES).decode(
                    "utf-8"
                )
            )
            if (
                not isinstance(manifest, dict)
                or set(manifest) != _MANIFEST_KEYS
                or manifest.get("schema_version") != CANONICAL_SCHEMA_VERSION
            ):
                raise ValueError("manifest version")
            if manifest.get("envelope_file") != _ENVELOPE_FILE:
                raise ValueError("envelope file")
            if manifest.get("content_ir_file") != _DOCUMENT_FILE:
                raise ValueError("content file")
            envelope_bytes = _decompress_bounded(
                _read_bounded(directory / _ENVELOPE_FILE, MAX_CANONICAL_COMPRESSED_BYTES)
            )
            document_bytes = _decompress_bounded(
                _read_bounded(directory / _DOCUMENT_FILE, MAX_CANONICAL_COMPRESSED_BYTES)
            )
            envelope_sha256 = _sha256_bytes(envelope_bytes)
            content_ir_sha256 = _sha256_bytes(document_bytes)
            if manifest.get("envelope_sha256") != envelope_sha256:
                raise ValueError("envelope hash")
            if manifest.get("content_ir_sha256") != content_ir_sha256:
                raise ValueError("content hash")
            if expected_envelope_sha256 and envelope_sha256 != expected_envelope_sha256:
                raise ValueError("expected envelope hash")
            if expected_content_ir_sha256 and content_ir_sha256 != expected_content_ir_sha256:
                raise ValueError("expected content hash")
            envelope = json.loads(envelope_bytes)
            document = json.loads(document_bytes)
            content_ir = envelope.get("content_ir") if isinstance(envelope, dict) else None
            if not isinstance(content_ir, dict):
                raise ValueError("content descriptor")
            if content_ir.get("kind") != "DoclingDocument":
                raise ValueError("content kind")
            if content_ir.get("relative_path") != _DOCUMENT_FILE:
                raise ValueError("content relative path")
            if content_ir.get("sha256") != content_ir_sha256:
                raise ValueError("bound content hash")
            if not isinstance(document, dict):
                raise ValueError("document JSON")
            if expected_identity is not None:
                _verify_envelope_identity(envelope, expected_identity)
            assets = _validated_asset_descriptors(manifest.get("assets"))
            if envelope.get("assets") != assets:
                raise ValueError("asset manifest binding")
            _verify_stored_assets(directory, assets)
        except (OSError, ValueError, json.JSONDecodeError, zstandard.ZstdError) as exc:
            raise ValidationError(
                "Knowledge canonical content failed integrity validation.",
                error_code="knowledge_canonical_integrity_failed",
            ) from exc
        return CanonicalBundle(
            envelope=envelope,
            docling_document=document,
            stored=StoredCanonicalBundle(
                envelope_sha256=envelope_sha256,
                content_ir_sha256=content_ir_sha256,
                relative_path=relative_path,
                path=directory,
            ),
        )

    def resolve_relative_path(self, relative_path: str) -> Path:
        return self._contained_path(relative_path)

    def resolve_legacy_canonical_path(self, stored_path: str) -> Path:
        """Resolve the v16-v18 single-file canonical locator without widening trust."""

        candidate = Path(stored_path).expanduser()
        if not candidate.is_absolute():
            candidate = self._root / candidate
        try:
            self._reject_link_like_path(candidate, stop=self._root)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._root)
            if (
                resolved.name != _DOCUMENT_FILE
                or not resolved.is_file()
                or _path_is_link_like(resolved)
            ):
                raise ValueError("legacy canonical locator")
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValidationError(
                "Legacy Knowledge canonical content is unavailable.",
                error_code="knowledge_canonical_unavailable",
            ) from exc
        return resolved

    def _source_directory(self, digest: str) -> Path:
        _require_sha256(digest)
        return self._objects / "source" / digest[:2] / digest[2:4] / digest

    def _canonical_directory(self, digest: str) -> Path:
        _require_sha256(digest)
        return self._objects / "canonical" / digest[:2] / digest[2:4] / digest

    def _contained_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or not relative_path.strip():
            raise ValidationError("Knowledge content path is invalid.")
        resolved = (self._root / candidate).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValidationError("Knowledge content path is invalid.") from exc
        return resolved

    def _task_canonical_relative_path(self, stage: Path) -> str:
        resolved = stage.resolve()
        try:
            relative = resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValidationError("Knowledge task output path is invalid.") from exc
        parts = relative.parts
        if (
            len(parts) != 4
            or parts[:2] != ("tasks", "imports")
            or len(parts[2]) != 32
            or any(character not in "0123456789abcdef" for character in parts[2])
            or parts[3] != "canonical"
        ):
            raise ValidationError("Knowledge task output path is invalid.")
        return relative.as_posix()

    @staticmethod
    def _reject_link_like_path(path: Path, *, stop: Path) -> None:
        current = path
        while True:
            is_junction = getattr(current, "is_junction", None)
            if current.is_symlink() or bool(is_junction and is_junction()):
                raise ValueError("link-like Knowledge path")
            if current == stop:
                return
            if current.parent == current:
                raise ValueError("Knowledge root is not an ancestor")
            current = current.parent

    @staticmethod
    def _verify_source(path: Path, *, expected_sha256: str, expected_size: int) -> None:
        if path.stat().st_size != expected_size or _sha256_file(path) != expected_sha256:
            raise ValidationError(
                "Knowledge source snapshot failed integrity validation.",
                error_code="knowledge_source_integrity_failed",
            )

    @staticmethod
    def _atomic_publish_file(staged: Path, target: Path) -> None:
        try:
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)


def _prepare_canonical_bundle(
    *,
    envelope: dict[str, Any],
    docling_document: dict[str, Any],
    assets: Sequence[CanonicalAsset],
) -> _CanonicalBundleMaterial:
    verified_assets = tuple(_validated_assets(assets))
    asset_descriptors = tuple(asset.descriptor() for asset in verified_assets)
    document_bytes = _canonical_json_bytes(docling_document)
    content_ir_sha256 = _sha256_bytes(document_bytes)
    frozen_envelope = json.loads(json.dumps(envelope, ensure_ascii=False))
    frozen_envelope["schema_version"] = CANONICAL_SCHEMA_VERSION
    frozen_envelope["content_ir"] = {
        "kind": "DoclingDocument",
        "relative_path": _DOCUMENT_FILE,
        "sha256": content_ir_sha256,
    }
    declared_assets = frozen_envelope.get("assets")
    if declared_assets not in (None, list(asset_descriptors)):
        raise ValidationError(
            "Knowledge canonical asset manifest does not match its payloads.",
            error_code="knowledge_canonical_asset_integrity_failed",
        )
    frozen_envelope["assets"] = list(asset_descriptors)
    envelope_bytes = _canonical_json_bytes(frozen_envelope)
    return _CanonicalBundleMaterial(
        envelope_bytes=envelope_bytes,
        document_bytes=document_bytes,
        envelope_sha256=_sha256_bytes(envelope_bytes),
        content_ir_sha256=content_ir_sha256,
        assets=verified_assets,
        asset_descriptors=asset_descriptors,
    )


def _write_canonical_directory(
    directory: Path,
    material: _CanonicalBundleMaterial,
) -> None:
    directory.mkdir(parents=False, exist_ok=False)
    compressor = zstandard.ZstdCompressor(level=7, write_checksum=True)
    for asset in material.assets:
        asset_path = directory.joinpath(*Path(asset.relative_path).parts)
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        _write_file_fsynced(asset_path, asset.payload)
    _write_file_fsynced(
        directory / _ENVELOPE_FILE,
        compressor.compress(material.envelope_bytes),
    )
    _write_file_fsynced(
        directory / _DOCUMENT_FILE,
        compressor.compress(material.document_bytes),
    )
    _write_file_fsynced(
        directory / _MANIFEST_FILE,
        _canonical_json_bytes(
            {
                "schema_version": CANONICAL_SCHEMA_VERSION,
                "envelope_file": _ENVELOPE_FILE,
                "envelope_sha256": material.envelope_sha256,
                "content_ir_file": _DOCUMENT_FILE,
                "content_ir_sha256": material.content_ir_sha256,
                "assets": list(material.asset_descriptors),
            }
        ),
    )


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("Knowledge canonical content is not valid JSON.") from exc
    if len(payload) > MAX_CANONICAL_JSON_BYTES:
        raise ValidationError("Knowledge canonical content exceeds the supported size.")
    return payload


def _decompress_bounded(payload: bytes) -> bytes:
    value = zstandard.ZstdDecompressor().decompress(
        payload,
        max_output_size=MAX_CANONICAL_JSON_BYTES,
    )
    if len(value) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical payload too large")
    return value


def _read_bounded(path: Path, maximum_bytes: int) -> bytes:
    if _path_is_link_like(path):
        raise ValueError("link-like canonical file")
    size = path.stat().st_size
    if size < 1 or size > maximum_bytes:
        raise ValueError("canonical file size")
    with path.open("rb") as stream:
        payload = stream.read(maximum_bytes + 1)
    if len(payload) != size or len(payload) > maximum_bytes:
        raise ValueError("canonical file size")
    return payload


def _validated_assets(assets: Sequence[CanonicalAsset]) -> tuple[CanonicalAsset, ...]:
    if isinstance(assets, (str, bytes, bytearray)):
        raise ValidationError("Knowledge canonical assets are invalid.")
    ordered = tuple(sorted(assets, key=lambda asset: asset.relative_path))
    try:
        descriptors = _validated_asset_descriptors(
            [asset.descriptor() for asset in ordered]
        )
    except ValueError as exc:
        raise ValidationError("Knowledge canonical assets are invalid.") from exc
    if descriptors != [asset.descriptor() for asset in ordered]:
        raise ValidationError("Knowledge canonical assets are invalid.")
    for asset in ordered:
        if (
            not isinstance(asset.payload, bytes)
            or len(asset.payload) != asset.size
            or _sha256_bytes(asset.payload) != asset.sha256
        ):
            raise ValidationError(
                "Knowledge canonical asset failed integrity validation.",
                error_code="knowledge_canonical_asset_integrity_failed",
            )
    return ordered


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
        ):
            raise ValueError("asset descriptor fields")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("asset digest")
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


def _verify_stored_assets(directory: Path, assets: list[dict[str, Any]]) -> None:
    assets_root = directory / "assets"
    expected_paths: set[Path] = set()
    for descriptor in assets:
        relative = PurePosixPath(str(descriptor["relative_path"]))
        path = directory.joinpath(*relative.parts)
        if _path_is_link_like(path) or path.resolve().parent != assets_root.resolve():
            raise ValueError("asset containment")
        if path.stat().st_size != descriptor["size"]:
            raise ValueError("asset size")
        if _sha256_file(path) != descriptor["sha256"]:
            raise ValueError("asset hash")
        expected_paths.add(path.resolve())
    if not assets_root.exists():
        if assets:
            raise ValueError("asset directory")
        return
    if _path_is_link_like(assets_root) or not assets_root.is_dir():
        raise ValueError("asset directory")
    actual_paths: set[Path] = set()
    for child in assets_root.rglob("*"):
        if _path_is_link_like(child):
            raise ValueError("asset link")
        if child.is_file():
            actual_paths.add(child.resolve())
        elif not child.is_dir():
            raise ValueError("asset entry")
    if actual_paths != expected_paths:
        raise ValueError("asset file set")


def _verify_envelope_identity(
    envelope: Any,
    expected: CanonicalBundleIdentity,
) -> None:
    if not isinstance(envelope, dict):
        raise ValueError("envelope identity")
    document = envelope.get("document")
    import_descriptor = envelope.get("import")
    source = envelope.get("source")
    if (
        envelope.get("canonical_generation_id") != expected.canonical_generation_id
        or not isinstance(document, dict)
        or document.get("id") != expected.document_id
        or document.get("library_id") != expected.library_id
        or not isinstance(import_descriptor, dict)
        or import_descriptor.get("id") != expected.import_id
        or not isinstance(source, dict)
        or source.get("artifact_id") != expected.source_artifact_id
        or source.get("sha256") != expected.source_sha256
        or source.get("format") != expected.source_format
    ):
        raise ValueError("envelope identity")


def _path_is_link_like(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _write_file_fsynced(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _safe_source_suffix(suffix: str) -> str:
    normalized = suffix.casefold()
    if normalized == ".jpeg":
        return ".jpg"
    if not normalized or len(normalized) > 12 or not normalized.startswith("."):
        return ".bin"
    if not normalized[1:].isalnum():
        return ".bin"
    return normalized


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError("Knowledge content digest is invalid.")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
