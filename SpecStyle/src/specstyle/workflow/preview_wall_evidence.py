"""Atomic engineering-only evidence for a complete Preview variation wall."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
import sys
import uuid

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.qa_report import canonical_json_bytes
from specstyle.observability.hashing import hash_bytes
from specstyle.workflow._job_store_fs import (
    CorruptStore,
    DestinationExists,
    StoreIO,
    close_owned,
    fsync_directory,
    open_directory,
    read_file,
    rename_noreplace,
    write_slot,
)
from specstyle.workflow.preview_evidence import (
    PreviewEvidencePublication,
    _duplicate_root,
    _verify_stored_publication,
)

_WALL_NAME = re.compile(r"preview-wall-[0-9a-f]{32}", re.ASCII)
_MANIFEST_BYTES = 128 * 1024
_STATUSES = {"COMPLETED", "FAILED", "UNAVAILABLE", "BUSY"}


@dataclass(frozen=True, slots=True)
class PreviewWallEvidenceItem:
    variation_index: int
    attempted: bool
    run_id: str
    status: str
    reason_code: str
    publication: PreviewEvidencePublication | None

    def __post_init__(self) -> None:
        completed = self.status == "COMPLETED"
        if (
            type(self.variation_index) is not int
            or not 0 <= self.variation_index < 4
            or type(self.attempted) is not bool
            or type(self.run_id) is not str
            or not self.run_id.startswith("preview-wall-")
            or self.status not in _STATUSES
            or type(self.reason_code) is not str
            or not self.reason_code
            or (completed != (type(self.publication) is PreviewEvidencePublication))
            or (completed and not self.attempted)
            or (completed and self.reason_code != "OK")
            or (self.status == "BUSY" and self.attempted)
            or (self.status == "BUSY" and self.reason_code != "GPU_BUSY")
        ):
            raise DomainError("invalid preview wall evidence item")
        if completed:
            publication = self.publication
            if (
                publication.schema_version != "specstyle.preview.evidence.v3"
                or publication.evidence_class != "ENGINEERING_ONLY"
                or publication.runtime_dtype != "float16"
                or publication.vae_at_rest_dtype != "float16"
                or publication.vae_compute_dtype != "float32"
                or publication.vae_precision_policy
                != "diffusers_force_upcast_roundtrip_v1"
                or publication.evidence_name != self.run_id
                or publication.variation_index != self.variation_index
            ):
                raise DomainError("invalid preview wall publication variation binding")


@dataclass(frozen=True, slots=True)
class PreviewWallEvidencePublication:
    evidence_name: str
    manifest_sha256: Sha256

    def __post_init__(self) -> None:
        if (
            type(self.evidence_name) is not str
            or _WALL_NAME.fullmatch(self.evidence_name) is None
            or type(self.manifest_sha256) is not Sha256
        ):
            raise DomainError("invalid preview wall evidence publication")


def _item_primitive(item: PreviewWallEvidenceItem) -> dict[str, object]:
    artifact = None
    if item.publication is not None:
        artifact = {
            "evidence_name": item.publication.evidence_name,
            "display_name": item.publication.display_name,
            "artifact_id": item.publication.artifact_id.value,
            "content_sha256": item.publication.content_sha256.value,
            "compiled_request_fingerprint": (
                item.publication.compiled_request_fingerprint.value
            ),
            "execution_fingerprint": item.publication.execution_fingerprint.value,
            "evidence_schema_version": item.publication.schema_version,
            "runtime_dtype": item.publication.runtime_dtype,
            "vae_at_rest_dtype": item.publication.vae_at_rest_dtype,
            "vae_compute_dtype": item.publication.vae_compute_dtype,
            "vae_precision_policy": item.publication.vae_precision_policy,
            "seed_algorithm": item.publication.seed_algorithm,
            "seed": item.publication.seed,
            "resolution": list(item.publication.resolution),
        }
    return {
        "variation_index": item.variation_index,
        "attempted": item.attempted,
        "run_id": item.run_id,
        "status": item.status,
        "reason_code": item.reason_code,
        "artifact": artifact,
    }


def _metrics(items: tuple[PreviewWallEvidenceItem, ...]) -> dict[str, int]:
    completed = tuple(item for item in items if item.status == "COMPLETED")
    hashes = {item.publication.content_sha256.value for item in completed}
    busy = sum(item.status == "BUSY" for item in items)
    return {
        "requested": len(items),
        "completed": len(completed),
        "failed": len(items) - len(completed) - busy,
        "busy": busy,
        "unique_content_hash_count": len(hashes),
        "duplicate_count": len(completed) - len(hashes),
    }


def _wall_status(items: tuple[PreviewWallEvidenceItem, ...], cleanup: str) -> str:
    completed = sum(item.status == "COMPLETED" for item in items)
    if all(item.status == "BUSY" for item in items):
        return "BUSY"
    if completed == len(items) and cleanup == "COMPLETED":
        return "COMPLETED"
    if completed:
        return "PARTIAL"
    return "FAILED"


def _manifest(
    wall_id: str,
    items: tuple[PreviewWallEvidenceItem, ...],
    elapsed_seconds: float,
    runtime_cleanup: str,
) -> bytes:
    if (
        _WALL_NAME.fullmatch(wall_id) is None
        or type(items) is not tuple
        or not 1 <= len(items) <= 4
        or any(type(item) is not PreviewWallEvidenceItem for item in items)
        or tuple(item.variation_index for item in items) != tuple(range(len(items)))
        or any(item.run_id != f"{wall_id}-v{item.variation_index}" for item in items)
        or type(elapsed_seconds) is not float
        or not math.isfinite(elapsed_seconds)
        or elapsed_seconds < 0
        or runtime_cleanup not in {"COMPLETED", "FAILED", "NOT_STARTED"}
    ):
        raise DomainError("invalid preview wall evidence")
    metrics = _metrics(items)
    if (
        metrics["requested"]
        != metrics["completed"] + metrics["failed"] + metrics["busy"]
    ):
        raise DomainError("invalid preview wall metrics")
    return canonical_json_bytes(
        {
            "schema_version": "specstyle.preview.wall-evidence.v2",
            "wall_id": wall_id,
            "profile": "preview",
            "evidence_class": "ENGINEERING_ONLY",
            "status": _wall_status(items, runtime_cleanup),
            "requested_variation_indices": list(range(len(items))),
            "elapsed_seconds": round(elapsed_seconds, 6),
            "runtime_cleanup": runtime_cleanup,
            "items": [_item_primitive(item) for item in items],
            "metrics": metrics,
            "quality": "NOT_EVALUATED",
            "diversity": "NOT_EVALUATED",
            "planes": {
                "verification": "NOT_RUN",
                "repair": "NOT_RUN",
                "export": "NOT_RUN",
            },
        }
    )


def _remove_staging(root_fd: int, name: str) -> None:
    try:
        root_dev = os.fstat(root_fd).st_dev
        opened = open_directory(root_fd, name, root_dev, missing_ok=True)
    except (OSError, CorruptStore, StoreIO):
        return
    if opened is None:
        return
    directory_fd = opened[0]
    try:
        try:
            os.unlink("manifest.json", dir_fd=directory_fd)
        except FileNotFoundError:
            pass
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass
    try:
        os.rmdir(name, dir_fd=root_fd)
    except OSError:
        pass


def _publish(root_fd: int, root_dev: int, name: str, manifest: bytes) -> None:
    staging = f".preview-wall-{uuid.uuid4().hex}"
    directory_fd = -1
    try:
        os.mkdir(staging, 0o700, dir_fd=root_fd)
        opened = open_directory(root_fd, staging, root_dev)
        if opened is None:
            raise CorruptStore
        directory_fd = opened[0]
        write_slot(directory_fd, "manifest.json", manifest, _MANIFEST_BYTES, root_dev)
        fsync_directory(directory_fd)
        close_owned(directory_fd)
        directory_fd = -1
        rename_noreplace(root_fd, staging, name)
        fsync_directory(root_fd)
    except DestinationExists:
        _remove_staging(root_fd, staging)
        raise DomainError("preview wall evidence already exists") from None
    except (OSError, CorruptStore, StoreIO):
        _remove_staging(root_fd, staging)
        raise InfrastructureError("preview wall evidence unavailable") from None
    finally:
        if directory_fd >= 0:
            close_owned(directory_fd, sys.exception())


def _verify(root_fd: int, root_dev: int, name: str, expected: Sha256) -> None:
    opened = open_directory(root_fd, name, root_dev)
    if opened is None:
        raise InfrastructureError("preview wall evidence unavailable")
    directory_fd = opened[0]
    try:
        record = read_file(directory_fd, "manifest.json", 1, _MANIFEST_BYTES, root_dev)
        if record is None or hash_bytes(record.data) != expected:
            raise InfrastructureError("preview wall evidence unavailable")
    except (CorruptStore, StoreIO):
        raise InfrastructureError("preview wall evidence unavailable") from None
    finally:
        close_owned(directory_fd, sys.exception())


def publish_preview_wall_evidence(
    evidence_root_fd: int,
    wall_id: str,
    items: tuple[PreviewWallEvidenceItem, ...],
    elapsed_seconds: float,
    runtime_cleanup: str,
    /,
) -> PreviewWallEvidencePublication:
    manifest = _manifest(wall_id, items, elapsed_seconds, runtime_cleanup)
    digest = hash_bytes(manifest)
    root_fd = -1
    try:
        root_fd, root_dev, _identity = _duplicate_root(evidence_root_fd)
        for item in items:
            if item.publication is not None:
                _verify_stored_publication(root_fd, root_dev, item.publication)
        _publish(root_fd, root_dev, wall_id, manifest)
        _verify(root_fd, root_dev, wall_id, digest)
        return PreviewWallEvidencePublication(wall_id, digest)
    finally:
        close_owned(root_fd, sys.exception())


__all__ = (
    "PreviewWallEvidenceItem",
    "PreviewWallEvidencePublication",
    "publish_preview_wall_evidence",
)
