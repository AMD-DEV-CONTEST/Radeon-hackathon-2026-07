"""Append-only prepared-reference authority for the competition single view.

The store is deliberately filesystem-only.  It accepts one exact standard-JSON
manifest, keys it by the frozen prompt authority SHA-256, and creates a second
append-only request index for constant-time API lookup.  Every read revalidates
the manifest and the bytes of both referenced files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid4


_SCHEMA_VERSION = "amd.competition-prepared-reference.v1"
_INDEX_SCHEMA_VERSION = "amd.competition-prepared-reference-request-index.v1"
_REFERENCE_PROFILE = "competition-prompt-single-view-v1"
_SOURCE_MODE = "prompt_synthesized"
_VIEW_NAME = "front_three_quarter"
_TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "status",
    "requestId",
    "projectId",
    "bookId",
    "directionRevisionId",
    "trialScriptRevisionId",
    "characterName",
    "referenceProfile",
    "sourceMode",
    "requiredImages",
    "promptAuthority",
    "reference",
    "runner",
}
_PROMPT_AUTHORITY_FIELDS = {
    "schemaVersion",
    "referenceProfile",
    "sourceMode",
    "requiredImages",
    "view",
    "characterName",
    "ageStage",
    "historicalContext",
    "bookIdentitySha256",
    "directionSha256",
    "trialScriptSha256",
    "researchSha256",
    "evidencePackSha256",
    "safetyReleaseDecisionSha256",
    "authoritySha256",
    "visualPrompt",
    "promptSha256",
    "h3Prompt",
    "h3PromptSha256",
    "seed",
    "workflowSha256",
    "generationInvocationCount",
    "technicalRetryLimit",
}
_REFERENCE_FIELDS = {
    "viewName",
    "path",
    "sha256",
    "mimeType",
    "width",
    "height",
    "byteSize",
    "promptId",
    "compiledWorkflowSha256",
    "generationAttemptOrdinal",
    "technicalFailureReceiptSha256",
}
_RUNNER_FIELDS = {"checkpointPath", "checkpointSha256", "cutoverComplete"}
_INDEX_FIELDS = {
    "schemaVersion",
    "requestId",
    "authoritySha256",
    "indexSha256",
}
_SHA256_CHARS = frozenset("0123456789abcdef")
_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 16 * 1024
_MAX_REFERENCED_FILE_BYTES = 25 * 1024 * 1024


class CompetitionPreparedReferenceError(ValueError):
    """A prepared-reference manifest or its persistent cache is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CompetitionPreparedReferenceError(
            "prepared reference must contain standard JSON values"
        ) from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _SHA256_CHARS for character in value)
    ):
        raise CompetitionPreparedReferenceError(f"{label} is not a SHA-256 digest")
    return value


def _require_text(value: object, label: str, *, limit: int = 4096) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise CompetitionPreparedReferenceError(f"{label} is invalid")
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise CompetitionPreparedReferenceError(f"{label} is invalid")
    return value


def _require_uuid_text(value: object, label: str) -> str:
    text = _require_text(value, label, limit=36)
    try:
        parsed = UUID(text)
    except (ValueError, AttributeError) as exc:
        raise CompetitionPreparedReferenceError(f"{label} is not a UUID") from exc
    if str(parsed) != text:
        raise CompetitionPreparedReferenceError(f"{label} is not a canonical UUID")
    return text


def _require_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise CompetitionPreparedReferenceError(f"{label} fields are not exact")
    return value


def _lexical_descendant(path: Path, anchor: Path, label: str) -> tuple[Path, Path]:
    if not path.is_absolute() or ".." in path.parts:
        raise CompetitionPreparedReferenceError(
            f"{label} must stay inside persistent storage"
        )
    lexical_anchor = anchor.absolute()
    lexical_path = path.absolute()
    try:
        relative = lexical_path.relative_to(lexical_anchor)
    except ValueError as exc:
        raise CompetitionPreparedReferenceError(
            f"{label} must stay inside persistent storage"
        ) from exc
    current = lexical_anchor
    if current.is_symlink():
        raise CompetitionPreparedReferenceError(
            f"{label} persistent storage symlink is forbidden"
        )
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise CompetitionPreparedReferenceError(f"{label} symlink is forbidden")
    return lexical_path, relative


