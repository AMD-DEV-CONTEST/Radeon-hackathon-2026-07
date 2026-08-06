"""Filesystem confinement and integrity verification for model packages."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config import get_runtime_path
from services.model_integrity import ArtifactChangedDuringHashError
from services.model_integrity import sha256_file as _sha256_file
from services.model_packages.manifest import ModelPackageManifest
from services.model_packages.registry import (
    get_manifest,
    list_packages,
    update_installation,
)


VERIFICATION_RECORD = ".aetherdb-package-verified.json"


class ModelPackageVerificationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


def managed_models_root() -> Path:
    configured = os.environ.get("AETHERDB_MODEL_PACKAGE_ROOT", "").strip()
    root = (
        Path(configured).expanduser()
        if configured
        else get_runtime_path("app_data", "models")
    )
    return root.resolve()


def package_target(manifest: ModelPackageManifest) -> tuple[Path, str]:
    managed_root = managed_models_root()
    managed_target = managed_root.joinpath(*manifest.install_subdir.split("/")).resolve()
    external = (
        os.environ.get("AETHERDB_MODEL_ROOT", "").strip()
        if manifest.package_id == "aetherdb.bge-m3"
        else ""
    )
    if external:
        target = Path(external).expanduser().resolve()
        if target == managed_target:
            return target, "managed"
        if target == Path(target.anchor):
            raise ModelPackageVerificationError(
                "UNSAFE_MODEL_ROOT", "External model root cannot be a filesystem root"
            )
        return target, "external_override"

    root = managed_root
    target = managed_target
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ModelPackageVerificationError(
            "UNSAFE_MODEL_ROOT", "Managed model package escaped its storage root"
        ) from exc
    if target == root:
        raise ModelPackageVerificationError(
            "UNSAFE_MODEL_ROOT", "A package cannot own the entire model root"
        )
    return target, "managed"


def safe_package_file(root: Path, relative_path: str) -> Path:
    destination = root.joinpath(*relative_path.split("/"))
    resolved = destination.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ModelPackageVerificationError(
            "UNSAFE_PACKAGE_PATH", "Model artifact escaped the package root"
        ) from exc
    return destination


def sha256_file(path: Path) -> str:
    return _sha256_file(path)


def verify_package(
    manifest: ModelPackageManifest,
    root: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[str, ...]:
    issues = []
    completed = 0
    for artifact in manifest.files:
        path = safe_package_file(root, artifact.path)
        if path.is_symlink():
            issues.append(f"symlink:{artifact.path}")
            continue
        if not path.is_file():
            issues.append(f"missing:{artifact.path}")
            continue
        if path.stat().st_size != artifact.size:
            issues.append(f"size:{artifact.path}")
            continue
        try:
            digest = sha256_file(path)
        except (OSError, ArtifactChangedDuringHashError):
            issues.append(f"changed:{artifact.path}")
            continue
        if digest != artifact.sha256:
            issues.append(f"sha256:{artifact.path}")
            continue
        completed += artifact.size
        if progress:
            progress(completed, manifest.install_size_bytes)
    return tuple(issues)


def write_verification_record(
    manifest: ModelPackageManifest,
    root: Path,
) -> Path:
    artifacts = []
    for artifact in manifest.files:
        path = safe_package_file(root, artifact.path)
        stat = path.stat()
        artifacts.append(
            {
                "path": artifact.path,
                "size": artifact.size,
                "sha256": artifact.sha256,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    payload = {
        "schema_version": 1,
        "package_id": manifest.package_id,
        "package_version": manifest.package_version,
        "manifest_digest": manifest.digest(),
        "artifacts": artifacts,
    }
    destination = root / VERIFICATION_RECORD
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination


def verification_record_is_current(
    manifest: ModelPackageManifest,
    root: Path,
) -> bool:
    try:
        payload = json.loads((root / VERIFICATION_RECORD).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return _legacy_bge_record_is_current(manifest, root)
    if (
        payload.get("schema_version") != 1
        or payload.get("package_id") != manifest.package_id
        or payload.get("package_version") != manifest.package_version
        or payload.get("manifest_digest") != manifest.digest()
    ):
        return False
    recorded = payload.get("artifacts")
    if not isinstance(recorded, list) or len(recorded) != len(manifest.files):
        return False
    expected = {item.path: item for item in manifest.files}
    for item in recorded:
        artifact = expected.get(item.get("path")) if isinstance(item, dict) else None
        if artifact is None:
            return False
        path = safe_package_file(root, artifact.path)
        try:
            stat = path.stat()
        except OSError:
            return False
        if (
            path.is_symlink()
            or stat.st_size != artifact.size
            or item.get("size") != artifact.size
            or item.get("sha256") != artifact.sha256
            or item.get("mtime_ns") != stat.st_mtime_ns
        ):
            return False
        try:
            if sha256_file(path) != artifact.sha256:
                return False
        except (OSError, ArtifactChangedDuringHashError):
            return False
    return True


def _legacy_bge_record_is_current(
    manifest: ModelPackageManifest,
    root: Path,
) -> bool:
    if manifest.package_id != "aetherdb.bge-m3":
        return False
    try:
        payload = json.loads(
            (root / ".aetherdb-model-verified.json").read_text(encoding="utf-8")
        )
    except (OSError, TypeError, ValueError):
        return False
    if (
        payload.get("schema_version") != 1
        or payload.get("model_id") != manifest.model_family
        or payload.get("revision") != manifest.source.revision
    ):
        return False
    expected = {item.path: item for item in manifest.files}
    recorded = payload.get("artifacts")
    if not isinstance(recorded, list) or len(recorded) != len(expected):
        return False
    for item in recorded:
        artifact = expected.get(item.get("path")) if isinstance(item, dict) else None
        if artifact is None:
            return False
        path = safe_package_file(root, artifact.path)
        try:
            stat = path.stat()
        except OSError:
            return False
        if (
            path.is_symlink()
            or stat.st_size != artifact.size
            or item.get("size") != artifact.size
            or item.get("sha256") != artifact.sha256
            or item.get("mtime_ns") != stat.st_mtime_ns
        ):
            return False
        try:
            if sha256_file(path) != artifact.sha256:
                return False
        except (OSError, ArtifactChangedDuringHashError):
            return False
    return True


def reconcile_catalog_installations() -> None:
    for package in list_packages(sync=False):
        manifest = get_manifest(
            package["package_id"],
            package["package_version"],
            sync=False,
        )
        target, storage_scope = package_target(manifest)
        if not target.is_dir() or not verification_record_is_current(manifest, target):
            continue
        timestamp = datetime.now(timezone.utc).isoformat()
        update_installation(
            manifest.package_id,
            package_version=manifest.package_version,
            manifest_digest=manifest.digest(),
            status="installed",
            install_ref=manifest.install_subdir,
            storage_scope=storage_scope,
            verified_files=len(manifest.files),
            total_files=len(manifest.files),
            installed_size_bytes=manifest.install_size_bytes,
            error_code=None,
            error_message=None,
            installed_at=timestamp,
            verified_at=timestamp,
        )


def reconcile_package(package_id: str, package_version: str | None = None) -> dict:
    manifest = get_manifest(package_id, package_version)
    target, storage_scope = package_target(manifest)
    if not target.exists():
        return update_installation(
            package_id,
            package_version=manifest.package_version,
            manifest_digest=manifest.digest(),
            status="install_available",
            install_ref=manifest.install_subdir,
            storage_scope=storage_scope,
            verified_files=0,
            total_files=len(manifest.files),
            installed_size_bytes=0,
            error_code=None,
            error_message=None,
            installed_at=None,
            verified_at=None,
        )
    issues = verify_package(manifest, target)
    if issues:
        return update_installation(
            package_id,
            package_version=manifest.package_version,
            manifest_digest=manifest.digest(),
            status="repair_required",
            install_ref=manifest.install_subdir,
            storage_scope=storage_scope,
            verified_files=len(manifest.files) - len(issues),
            total_files=len(manifest.files),
            installed_size_bytes=0,
            error_code="PACKAGE_INTEGRITY_FAILED",
            error_message="One or more model package files failed verification",
            verified_at=None,
        )
    write_verification_record(manifest, target)
    timestamp = datetime.now(timezone.utc).isoformat()
    return update_installation(
        package_id,
        package_version=manifest.package_version,
        manifest_digest=manifest.digest(),
        status="installed",
        install_ref=manifest.install_subdir,
        storage_scope=storage_scope,
        verified_files=len(manifest.files),
        total_files=len(manifest.files),
        installed_size_bytes=manifest.install_size_bytes,
        error_code=None,
        error_message=None,
        installed_at=timestamp,
        verified_at=timestamp,
    )
