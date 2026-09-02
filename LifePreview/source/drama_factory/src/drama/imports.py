from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError
from shared_contracts import (
    FactoryDocument,
    FactoryDocumentSnapshot,
    FactoryProjectSnapshot,
    FieldLock,
    ImportAction,
    ImportPlan,
    KnowledgeMappingPolicy,
    KnowledgePack,
    canonical_json,
    stable_json_sha256,
)

from .runtime import (
    ProjectPathCodec,
    atomic_write_text,
    safe_project_root,
    validate_episode_id,
    validate_project_key,
)
from .image_validation import ImageValidationError, validate_image_bytes


FACTORY_SCHEMA_VERSION = "factory.project.v1"
FACTORY_CAPABILITIES = (
    "i2v",
    "knowledge-pack-import-v1",
    "run-from-import-v1",
)
SUPPORTED_COMPILER_VERSIONS = frozenset({"knowledge-pack-compiler-v1"})
_REVISION_NAMESPACE = UUID("f45c013f-6a53-4a79-9faa-0140c35efdb8")
_MAX_DOCUMENT_BYTES = 1_000_000
_MAX_SOURCE_ASSET_COUNT = 64
_MAX_SOURCE_ASSET_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_ASSET_TOTAL_BYTES = 64 * 1024 * 1024

_SOURCE_NAMES = {
    FactoryDocument.STORY_BIBLE: "story_bible.json",
    FactoryDocument.CHARACTER_BIBLE: "character_bible.json",
    FactoryDocument.SCENE_BIBLE: "scene_bible.json",
    FactoryDocument.SHOT_LIST: "shot_list.json",
    FactoryDocument.PROMPT_CONSTRAINTS: "prompt_constraints.json",
}
_PROJECT_PATHS = {
    FactoryDocument.STORY_BIBLE: Path("bible/story_bible.json"),
    FactoryDocument.CHARACTER_BIBLE: Path("bible/character_bible.json"),
    FactoryDocument.SCENE_BIBLE: Path("bible/scene_bible.json"),
    FactoryDocument.PROMPT_CONSTRAINTS: Path(
        "bible/prompt_constraints.json"
    ),
}
_DEFAULT_DOCUMENTS: dict[FactoryDocument, dict[str, Any]] = {
    FactoryDocument.STORY_BIBLE: {
        "novel_title": "",
        "genre": "",
        "visual_style": "",
        "episode_plan": [],
    },
    FactoryDocument.CHARACTER_BIBLE: {
        "novel_title": "",
        "characters": [],
    },
    FactoryDocument.SCENE_BIBLE: {
        "novel_title": "",
        "scenes": [],
    },
    FactoryDocument.SHOT_LIST: {"episodes": {}},
    FactoryDocument.PROMPT_CONSTRAINTS: {
        "visual": [],
        "video": [],
        "negative": [],
    },
}


class FactoryImportError(RuntimeError):
    """Base class for safe factory import failures."""


class FactoryImportConflict(FactoryImportError):
    """The confirmed plan no longer matches the factory target."""


class FactoryImportCorrupt(FactoryImportError):
    """An immutable import revision failed content verification."""


@dataclass(frozen=True, slots=True)
class FactoryImportRevision:
    project_key: str
    revision_id: UUID
    revision_sha256: str
    base_revision_id: UUID | None
    pack_id: UUID
    pack_sha256: str
    plan_id: UUID
    plan_sha256: str
    target_snapshot_sha256: str
    resulting_snapshot_sha256: str
    root: Path
    created: bool


def factory_snapshot_sha256(snapshot: FactoryProjectSnapshot) -> str:
    snapshot = FactoryProjectSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    return stable_json_sha256(
        {
            "schema_version": snapshot.schema_version,
            "capabilities": sorted(snapshot.capabilities),
            "documents": [
                item.model_dump(mode="json")
                for item in sorted(
                    snapshot.documents,
                    key=lambda item: item.document.value,
                )
            ],
            "locked_fields": [
                item.model_dump(mode="json")
                for item in sorted(
                    snapshot.locked_fields,
                    key=lambda item: (item.document.value, item.path),
                )
            ],
        }
    )


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    reparse = getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    )
    return path.is_symlink() or bool(reparse)


