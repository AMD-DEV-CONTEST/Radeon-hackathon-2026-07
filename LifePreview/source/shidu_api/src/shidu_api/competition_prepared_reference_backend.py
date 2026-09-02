"""Steve Jobs imported-reference authority for the AMD competition proof.

The imported PNG is deliberately independent from the FLUX runtime proof.  A
user click still causes a real FLUX submission and observable GPU work, but
that FLUX output is discarded.  H3 receives only the fixed, pre-uploaded image
validated here.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.shidu.repository import ShiduRepository

from .competition_prompt_reference import build_competition_prompt_authority
from .visual_identity_preparation import ShiduRepositorySnapshotSource


IMPORTED_SOURCE_MODE = "preuploaded_imported"
IMPORTED_REFERENCE_PROFILE = "competition-imported-single-view-v1"
IMPORTED_REFERENCE_VIEW = "front_three_quarter"
IMPORTED_REFERENCE_SHA256 = (
    "fe82d64b5c47c2ef9159428f7dc1bedc18bf90dfe4ff86dff551672bbc673153"
)
IMPORTED_REFERENCE_BYTES = 1_518_792
IMPORTED_REFERENCE_WIDTH = 880
IMPORTED_REFERENCE_HEIGHT = 1_168
_DEFAULT_IMPORTED_REFERENCE = Path(
    "/persistent/douyin-amd/prepared-reference-imports/steve-jobs/"
    "steve-jobs-front-three-quarter-fe82d64b5c47c2ef.png"
)


class CompetitionPreparedReferenceBackendError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class CompetitionPreparedReferenceBackend:
    """Expose one immutable imported asset plus the separate FLUX proof prompt."""

    def __init__(
        self,
        *,
        session_factory: Any,
        persistent_root: Path,
        release_root: Path,
        imported_reference_path: Path | None = None,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("session factory is invalid")
        self._sessions = session_factory
        self._persistent_root = Path(persistent_root).resolve(strict=True)
        self._release_root = Path(release_root).resolve(strict=True)
        self._flux_manifest = self._release_root / (
            "drama_factory/config/flux2_dev_fp8mixed_amd_capability.json"
        )
        candidate = imported_reference_path or _DEFAULT_IMPORTED_REFERENCE
        try:
            self._imported_path = Path(candidate).resolve(strict=True)
            self._imported_path.relative_to(self._persistent_root)
        except (OSError, ValueError) as exc:
            raise CompetitionPreparedReferenceBackendError(
                "Steve Jobs imported reference is outside persistent storage"
            ) from exc
        self._validate_imported_bytes()

    @classmethod
    def from_environment(cls, *, session_factory: Any):
        configured = os.environ.get("AMD_STEVE_JOBS_REFERENCE_PATH")
        return cls(
            session_factory=session_factory,
            persistent_root=Path(os.environ["AMD_ROOT"]),
            release_root=Path(os.environ["AMD_RELEASE_DIR"]),
            imported_reference_path=(Path(configured) if configured else None),
        )

    def _validate_imported_bytes(self) -> None:
        path = self._imported_path
        if path.is_symlink() or not path.is_file():
            raise CompetitionPreparedReferenceBackendError(
                "Steve Jobs imported reference is unavailable"
            )
        if path.stat().st_size != IMPORTED_REFERENCE_BYTES:
            raise CompetitionPreparedReferenceBackendError(
                "Steve Jobs imported reference byte size changed"
            )
        if _sha256_file(path) != IMPORTED_REFERENCE_SHA256:
            raise CompetitionPreparedReferenceBackendError(
                "Steve Jobs imported reference SHA-256 changed"
            )

    @staticmethod
    def _request_ids(request: Mapping[str, Any]) -> tuple[UUID, UUID, UUID]:
        return (
            UUID(str(request["bookId"])),
            UUID(str(request["directionRevisionId"])),
            UUID(str(request["trialScriptRevisionId"])),
        )

    def _snapshot_and_prompt(
        self, *, project_id: UUID, request: Mapping[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        book_id, direction_id, script_id = self._request_ids(request)
        with self._sessions() as session:
            snapshot = ShiduRepositorySnapshotSource(ShiduRepository(session)).load(
                project_id=project_id,
                book_id=book_id,
                direction_revision_id=direction_id,
                trial_script_revision_id=script_id,
            )
        title = str(snapshot.project_authority_payload.get("title", ""))
        if "乔布斯" not in title and "steve jobs" not in title.casefold():
            raise ValueError("competition demo book must be Steve Jobs")
        snapshot = replace(
            snapshot,
            character_name="Steve Jobs (史蒂夫·乔布斯)",
            age_stage="adult",
        )
        click_input = canonical_json_digest(
            {
                "schemaVersion": "amd.flux-runtime-proof-input.v1",
                "projectId": str(project_id),
                "bookId": str(book_id),
                "directionRevisionId": str(direction_id),
                "trialScriptRevisionId": str(script_id),
            }
        )
        prompt = build_competition_prompt_authority(
            snapshot=snapshot,
            job_authority_digest=click_input,
            flux_manifest=self._flux_manifest,
        )
        return snapshot, prompt

    def _manifest(self, *, project_id: UUID, request: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_imported_bytes()
        snapshot, prompt = self._snapshot_and_prompt(project_id=project_id, request=request)
        request_id = uuid5(
            NAMESPACE_URL,
            f"amd:steve-jobs-imported-reference:{IMPORTED_REFERENCE_SHA256}",
        )
        identity = {
            "schemaVersion": "amd.competition-imported-reference.v1",
            "status": "prepared",
            "requestId": str(request_id),
            "projectId": str(project_id),
            "bookId": str(snapshot.book_id),
            "directionRevisionId": str(snapshot.direction_revision_id),
            "trialScriptRevisionId": str(snapshot.trial_script_revision_id),
            "characterName": snapshot.character_name,
            "referenceProfile": IMPORTED_REFERENCE_PROFILE,
            "sourceMode": IMPORTED_SOURCE_MODE,
            "requiredImages": 1,
            "fluxRuntimeProofPromptAuthority": prompt,
            "reference": {
                "viewName": IMPORTED_REFERENCE_VIEW,
                "path": str(self._imported_path),
                "sha256": IMPORTED_REFERENCE_SHA256,
                "mimeType": "image/png",
                "width": IMPORTED_REFERENCE_WIDTH,
                "height": IMPORTED_REFERENCE_HEIGHT,
                "byteSize": IMPORTED_REFERENCE_BYTES,
                "importedBeforeUserClick": True,
                "generatedByCurrentFlux": False,
            },
        }
        return {
            **identity,
            "importAuthoritySha256": self._import_authority_sha256(),
        }

    def _import_authority_sha256(self) -> str:
        return canonical_json_digest(
            {
                "schemaVersion": "amd.preuploaded-imported-asset-authority.v1",
                "sourceMode": IMPORTED_SOURCE_MODE,
                "viewName": IMPORTED_REFERENCE_VIEW,
                "path": str(self._imported_path),
                "sha256": IMPORTED_REFERENCE_SHA256,
                "mimeType": "image/png",
                "width": IMPORTED_REFERENCE_WIDTH,
                "height": IMPORTED_REFERENCE_HEIGHT,
                "byteSize": IMPORTED_REFERENCE_BYTES,
                "generatedByCurrentFlux": False,
            }
        )

    @staticmethod
    def _public(manifest: Mapping[str, Any]) -> dict[str, Any]:
        prompt = manifest["fluxRuntimeProofPromptAuthority"]
        reference = manifest["reference"]
        return {
            "status": "prepared",
            "cacheHit": True,
            "requestId": manifest["requestId"],
            "characterName": manifest["characterName"],
            "referenceProfile": manifest["referenceProfile"],
            "sourceMode": manifest["sourceMode"],
            "requiredImages": 1,
            "importAuthoritySha256": manifest["importAuthoritySha256"],
            "fluxProofPromptSha256": prompt["promptSha256"],
            "fluxProofSeed": prompt["seed"],
            "fluxProofTemplateWorkflowSha256": prompt["workflowSha256"],
            "reference": {
                "viewName": reference["viewName"],
                "sha256": reference["sha256"],
                "mimeType": reference["mimeType"],
                "width": reference["width"],
                "height": reference["height"],
                "byteSize": reference["byteSize"],
                "importedBeforeUserClick": True,
                "generatedByCurrentFlux": False,
            },
        }

    def prepare(
        self,
        *,
        project_id: UUID,
        request: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Resolve the import only; this endpoint never starts FLUX or H3."""

        if not isinstance(project_id, UUID) or not idempotency_key.strip():
            raise ValueError("prepared import request is invalid")
        return self._public(self._manifest(project_id=project_id, request=request))

    def lookup(
        self, *, project_id: UUID, request: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        try:
            return self._public(self._manifest(project_id=project_id, request=request))
        except (KeyError, OSError, TypeError, ValueError):
            return None

    def load_for_prompt(self, prompt: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Return the immutable import for the exact persisted FLUX-proof prompt."""

        self._validate_imported_bytes()
        character = str(prompt.get("characterName", ""))
        if "乔布斯" not in character and "steve jobs" not in character.casefold():
            return None
        request_id = uuid5(
            NAMESPACE_URL,
            f"amd:steve-jobs-imported-reference:{IMPORTED_REFERENCE_SHA256}",
        )
        identity = {
            "schemaVersion": "amd.competition-imported-reference.v1",
            "status": "prepared",
            "requestId": str(request_id),
            "characterName": prompt["characterName"],
            "referenceProfile": IMPORTED_REFERENCE_PROFILE,
            "sourceMode": IMPORTED_SOURCE_MODE,
            "requiredImages": 1,
            "fluxRuntimeProofPromptAuthority": dict(prompt),
            "reference": {
                "viewName": IMPORTED_REFERENCE_VIEW,
                "path": str(self._imported_path),
                "sha256": IMPORTED_REFERENCE_SHA256,
                "mimeType": "image/png",
                "width": IMPORTED_REFERENCE_WIDTH,
                "height": IMPORTED_REFERENCE_HEIGHT,
                "byteSize": IMPORTED_REFERENCE_BYTES,
                "importedBeforeUserClick": True,
                "generatedByCurrentFlux": False,
            },
        }
        return {
            **identity,
            "importAuthoritySha256": self._import_authority_sha256(),
        }

    def read_image(
        self, *, project_id: UUID, request_id: UUID
    ) -> tuple[bytes, str, str]:
        del project_id
        expected_id = uuid5(
            NAMESPACE_URL,
            f"amd:steve-jobs-imported-reference:{IMPORTED_REFERENCE_SHA256}",
        )
        if request_id != expected_id:
            raise ValueError("prepared imported reference does not exist")
        self._validate_imported_bytes()
        return self._imported_path.read_bytes(), "image/png", IMPORTED_REFERENCE_SHA256


__all__ = [
    "CompetitionPreparedReferenceBackend",
    "CompetitionPreparedReferenceBackendError",
    "IMPORTED_REFERENCE_BYTES",
    "IMPORTED_REFERENCE_HEIGHT",
    "IMPORTED_REFERENCE_PROFILE",
    "IMPORTED_REFERENCE_SHA256",
    "IMPORTED_REFERENCE_VIEW",
    "IMPORTED_REFERENCE_WIDTH",
    "IMPORTED_SOURCE_MODE",
]
