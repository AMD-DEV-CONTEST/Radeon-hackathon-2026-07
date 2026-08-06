from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ..exceptions import ValidationError

MAX_CANONICAL_ASSET_BYTES = 64 * 1024 * 1024
MAX_CANONICAL_ASSETS_BYTES = 256 * 1024 * 1024
_IMAGE_MEDIA_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
}


@dataclass(frozen=True)
class CanonicalIdentity:
    library_id: str
    document_id: str
    import_id: str
    canonical_generation_id: str
    source_artifact_id: str
    source_sha256: str
    source_format: str
    media_type: str | None
    display_name: str
    title: str
    attempt_number: int


@dataclass(frozen=True)
class CanonicalMaterial:
    envelope: dict[str, Any]
    docling_document: dict[str, Any]
    assets: tuple["CanonicalAsset", ...] = ()


@dataclass(frozen=True)
class CanonicalAsset:
    relative_path: str
    media_type: str
    sha256: str
    size: int
    payload: bytes

    def descriptor(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "size": self.size,
        }


class Canonicalizer:
    """Freeze a DoclingDocument and Xenix lifecycle/pipeline descriptors."""

    def freeze(
        self,
        document: Any,
        *,
        identity: CanonicalIdentity,
        pipeline: dict[str, Any],
        warnings: list[str],
        projections: list[dict[str, Any]] | None = None,
    ) -> CanonicalMaterial:
        try:
            exported = document.export_to_dict()
        except Exception as exc:
            raise ValidationError(
                "Docling content could not be serialized.",
                error_code="knowledge_canonical_serialization_failed",
            ) from exc
        externalized, assets = _externalize_embedded_assets(exported)
        sanitized = _sanitize_docling_payload(externalized)
        if not isinstance(sanitized, dict):
            raise ValidationError("Docling content has an invalid shape.")
        _validate_docling_document(sanitized)
        docling_schema = _docling_schema_descriptor()
        envelope = {
            "canonical_generation_id": identity.canonical_generation_id,
            "document": {
                "id": identity.document_id,
                "library_id": identity.library_id,
                "title": identity.title,
            },
            "import": {
                "id": identity.import_id,
                "attempt_number": identity.attempt_number,
            },
            "source": {
                "artifact_id": identity.source_artifact_id,
                "sha256": identity.source_sha256,
                "format": identity.source_format,
                "media_type": identity.media_type,
                "display_name": identity.display_name,
            },
            "runtime": {
                "docling": _package_version("docling"),
                "docling_core": _package_version("docling-core"),
                "docling_schema": docling_schema,
            },
            "pipeline": _bounded_json_object(pipeline, label="Knowledge pipeline descriptor"),
            "assets": [asset.descriptor() for asset in assets],
            "projections": list(projections or ()),
            "warnings": sorted(dict.fromkeys(_safe_tokens(warnings))),
            "validation": {
                "docling_model_validated": True,
                "contained_references": True,
                "absolute_source_paths_removed": True,
            },
        }
        return CanonicalMaterial(
            envelope=envelope,
            docling_document=sanitized,
            assets=assets,
        )


def _externalize_embedded_assets(value: Any) -> tuple[Any, tuple[CanonicalAsset, ...]]:
    assets: dict[tuple[str, str], CanonicalAsset] = {}
    total_size = 0

    def visit(item: Any) -> Any:
        nonlocal total_size
        if isinstance(item, dict):
            copied = {str(key): visit(child) for key, child in item.items()}
            if {"mimetype", "dpi", "size", "uri"}.issubset(copied):
                uri = copied.get("uri")
                media_type = copied.get("mimetype")
                if not isinstance(uri, str) or not isinstance(media_type, str):
                    raise ValidationError(
                        "Docling image reference is invalid.",
                        error_code="knowledge_canonical_asset_invalid",
                    )
                if not uri.startswith("data:"):
                    raise ValidationError(
                        "Docling image bytes are unavailable for canonical storage.",
                        error_code="knowledge_canonical_asset_unavailable",
                    )
                prefix = f"data:{media_type};base64,"
                extension = _IMAGE_MEDIA_EXTENSIONS.get(media_type.casefold())
                if extension is None or not uri.startswith(prefix):
                    raise ValidationError(
                        "Docling image encoding is not supported.",
                        error_code="knowledge_canonical_asset_invalid",
                    )
                try:
                    payload = base64.b64decode(uri[len(prefix) :], validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValidationError(
                        "Docling image encoding is invalid.",
                        error_code="knowledge_canonical_asset_invalid",
                    ) from exc
                if not payload or len(payload) > MAX_CANONICAL_ASSET_BYTES:
                    raise ValidationError(
                        "Docling image exceeds the supported size.",
                        error_code="knowledge_canonical_asset_too_large",
                    )
                digest = hashlib.sha256(payload).hexdigest()
                key = (digest, media_type.casefold())
                if key not in assets:
                    total_size += len(payload)
                    if total_size > MAX_CANONICAL_ASSETS_BYTES:
                        raise ValidationError(
                            "Docling images exceed the supported total size.",
                            error_code="knowledge_canonical_assets_too_large",
                        )
                    assets[key] = CanonicalAsset(
                        relative_path=f"assets/{digest}.{extension}",
                        media_type=media_type.casefold(),
                        sha256=digest,
                        size=len(payload),
                        payload=payload,
                    )
                copied["uri"] = assets[key].relative_path
            return copied
        if isinstance(item, list):
            return [visit(child) for child in item]
        return item

    transformed = visit(value)
    ordered = tuple(sorted(assets.values(), key=lambda asset: asset.relative_path))
    return transformed, ordered


def _validate_docling_document(payload: dict[str, Any]) -> None:
    try:
        from docling_core.types.doc import DoclingDocument

        DoclingDocument.model_validate(payload)
    except Exception as exc:
        raise ValidationError(
            "Docling content failed schema validation.",
            error_code="knowledge_canonical_schema_failed",
        ) from exc


def _docling_schema_descriptor() -> dict[str, str]:
    from docling_core.types.doc import DoclingDocument

    schema = DoclingDocument.model_json_schema()
    schema_payload = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    fields = DoclingDocument.model_fields
    schema_name = str(fields["schema_name"].default)
    schema_version = str(fields["version"].default)
    return {
        "name": schema_name,
        "version": schema_version,
        "fingerprint": hashlib.sha256(schema_payload).hexdigest(),
    }


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _sanitize_docling_payload(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_docling_payload(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_docling_payload(item, key=key) for item in value]
    if isinstance(value, str) and key in {"path", "uri"}:
        candidate = Path(value)
        if candidate.is_absolute() or "://" in value or value.startswith(("~", "\\\\")):
            name = candidate.name.strip()
            return name if name and name not in {".", ".."} else None
    return value


def _bounded_json_object(value: dict[str, Any], *, label: str) -> dict[str, Any]:
    try:
        frozen = json.loads(
            json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} is invalid.") from exc
    if not isinstance(frozen, dict):
        raise ValidationError(f"{label} must be an object.")
    if len(json.dumps(frozen, ensure_ascii=False).encode("utf-8")) > 256 * 1024:
        raise ValidationError(f"{label} is too large.")
    return frozen


def _safe_tokens(values: list[str]) -> list[str]:
    safe: list[str] = []
    for value in values:
        token = str(value).strip()
        if token and len(token) <= 96 and token.replace("_", "").replace("-", "").isalnum():
            safe.append(token)
    return safe