def _source_asset_filename(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise FactoryImportCorrupt("factory source asset filename is invalid")
    if value.endswith(".png"):
        digest = value[:-4]
        media_type = "image/png"
    elif value.endswith(".jpg"):
        digest = value[:-4]
        media_type = "image/jpeg"
    else:
        raise FactoryImportCorrupt("factory source asset filename is invalid")
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or value != f"{digest}{Path(value).suffix}"
    ):
        raise FactoryImportCorrupt("factory source asset filename is invalid")
    return digest, media_type


def _source_asset_magic(data: bytes, media_type: str) -> bool:
    try:
        detected_type, _extension, _width, _height = validate_image_bytes(data)
    except ImageValidationError:
        return False
    return detected_type == media_type


def _normalize_source_assets(
    source_assets: Mapping[str, bytes] | None,
) -> tuple[dict[str, bytes], list[dict[str, Any]] | None]:
    if source_assets is None:
        return {}, None
    if not isinstance(source_assets, Mapping):
        raise FactoryImportCorrupt("factory source asset mapping is invalid")
    if len(source_assets) > _MAX_SOURCE_ASSET_COUNT:
        raise FactoryImportCorrupt("factory source asset count limit exceeded")
    normalized: dict[str, bytes] = {}
    index: list[dict[str, Any]] = []
    total = 0
    for filename, content in source_assets.items():
        digest, media_type = _source_asset_filename(filename)
        if not isinstance(content, bytes):
            raise FactoryImportCorrupt("factory source asset value must be bytes")
        size = len(content)
        if size > _MAX_SOURCE_ASSET_BYTES:
            raise FactoryImportCorrupt("factory source asset size limit exceeded")
        total += size
        if total > _MAX_SOURCE_ASSET_TOTAL_BYTES:
            raise FactoryImportCorrupt(
                "factory source asset total size limit exceeded"
            )
        if hashlib.sha256(content).hexdigest() != digest:
            raise FactoryImportCorrupt("factory source asset digest does not match")
        if not _source_asset_magic(content, media_type):
            raise FactoryImportCorrupt("factory source asset image magic is invalid")
        normalized[filename] = content
        index.append(
            {
                "filename": filename,
                "media_type": media_type,
                "sha256": digest,
                "size": size,
            }
        )
    index.sort(key=lambda item: item["filename"])
    if not index:
        return {}, None
    return normalized, index


