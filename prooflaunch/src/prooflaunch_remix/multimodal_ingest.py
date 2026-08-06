from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class IngestError(ValueError):
    pass


class MediaKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    PDF = "pdf"
    TEXT = "text"


class RightsStatus(str, Enum):
    OWNED = "owned"
    LICENSED = "licensed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MediaSource:
    path: str
    role: str
    rights: RightsStatus = RightsStatus.UNKNOWN
    declared_kind: MediaKind | None = None


@dataclass(frozen=True)
class MediaArtifact:
    id: str
    path: str
    role: str
    kind: MediaKind
    mime_type: str
    sha256: str
    byte_size: int
    rights: RightsStatus

    def serializable(self) -> dict:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["rights"] = self.rights.value
        return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kind_from_signature(path: Path) -> tuple[MediaKind, str]:
    with path.open("rb") as handle:
        header = handle.read(32)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaKind.IMAGE, "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return MediaKind.IMAGE, "image/jpeg"
    if header[:6] in {b"GIF87a", b"GIF89a"}:
        return MediaKind.IMAGE, "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return MediaKind.IMAGE, "image/webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return MediaKind.VIDEO, "video/mp4"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return MediaKind.VIDEO, "video/webm"
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return MediaKind.AUDIO, "audio/wav"
    if header.startswith(b"fLaC"):
        return MediaKind.AUDIO, "audio/flac"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    ):
        return MediaKind.AUDIO, "audio/mpeg"
    if header.startswith(b"%PDF-"):
        return MediaKind.PDF, "application/pdf"

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}:
        try:
            header.decode("utf-8")
        except UnicodeDecodeError as error:
            raise IngestError(f"text input is not valid UTF-8: {path}") from error
        mime = mimetypes.guess_type(path.name)[0] or "text/plain"
        return MediaKind.TEXT, mime
    raise IngestError(f"unsupported or signature-mismatched media: {path}")


class MultimodalIngestor:
    """Signature-aware, hash-addressed intake for user-supplied media."""

    def ingest(self, sources: Iterable[MediaSource]) -> tuple[MediaArtifact, ...]:
        artifacts: list[MediaArtifact] = []
        seen: dict[str, str] = {}
        for position, source in enumerate(sources, start=1):
            path = Path(source.path).expanduser().resolve()
            if not path.is_file():
                raise IngestError(f"input file not found: {path}")
            kind, mime_type = _kind_from_signature(path)
            if source.declared_kind is not None and source.declared_kind != kind:
                raise IngestError(
                    f"declared {source.declared_kind.value} but detected "
                    f"{kind.value}: {path}"
                )
            digest = _sha256(path)
            if digest in seen:
                raise IngestError(
                    f"duplicate media content: {path} matches {seen[digest]}"
                )
            seen[digest] = str(path)
            artifacts.append(
                MediaArtifact(
                    id=f"MED-{position:03d}-{digest[:8]}",
                    path=str(path),
                    role=source.role.strip() or "reference",
                    kind=kind,
                    mime_type=mime_type,
                    sha256=digest,
                    byte_size=path.stat().st_size,
                    rights=source.rights,
                )
            )
        if not artifacts:
            raise IngestError("at least one media source is required")
        return tuple(artifacts)

