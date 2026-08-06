"""Resumable, verified, atomic model-package installation operations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse

import requests

from app.config import get_runtime_path
from services.model_packages.manifest import (
    ModelPackageManifest,
    load_package_manifest,
)
from services.model_packages.registry import (
    ACTIVE_OPERATION_STATUSES,
    ModelPackageRegistryError,
    cancel_requested,
    create_operation,
    get_installation,
    get_manifest,
    get_operation,
    license_is_accepted,
    list_operations,
    manifest_is_compatible,
    sync_catalog,
    update_installation,
    update_operation,
    validate_source_ref,
)
from services.model_packages.verifier import (
    ModelPackageVerificationError,
    managed_models_root,
    package_target,
    safe_package_file,
    sha256_file,
    verification_record_is_current,
    verify_package,
    write_verification_record,
)


CHUNK_SIZE = 8 * 1024 * 1024
MAX_REDIRECTS = 5
ACTIVE_RESPONSES: dict[str, requests.Response] = {}
RESPONSE_LOCK = threading.RLock()
TASK_LOCK = threading.RLock()
ACTIVE_THREADS: dict[str, threading.Thread] = {}


class ModelPackageOperationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


class _OperationCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def model_package_cache_root() -> Path:
    return get_runtime_path("app_data", "cache", "model_packages").resolve()


def model_package_inbox() -> Path:
    return get_runtime_path("app_data", "model_packages", "inbox").resolve()


def _operation_cache(manifest: ModelPackageManifest) -> Path:
    return (
        model_package_cache_root()
        / manifest.package_id
        / manifest.package_version
    ).resolve()


def _operation_paths(
    operation_id: str,
    manifest: ModelPackageManifest,
) -> tuple[Path, Path, Path]:
    target, _ = package_target(manifest)
    parent = target.parent
    safe_id = manifest.package_id.replace(".", "-")
    stage = parent / f".aetherdb-stage-{safe_id}-{operation_id}"
    rollback = parent / f".aetherdb-rollback-{safe_id}-{operation_id}"
    return target, stage, rollback


def _set_install_state(manifest: ModelPackageManifest, status: str, **updates) -> dict:
    target, storage_scope = package_target(manifest)
    return update_installation(
        manifest.package_id,
        package_version=manifest.package_version,
        manifest_digest=manifest.digest(),
        status=status,
        install_ref=manifest.install_subdir,
        storage_scope=storage_scope,
        total_files=len(manifest.files),
        **updates,
    )


def _start_thread(operation_id: str) -> None:
    with TASK_LOCK:
        current = ACTIVE_THREADS.get(operation_id)
        if current and current.is_alive():
            return
        thread = threading.Thread(
            target=_run_operation_safely,
            args=(operation_id,),
            name=f"model-package-{operation_id[:8]}",
            daemon=True,
        )
        ACTIVE_THREADS[operation_id] = thread
        thread.start()


def start_install_operation(
    package_id: str,
    *,
    package_version: str | None = None,
    source_kind: str = "catalog",
    source_ref: str | None = None,
    repair: bool = False,
    retry_of: str | None = None,
) -> dict:
    sync_catalog()
    manifest = get_manifest(package_id, package_version, sync=False)
    if not manifest_is_compatible(manifest):
        _set_install_state(manifest, "incompatible")
        raise ModelPackageOperationError(
            "PACKAGE_INCOMPATIBLE", "Model package is incompatible with this host"
        )
    if not license_is_accepted(manifest):
        raise ModelPackageOperationError(
            "LICENSE_ACCEPTANCE_REQUIRED",
            "The exact model package license must be accepted before installation",
        )
    _, storage_scope = package_target(manifest)
    if storage_scope == "external_override":
        raise ModelPackageOperationError(
            "EXTERNAL_PACKAGE_READ_ONLY",
            "Externally supplied model files can be verified but not replaced by AetherDB",
        )
    if source_kind == "catalog" and manifest.source.kind != "trusted_https":
        raise ModelPackageOperationError(
            "CATALOG_DOWNLOAD_UNAVAILABLE",
            "This model package is available only as a verified offline archive",
        )
    safe_source_ref = validate_source_ref(source_kind, source_ref)
    if source_kind == "offline_cache":
        archive = model_package_inbox() / safe_source_ref
        if not archive.is_file():
            raise ModelPackageOperationError(
                "OFFLINE_PACKAGE_MISSING",
                "The selected offline package is not present in the managed inbox",
            )
    operation = create_operation(
        manifest,
        operation="repair" if repair else "install",
        source_kind=source_kind,
        source_ref=safe_source_ref,
        retry_of=retry_of,
    )
    if operation["status"] in ACTIVE_OPERATION_STATUSES:
        _start_thread(operation["id"])
    return get_operation(operation["id"]) or operation


def start_verify_operation(
    package_id: str,
    *,
    package_version: str | None = None,
) -> dict:
    sync_catalog()
    manifest = get_manifest(package_id, package_version, sync=False)
    operation = create_operation(
        manifest,
        operation="verify",
        source_kind="installed",
        source_ref="installed",
    )
    if operation["status"] in ACTIVE_OPERATION_STATUSES:
        _start_thread(operation["id"])
    return get_operation(operation["id"]) or operation


def cancel_operation(operation_id: str) -> dict:
    operation = get_operation(operation_id)
    if operation is None:
        raise KeyError(operation_id)
    if operation["status"] not in ACTIVE_OPERATION_STATUSES:
        return operation
    updated = update_operation(
        operation_id,
        cancel_requested=1,
        error_code=None,
        error_message=None,
    )
    with RESPONSE_LOCK:
        response = ACTIVE_RESPONSES.get(operation_id)
    if response is not None:
        response.close()
    return updated


def retry_operation(operation_id: str) -> dict:
    previous = get_operation(operation_id)
    if previous is None:
        raise KeyError(operation_id)
    if previous["status"] not in {"failed", "cancelled"}:
        raise ModelPackageOperationError(
            "RETRY_NOT_ALLOWED", "Only failed or cancelled package operations can be retried"
        )
    if previous["operation"] == "verify":
        return start_verify_operation(
            previous["package_id"], package_version=previous["package_version"]
        )
    return start_install_operation(
        previous["package_id"],
        package_version=previous["package_version"],
        source_kind=previous["source_kind"],
        source_ref=previous["source_ref"],
        repair=previous["operation"] == "repair",
        retry_of=previous["id"],
    )


def _check_cancelled(operation_id: str) -> None:
    if cancel_requested(operation_id):
        raise _OperationCancelled()


def _trusted_host(manifest: ModelPackageManifest, hostname: str | None) -> bool:
    host = (hostname or "").lower()
    return any(
        host == allowed or (allowed.startswith(".") and host.endswith(allowed))
        for allowed in manifest.source.trusted_redirect_hosts
    )


def _request_download(
    session: requests.Session,
    operation_id: str,
    manifest: ModelPackageManifest,
    url: str,
    headers: dict,
):
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(current_url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or not _trusted_host(manifest, parsed.hostname)
        ):
            raise ModelPackageOperationError(
                "DOWNLOAD_TARGET_BLOCKED", "Model package download target is not trusted"
            )
        try:
            response = session.get(
                current_url,
                headers=headers,
                stream=True,
                timeout=(15, 180),
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            if cancel_requested(operation_id):
                raise _OperationCancelled() from exc
            raise ModelPackageOperationError(
                "DOWNLOAD_TIMEOUT", "Model package download timed out"
            ) from exc
        except requests.RequestException as exc:
            if cancel_requested(operation_id):
                raise _OperationCancelled() from exc
            raise ModelPackageOperationError(
                "DOWNLOAD_FAILED", "Model package download failed"
            ) from exc
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                raise ModelPackageOperationError(
                    "REDIRECT_BLOCKED", "Model package redirect was invalid"
                )
            current_url = urljoin(current_url, location)
            continue
        with RESPONSE_LOCK:
            ACTIVE_RESPONSES[operation_id] = response
        return response
    raise ModelPackageOperationError(
        "REDIRECT_BLOCKED", "Model package download exceeded the redirect limit"
    )


def _download_artifact(
    session: requests.Session,
    operation_id: str,
    manifest: ModelPackageManifest,
    artifact,
    destination: Path,
    base_completed: int,
) -> None:
    if (
        destination.is_file()
        and destination.stat().st_size == artifact.size
        and sha256_file(destination) == artifact.sha256
    ):
        update_operation(
            operation_id,
            completed_bytes=base_completed + artifact.size,
            progress=(base_completed + artifact.size) / manifest.install_size_bytes,
        )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > artifact.size:
        partial.unlink()
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    url = urljoin(manifest.source.base_url or "", artifact.download_path)
    response = _request_download(
        session, operation_id, manifest, url, headers
    )
    try:
        if response.status_code not in {200, 206}:
            if response.status_code in {401, 403}:
                code = "DOWNLOAD_AUTH_FAILED"
            elif response.status_code == 404:
                code = "PACKAGE_FILE_MISSING"
            else:
                code = f"DOWNLOAD_HTTP_{response.status_code}"
            raise ModelPackageOperationError(code, "Model package download failed")
        append = offset > 0 and response.status_code == 206
        if append:
            content_range = response.headers.get("Content-Range", "")
            if content_range and not content_range.startswith(f"bytes {offset}-"):
                raise ModelPackageOperationError(
                    "INVALID_RANGE_RESPONSE", "Download server returned an invalid range"
                )
        else:
            offset = 0
        mode = "ab" if append else "wb"
        with partial.open(mode) as output:
            completed = offset
            try:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    _check_cancelled(operation_id)
                    if not chunk:
                        continue
                    completed += len(chunk)
                    if completed > artifact.size:
                        partial.unlink(missing_ok=True)
                        raise ModelPackageOperationError(
                            "DOWNLOAD_SIZE_MISMATCH",
                            "Downloaded model package file exceeded its declared size",
                        )
                    output.write(chunk)
                    total_completed = base_completed + completed
                    update_operation(
                        operation_id,
                        completed_bytes=total_completed,
                        progress=min(
                            0.75,
                            0.75 * total_completed / manifest.install_size_bytes,
                        ),
                    )
            except requests.RequestException as exc:
                if cancel_requested(operation_id):
                    raise _OperationCancelled() from exc
                raise ModelPackageOperationError(
                    "DOWNLOAD_FAILED", "Model package download failed"
                ) from exc
        if partial.stat().st_size != artifact.size:
            raise ModelPackageOperationError(
                "DOWNLOAD_SIZE_MISMATCH",
                "Downloaded model package file did not match its declared size",
            )
        if sha256_file(partial) != artifact.sha256:
            partial.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise ModelPackageOperationError(
                "SHA256_MISMATCH", "Downloaded model package file failed SHA-256 verification"
            )
        os.replace(partial, destination)
    finally:
        with RESPONSE_LOCK:
            ACTIVE_RESPONSES.pop(operation_id, None)
        response.close()


def _download_catalog(
    operation_id: str,
    manifest: ModelPackageManifest,
) -> Path:
    cache = _operation_cache(manifest)
    cache.mkdir(parents=True, exist_ok=True)
    update_operation(
        operation_id,
        status="downloading",
        progress=0,
        error_code=None,
        error_message=None,
    )
    _set_install_state(
        manifest,
        "downloading",
        verified_files=0,
        installed_size_bytes=0,
        error_code=None,
        error_message=None,
    )
    completed = 0
    with requests.Session() as session:
        for artifact in manifest.files:
            _check_cancelled(operation_id)
            destination = safe_package_file(cache, artifact.path)
            _download_artifact(
                session,
                operation_id,
                manifest,
                artifact,
                destination,
                completed,
            )
            completed += artifact.size
    return cache


def _zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _validate_archive_entry(name: str) -> str:
    if "\\" in name or "\x00" in name:
        raise ModelPackageOperationError(
            "ARCHIVE_LAYOUT_INVALID", "Offline model package contains an unsafe path"
        )
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelPackageOperationError(
            "ARCHIVE_LAYOUT_INVALID", "Offline model package contains an unsafe path"
        )
    return path.as_posix()


def _extract_offline_archive(
    operation_id: str,
    manifest: ModelPackageManifest,
    archive_path: Path,
    stage: Path,
) -> None:
    expected = {item.path: item for item in manifest.files}
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ModelPackageOperationError(
            "ARCHIVE_INVALID", "Offline model package is not a valid ZIP archive"
        ) from exc
    with archive:
        files = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = _validate_archive_entry(info.filename)
            if name in files or _zip_entry_is_symlink(info):
                raise ModelPackageOperationError(
                    "ARCHIVE_LAYOUT_INVALID",
                    "Offline model package contains duplicate or linked files",
                )
            files[name] = info
        expected_names = {*expected, "package-manifest.json"}
        if set(files) != expected_names:
            raise ModelPackageOperationError(
                "ARCHIVE_LAYOUT_INVALID",
                "Offline model package contents do not match the trusted manifest",
            )
        manifest_info = files["package-manifest.json"]
        if manifest_info.file_size > 2 * 1024 * 1024:
            raise ModelPackageOperationError(
                "ARCHIVE_LAYOUT_INVALID", "Offline package manifest is too large"
            )
        try:
            archived_manifest = ModelPackageManifest.model_validate_json(
                archive.read(manifest_info)
            )
        except (ValueError, TypeError) as exc:
            raise ModelPackageOperationError(
                "MANIFEST_MISMATCH", "Offline package manifest is invalid"
            ) from exc
        if archived_manifest.digest() != manifest.digest():
            raise ModelPackageOperationError(
                "MANIFEST_MISMATCH",
                "Offline package manifest does not match the trusted catalog",
            )
        update_operation(operation_id, status="verifying", progress=0)
        _set_install_state(manifest, "verifying")
        completed = 0
        for relative_path, artifact in expected.items():
            _check_cancelled(operation_id)
            info = files[relative_path]
            if info.file_size != artifact.size:
                raise ModelPackageOperationError(
                    "ARCHIVE_SIZE_MISMATCH",
                    "Offline package file size does not match the manifest",
                )
            destination = safe_package_file(stage, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with archive.open(info) as source, destination.open("wb") as output:
                while True:
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    _check_cancelled(operation_id)
                    digest.update(chunk)
                    output.write(chunk)
                    completed += len(chunk)
                    update_operation(
                        operation_id,
                        completed_bytes=completed,
                        progress=min(
                            0.75,
                            0.75 * completed / manifest.install_size_bytes,
                        ),
                    )
            if digest.hexdigest() != artifact.sha256:
                raise ModelPackageOperationError(
                    "SHA256_MISMATCH",
                    "Offline model package file failed SHA-256 verification",
                )


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _prepare_catalog_stage(
    operation_id: str,
    manifest: ModelPackageManifest,
    cache: Path,
    stage: Path,
) -> None:
    update_operation(operation_id, status="verifying", progress=0.75)
    _set_install_state(manifest, "verifying")
    issues = verify_package(manifest, cache)
    if issues:
        raise ModelPackageOperationError(
            "PACKAGE_INTEGRITY_FAILED",
            "Downloaded model package failed integrity verification",
        )
    for artifact in manifest.files:
        _check_cancelled(operation_id)
        _link_or_copy(
            safe_package_file(cache, artifact.path),
            safe_package_file(stage, artifact.path),
        )


def _recover_atomic_state(
    operation_id: str,
    manifest: ModelPackageManifest,
) -> tuple[Path, Path, Path]:
    target, stage, rollback = _operation_paths(operation_id, manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    if rollback.exists() and not target.exists():
        os.replace(rollback, target)
    elif rollback.exists() and target.exists():
        if verification_record_is_current(manifest, target):
            _remove_path(rollback)
        else:
            _remove_path(target)
            os.replace(rollback, target)
    if stage.exists():
        _remove_path(stage)
    return target, stage, rollback


def _atomic_install(
    operation_id: str,
    manifest: ModelPackageManifest,
    stage: Path,
) -> Path:
    target, _, rollback = _operation_paths(operation_id, manifest)
    update_operation(operation_id, status="installing", progress=0.9)
    _set_install_state(manifest, "installing")
    if target.exists():
        os.replace(target, rollback)
    try:
        os.replace(stage, target)
        issues = verify_package(manifest, target)
        if issues:
            raise ModelPackageOperationError(
                "POST_INSTALL_VERIFICATION_FAILED",
                "Installed model package failed final verification",
            )
        write_verification_record(manifest, target)
    except Exception:
        if target.exists():
            _remove_path(target)
        if rollback.exists():
            os.replace(rollback, target)
        raise
    if rollback.exists():
        _remove_path(rollback)
    return target


def _run_install(operation: dict, manifest: ModelPackageManifest) -> None:
    operation_id = operation["id"]
    target, stage, _ = _recover_atomic_state(operation_id, manifest)
    required = manifest.install_size_bytes + 512 * 1024 * 1024
    if shutil.disk_usage(target.parent).free < required:
        raise ModelPackageOperationError(
            "INSUFFICIENT_DISK_SPACE",
            "Insufficient free space for atomic model package installation",
        )
    stage.mkdir(parents=True, exist_ok=False)
    try:
        if operation["source_kind"] == "catalog":
            cache = _download_catalog(operation_id, manifest)
            _prepare_catalog_stage(operation_id, manifest, cache, stage)
        elif operation["source_kind"] == "offline_cache":
            inbox = model_package_inbox()
            archive = (inbox / operation["source_ref"]).resolve()
            try:
                archive.relative_to(inbox)
            except ValueError as exc:
                raise ModelPackageOperationError(
                    "INVALID_SOURCE", "Offline model package escaped the managed inbox"
                ) from exc
            _extract_offline_archive(operation_id, manifest, archive, stage)
        else:
            raise ModelPackageOperationError(
                "INVALID_SOURCE", "Unsupported model package source"
            )
        _check_cancelled(operation_id)
        _atomic_install(operation_id, manifest, stage)
    finally:
        if stage.exists():
            _remove_path(stage)

    timestamp = _now()
    _set_install_state(
        manifest,
        "installed",
        verified_files=len(manifest.files),
        installed_size_bytes=manifest.install_size_bytes,
        error_code=None,
        error_message=None,
        installed_at=timestamp,
        verified_at=timestamp,
    )
    update_operation(
        operation_id,
        status="installed",
        progress=1.0,
        completed_bytes=manifest.install_size_bytes,
        error_code=None,
        error_message=None,
        completed_at=timestamp,
    )


def _run_verify(operation: dict, manifest: ModelPackageManifest) -> None:
    operation_id = operation["id"]
    target, storage_scope = package_target(manifest)
    if not target.is_dir():
        raise ModelPackageOperationError(
            "PACKAGE_NOT_INSTALLED", "Model package is not installed"
        )
    update_operation(
        operation_id,
        status="verifying",
        progress=0,
        total_bytes=manifest.install_size_bytes,
    )
    _set_install_state(manifest, "verifying")
    if verification_record_is_current(manifest, target):
        timestamp = _now()
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
            verified_at=timestamp,
        )
        update_operation(
            operation_id,
            status="verified",
            progress=1.0,
            completed_bytes=manifest.install_size_bytes,
            completed_at=timestamp,
            error_code=None,
            error_message=None,
        )
        return

    def progress(completed: int, total: int) -> None:
        _check_cancelled(operation_id)
        update_operation(
            operation_id,
            completed_bytes=completed,
            progress=completed / total,
        )

    issues = verify_package(manifest, target, progress=progress)
    if issues:
        _set_install_state(
            manifest,
            "repair_required",
            verified_files=len(manifest.files) - len(issues),
            installed_size_bytes=0,
            error_code="PACKAGE_INTEGRITY_FAILED",
            error_message="One or more model package files failed verification",
            verified_at=None,
        )
        raise ModelPackageOperationError(
            "PACKAGE_INTEGRITY_FAILED", "Installed model package failed verification"
        )
    write_verification_record(manifest, target)
    timestamp = _now()
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
        verified_at=timestamp,
    )
    update_operation(
        operation_id,
        status="verified",
        progress=1.0,
        completed_bytes=manifest.install_size_bytes,
        completed_at=timestamp,
        error_code=None,
        error_message=None,
    )


def _run_operation_safely(operation_id: str) -> None:
    operation = get_operation(operation_id)
    if operation is None:
        return
    try:
        manifest = get_manifest(
            operation["package_id"],
            operation["package_version"],
            sync=False,
        )
        if manifest.digest() != operation["manifest_digest"]:
            raise ModelPackageOperationError(
                "MANIFEST_CHANGED",
                "Trusted package manifest changed after the operation was created",
            )
        if operation["operation"] == "verify":
            _run_verify(operation, manifest)
        else:
            _run_install(operation, manifest)
    except _OperationCancelled:
        update_operation(
            operation_id,
            status="cancelled",
            error_code=None,
            error_message=None,
            completed_at=_now(),
        )
        if operation:
            manifest = get_manifest(
                operation["package_id"],
                operation["package_version"],
                sync=False,
            )
            target, _ = package_target(manifest)
            _set_install_state(
                manifest,
                "repair_required" if target.exists() else "install_available",
            )
    except (
        ModelPackageOperationError,
        ModelPackageRegistryError,
        ModelPackageVerificationError,
    ) as exc:
        update_operation(
            operation_id,
            status="failed",
            error_code=exc.code,
            error_message=exc.safe_message,
            completed_at=_now(),
        )
        try:
            manifest = get_manifest(
                operation["package_id"],
                operation["package_version"],
                sync=False,
            )
            target, _ = package_target(manifest)
            _set_install_state(
                manifest,
                "repair_required" if target.exists() else "failed",
                error_code=exc.code,
                error_message=exc.safe_message,
            )
        except (KeyError, ModelPackageVerificationError):
            pass
    except Exception:
        update_operation(
            operation_id,
            status="failed",
            error_code="PACKAGE_OPERATION_FAILED",
            error_message="Model package operation failed",
            completed_at=_now(),
        )
        try:
            manifest = get_manifest(
                operation["package_id"],
                operation["package_version"],
                sync=False,
            )
            target, _ = package_target(manifest)
            _set_install_state(
                manifest,
                "repair_required" if target.exists() else "failed",
                error_code="PACKAGE_OPERATION_FAILED",
                error_message="Model package operation failed",
            )
        except (KeyError, ModelPackageVerificationError):
            pass
    finally:
        with TASK_LOCK:
            ACTIVE_THREADS.pop(operation_id, None)


def uninstall_package(
    package_id: str,
    *,
    confirm_package_id: str,
    confirm_package_version: str,
) -> dict:
    sync_catalog()
    manifest = get_manifest(package_id, confirm_package_version, sync=False)
    if confirm_package_id != manifest.package_id:
        raise ModelPackageOperationError(
            "CONFIRMATION_MISMATCH", "Package removal confirmation did not match"
        )
    if manifest.core_required:
        raise ModelPackageOperationError(
            "CORE_PACKAGE_REQUIRED", "The default BGE-M3 core package cannot be removed"
        )
    target, storage_scope = package_target(manifest)
    if storage_scope != "managed":
        raise ModelPackageOperationError(
            "EXTERNAL_PACKAGE_NOT_REMOVABLE",
            "Externally managed model files cannot be removed by AetherDB",
        )
    _set_install_state(manifest, "uninstalling")
    if target.exists():
        root = managed_models_root()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ModelPackageOperationError(
                "UNSAFE_MODEL_ROOT", "Package removal target escaped managed storage"
            ) from exc
        quarantine = target.parent / f".aetherdb-uninstall-{uuid.uuid4().hex}"
        os.replace(target, quarantine)
        _remove_path(quarantine)
    return _set_install_state(
        manifest,
        "install_available",
        verified_files=0,
        installed_size_bytes=0,
        error_code=None,
        error_message=None,
        installed_at=None,
        verified_at=None,
    )


def set_package_enabled(package_id: str, enabled: bool) -> dict:
    sync_catalog()
    manifest = get_manifest(package_id, sync=False)
    installation = get_installation(package_id)
    if installation is None:
        raise KeyError(package_id)
    if not enabled:
        if manifest.core_required:
            raise ModelPackageOperationError(
                "CORE_PACKAGE_REQUIRED", "The default BGE-M3 core package cannot be disabled"
            )
        if installation["status"] != "installed":
            raise ModelPackageOperationError(
                "PACKAGE_NOT_INSTALLED", "Only installed model packages can be disabled"
            )
        return _set_install_state(manifest, "disabled")
    target, _ = package_target(manifest)
    if not verification_record_is_current(manifest, target):
        raise ModelPackageOperationError(
            "PACKAGE_VERIFICATION_REQUIRED",
            "Model package must be verified before it can be enabled",
        )
    return _set_install_state(
        manifest,
        "installed",
        verified_files=len(manifest.files),
        installed_size_bytes=manifest.install_size_bytes,
        error_code=None,
        error_message=None,
    )


def recover_interrupted_operations() -> None:
    sync_catalog()
    for operation in list_operations(100):
        if operation["status"] in ACTIVE_OPERATION_STATUSES:
            if operation["cancel_requested"]:
                update_operation(
                    operation["id"],
                    status="cancelled",
                    completed_at=_now(),
                )
            else:
                _start_thread(operation["id"])
