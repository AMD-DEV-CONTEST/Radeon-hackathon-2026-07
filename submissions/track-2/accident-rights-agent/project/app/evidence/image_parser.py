"""Image validation and evidence-node creation."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

from app.evidence.errors import DependencyUnavailable, UnsupportedEvidence
from app.schemas.evidence import EvidenceNode, SourceFile


def parse_image(source: SourceFile, path: Path) -> EvidenceNode:
    width, height, metadata = image_metadata(path)
    if width < 16 or height < 16:
        raise UnsupportedEvidence(
            f"Image is too small for evidence extraction: {width}x{height}."
        )
    digest = _sha256(path)
    return EvidenceNode(
        node_id=f"NODE-{source.source_id[4:]}-IMAGE",
        case_id=source.case_id,
        source_id=source.source_id,
        node_type="image",
        locator={"source_path": source.stored_path, "region": "full_image"},
        content_sha256=digest,
        confidence=1.0,
        extraction_method="image_metadata",
        metadata={"width": width, "height": height, **metadata},
    )


def image_metadata(path: Path) -> tuple[int, int, dict[str, Any]]:
    """Read basic metadata with Pillow, with a pure-Python PNG fallback."""

    try:
        from PIL import Image
    except ImportError:
        return _png_metadata_without_pillow(path)

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            metadata = {
                "format": image.format,
                "mode": image.mode,
                "exif_orientation": image.getexif().get(274),
            }
    except Exception as exc:
        raise UnsupportedEvidence(f"Image decoder rejected {path.name}: {exc}") from exc
    return width, height, metadata


def _png_metadata_without_pillow(path: Path) -> tuple[int, int, dict[str, Any]]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if not header.startswith(b"\x89PNG\r\n\x1a\n") or header[12:16] != b"IHDR":
        raise DependencyUnavailable(
            "Pillow is required to decode non-PNG images. "
            "Install the project 'evidence' extra."
        )
    width, height = struct.unpack(">II", header[16:24])
    return width, height, {"format": "PNG", "mode": None, "exif_orientation": None}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
