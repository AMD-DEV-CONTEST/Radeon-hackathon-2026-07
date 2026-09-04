"""Safe case creation and immutable source-file intake."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.evidence.database import EvidenceStore
from app.evidence.errors import (
    EvidenceTooLarge,
    InvalidCaseId,
    UnsupportedEvidence,
)
from app.schemas.evidence import SourceFile, SourceKind, SourceRole


CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")
DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


class CaseWorkspace:
    def __init__(self, root: Path | str = Path("data/cases")):
        self.root = Path(root).resolve()

    @staticmethod
    def new_case_id() -> str:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"CASE-{day}-{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    def validate_case_id(case_id: str) -> str:
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise InvalidCaseId(
                "case_id must be 1-64 characters using letters, numbers, _ or -."
            )
        return case_id

    def case_dir(self, case_id: str) -> Path:
        safe_id = self.validate_case_id(case_id)
        candidate = (self.root / safe_id).resolve()
        if candidate.parent != self.root:
            raise InvalidCaseId("case_id escapes the configured case root.")
        return candidate

    def create_case(self, case_id: str | None = None) -> str:
        selected = self.validate_case_id(case_id or self.new_case_id())
        directory = self.case_dir(selected)
        (directory / "sources").mkdir(parents=True, exist_ok=True)
        (directory / "derived").mkdir(parents=True, exist_ok=True)
        store = EvidenceStore(directory / "case.sqlite3")
        store.initialize(selected)
        store.audit(selected, "case_created", {"case_id": selected}, "case_intake")
        return selected

    def store(self, case_id: str) -> EvidenceStore:
        directory = self.case_dir(case_id)
        database = directory / "case.sqlite3"
        if not database.is_file():
            raise KeyError(f"Unknown case: {case_id}")
        return EvidenceStore(database)

    def ingest_file(
        self,
        case_id: str,
        source_path: Path | str,
        *,
        role: SourceRole = SourceRole.OTHER,
        original_name: str | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> SourceFile:
        source = Path(source_path)
        if source.is_symlink() or not source.is_file():
            raise UnsupportedEvidence("Source must be a regular, non-symlink file.")
        stat = source.stat()
        if stat.st_size <= 0:
            raise UnsupportedEvidence("Empty source files are not accepted.")
        if stat.st_size > max_bytes:
            raise EvidenceTooLarge(
                f"Source is {stat.st_size} bytes; limit is {max_bytes} bytes."
            )

        case_dir = self.case_dir(case_id)
        store = self.store(case_id)
        digest = _sha256(source)
        existing = next(
            (item for item in store.list_sources(case_id) if item.sha256 == digest),
            None,
        )
        if existing:
            if existing.role is SourceRole.OTHER and role is not SourceRole.OTHER:
                return store.update_source_role(existing.source_id, role)
            return existing

        display_name = original_name or source.name
        header = _read_header(source)
        kind, media_type = identify_evidence(display_name, header)
        safe_name = sanitize_filename(display_name)
        source_id = f"SRC-{digest[:16].upper()}"
        relative = Path("sources") / source_id / safe_name
        destination = case_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy(source, destination)

        record = SourceFile(
            source_id=source_id,
            case_id=case_id,
            original_name=display_name,
            stored_path=relative.as_posix(),
            media_type=media_type,
            kind=kind,
            role=role,
            sha256=digest,
            size_bytes=stat.st_size,
        )
        stored = store.add_source(record)
        if stored.source_id != record.source_id:
            destination.unlink(missing_ok=True)
        return stored

    def resolve_source(self, source: SourceFile) -> Path:
        case_dir = self.case_dir(source.case_id)
        candidate = (case_dir / source.stored_path).resolve()
        if case_dir not in candidate.parents:
            raise UnsupportedEvidence("Stored source path escapes its case.")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if _sha256(candidate) != source.sha256:
            raise UnsupportedEvidence(
                f"Immutable source hash mismatch for {source.source_id}."
            )
        return candidate

    def repair_declared_synthetic_pdf(
        self,
        source: SourceFile,
        content: bytes,
    ) -> SourceFile:
        """Repair a known synthetic PDF while preserving its evidence links."""

        if source.kind is not SourceKind.PDF or not source.original_name.endswith(
            "-synthetic.pdf"
        ):
            raise PermissionError(
                "Only declared synthetic PDF fixtures may be repaired."
            )
        identify_evidence(source.original_name, content[:64])
        if not _has_complete_pdf_structure(content):
            raise UnsupportedEvidence("Synthetic replacement is not a complete PDF.")

        case_dir = self.case_dir(source.case_id)
        destination = (case_dir / source.stored_path).resolve()
        if case_dir not in destination.parents or not destination.is_file():
            raise UnsupportedEvidence("Synthetic source path is not repairable.")
        new_digest = hashlib.sha256(content).hexdigest()
        if (
            new_digest == source.sha256
            and len(content) == source.size_bytes
            and _sha256(destination) == source.sha256
        ):
            return source

        previous = destination.read_bytes()
        _atomic_write_bytes(content, destination)
        try:
            return self.store(source.case_id).repair_synthetic_source_integrity(
                source.source_id,
                sha256=new_digest,
                size_bytes=len(content),
                old_sha256=source.sha256,
                old_size_bytes=source.size_bytes,
            )
        except Exception:
            _atomic_write_bytes(previous, destination)
            raise

    def replace_declared_synthetic_fixture(
        self,
        source: SourceFile,
        replacement_path: Path | str,
        *,
        original_name: str,
    ) -> SourceFile:
        """Upgrade only a declared synthetic media fixture without changing its ID."""

        allowed_legacy_pdf = source.original_name.endswith("-synthetic.pdf")
        allowed_legacy_avi = (
            source.role is SourceRole.DASHCAM_VIDEO
            and source.original_name.endswith("-synthetic.avi")
        )
        if not (allowed_legacy_pdf or allowed_legacy_avi) or source.role not in {
            SourceRole.SCENE_PHOTO,
            SourceRole.DASHCAM_VIDEO,
            SourceRole.ROAD_SIGNAL_EVIDENCE,
        }:
            raise PermissionError(
                "Only declared synthetic photo/video fixtures may be upgraded."
            )
        replacement = Path(replacement_path)
        if replacement.is_symlink() or not replacement.is_file():
            raise UnsupportedEvidence("Synthetic replacement must be a regular file.")
        kind, media_type = identify_evidence(
            original_name,
            _read_header(replacement),
        )
        expected_kind = (
            SourceKind.VIDEO
            if source.role is SourceRole.DASHCAM_VIDEO
            else SourceKind.IMAGE
        )
        if kind is not expected_kind:
            raise UnsupportedEvidence("Synthetic replacement media type is incorrect.")

        case_dir = self.case_dir(source.case_id)
        source_directory = (case_dir / source.stored_path).resolve().parent
        if case_dir not in source_directory.parents:
            raise UnsupportedEvidence("Synthetic source path is not repairable.")
        destination = source_directory / sanitize_filename(original_name)
        _atomic_copy(replacement, destination)
        digest = _sha256(destination)
        relative = destination.relative_to(case_dir).as_posix()
        return self.store(source.case_id).migrate_synthetic_source_media(
            source.source_id,
            original_name=original_name,
            stored_path=relative,
            media_type=media_type,
            kind=kind.value,
            sha256=digest,
            size_bytes=destination.stat().st_size,
        )


def sanitize_filename(name: str) -> str:
    basename = Path(name).name.replace("\x00", "")
    cleaned = SAFE_FILENAME_PATTERN.sub("_", basename).strip("._")
    if not cleaned:
        cleaned = "evidence"
    suffix = Path(basename).suffix.lower()
    if suffix and not cleaned.lower().endswith(suffix):
        cleaned = f"{cleaned}{suffix}"
    return cleaned[:160]


def identify_evidence(name: str, header: bytes) -> tuple[SourceKind, str]:
    suffix = Path(name).suffix.lower()
    guessed = mimetypes.guess_type(name)[0]

    if header.startswith(b"%PDF-"):
        if suffix and suffix != ".pdf":
            raise UnsupportedEvidence(
                "PDF signature does not match the file extension."
            )
        return SourceKind.PDF, "application/pdf"

    image_type = _image_signature(header)
    if image_type:
        if suffix and suffix not in IMAGE_SUFFIXES:
            raise UnsupportedEvidence(
                "Image signature does not match the file extension."
            )
        return SourceKind.IMAGE, image_type

    video_type = _video_signature(header)
    if video_type:
        if suffix and suffix not in VIDEO_SUFFIXES:
            raise UnsupportedEvidence(
                "Video signature does not match the file extension."
            )
        return SourceKind.VIDEO, video_type

    if suffix == ".pdf" or suffix in IMAGE_SUFFIXES or suffix in VIDEO_SUFFIXES:
        raise UnsupportedEvidence(
            f"File extension {suffix} is recognized but its signature is invalid."
        )
    raise UnsupportedEvidence(f"Unsupported evidence type: {guessed or 'unknown'}")


def _image_signature(header: bytes) -> str | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if header.startswith(b"BM"):
        return "image/bmp"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def _video_signature(header: bytes) -> str | None:
    if len(header) >= 12 and header[4:8] == b"ftyp":
        major_brand = header[8:12]
        if major_brand == b"qt  ":
            return "video/quicktime"
        return "video/mp4"
    if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
        return "video/x-msvideo"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/x-matroska"
    return None


def _read_header(path: Path, size: int = 64) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".intake-", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_bytes(content: bytes, destination: Path) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".repair-", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _has_complete_pdf_structure(content: bytes) -> bool:
    return (
        len(content) >= 512
        and content.startswith(b"%PDF-")
        and b"\nxref\n" in content
        and b"\ntrailer\n" in content
        and b"\nstartxref\n" in content
        and content.rstrip().endswith(b"%%EOF")
    )
