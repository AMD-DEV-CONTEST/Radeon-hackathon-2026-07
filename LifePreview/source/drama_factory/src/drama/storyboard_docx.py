"""Safe ingestion of the six-image storyboard DOCX hand-off format.

The module deliberately uses only the ZIP/XML standard library.  A DOCX is an
untrusted archive here: member paths and sizes are checked before any content
is read, relationships are resolved inside the package, and embedded images
are accepted by their bytes rather than their filename extensions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from types import MappingProxyType
from typing import Literal, Mapping
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from .image_validation import ImageValidationError, validate_image_bytes
from .runtime import atomic_write_json, validate_episode_id


EXPECTED_IMAGE_COUNT = 6
MAX_EMBEDDED_IMAGE_COUNT = 64
MAX_DOCX_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 256
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_MEDIA_BYTES = 16 * 1024 * 1024
MAX_TOTAL_MEDIA_BYTES = 48 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000
MAX_PARAGRAPH_COUNT = 512
MAX_PARAGRAPH_TEXT_CHARS = 8 * 1024 * 1024

_CONTENT_TYPES = "[Content_Types].xml"
_DOCUMENT = "word/document.xml"
_DOCUMENT_RELS = "word/_rels/document.xml.rels"
_DOCX_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPE_NS = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StoryboardDocxError(ValueError):
    """Raised when an untrusted storyboard package violates the contract."""


@dataclass(frozen=True, slots=True)
class EmbeddedStoryboardImage:
    index: int
    media_type: Literal["image/png", "image/jpeg"]
    sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class StoryboardDocxPackage:
    source_path: Path
    source_sha256: str
    paragraphs: tuple[str, ...]
    images: tuple[EmbeddedStoryboardImage, ...]


@dataclass(frozen=True, slots=True)
class StoryboardImageRole:
    """Explicitly maps a one-based DOCX image to a factory asset.

    Multiple images may map to the same character or scene. ``shot_numbers``
    is one-based within the three-segment split.  An empty tuple means the
    character/scene is available to all segments; callers should normally be
    more precise when more than one scene is present.
    """

    kind: Literal["character", "scene", "prop", "source_only"]
    asset_id: str = ""
    name: str = ""
    prompt_lock_en: str = ""
    shot_numbers: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class StoryboardShotPlan:
    """Caller-confirmed semantics for one five-second generation segment."""

    action: str
    visual_prompt_en: str
    video_prompt_en: str
    shot_type: str = "medium"
    camera_motion: str = "static"
    audio_notes: str = "No background music and no dialogue."
    continue_from_prev: bool = False


@dataclass(frozen=True, slots=True)
class StoryboardMaterialization:
    project_root: Path
    documents: Mapping[str, Path]
    manifest_path: Path
    asset_paths: tuple[Path, ...]


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    reparse = getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    )
    return path.is_symlink() or bool(reparse)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise StoryboardDocxError("unsafe archive path")
    if name.startswith("/") or "//" in name:
        raise StoryboardDocxError("unsafe archive path")
    raw_parts = name.rstrip("/").split("/")
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise StoryboardDocxError("unsafe archive path")
    if any(":" in part for part in raw_parts):
        raise StoryboardDocxError("unsafe archive path")
    normalized = PurePosixPath(*raw_parts).as_posix()
    if normalized != name.rstrip("/"):
        raise StoryboardDocxError("unsafe archive path")
    return normalized


def _validate_archive(archive: ZipFile) -> dict[str, object]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise StoryboardDocxError("DOCX archive entry count limit exceeded")
    entries: dict[str, object] = {}
    seen: set[str] = set()
    total = 0
    media_total = 0
    media_count = 0
    for info in infos:
        normalized = _safe_member_name(info.filename)
        folded = normalized.casefold()
        if folded in seen:
            raise StoryboardDocxError("DOCX archive contains duplicate paths")
        seen.add(folded)
        if info.flag_bits & 0x1:
            raise StoryboardDocxError("encrypted DOCX entries are not supported")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise StoryboardDocxError("DOCX archive links are not allowed")
        if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
            raise StoryboardDocxError("unsupported DOCX compression method")
        if info.file_size < 0 or info.compress_size < 0:
            raise StoryboardDocxError("invalid DOCX archive size")
        total += info.file_size
        if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise StoryboardDocxError("DOCX archive size limit exceeded")
        if info.file_size and (
            info.compress_size == 0
            or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise StoryboardDocxError("unsafe DOCX compression ratio")
        if not info.is_dir():
            entries[normalized] = info
        if normalized.startswith("word/media/") and not info.is_dir():
            media_count += 1
            media_total += info.file_size
            if info.file_size > MAX_MEDIA_BYTES:
                raise StoryboardDocxError("embedded media size limit exceeded")
            if media_total > MAX_TOTAL_MEDIA_BYTES:
                raise StoryboardDocxError("embedded media size limit exceeded")
    if media_count > MAX_EMBEDDED_IMAGE_COUNT:
        raise StoryboardDocxError("DOCX contains too many embedded media files")
    for required in (_CONTENT_TYPES, _DOCUMENT, _DOCUMENT_RELS):
        if required not in entries:
            raise StoryboardDocxError("file is not a valid DOCX document")
    return entries


def _read_member(
    archive: ZipFile,
    entries: Mapping[str, object],
    name: str,
    *,
    limit: int,
) -> bytes:
    info = entries.get(name)
    if info is None:
        raise StoryboardDocxError("DOCX relationship target is missing")
    if getattr(info, "file_size", limit + 1) > limit:
        raise StoryboardDocxError("DOCX member size limit exceeded")
    try:
        with archive.open(info) as handle:  # type: ignore[arg-type]
            data = handle.read(limit + 1)
    except (BadZipFile, OSError, RuntimeError):
        raise StoryboardDocxError("DOCX member could not be read") from None
    if len(data) > limit:
        raise StoryboardDocxError("DOCX member size limit exceeded")
    return data


def _parse_xml(data: bytes, label: str) -> ET.Element:
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise StoryboardDocxError(f"unsafe XML in DOCX {label}")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise StoryboardDocxError(f"invalid XML in DOCX {label}") from None


def _validate_content_types(root: ET.Element) -> None:
    expected_tag = f"{{{_CONTENT_TYPE_NS}}}Override"
    valid = any(
        node.tag == expected_tag
        and node.attrib.get("PartName") == "/word/document.xml"
        and node.attrib.get("ContentType") == _DOCX_MAIN_CONTENT_TYPE
        for node in root
    )
    if not valid:
        raise StoryboardDocxError("file is not a valid non-macro DOCX document")


def _relationship_targets(root: ET.Element) -> dict[str, str]:
    targets: dict[str, str] = {}
    relationship_tag = f"{{{_REL_NS}}}Relationship"
    for node in root:
        if node.tag != relationship_tag:
            continue
        relationship_id = node.attrib.get("Id", "")
        relationship_type = node.attrib.get("Type", "")
        if not relationship_id or not relationship_type.endswith("/image"):
            continue
        if node.attrib.get("TargetMode", "").casefold() == "external":
            targets[relationship_id] = ""
            continue
        raw_target = node.attrib.get("Target", "")
        if not raw_target or "\\" in raw_target or ":" in raw_target:
            raise StoryboardDocxError("unsafe image relationship target")
        base_parts = list(PurePosixPath(_DOCUMENT).parent.parts)
        for part in PurePosixPath(raw_target).parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if not base_parts:
                    raise StoryboardDocxError("unsafe image relationship target")
                base_parts.pop()
            else:
                base_parts.append(part)
        resolved = PurePosixPath(*base_parts).as_posix()
        if not resolved.startswith("word/media/"):
            raise StoryboardDocxError("unsafe image relationship target")
        targets[relationship_id] = resolved
    return targets


def _image_relationship_ids(document: ET.Element) -> list[str]:
    ids: list[str] = []
    for node in document.iter():
        if node.tag == f"{{{_A_NS}}}blip":
            relationship_id = node.attrib.get(f"{{{_R_NS}}}embed")
            if relationship_id:
                ids.append(relationship_id)
        elif node.tag.endswith("}imagedata"):
            relationship_id = node.attrib.get(f"{{{_R_NS}}}id")
            if relationship_id:
                ids.append(relationship_id)
    return ids


def _paragraphs(document: ET.Element) -> tuple[str, ...]:
    values: list[str] = []
    character_count = 0
    for paragraph in document.iter(f"{{{_W_NS}}}p"):
        raw = "".join(
            node.text or ""
            for node in paragraph.iter(f"{{{_W_NS}}}t")
        )
        normalized = " ".join(raw.split())
        if normalized:
            character_count += len(normalized)
            if len(values) >= MAX_PARAGRAPH_COUNT:
                raise StoryboardDocxError(
                    "DOCX contains more than 512 text segments"
                )
            if character_count > MAX_PARAGRAPH_TEXT_CHARS:
                raise StoryboardDocxError("DOCX text exceeds the safe limit")
            values.append(normalized)
    return tuple(values)


def _image_type(data: bytes) -> tuple[str, str]:
    try:
        media_type, extension, _width, _height = validate_image_bytes(data)
    except ImageValidationError as exc:
        if not (
            data.startswith(b"\x89PNG\r\n\x1a\n")
            or data.startswith(b"\xff\xd8")
        ):
            raise StoryboardDocxError(
                "embedded media is not a PNG or JPEG image"
            ) from None
        raise StoryboardDocxError(
            f"embedded PNG or JPEG image structure is invalid: {exc}"
        ) from None
    return media_type, extension


def parse_document_docx(source: str | Path) -> StoryboardDocxPackage:
    """Safely parse text and a dynamic number of embedded DOCX images."""

    path = Path(source)
    if path.suffix.casefold() != ".docx":
        raise StoryboardDocxError("storyboard source must be a DOCX file")
    if not path.exists() or not path.is_file() or _is_link_or_reparse(path):
        raise StoryboardDocxError("storyboard DOCX must be a regular readable file")
    try:
        size = path.stat().st_size
    except OSError:
        raise StoryboardDocxError("storyboard DOCX must be a regular readable file") from None
    if size <= 0 or size > MAX_DOCX_BYTES:
        raise StoryboardDocxError("storyboard DOCX size limit exceeded")
    source_sha256 = _sha256_file(path)
    try:
        with ZipFile(path) as archive:
            entries = _validate_archive(archive)
            content_types = _parse_xml(
                _read_member(
                    archive,
                    entries,
                    _CONTENT_TYPES,
                    limit=MAX_XML_BYTES,
                ),
                "content types",
            )
            _validate_content_types(content_types)
            document = _parse_xml(
                _read_member(
                    archive,
                    entries,
                    _DOCUMENT,
                    limit=MAX_XML_BYTES,
                ),
                "document",
            )
            relationships = _parse_xml(
                _read_member(
                    archive,
                    entries,
                    _DOCUMENT_RELS,
                    limit=MAX_XML_BYTES,
                ),
                "relationships",
            )
            targets = _relationship_targets(relationships)
            relationship_ids = _image_relationship_ids(document)
            target_names: list[str] = []
            for relationship_id in relationship_ids:
                target = targets.get(relationship_id)
                if not target:
                    raise StoryboardDocxError(
                        "embedded image relationship is missing or external"
                    )
                target_names.append(target)
            images: list[EmbeddedStoryboardImage] = []
            total_media = 0
            for index, target in enumerate(target_names, start=1):
                data = _read_member(
                    archive,
                    entries,
                    target,
                    limit=MAX_MEDIA_BYTES,
                )
                total_media += len(data)
                if total_media > MAX_TOTAL_MEDIA_BYTES:
                    raise StoryboardDocxError("embedded media size limit exceeded")
                media_type, _extension = _image_type(data)
                images.append(
                    EmbeddedStoryboardImage(
                        index=index,
                        media_type=media_type,  # type: ignore[arg-type]
                        sha256=hashlib.sha256(data).hexdigest(),
                        data=data,
                    )
                )
            paragraphs = _paragraphs(document)
            if not paragraphs and not images:
                raise StoryboardDocxError("DOCX contains no readable text or embedded image")
    except BadZipFile:
        raise StoryboardDocxError("file is not a valid DOCX document") from None
    except OSError:
        raise StoryboardDocxError("storyboard DOCX could not be read") from None
    return StoryboardDocxPackage(
        source_path=path.resolve(),
        source_sha256=source_sha256,
        paragraphs=paragraphs,
        images=tuple(images),
    )


def parse_storyboard_docx(source: str | Path) -> StoryboardDocxPackage:
    """Parse the legacy six-image storyboard profile.

    The exact-six constraint belongs only to this compatibility adapter.  New
    generic imports use :func:`parse_document_docx` and may contain zero to N
    images.
    """

    package = parse_document_docx(source)
    if len(package.images) != EXPECTED_IMAGE_COUNT:
        raise StoryboardDocxError(
            f"storyboard DOCX must contain exactly {EXPECTED_IMAGE_COUNT} embedded images"
        )
    if not package.paragraphs:
        raise StoryboardDocxError("storyboard DOCX contains no non-empty prompt")
    return package


def _validate_roles(
    image_roles: Mapping[int, StoryboardImageRole],
) -> dict[int, StoryboardImageRole]:
    expected = set(range(1, EXPECTED_IMAGE_COUNT + 1))
    if set(image_roles) != expected:
        raise StoryboardDocxError("image_roles must explicitly map images 1 through 6")
    roles: dict[int, StoryboardImageRole] = {}
    asset_kinds: dict[str, str] = {}
    asset_metadata: dict[tuple[str, str], tuple[str, str]] = {}
    for index in sorted(expected):
        role = image_roles[index]
        if not isinstance(role, StoryboardImageRole):
            raise StoryboardDocxError("image_roles values must be StoryboardImageRole objects")
        if role.kind not in {"character", "scene", "prop", "source_only"}:
            raise StoryboardDocxError("image_roles contains an unsupported role kind")
        if any(
            not isinstance(number, int) or isinstance(number, bool) or number not in {1, 2, 3}
            for number in role.shot_numbers
        ) or len(set(role.shot_numbers)) != len(role.shot_numbers):
            raise StoryboardDocxError("image_roles contains invalid shot_numbers")
        if role.kind == "source_only":
            if role.asset_id or role.prompt_lock_en or role.shot_numbers:
                raise StoryboardDocxError("source_only image_roles cannot identify a factory asset")
        else:
            if not _ASSET_ID.fullmatch(role.asset_id):
                raise StoryboardDocxError("image_roles contains an invalid asset_id")
            previous_kind = asset_kinds.setdefault(role.asset_id, role.kind)
            if previous_kind != role.kind:
                raise StoryboardDocxError("one asset_id cannot be both a character and a scene")
            key = (role.kind, role.asset_id)
            metadata = (role.name, role.prompt_lock_en)
            previous_metadata = asset_metadata.setdefault(key, metadata)
            if previous_metadata != metadata:
                raise StoryboardDocxError("repeated image_roles asset metadata does not match")
        roles[index] = role
    if roles[2].kind != "source_only" or any(
        role.kind == "source_only" for index, role in roles.items() if index != 2
    ):
        raise StoryboardDocxError("image 2 must be the sole source_only image role")
    return roles


def _prepare_project_root(project_root: str | Path) -> Path:
    root = Path(project_root)
    if (root.exists() or root.is_symlink()) and _is_link_or_reparse(root):
        raise StoryboardDocxError("project root must not be a link")
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve(strict=True)
    assets = resolved / "source_assets"
    if (assets.exists() or assets.is_symlink()) and _is_link_or_reparse(assets):
        raise StoryboardDocxError("source_assets must not be a link")
    assets.mkdir(parents=True, exist_ok=True)
    return resolved


def _prepare_child_directory(root: Path, name: str) -> Path:
    """Create one fixed child without following a pre-existing link/reparse point."""
    child = root / name
    if (child.exists() or child.is_symlink()) and _is_link_or_reparse(child):
        raise StoryboardDocxError(f"{name} must not be a link")
    child.mkdir(parents=False, exist_ok=True)
    resolved = child.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise StoryboardDocxError(f"{name} must remain inside the project root")
    return resolved


def _atomic_write_bytes(path: Path, data: bytes) -> Path:
    if path.exists() and path.is_file() and not _is_link_or_reparse(path):
        try:
            if path.read_bytes() == data:
                return path
        except OSError:
            pass
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return path
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _asset_rows(
    roles: Mapping[int, StoryboardImageRole],
    asset_references: tuple[str, ...],
    *,
    kind: Literal["character", "scene"],
) -> list[dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for index, role in roles.items():
        if role.kind != kind:
            continue
        row = rows.setdefault(
            role.asset_id,
            {
                ("char_id" if kind == "character" else "scene_id"): role.asset_id,
                "name": role.name or role.asset_id,
                "prompt_lock_en": role.prompt_lock_en,
                "ref_images": [],
            },
        )
        refs = row["ref_images"]
        assert isinstance(refs, list)
        reference = asset_references[index - 1]
        if reference not in refs:
            refs.append(reference)
    if kind == "character":
        for row in rows.values():
            row["model_version"] = "source-docx"
    else:
        scene_shots: dict[str, set[int]] = {}
        for role in roles.values():
            if role.kind == "scene":
                scene_shots.setdefault(role.asset_id, set()).update(
                    role.shot_numbers or (1, 2, 3)
                )
        props = [role for role in roles.values() if role.kind == "prop"]
        for asset_id, row in rows.items():
            used_in = scene_shots.get(asset_id, set())
            row["props"] = [
                (
                    f"{role.name}: {role.prompt_lock_en}"
                    if role.name and role.prompt_lock_en
                    else role.name or role.prompt_lock_en or role.asset_id
                )
                for role in props
                if used_in.intersection(role.shot_numbers or (1, 2, 3))
            ]
    return list(rows.values())


def _shot_assets(
    roles: Mapping[int, StoryboardImageRole],
    shot_number: int,
) -> tuple[list[str], str]:
    characters: list[str] = []
    scenes: list[str] = []
    for role in roles.values():
        if role.kind in {"source_only", "prop"}:
            continue
        if role.shot_numbers and shot_number not in role.shot_numbers:
            continue
        target = characters if role.kind == "character" else scenes
        if role.asset_id not in target:
            target.append(role.asset_id)
    if not scenes:
        raise StoryboardDocxError(
            f"image_roles do not map a scene to shot {shot_number}"
        )
    if len(scenes) != 1:
        raise StoryboardDocxError(
            f"image_roles map multiple scenes to shot {shot_number}"
        )
    return characters, scenes[0]


def materialize_storyboard_import(
    package: StoryboardDocxPackage,
    project_root: str | Path,
    *,
    image_roles: Mapping[int, StoryboardImageRole],
    shot_plans: Mapping[int, StoryboardShotPlan] | None = None,
    novel_title: str = "短剧片段",
    episode_id: str = "E001",
) -> StoryboardMaterialization:
    """Persist source images and atomically emit the five factory documents."""

    if not isinstance(package, StoryboardDocxPackage):
        raise TypeError("package must be a parsed StoryboardDocxPackage")
    if (
        len(package.images) != EXPECTED_IMAGE_COUNT
        or [image.index for image in package.images]
        != list(range(1, EXPECTED_IMAGE_COUNT + 1))
        or len(package.paragraphs) != 3
    ):
        raise StoryboardDocxError(
            "storyboard package must contain exactly three prompt paragraphs"
        )
    roles = _validate_roles(image_roles)
    if not novel_title.strip() or not episode_id.strip():
        raise StoryboardDocxError("novel_title and episode_id must be non-empty")
    try:
        validate_episode_id(episode_id.strip())
    except ValueError:
        raise StoryboardDocxError("episode_id contains unsafe characters")
    root = _prepare_project_root(project_root)
    assets_root = root / "source_assets"
    asset_paths: list[Path] = []
    for image in package.images:
        _media_type, extension = _image_type(image.data)
        if _media_type != image.media_type:
            raise StoryboardDocxError("parsed storyboard image media type does not match")
        if hashlib.sha256(image.data).hexdigest() != image.sha256:
            raise StoryboardDocxError("parsed storyboard image hash does not match")
        destination = assets_root / f"{image.sha256}{extension}"
        _atomic_write_bytes(destination, image.data)
        asset_paths.append(destination)
    persisted = tuple(asset_paths)
    asset_references = tuple(
        path.relative_to(root).as_posix() for path in persisted
    )

    title = novel_title.strip()
    eid = episode_id.strip()
    visual_constraint, narrative_prompt, negative_constraint = package.paragraphs
    characters = _asset_rows(roles, asset_references, kind="character")
    scenes = _asset_rows(roles, asset_references, kind="scene")
    shots: list[dict[str, object]] = []
    shot_types = ("medium", "wide", "over-the-shoulder")
    motions = ("slow push in", "smooth pull back", "smooth pull back and settle")
    if shot_plans is not None:
        if set(shot_plans) != {1, 2, 3} or any(
            not isinstance(plan, StoryboardShotPlan)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in (
                    plan.action,
                    plan.visual_prompt_en,
                    plan.video_prompt_en,
                    plan.shot_type,
                    plan.camera_motion,
                    plan.audio_notes,
                )
            )
            or not isinstance(plan.continue_from_prev, bool)
            for plan in shot_plans.values()
        ):
            raise StoryboardDocxError(
                "shot_plans must explicitly define three non-empty segments"
            )
    for number in range(1, 4):
        shot_characters, scene_id = _shot_assets(roles, number)
        start = (number - 1) * 5
        end = number * 5
        plan = (
            shot_plans[number]
            if shot_plans is not None
            else StoryboardShotPlan(
                action=f"原15秒连续镜头的第{start}-{end}秒",
                visual_prompt_en=(
                    f"{narrative_prompt} Segment {number} of 3, "
                    f"source seconds {start}-{end}."
                ),
                video_prompt_en=(
                    "Preserve the source continuous-shot motion for seconds "
                    f"{start}-{end}; maintain temporal and identity continuity "
                    "with adjacent segments."
                ),
                shot_type=shot_types[number - 1],
                camera_motion=motions[number - 1],
                continue_from_prev=number > 1,
            )
        )
        shots.append(
            {
                "shot_id": f"{eid}_S{number:03d}",
                "episode_id": eid,
                "chapter_id": "",
                "scene_id": scene_id,
                "duration_sec": 5.0,
                "shot_type": plan.shot_type.strip(),
                "camera_motion": plan.camera_motion.strip(),
                "characters": shot_characters,
                "action": plan.action.strip(),
                "dialogue": "",
                "speaker": "",
                "visual_prompt_en": plan.visual_prompt_en.strip(),
                "video_prompt_en": plan.video_prompt_en.strip(),
                "negative_prompt": "",
                "audio_notes": plan.audio_notes.strip(),
                "needs_lipsync": False,
                "continue_from_prev": plan.continue_from_prev,
                "anchor_mode": "dual" if shot_characters else "scene",
            }
        )

    factory_documents: dict[str, object] = {
        "story_bible": {
            "novel_title": title,
            "genre": "short_drama",
            "tone": "mysterious, quiet, dangerous",
            "visual_style": visual_constraint,
            "aspect_ratio": "9:16",
            "episode_plan": [{"episode_id": eid, "chapters": []}],
        },
        "character_bible": {
            "novel_title": title,
            "characters": characters,
        },
        "scene_bible": {
            "novel_title": title,
            "scenes": scenes,
        },
        "shot_list": {
            "episodes": {
                eid: {
                    "episode_id": eid,
                    "novel_title": title,
                    "shots": shots,
                }
            }
        },
        "prompt_constraints": {
            "visual": [visual_constraint],
            "video": ["continuous camera motion, coherent temporal continuity"],
            "negative": [negative_constraint] if negative_constraint else [],
        },
    }
    document_root = _prepare_child_directory(root, "factory_import")
    document_paths: dict[str, Path] = {}
    for name, value in factory_documents.items():
        path = document_root / f"{name}.json"
        atomic_write_json(path, value)
        document_paths[name] = path

    images_manifest = []
    for image, asset_reference in zip(package.images, asset_references):
        role = roles[image.index]
        images_manifest.append(
            {
                "index": image.index,
                "sha256": image.sha256,
                "media_type": image.media_type,
                "asset_path": asset_reference,
                "role": asdict(role),
                "included_in_ref_images": role.kind in {"character", "scene"},
            }
        )
    manifest_path = root / "source_manifest.json"
    atomic_write_json(
        manifest_path,
        {
            "schema_version": "storyboard-docx-source.v1",
            "source_name": package.source_path.name,
            "source_sha256": package.source_sha256,
            "original_prompts": list(package.paragraphs),
            "images": images_manifest,
            "split_strategy": {
                "source_duration_sec": 15.0,
                "segments": 3,
                "segment_duration_sec": 5.0,
                "preserve_continuity": all(
                    bool(shot["continue_from_prev"])
                    for shot in shots[1:]
                ),
            },
        },
    )
    return StoryboardMaterialization(
        project_root=root,
        documents=MappingProxyType(document_paths),
        manifest_path=manifest_path,
        asset_paths=persisted,
    )