def _strict_persistent_file(value: object, anchor: Path, label: str) -> Path:
    if type(value) is not str:
        raise CompetitionPreparedReferenceError(f"{label} path is invalid")
    candidate, _ = _lexical_descendant(Path(value), anchor, label)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(anchor.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise CompetitionPreparedReferenceError(f"{label} path is unavailable") from exc
    if candidate.is_symlink() or resolved.is_symlink():
        raise CompetitionPreparedReferenceError(f"{label} symlink is forbidden")
    if not resolved.is_file():
        raise CompetitionPreparedReferenceError(f"{label} path is not a file")
    return resolved


def _validate_file_authority(
    *,
    path_value: object,
    sha_value: object,
    anchor: Path,
    label: str,
    expected_byte_size: object | None = None,
) -> Path:
    path = _strict_persistent_file(path_value, anchor, label)
    expected_sha = _require_sha256(sha_value, f"{label} SHA-256")
    try:
        byte_size = path.stat().st_size
    except OSError as exc:
        raise CompetitionPreparedReferenceError(f"{label} path is unavailable") from exc
    if not 1 <= byte_size <= _MAX_REFERENCED_FILE_BYTES:
        raise CompetitionPreparedReferenceError(f"{label} byte size is invalid")
    if expected_byte_size is not None and (
        type(expected_byte_size) is not int or expected_byte_size != byte_size
    ):
        raise CompetitionPreparedReferenceError(f"{label} byte size changed")
    try:
        actual_sha = _sha256_file(path)
    except OSError as exc:
        raise CompetitionPreparedReferenceError(f"{label} path is unavailable") from exc
    if actual_sha != expected_sha:
        raise CompetitionPreparedReferenceError(f"{label} SHA-256 changed")
    return path


def validate_competition_prepared_reference(
    manifest: dict[str, Any],
    *,
    persistent_root: Path,
) -> dict[str, Any]:
    """Strictly validate and return the supplied full manifest unchanged."""

    anchor = Path(persistent_root)
    if not anchor.is_absolute() or not anchor.exists() or anchor.is_symlink():
        raise CompetitionPreparedReferenceError("persistent storage root is invalid")
    try:
        anchor = anchor.resolve(strict=True)
    except OSError as exc:
        raise CompetitionPreparedReferenceError(
            "persistent storage root is invalid"
        ) from exc
    if not anchor.is_dir():
        raise CompetitionPreparedReferenceError("persistent storage root is invalid")
    full_fields = _TOP_LEVEL_FIELDS | {"manifestSha256"}
    _require_object(manifest, full_fields, "prepared reference manifest")
    if manifest["schemaVersion"] != _SCHEMA_VERSION:
        raise CompetitionPreparedReferenceError("prepared reference schema is invalid")
    if manifest["status"] != "prepared":
        raise CompetitionPreparedReferenceError("prepared reference status is invalid")
    for name in (
        "requestId",
        "projectId",
        "bookId",
        "directionRevisionId",
        "trialScriptRevisionId",
    ):
        _require_uuid_text(manifest[name], name)
    _require_text(manifest["characterName"], "characterName", limit=120)
    if (
        manifest["referenceProfile"] != _REFERENCE_PROFILE
        or manifest["sourceMode"] != _SOURCE_MODE
        or manifest["requiredImages"] != 1
        or type(manifest["requiredImages"]) is not int
    ):
        raise CompetitionPreparedReferenceError(
            "prepared reference single-view contract is invalid"
        )

    prompt = _require_object(
        manifest["promptAuthority"],
        _PROMPT_AUTHORITY_FIELDS,
        "promptAuthority",
    )
    authority_sha = _require_sha256(
        prompt["authoritySha256"], "prompt authority SHA-256"
    )
    if (
        prompt["schemaVersion"]
        != "amd.competition-prompt-reference-authority.v1"
        or prompt["referenceProfile"] != manifest["referenceProfile"]
        or prompt["sourceMode"] != manifest["sourceMode"]
        or prompt["requiredImages"] != manifest["requiredImages"]
        or prompt["view"] != _VIEW_NAME
        or prompt["characterName"] != manifest["characterName"]
        or prompt["generationInvocationCount"] != 1
        or type(prompt["generationInvocationCount"]) is not int
        or prompt["technicalRetryLimit"] != 1
        or type(prompt["technicalRetryLimit"]) is not int
    ):
        raise CompetitionPreparedReferenceError("prompt authority contract is invalid")
    _require_text(prompt["ageStage"], "prompt ageStage", limit=80)
    _require_text(
        prompt["historicalContext"], "prompt historicalContext", limit=1200
    )
    for name in (
        "bookIdentitySha256",
        "directionSha256",
        "trialScriptSha256",
        "researchSha256",
        "evidencePackSha256",
        "safetyReleaseDecisionSha256",
    ):
        _require_sha256(prompt[name], f"prompt {name}")
    visual_prompt = _require_text(prompt["visualPrompt"], "visualPrompt", limit=16_000)
    prompt_sha = _require_sha256(prompt["promptSha256"], "prompt SHA-256")
    if hashlib.sha256(visual_prompt.encode("utf-8")).hexdigest() != prompt_sha:
        raise CompetitionPreparedReferenceError("prompt SHA-256 changed")
    h3_prompt = _require_text(prompt["h3Prompt"], "h3Prompt", limit=16_000)
    h3_prompt_sha = _require_sha256(prompt["h3PromptSha256"], "H3 prompt SHA-256")
    if hashlib.sha256(h3_prompt.encode("utf-8")).hexdigest() != h3_prompt_sha:
        raise CompetitionPreparedReferenceError("H3 prompt SHA-256 changed")
    if type(prompt["seed"]) is not int or not 0 <= prompt["seed"] < 2**63:
        raise CompetitionPreparedReferenceError("prompt seed is invalid")
    _require_sha256(prompt["workflowSha256"], "template workflow SHA-256")
    prompt_identity = dict(prompt)
    prompt_identity.pop("authoritySha256")
    if _canonical_sha256(prompt_identity) != authority_sha:
        raise CompetitionPreparedReferenceError("prompt authority SHA-256 changed")

    reference = _require_object(
        manifest["reference"], _REFERENCE_FIELDS, "reference"
    )
    if reference["viewName"] != _VIEW_NAME:
        raise CompetitionPreparedReferenceError("reference view is invalid")
    if reference["mimeType"] not in _IMAGE_MIME_TYPES:
        raise CompetitionPreparedReferenceError("reference MIME type is invalid")
    if (
        type(reference["width"]) is not int
        or type(reference["height"]) is not int
        or (reference["width"], reference["height"]) != (512, 768)
    ):
        raise CompetitionPreparedReferenceError("reference dimensions are invalid")
    _require_text(reference["promptId"], "Comfy promptId", limit=512)
    _require_sha256(
        reference["compiledWorkflowSha256"], "compiled workflow SHA-256"
    )
    attempt = reference["generationAttemptOrdinal"]
    failure_receipt = reference["technicalFailureReceiptSha256"]
    if type(attempt) is not int or attempt not in {0, 1}:
        raise CompetitionPreparedReferenceError("generation attempt is invalid")
    if attempt == 0 and failure_receipt is not None:
        raise CompetitionPreparedReferenceError("failure receipt is invalid")
    if attempt == 1:
        _require_sha256(failure_receipt, "technical failure receipt SHA-256")
    _validate_file_authority(
        path_value=reference["path"],
        sha_value=reference["sha256"],
        expected_byte_size=reference["byteSize"],
        anchor=anchor,
        label="reference image",
    )

    runner = _require_object(manifest["runner"], _RUNNER_FIELDS, "runner")
    if runner["cutoverComplete"] is not True:
        raise CompetitionPreparedReferenceError("runner cutover is incomplete")
    _validate_file_authority(
        path_value=runner["checkpointPath"],
        sha_value=runner["checkpointSha256"],
        anchor=anchor,
        label="runner checkpoint",
    )

    claimed_manifest_sha = _require_sha256(
        manifest["manifestSha256"], "manifest SHA-256"
    )
    identity = dict(manifest)
    identity.pop("manifestSha256")
    if _canonical_sha256(identity) != claimed_manifest_sha:
        raise CompetitionPreparedReferenceError("manifest SHA-256 changed")
    # Force a final traversal through the complete value so non-finite floats,
    # non-string keys, and other non-standard JSON values cannot hide inside it.
    _canonical_bytes(manifest)
    return manifest


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class CompetitionPreparedReferenceStore:
    """Atomic append-only JSON store keyed by prompt authority SHA-256."""

    def __init__(
        self,
        root: Path,
        *,
        persistent_root: Path = Path("/persistent"),
    ) -> None:
        anchor = Path(persistent_root)
        location = Path(root)
        if not anchor.is_absolute() or not location.is_absolute():
            raise ValueError("prepared-reference root must be absolute persistent storage")
        if ".." in anchor.parts or ".." in location.parts:
            raise ValueError("prepared-reference root traversal is forbidden")
        try:
            anchor.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError("persistent storage root is unavailable") from exc
        if anchor.is_symlink() or not anchor.is_dir():
            raise ValueError("persistent storage root symlinks are forbidden")
        resolved_anchor = anchor.resolve(strict=True)
        try:
            _, relative = _lexical_descendant(location, anchor, "prepared-reference root")
            resolved_location = location.resolve(strict=False)
            resolved_location.relative_to(resolved_anchor)
        except CompetitionPreparedReferenceError as exc:
            raise ValueError("prepared-reference root must stay inside persistent storage") from exc
        except ValueError as exc:
            raise ValueError("prepared-reference root must stay inside persistent storage") from exc
        self._anchor = resolved_anchor
        self._root = resolved_anchor / relative
        self._mkdir_safe(self._root)

    def _mkdir_safe(self, location: Path) -> None:
        try:
            relative = location.relative_to(self._anchor)
        except ValueError as exc:
            raise CompetitionPreparedReferenceError(
                "cache directory must stay inside persistent storage"
            ) from exc
        current = self._anchor
        for part in relative.parts:
            current = current / part
            if current.exists():
                if current.is_symlink() or not current.is_dir():
                    raise CompetitionPreparedReferenceError("cache directory is unsafe")
            else:
                try:
                    current.mkdir(mode=0o700)
                except OSError as exc:
                    raise CompetitionPreparedReferenceError(
                        "cache directory is unavailable"
                    ) from exc

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, authority_sha256: str) -> Path:
        digest = _require_sha256(authority_sha256, "prompt authority SHA-256")
        self._mkdir_safe(self._root)
        target = self._root / f"{digest}.json"
        if target.is_symlink():
            raise CompetitionPreparedReferenceError("manifest symlink is forbidden")
        return target

    def request_index_path_for(self, request_id: UUID) -> Path:
        if not isinstance(request_id, UUID):
            raise CompetitionPreparedReferenceError("request_id must be a UUID")
        directory = self._root / "request-index"
        self._mkdir_safe(directory)
        target = directory / f"{request_id}.json"
        if target.is_symlink():
            raise CompetitionPreparedReferenceError("request index symlink is forbidden")
        return target

    @staticmethod
    def _read_json(path: Path, *, limit: int, label: str) -> dict[str, Any] | None:
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise CompetitionPreparedReferenceError(f"{label} path is unsafe")
        try:
            size = path.stat().st_size
            if not 1 <= size <= limit:
                raise OSError
            value = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise CompetitionPreparedReferenceError(
                f"{label} standard JSON is unavailable"
            ) from exc
        if type(value) is not dict:
            raise CompetitionPreparedReferenceError(f"{label} must be a JSON object")
        return value

    def load(self, authority_sha256: str) -> dict[str, Any] | None:
        digest = _require_sha256(authority_sha256, "prompt authority SHA-256")
        value = self._read_json(
            self.path_for(digest),
            limit=_MAX_MANIFEST_BYTES,
            label="prepared reference manifest",
        )
        if value is None:
            return None
        validate_competition_prepared_reference(value, persistent_root=self._anchor)
        if value["promptAuthority"]["authoritySha256"] != digest:
            raise CompetitionPreparedReferenceError(
                "manifest belongs to another prompt authority"
            )
        return value

    def _validate_index(
        self,
        value: dict[str, Any],
        *,
        request_id: UUID,
    ) -> str:
        _require_object(value, _INDEX_FIELDS, "request index")
        if (
            value["schemaVersion"] != _INDEX_SCHEMA_VERSION
            or value["requestId"] != str(request_id)
        ):
            raise CompetitionPreparedReferenceError("request index identity is invalid")
        authority_sha = _require_sha256(
            value["authoritySha256"], "request index authority SHA-256"
        )
        claimed = _require_sha256(value["indexSha256"], "request index SHA-256")
        identity = dict(value)
        identity.pop("indexSha256")
        if claimed != _canonical_sha256(identity):
            raise CompetitionPreparedReferenceError("request index SHA-256 changed")
        return authority_sha

    def load_by_request_id(
        self,
        request_id: UUID,
        expected_project_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        """Load through the append-only request index without scanning manifests."""

        if not isinstance(request_id, UUID):
            raise CompetitionPreparedReferenceError("request_id must be a UUID")
        if expected_project_id is not None and not isinstance(expected_project_id, UUID):
            raise CompetitionPreparedReferenceError(
                "expected_project_id must be a UUID"
            )
        value = self._read_json(
            self.request_index_path_for(request_id),
            limit=_MAX_INDEX_BYTES,
            label="request index",
        )
        if value is None:
            return None
        authority_sha = self._validate_index(value, request_id=request_id)
        manifest = self.load(authority_sha)
        if manifest is None:
            raise CompetitionPreparedReferenceError(
                "request index target manifest is unavailable"
            )
        if manifest["requestId"] != str(request_id):
            raise CompetitionPreparedReferenceError("request index targets another request")
        if (
            expected_project_id is not None
            and manifest["projectId"] != str(expected_project_id)
        ):
            raise CompetitionPreparedReferenceError(
                "prepared reference belongs to another project"
            )
        return manifest

    @staticmethod
    def _atomic_create(path: Path, body: bytes, *, label: str) -> None:
        if path.is_symlink():
            raise CompetitionPreparedReferenceError(f"{label} symlink is forbidden")
        if path.exists():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise CompetitionPreparedReferenceError(f"{label} is unavailable") from exc
            if existing != body:
                raise CompetitionPreparedReferenceError(f"{label} conflicts")
            return
        temporary = path.with_name(f".pr-{uuid4().hex}.partial")
        try:
            with temporary.open("xb") as handle:
                try:
                    os.chmod(temporary, 0o600)
                except OSError:
                    pass
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                try:
                    existing = path.read_bytes()
                except OSError as exc:
                    raise CompetitionPreparedReferenceError(
                        f"{label} is unavailable"
                    ) from exc
                if existing != body:
                    raise CompetitionPreparedReferenceError(f"{label} conflicts")
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def publish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and atomically create one immutable manifest and request index."""

        if type(payload) is not dict:
            raise CompetitionPreparedReferenceError(
                "prepared reference payload must be a JSON object"
            )
        fields = set(payload)
        if fields == _TOP_LEVEL_FIELDS:
            identity = dict(payload)
            manifest = {
                **identity,
                "manifestSha256": _canonical_sha256(identity),
            }
        elif fields == _TOP_LEVEL_FIELDS | {"manifestSha256"}:
            manifest = dict(payload)
        else:
            raise CompetitionPreparedReferenceError(
                "prepared reference manifest fields are not exact"
            )
        validate_competition_prepared_reference(
            manifest,
            persistent_root=self._anchor,
        )
        authority_sha = manifest["promptAuthority"]["authoritySha256"]
        manifest_path = self.path_for(authority_sha)
        self._atomic_create(
            manifest_path,
            _canonical_bytes(manifest),
            label="prepared reference manifest",
        )

        request_id = UUID(manifest["requestId"])
        index_identity = {
            "schemaVersion": _INDEX_SCHEMA_VERSION,
            "requestId": str(request_id),
            "authoritySha256": authority_sha,
        }
        index = {
            **index_identity,
            "indexSha256": _canonical_sha256(index_identity),
        }
        self._atomic_create(
            self.request_index_path_for(request_id),
            _canonical_bytes(index),
            label="prepared reference request index",
        )
        # Re-read both authorities and all referenced bytes before returning.
        persisted = self.load_by_request_id(
            request_id,
            expected_project_id=UUID(manifest["projectId"]),
        )
        if persisted is None:
            raise CompetitionPreparedReferenceError(
                "prepared reference publication is unavailable"
            )
        return persisted


# Short aliases keep caller wiring readable without weakening the competition
# boundary carried by the primary names.
PreparedReferenceStore = CompetitionPreparedReferenceStore
validate_prepared_reference_manifest = validate_competition_prepared_reference


__all__ = [
    "CompetitionPreparedReferenceError",
    "CompetitionPreparedReferenceStore",
    "PreparedReferenceStore",
    "validate_competition_prepared_reference",
    "validate_prepared_reference_manifest",
]