def _validate_revision_source_assets(
    identity: dict[str, Any],
    revision_root: Path,
) -> None:
    assets_root = revision_root / "source_assets"
    if "source_assets" not in identity:
        if assets_root.exists() or assets_root.is_symlink():
            raise FactoryImportCorrupt(
                "factory import contains an unindexed source asset directory"
            )
        return
    index = identity["source_assets"]
    if not isinstance(index, list) or len(index) > _MAX_SOURCE_ASSET_COUNT:
        raise FactoryImportCorrupt("factory import source asset index is invalid")
    expected: dict[str, dict[str, Any]] = {}
    total = 0
    for item in index:
        if (
            not isinstance(item, dict)
            or set(item) != {"filename", "media_type", "sha256", "size"}
        ):
            raise FactoryImportCorrupt(
                "factory import source asset index is invalid"
            )
        digest, media_type = _source_asset_filename(item.get("filename"))
        size = item.get("size")
        if (
            item.get("sha256") != digest
            or item.get("media_type") != media_type
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > _MAX_SOURCE_ASSET_BYTES
            or item["filename"] in expected
        ):
            raise FactoryImportCorrupt(
                "factory import source asset index is invalid"
            )
        total += size
        if total > _MAX_SOURCE_ASSET_TOTAL_BYTES:
            raise FactoryImportCorrupt(
                "factory import source asset index total size is invalid"
            )
        expected[item["filename"]] = item
    if not index:
        if not assets_root.exists() and not assets_root.is_symlink():
            return
    if (
        not assets_root.is_dir()
        or _is_link_or_reparse(assets_root)
    ):
        raise FactoryImportCorrupt(
            "factory import source asset directory is invalid"
        )
    try:
        actual = {path.name: path for path in assets_root.iterdir()}
    except OSError:
        raise FactoryImportCorrupt(
            "factory import source asset directory is invalid"
        ) from None
    if set(actual) != set(expected):
        raise FactoryImportCorrupt(
            "factory import source asset file set does not match"
        )
    for filename, item in expected.items():
        path = actual[filename]
        try:
            if _is_link_or_reparse(path):
                raise FactoryImportCorrupt(
                    "factory import source asset must not be linked"
                )
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size != item["size"]:
                raise FactoryImportCorrupt(
                    "factory import source asset size does not match"
                )
            content = path.read_bytes()
        except FactoryImportCorrupt:
            raise
        except OSError:
            raise FactoryImportCorrupt(
                "factory import source asset could not be read"
            ) from None
        if (
            hashlib.sha256(content).hexdigest() != item["sha256"]
            or not _source_asset_magic(content, item["media_type"])
        ):
            raise FactoryImportCorrupt(
                "factory import source asset hash or image magic does not match"
            )


def _read_json_object(path: Path) -> dict[str, Any]:
    if _is_link_or_reparse(path):
        raise FactoryImportCorrupt("factory document must not be a link")
    if path.stat().st_size > _MAX_DOCUMENT_BYTES:
        raise FactoryImportCorrupt("factory document exceeds the size limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FactoryImportCorrupt("factory document is invalid JSON") from None
    if not isinstance(value, dict):
        raise FactoryImportCorrupt("factory document must contain a JSON object")
    return value


def _load_shot_document(project_root: Path) -> dict[str, Any]:
    shots_root = project_root / "shots"
    if not shots_root.exists():
        return {"episodes": {}}
    if _is_link_or_reparse(shots_root):
        raise FactoryImportCorrupt("factory shots directory must not be a link")
    episodes: dict[str, Any] = {}
    for path in sorted(shots_root.glob("*_shot_list.json")):
        value = _read_json_object(path)
        episode_id = value.get("episode_id")
        try:
            safe_episode_id = validate_episode_id(episode_id)
        except ValueError:
            raise FactoryImportCorrupt(
                "factory shot list has an invalid episode identifier"
            ) from None
        if path.name != f"{safe_episode_id}_shot_list.json":
            raise FactoryImportCorrupt(
                "factory shot list filename does not match its episode identifier"
            )
        if safe_episode_id in episodes:
            raise FactoryImportCorrupt(
                "factory contains duplicate episode shot lists"
            )
        episodes[safe_episode_id] = value
    return {"episodes": episodes}


def _validate_snapshot_episode_ids(snapshot: FactoryProjectSnapshot) -> None:
    document = next(
        (
            item
            for item in snapshot.documents
            if item.document is FactoryDocument.SHOT_LIST
        ),
        None,
    )
    if document is None:
        raise FactoryImportCorrupt("factory snapshot has no shot list")
    try:
        value = json.loads(document.content_json)
    except (TypeError, json.JSONDecodeError):
        raise FactoryImportCorrupt("factory shot list is invalid") from None
    episodes = value.get("episodes") if isinstance(value, dict) else None
    if not isinstance(episodes, dict):
        raise FactoryImportCorrupt("factory shot list episodes are invalid")
    for episode_id, episode in episodes.items():
        try:
            safe_episode_id = validate_episode_id(episode_id)
        except ValueError:
            raise FactoryImportCorrupt(
                "factory shot list has an invalid episode identifier"
            ) from None
        if not isinstance(episode, dict) or episode.get("episode_id") != safe_episode_id:
            raise FactoryImportCorrupt(
                "factory shot list identity is invalid"
            )


def _load_locks(project_root: Path) -> tuple[FieldLock, ...]:
    path = project_root / "bible" / "import_locks.json"
    if not path.exists():
        return ()
    value = _read_json_object(path)
    rows = value.get("locks")
    if not isinstance(rows, list):
        raise FactoryImportCorrupt("factory import locks are invalid")
    try:
        locks = tuple(FieldLock.model_validate(item) for item in rows)
    except ValidationError:
        raise FactoryImportCorrupt("factory import locks are invalid") from None
    if len({(item.document, item.path) for item in locks}) != len(locks):
        raise FactoryImportCorrupt("factory import locks are duplicated")
    return tuple(
        sorted(locks, key=lambda item: (item.document.value, item.path))
    )


def _pointer_parts(path: str) -> tuple[str, ...]:
    return tuple(
        part.replace("~1", "/").replace("~0", "~")
        for part in path[1:].split("/")
    )


def _lookup_pointer(document: object, path: str) -> tuple[bool, object | None]:
    current = document
    for part in _pointer_parts(path):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
            continue
        return False, None
    return True, current


def _parent_exists(document: object, path: str) -> bool:
    parts = _pointer_parts(path)
    if len(parts) == 1:
        return isinstance(document, dict)
    current = document
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return False
            current = current[index]
        else:
            return False
    return isinstance(current, (dict, list))


def _set_pointer(document: object, path: str, value: object) -> None:
    parts = _pointer_parts(path)
    current = document
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            raise FactoryImportConflict(
                "import plan target path is unavailable"
            )
    final = parts[-1]
    if isinstance(current, dict):
        current[final] = value
        return
    if isinstance(current, list) and final.isdigit():
        index = int(final)
        if index == len(current):
            current.append(value)
        elif index < len(current):
            current[index] = value
        else:
            raise FactoryImportConflict(
                "import plan array target is unavailable"
            )
        return
    raise FactoryImportConflict("import plan target path is unavailable")


def _paths_overlap(first: str, second: str) -> bool:
    return (
        first == second
        or first.startswith(second + "/")
        or second.startswith(first + "/")
    )


def _field_is_locked(
    snapshot: FactoryProjectSnapshot,
    document: FactoryDocument,
    path: str,
) -> bool:
    return any(
        lock.document is document and _paths_overlap(lock.path, path)
        for lock in snapshot.locked_fields
    )


def _expected_action(
    *,
    mapping,
    snapshot: FactoryProjectSnapshot,
    document: object,
    exists: bool,
    current_json: str | None,
) -> tuple[ImportAction, str | None]:
    if not mapping.enabled:
        return ImportAction.DISABLED, current_json
    if set(mapping.required_capabilities) - set(snapshot.capabilities):
        return ImportAction.DISABLED, current_json
    if exists and current_json == mapping.incoming_json:
        return ImportAction.UNCHANGED, current_json
    if _field_is_locked(snapshot, mapping.document, mapping.path):
        return ImportAction.LOCKED, current_json
    if not _parent_exists(document, mapping.path):
        return ImportAction.CONFLICT, None
    if not exists:
        return ImportAction.ADD, mapping.incoming_json
    if mapping.policy is KnowledgeMappingPolicy.REPLACE:
        return ImportAction.REPLACE, mapping.incoming_json
    return ImportAction.CONFLICT, None


def _validate_confirmed_plan(
    pack: KnowledgePack,
    plan: ImportPlan,
    snapshot: FactoryProjectSnapshot,
) -> None:
    if plan.compiler_version not in SUPPORTED_COMPILER_VERSIONS:
        raise FactoryImportConflict("import plan compiler version is unsupported")
    if (
        plan.pack_id != pack.pack_id
        or plan.pack_sha256 != pack.pack_sha256
    ):
        raise FactoryImportConflict("import plan references a different pack")
    if not plan.compatible or not plan.ready_for_confirmation:
        raise FactoryImportConflict("import plan is not ready for confirmation")
    if (
        pack.target_schema_version != snapshot.schema_version
        or set(pack.required_capabilities) - set(snapshot.capabilities)
    ):
        raise FactoryImportConflict("factory capabilities changed after preview")
    if (
        plan.target_snapshot_sha256
        != factory_snapshot_sha256(snapshot)
    ):
        raise FactoryImportConflict(
            "factory snapshot changed after import preview"
        )
    mapping_by_id = {item.mapping_id: item for item in pack.mappings}
    operation_by_id = {item.mapping_id: item for item in plan.operations}
    if set(mapping_by_id) != set(operation_by_id):
        raise FactoryImportConflict(
            "import plan operations do not match the knowledge pack"
        )
    documents = {
        item.document: json.loads(item.content_json)
        for item in snapshot.documents
    }
    for mapping_id, mapping in mapping_by_id.items():
        operation = operation_by_id[mapping_id]
        if (
            operation.source_revision_id != mapping.source_revision_id
            or operation.document is not mapping.document
            or operation.path != mapping.path
            or operation.incoming_json != mapping.incoming_json
        ):
            raise FactoryImportConflict(
                "import operation does not match its knowledge mapping"
            )
        document = documents.get(mapping.document)
        if document is None:
            raise FactoryImportConflict(
                "import target document is unavailable"
            )
        exists, current = _lookup_pointer(document, mapping.path)
        current_json = canonical_json(current) if exists else None
        expected_action, expected_resolved = _expected_action(
            mapping=mapping,
            snapshot=snapshot,
            document=document,
            exists=exists,
            current_json=current_json,
        )
        if expected_action in {ImportAction.CONFLICT, ImportAction.LOCKED}:
            raise FactoryImportConflict(
                "import plan requires unresolved human confirmation"
            )
        if (
            operation.action is not expected_action
            or operation.current_exists != exists
            or operation.current_json != current_json
            or operation.resolved_json != expected_resolved
            or operation.requires_resolution
        ):
            raise FactoryImportConflict(
                "import operation no longer matches the target"
            )
    expected_locks = {
        (item.document, item.path): item for item in snapshot.locked_fields
    }
    for item in pack.forbidden_fields:
        expected_locks.setdefault((item.document, item.path), item)
    if set(plan.resulting_locks) != set(expected_locks.values()):
        raise FactoryImportConflict("import plan field locks are invalid")


def _apply_plan(
    snapshot: FactoryProjectSnapshot,
    plan: ImportPlan,
) -> FactoryProjectSnapshot:
    documents = {
        item.document: json.loads(item.content_json)
        for item in snapshot.documents
    }
    for operation in plan.operations:
        if operation.action not in {ImportAction.ADD, ImportAction.REPLACE}:
            continue
        if operation.resolved_json is None:
            raise FactoryImportConflict(
                "applicable import operation has no value"
            )
        _set_pointer(
            documents[operation.document],
            operation.path,
            json.loads(operation.resolved_json),
        )
    result = FactoryProjectSnapshot(
        schema_version=snapshot.schema_version,
        capabilities=snapshot.capabilities,
        documents=tuple(
            FactoryDocumentSnapshot(
                document=document,
                content_json=canonical_json(value),
            )
            for document, value in sorted(
                documents.items(),
                key=lambda item: item[0].value,
            )
        ),
        locked_fields=plan.resulting_locks,
    )
    _validate_snapshot_episode_ids(result)
    return result


def _revision_identity(
    *,
    project_key: str,
    base_revision_id: UUID | None,
    pack: KnowledgePack,
    plan: ImportPlan,
    resulting_snapshot: FactoryProjectSnapshot,
    document_hashes: list[dict[str, str]],
    source_asset_hashes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identity = {
        "contract": "factory-import-revision-v1",
        "project_key": project_key,
        "base_revision_id": (
            str(base_revision_id) if base_revision_id is not None else None
        ),
        "pack_id": str(pack.pack_id),
        "pack_sha256": pack.pack_sha256,
        "plan_id": str(plan.plan_id),
        "plan_sha256": plan.plan_sha256,
        "target_snapshot_sha256": plan.target_snapshot_sha256,
        "schema_version": resulting_snapshot.schema_version,
        "capabilities": list(resulting_snapshot.capabilities),
        "resulting_snapshot_sha256": factory_snapshot_sha256(
            resulting_snapshot
        ),
        "documents": document_hashes,
        "locks": [
            item.model_dump(mode="json")
            for item in resulting_snapshot.locked_fields
        ],
    }
    if source_asset_hashes is not None:
        identity["source_assets"] = source_asset_hashes
    return identity


def _manifest_revision(value: dict[str, Any], root: Path) -> FactoryImportRevision:
    try:
        identity = value["identity"]
        revision_id = UUID(value["revision_id"])
        revision_sha256 = value["revision_sha256"]
        if (
            not isinstance(identity, dict)
            or stable_json_sha256(identity) != revision_sha256
            or uuid5(_REVISION_NAMESPACE, revision_sha256) != revision_id
        ):
            raise ValueError
        return FactoryImportRevision(
            project_key=identity["project_key"],
            revision_id=revision_id,
            revision_sha256=revision_sha256,
            base_revision_id=(
                UUID(identity["base_revision_id"])
                if identity["base_revision_id"] is not None
                else None
            ),
            pack_id=UUID(identity["pack_id"]),
            pack_sha256=identity["pack_sha256"],
            plan_id=UUID(identity["plan_id"]),
            plan_sha256=identity["plan_sha256"],
            target_snapshot_sha256=identity["target_snapshot_sha256"],
            resulting_snapshot_sha256=identity[
                "resulting_snapshot_sha256"
            ],
            root=root,
            created=False,
        )
    except (KeyError, TypeError, ValueError):
        raise FactoryImportCorrupt(
            "factory import manifest identity is invalid"
        ) from None


def load_revision_root(root: str | Path) -> FactoryImportRevision:
    revision_root = Path(root)
    if (
        not revision_root.is_dir()
        or _is_link_or_reparse(revision_root)
    ):
        raise FactoryImportCorrupt("factory import revision is unavailable")
    ready_path = revision_root / "READY"
    manifest_path = revision_root / "import_manifest.json"
    if not ready_path.is_file() or not manifest_path.is_file():
        raise FactoryImportCorrupt("factory import revision is not ready")
    if _is_link_or_reparse(ready_path) or _is_link_or_reparse(manifest_path):
        raise FactoryImportCorrupt("factory import metadata must not be linked")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FactoryImportCorrupt(
            "factory import manifest is invalid"
        ) from None
    if not isinstance(value, dict):
        raise FactoryImportCorrupt("factory import manifest is invalid")
    revision = _manifest_revision(value, revision_root)
    if (
        ready_path.read_text(encoding="utf-8").strip()
        != revision.revision_sha256
    ):
        raise FactoryImportCorrupt("factory import ready marker is invalid")
    identity = value["identity"]
    documents = identity.get("documents")
    if not isinstance(documents, list):
        raise FactoryImportCorrupt("factory import document index is invalid")
    seen: set[str] = set()
    for item in documents:
        if (
            not isinstance(item, dict)
            or set(item) != {"document", "filename", "sha256"}
            or not isinstance(item["filename"], str)
            or Path(item["filename"]).name != item["filename"]
            or item["filename"] in seen
        ):
            raise FactoryImportCorrupt(
                "factory import document index is invalid"
            )
        seen.add(item["filename"])
        path = revision_root / "source" / item["filename"]
        if (
            not path.is_file()
            or _is_link_or_reparse(path)
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != item["sha256"]
        ):
            raise FactoryImportCorrupt(
                "factory import document hash does not match"
            )
    if seen != set(_SOURCE_NAMES.values()):
        raise FactoryImportCorrupt(
            "factory import document set is incomplete"
        )
    _validate_revision_source_assets(identity, revision_root)
    return revision


def load_revision_snapshot(
    root: str | Path,
) -> tuple[FactoryImportRevision, FactoryProjectSnapshot]:
    revision = load_revision_root(root)
    manifest = json.loads(
        (revision.root / "import_manifest.json").read_text(encoding="utf-8")
    )
    identity = manifest["identity"]
    documents = []
    try:
        for item in identity["documents"]:
            document = FactoryDocument(item["document"])
            content = (
                revision.root / "source" / item["filename"]
            ).read_text(encoding="utf-8").strip()
            documents.append(
                FactoryDocumentSnapshot(
                    document=document,
                    content_json=content,
                )
            )
        snapshot = FactoryProjectSnapshot(
            schema_version=identity["schema_version"],
            capabilities=tuple(identity["capabilities"]),
            documents=tuple(documents),
            locked_fields=tuple(
                FieldLock.model_validate(item)
                for item in identity["locks"]
            ),
        )
    except (KeyError, OSError, UnicodeError, ValidationError, ValueError):
        raise FactoryImportCorrupt(
            "factory import snapshot is invalid"
        ) from None
    if (
        factory_snapshot_sha256(snapshot)
        != revision.resulting_snapshot_sha256
    ):
        raise FactoryImportCorrupt(
            "factory import resulting snapshot hash does not match"
        )
    _validate_snapshot_episode_ids(snapshot)
    return revision, snapshot


class FactoryImportStore:
    def __init__(self, projects_root: str | Path) -> None:
        self.projects_root = Path(projects_root)

    def snapshot(
        self,
        project_key: str,
        base_revision_id: UUID | None = None,
    ) -> FactoryProjectSnapshot:
        validate_project_key(project_key)
        if base_revision_id is not None:
            _revision, snapshot = load_revision_snapshot(
                self.load_revision(project_key, base_revision_id).root
            )
            return snapshot
        project_root = safe_project_root(self.projects_root, project_key)
        codec = ProjectPathCodec(project_root)
        documents: dict[FactoryDocument, dict[str, Any]] = {
            key: json.loads(json.dumps(value))
            for key, value in _DEFAULT_DOCUMENTS.items()
        }
        if project_root.exists():
            for document, relative in _PROJECT_PATHS.items():
                path = codec.decode(relative)
                if path.exists():
                    documents[document] = _read_json_object(path)
            documents[FactoryDocument.SHOT_LIST] = _load_shot_document(
                project_root
            )
            locks = _load_locks(project_root)
        else:
            locks = ()
        return FactoryProjectSnapshot(
            schema_version=FACTORY_SCHEMA_VERSION,
            capabilities=FACTORY_CAPABILITIES,
            documents=tuple(
                FactoryDocumentSnapshot(
                    document=document,
                    content_json=canonical_json(value),
                )
                for document, value in sorted(
                    documents.items(),
                    key=lambda item: item[0].value,
                )
            ),
            locked_fields=locks,
        )

    def create_revision(
        self,
        project_key: str,
        pack: KnowledgePack,
        plan: ImportPlan,
        *,
        base_revision_id: UUID | None = None,
        source_assets: Mapping[str, bytes] | None = None,
    ) -> FactoryImportRevision:
        pack = KnowledgePack.model_validate(pack.model_dump(mode="json"))
        plan = ImportPlan.model_validate(plan.model_dump(mode="json"))
        normalized_assets, source_asset_hashes = _normalize_source_assets(
            source_assets
        )
        snapshot = self.snapshot(project_key, base_revision_id)
        _validate_confirmed_plan(pack, plan, snapshot)
        resulting = _apply_plan(snapshot, plan)
        document_hashes = []
        document_bytes: dict[str, bytes] = {}
        for item in resulting.documents:
            filename = _SOURCE_NAMES[item.document]
            content = (item.content_json + "\n").encode("utf-8")
            document_bytes[filename] = content
            document_hashes.append(
                {
                    "document": item.document.value,
                    "filename": filename,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        identity = _revision_identity(
            project_key=project_key,
            base_revision_id=base_revision_id,
            pack=pack,
            plan=plan,
            resulting_snapshot=resulting,
            document_hashes=document_hashes,
            source_asset_hashes=source_asset_hashes,
        )
        revision_sha256 = stable_json_sha256(identity)
        revision_id = uuid5(_REVISION_NAMESPACE, revision_sha256)
        project_root = safe_project_root(self.projects_root, project_key)
        project_root.mkdir(parents=True, exist_ok=True)
        revisions_root = ProjectPathCodec(project_root).decode("revisions")
        revisions_root.mkdir(parents=True, exist_ok=True)
        if _is_link_or_reparse(revisions_root):
            raise FactoryImportCorrupt(
                "factory revisions directory must not be linked"
            )
        target = revisions_root / str(revision_id)
        if target.exists() or target.is_symlink():
            existing = load_revision_root(target)
            if (
                existing.project_key != project_key
                or existing.base_revision_id != base_revision_id
                or existing.pack_id != pack.pack_id
                or existing.pack_sha256 != pack.pack_sha256
                or existing.plan_id != plan.plan_id
                or existing.plan_sha256 != plan.plan_sha256
                or existing.revision_sha256 != revision_sha256
            ):
                raise FactoryImportConflict(
                    "factory revision identity already exists"
                )
            return existing

        # Keep the staging component short enough for Windows paths once a
        # 64-character content-addressed asset filename is appended.
        staging = revisions_root / f".staging-{revision_id}-{uuid4().hex[:8]}"
        staging.mkdir()
        try:
            source_root = staging / "source"
            source_root.mkdir()
            for filename, content in document_bytes.items():
                atomic_write_text(
                    source_root / filename,
                    content.decode("utf-8"),
                )
            if normalized_assets:
                assets_root = staging / "source_assets"
                assets_root.mkdir()
                for filename, content in sorted(normalized_assets.items()):
                    with (assets_root / filename).open("xb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
            atomic_write_text(
                staging / "import_manifest.json",
                json.dumps(
                    {
                        "revision_id": str(revision_id),
                        "revision_sha256": revision_sha256,
                        "identity": identity,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            atomic_write_text(staging / "READY", revision_sha256 + "\n")
            self._publish_revision(staging, target)
        except BaseException:
            if staging.exists():
                resolved_staging = staging.resolve(strict=False)
                resolved_root = revisions_root.resolve(strict=True)
                if resolved_staging.parent == resolved_root:
                    shutil.rmtree(resolved_staging)
            raise
        loaded = load_revision_root(target)
        return FactoryImportRevision(
            project_key=loaded.project_key,
            revision_id=loaded.revision_id,
            revision_sha256=loaded.revision_sha256,
            base_revision_id=loaded.base_revision_id,
            pack_id=loaded.pack_id,
            pack_sha256=loaded.pack_sha256,
            plan_id=loaded.plan_id,
            plan_sha256=loaded.plan_sha256,
            target_snapshot_sha256=loaded.target_snapshot_sha256,
            resulting_snapshot_sha256=loaded.resulting_snapshot_sha256,
            root=loaded.root,
            created=True,
        )

    @staticmethod
    def _publish_revision(staging: Path, target: Path) -> None:
        os.rename(staging, target)

    def load_revision(
        self,
        project_key: str,
        revision_id: UUID,
    ) -> FactoryImportRevision:
        project_root = safe_project_root(self.projects_root, project_key)
        root = ProjectPathCodec(project_root).decode(
            Path("revisions") / str(revision_id)
        )
        revision = load_revision_root(root)
        if (
            revision.project_key != project_key
            or revision.revision_id != revision_id
        ):
            raise FactoryImportCorrupt(
                "factory import revision identity does not match its path"
            )
        return revision
