"""Persistent, verified downloads for separately installed Ollama releases."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse

import requests

from services.database_registry import _get_registry_conn
from services.ollama_installation import (
    OllamaInstallPlan,
    OllamaInstallationError,
    TrustedOllamaArtifact,
    resolve_install_plan,
)
from services.ollama_installer import (
    OllamaInstallerError,
    apply_post_discovery_addons,
    install_verified_plan,
)
from services.ollama_management import (
    OllamaManagementError,
    ensure_default_ollama_provider,
    find_ollama_executable,
    get_runtime_status,
    start_existing_runtime,
)


ACTIVE_STATUSES = {
    "checking",
    "awaiting_confirmation",
    "downloading",
    "verifying",
    "ready_to_launch",
    "launching_installer",
    "waiting_for_installer",
    "rediscovering",
    "service_starting",
    "api_verifying",
    "provider_registering",
    "ready",
}
REDIRECT_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
MAX_REDIRECTS = 5
CHUNK_SIZE = 1024 * 1024
_TASK_LOCK = threading.RLock()
_RESPONSE_LOCK = threading.RLock()
_ACTIVE_RESPONSES: dict[str, requests.Response] = {}


class OllamaInstallTaskError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


class _DownloadCancelled(RuntimeError):
    pass


def _row(operation_id: str) -> dict | None:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT * FROM ollama_install_operations WHERE id=?", (operation_id,)
        ).fetchone()
        return _serialize_row(dict(row)) if row else None
    finally:
        conn.close()


def _serialize_row(row: dict) -> dict:
    try:
        row["artifacts"] = json.loads(row.pop("artifacts_json"))
    except (KeyError, TypeError, ValueError):
        row["artifacts"] = []
        row.pop("artifacts_json", None)
    row["cancel_requested"] = bool(row.get("cancel_requested"))
    return row


def _update(operation_id: str, **updates) -> None:
    allowed = {
        "status",
        "progress",
        "completed_bytes",
        "total_bytes",
        "current_artifact_id",
        "artifacts_json",
        "cache_root",
        "status_message",
        "error_code",
        "provider_id",
        "launch_method",
        "cancel_requested",
    }
    clean = {key: value for key, value in updates.items() if key in allowed}
    if not clean:
        return
    columns = ",".join(f"{key}=?" for key in clean)
    conn = _get_registry_conn()
    try:
        conn.execute(
            f"UPDATE ollama_install_operations SET {columns},"
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (*clean.values(), operation_id),
        )
        conn.commit()
    finally:
        conn.close()


def _start_background_thread(target, args, name: str) -> None:
    threading.Thread(target=target, args=args, name=name, daemon=True).start()


def get_install_plan(*, accelerator: str | None = None) -> dict:
    try:
        return resolve_install_plan(accelerator=accelerator).to_dict()
    except OllamaInstallationError as exc:
        raise OllamaInstallTaskError(exc.code, exc.safe_message) from exc


def create_install_operation(*, accelerator: str | None = None) -> dict:
    try:
        plan = resolve_install_plan(accelerator=accelerator)
    except OllamaInstallationError as exc:
        raise OllamaInstallTaskError(exc.code, exc.safe_message) from exc

    artifacts_json = json.dumps(
        [
            {
                **_artifact_dict(artifact),
                "cache_path": str(Path(plan.cache_root) / artifact.filename),
                "verified": False,
            }
            for artifact in plan.artifacts
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    total_bytes = sum(artifact.size for artifact in plan.artifacts)
    with _TASK_LOCK:
        conn = _get_registry_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ollama_install_operations "
                "WHERE version=? AND platform=? AND architecture=? "
                "AND COALESCE(accelerator,'')=COALESCE(?,'') "
                "AND status IN ('checking','awaiting_confirmation','downloading',"
                "'verifying','ready_to_launch','launching_installer',"
                "'waiting_for_installer','rediscovering','service_starting',"
                "'api_verifying','provider_registering','ready') "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (plan.version, plan.platform, plan.architecture, plan.accelerator),
            ).fetchone()
            if existing:
                conn.commit()
                return _serialize_row(dict(existing))

            operation_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO ollama_install_operations "
                "(id,version,platform,architecture,accelerator,status,total_bytes,"
                "artifacts_json,cache_root,status_message) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    operation_id,
                    plan.version,
                    plan.platform,
                    plan.architecture,
                    plan.accelerator,
                    "awaiting_confirmation",
                    total_bytes,
                    artifacts_json,
                    plan.cache_root,
                    "Download requires explicit confirmation",
                ),
            )
            conn.commit()
        finally:
            conn.close()
    result = _row(operation_id)
    if result is None:
        raise OllamaInstallTaskError("CREATE_FAILED", "Install operation was not created")
    return result


def _artifact_dict(artifact: TrustedOllamaArtifact) -> dict:
    return {
        "id": artifact.id,
        "platform": artifact.platform,
        "architectures": list(artifact.architectures),
        "role": artifact.role,
        "install_type": artifact.install_type,
        "filename": artifact.filename,
        "url": artifact.url,
        "size": artifact.size,
        "sha256": artifact.sha256,
        "verification": list(artifact.verification),
        "requires_user_confirmation": artifact.requires_user_confirmation,
        "accelerator": artifact.accelerator,
    }


def get_install_operation(operation_id: str) -> dict | None:
    return _row(operation_id)


def list_install_operations(limit: int = 20) -> list[dict]:
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ollama_install_operations "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [_serialize_row(dict(row)) for row in rows]
    finally:
        conn.close()


def confirm_install_download(operation_id: str) -> dict:
    with _TASK_LOCK:
        operation = _row(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation["status"] in {"downloading", "verifying", "ready_to_launch"}:
            return operation
        if operation["status"] != "awaiting_confirmation":
            raise OllamaInstallTaskError(
                "CONFIRM_NOT_ALLOWED", "This install operation cannot be confirmed"
            )
        _update(
            operation_id,
            status="checking",
            status_message="Checking trusted release plan",
            error_code=None,
            cancel_requested=0,
        )
        _start_background_thread(
            _run_install_download,
            (operation_id,),
            f"ollama-install-{operation_id[:8]}",
        )
    result = _row(operation_id)
    if result is None:
        raise OllamaInstallTaskError("START_FAILED", "Install download was not started")
    return result


def cancel_install_operation(operation_id: str) -> dict:
    operation = _row(operation_id)
    if operation is None:
        raise KeyError(operation_id)
    if operation["status"] in {"failed", "cancelled", "ready_to_launch", "ready"}:
        if operation["status"] in {"ready_to_launch", "ready"}:
            raise OllamaInstallTaskError(
                "CANCEL_NOT_ALLOWED", "This install operation cannot be cancelled"
            )
        return operation
    if operation["status"] == "awaiting_confirmation":
        _update(
            operation_id,
            status="cancelled",
            status_message="Download cancelled before confirmation",
            cancel_requested=1,
        )
    else:
        _update(
            operation_id,
            status_message="Cancellation requested",
            cancel_requested=1,
        )
        with _RESPONSE_LOCK:
            response = _ACTIVE_RESPONSES.get(operation_id)
        if response is not None:
            response.close()
    return _row(operation_id) or operation


def launch_install_operation(operation_id: str, confirm_version: str) -> dict:
    with _TASK_LOCK:
        operation = _row(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation["status"] in {
            "launching_installer",
            "waiting_for_installer",
            "rediscovering",
            "service_starting",
            "api_verifying",
            "provider_registering",
            "ready",
        }:
            return operation
        if operation["status"] != "ready_to_launch":
            raise OllamaInstallTaskError(
                "LAUNCH_NOT_ALLOWED", "Install packages are not ready to launch"
            )
        if confirm_version != operation["version"]:
            raise OllamaInstallTaskError(
                "CONFIRMATION_MISMATCH",
                "Install confirmation does not match the pinned Ollama version",
            )
        _update(
            operation_id,
            status="launching_installer",
            status_message="Rechecking verified install packages",
            error_code=None,
            cancel_requested=0,
        )
        _start_background_thread(
            _run_install_launch,
            (operation_id,),
            f"ollama-launch-{operation_id[:8]}",
        )
    result = _row(operation_id)
    if result is None:
        raise OllamaInstallTaskError("LAUNCH_FAILED", "Install launch was not started")
    return result


def _cancel_requested(operation_id: str) -> bool:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM ollama_install_operations WHERE id=?",
            (operation_id,),
        ).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def _plan_for_operation(operation: dict) -> OllamaInstallPlan:
    try:
        plan = resolve_install_plan(
            system=operation["platform"],
            machine=operation["architecture"],
            accelerator=operation.get("accelerator"),
        )
    except OllamaInstallationError as exc:
        raise OllamaInstallTaskError(exc.code, exc.safe_message) from exc
    expected = [artifact.id for artifact in plan.artifacts]
    persisted = [artifact.get("id") for artifact in operation.get("artifacts", [])]
    if (
        plan.version != operation["version"]
        or expected != persisted
        or str(Path(plan.cache_root)) != str(Path(operation["cache_root"]))
    ):
        raise OllamaInstallTaskError(
            "PLAN_CHANGED", "Trusted install plan changed; create a new operation"
        )
    return plan


def _validate_redirect(source_url: str, location: str) -> str:
    target = urljoin(source_url, location)
    parsed = urlparse(target)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in REDIRECT_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise OllamaInstallTaskError(
            "REDIRECT_BLOCKED", "Release download redirected to an untrusted location"
        )
    return target


def _open_trusted_response(operation_id: str, artifact: TrustedOllamaArtifact):
    current_url = artifact.url
    for _ in range(MAX_REDIRECTS + 1):
        response = requests.get(
            current_url,
            headers={"Accept": "application/octet-stream", "User-Agent": "AetherDB"},
            stream=True,
            allow_redirects=False,
            timeout=(10, 120),
        )
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise OllamaInstallTaskError(
                    "INVALID_REDIRECT", "Release download returned an invalid redirect"
                )
            current_url = _validate_redirect(current_url, location)
            continue
        if not 200 <= response.status_code < 300:
            response.close()
            raise OllamaInstallTaskError(
                f"HTTP_{response.status_code}",
                f"Release server returned HTTP {response.status_code}",
            )
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                received_size = int(content_length)
            except ValueError:
                response.close()
                raise OllamaInstallTaskError(
                    "INVALID_CONTENT_LENGTH", "Release server returned an invalid size"
                )
            if received_size != artifact.size:
                response.close()
                raise OllamaInstallTaskError(
                    "SIZE_MISMATCH", "Release package size did not match the trusted manifest"
                )
        with _RESPONSE_LOCK:
            _ACTIVE_RESPONSES[operation_id] = response
        return response
    raise OllamaInstallTaskError(
        "TOO_MANY_REDIRECTS", "Release download exceeded the redirect limit"
    )


def _safe_target(cache_root: Path, filename: str) -> Path:
    cache_root.mkdir(parents=True, exist_ok=True)
    root = cache_root.resolve()
    target = (root / filename).resolve()
    if target.parent != root:
        raise OllamaInstallTaskError("UNSAFE_PATH", "Unsafe release package path")
    return target


def _download_artifact(
    operation_id: str,
    artifact: TrustedOllamaArtifact,
    target: Path,
    completed_before: int,
    total_bytes: int,
) -> None:
    part_path = target.with_name(f"{target.name}.{operation_id}.part")
    part_path.unlink(missing_ok=True)
    digest = hashlib.sha256()
    completed = 0
    response = None
    try:
        response = _open_trusted_response(operation_id, artifact)
        with part_path.open("xb") as output:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if _cancel_requested(operation_id):
                    raise _DownloadCancelled()
                if not chunk:
                    continue
                completed += len(chunk)
                if completed > artifact.size:
                    raise OllamaInstallTaskError(
                        "SIZE_MISMATCH",
                        "Release package exceeded the trusted manifest size",
                    )
                output.write(chunk)
                digest.update(chunk)
                aggregate = completed_before + completed
                _update(
                    operation_id,
                    completed_bytes=aggregate,
                    progress=min(1.0, aggregate / total_bytes) if total_bytes else 0.0,
                )
            output.flush()
            os.fsync(output.fileno())
        if completed != artifact.size:
            raise OllamaInstallTaskError(
                "SIZE_MISMATCH", "Release package size did not match the trusted manifest"
            )
        if digest.hexdigest().lower() != artifact.sha256.lower():
            raise OllamaInstallTaskError(
                "SHA256_MISMATCH", "Release package checksum verification failed"
            )
        if _cancel_requested(operation_id):
            raise _DownloadCancelled()
        os.replace(part_path, target)
    finally:
        with _RESPONSE_LOCK:
            _ACTIVE_RESPONSES.pop(operation_id, None)
        if response is not None:
            response.close()
        part_path.unlink(missing_ok=True)


def _file_matches_manifest(path: Path, artifact: TrustedOllamaArtifact) -> bool:
    if not path.is_file() or path.stat().st_size != artifact.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == artifact.sha256.lower()


def _safe_archive_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    trimmed = normalized.rstrip("/")
    raw_parts = trimmed.split("/") if trimmed else []
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    return bool(raw_parts) and not normalized.startswith("/") and all(
        part not in {"", ".", ".."}
        and "\x00" not in part
        and ":" not in part
        and part.rstrip(" .").split(".", 1)[0].upper() not in reserved
        for part in raw_parts
    )


def _verify_zip_archive(
    path: Path, *, require_ollama_executable: bool, verify_pe: bool
) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not members or any(not _safe_archive_member(item.filename) for item in members):
                raise OllamaInstallTaskError(
                    "ARCHIVE_LAYOUT_INVALID", "Release archive contains an unsafe path"
                )
            if any(((item.external_attr >> 16) & 0o170000) == 0o120000 for item in members):
                raise OllamaInstallTaskError(
                    "ARCHIVE_LAYOUT_INVALID", "Release archive contains a symbolic link"
                )
            executable = next(
                (item for item in members if PurePosixPath(item.filename).name.lower() == "ollama.exe"),
                None,
            )
            if require_ollama_executable and executable is None:
                raise OllamaInstallTaskError(
                    "ARCHIVE_LAYOUT_INVALID", "Release archive does not contain ollama.exe"
                )
            if verify_pe and executable is not None:
                with tempfile.TemporaryDirectory(dir=path.parent) as temp_dir:
                    extracted = Path(temp_dir) / "ollama.exe"
                    with archive.open(executable) as source, extracted.open("xb") as output:
                        while chunk := source.read(CHUNK_SIZE):
                            output.write(chunk)
                    _verify_windows_authenticode(extracted)
    except zipfile.BadZipFile as exc:
        raise OllamaInstallTaskError(
            "ARCHIVE_LAYOUT_INVALID", "Release archive could not be opened"
        ) from exc


def _verify_tar_zstd_archive(path: Path, *, require_ollama_executable: bool) -> None:
    try:
        result = subprocess.run(
            ["tar", "--list", "--zstd", "--file", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaInstallTaskError(
            "ARCHIVE_VERIFIER_UNAVAILABLE", "System archive verifier is unavailable"
        ) from exc
    if result.returncode != 0:
        raise OllamaInstallTaskError(
            "ARCHIVE_LAYOUT_INVALID", "Release archive failed its layout check"
        )
    names = result.stdout.splitlines()
    if (
        not names
        or sum(len(name) for name in names) > 4 * 1024 * 1024
        or any(not _safe_archive_member(name) for name in names)
        or (
            require_ollama_executable
            and not any(PurePosixPath(name).name == "ollama" for name in names)
        )
    ):
        raise OllamaInstallTaskError(
            "ARCHIVE_LAYOUT_INVALID", "Release archive contains an invalid layout"
        )


def _verify_windows_authenticode(path: Path) -> None:
    if os.name != "nt":
        raise OllamaInstallTaskError(
            "SIGNATURE_VERIFIER_UNAVAILABLE", "Windows signature verifier is unavailable"
        )
    import ctypes

    system_directory = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(
        system_directory, len(system_directory)
    )
    if not length or length >= len(system_directory):
        raise OllamaInstallTaskError(
            "SIGNATURE_VERIFIER_UNAVAILABLE", "Windows signature verifier is unavailable"
        )
    powershell = (
        Path(system_directory.value)
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        raise OllamaInstallTaskError(
            "SIGNATURE_VERIFIER_UNAVAILABLE", "Windows signature verifier is unavailable"
        )
    environment = os.environ.copy()
    environment["AETHERDB_VERIFY_PATH"] = str(path)
    command = (
        "$signature = Get-AuthenticodeSignature -LiteralPath "
        "$env:AETHERDB_VERIFY_PATH; "
        "if ($signature.Status -eq 'Valid') { exit 0 }; exit 1"
    )
    try:
        result = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaInstallTaskError(
            "SIGNATURE_VERIFIER_UNAVAILABLE", "Windows signature verifier is unavailable"
        ) from exc
    if result.returncode != 0:
        raise OllamaInstallTaskError(
            "SIGNATURE_INVALID", "Release package Authenticode verification failed"
        )


def _run_fixed_verifier(arguments: list[str], code: str, message: str) -> None:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaInstallTaskError(code, message) from exc
    if result.returncode != 0:
        raise OllamaInstallTaskError(code, message)


def _verify_platform_artifact(path: Path, artifact: TrustedOllamaArtifact) -> None:
    checks = set(artifact.verification)
    if artifact.platform == "windows":
        if artifact.install_type == "native_installer":
            _verify_windows_authenticode(path)
        else:
            is_primary = artifact.role == "primary"
            _verify_zip_archive(
                path,
                require_ollama_executable=is_primary,
                verify_pe=is_primary,
            )
        return
    if artifact.platform == "macos":
        if sys.platform != "darwin":
            raise OllamaInstallTaskError(
                "SIGNATURE_VERIFIER_UNAVAILABLE", "macOS signature verifier is unavailable"
            )
        if "codesign" in checks:
            _run_fixed_verifier(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(path)],
                "SIGNATURE_INVALID",
                "Release package code signature verification failed",
            )
        if "notarization" in checks:
            _run_fixed_verifier(
                ["/usr/sbin/spctl", "--assess", "--type", "install", str(path)],
                "NOTARIZATION_INVALID",
                "Release package notarization verification failed",
            )
        return
    if artifact.platform == "linux":
        _verify_tar_zstd_archive(
            path, require_ollama_executable=artifact.role == "primary"
        )
        return
    raise OllamaInstallTaskError(
        "UNSUPPORTED_PLATFORM", "Unsupported operating system"
    )


def _mark_artifact_verified(operation_id: str, artifact_id: str) -> None:
    operation = _row(operation_id)
    if operation is None:
        return
    artifacts = operation.get("artifacts", [])
    for item in artifacts:
        if item.get("id") == artifact_id:
            item["verified"] = True
    _update(
        operation_id,
        artifacts_json=json.dumps(artifacts, ensure_ascii=True, separators=(",", ":")),
    )


def _verify_ready_artifacts(plan: OllamaInstallPlan) -> None:
    for artifact in plan.artifacts:
        target = _safe_target(Path(plan.cache_root), artifact.filename)
        if not _file_matches_manifest(target, artifact):
            raise OllamaInstallTaskError(
                "VERIFICATION_FAILED",
                "Install package no longer matches the trusted manifest",
            )
        _verify_platform_artifact(target, artifact)


def _raise_if_install_cancelled(operation_id: str) -> None:
    if _cancel_requested(operation_id):
        raise _DownloadCancelled()


def wait_for_ollama_executable(operation_id: str, timeout: float = 10 * 60) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _raise_if_install_cancelled(operation_id)
        executable = find_ollama_executable()
        if executable is not None:
            return executable
        time.sleep(0.5)
    raise OllamaInstallTaskError(
        "RUNTIME_NOT_DETECTED", "Ollama was not detected after installation"
    )


def _run_install_launch(operation_id: str) -> None:
    operation = _row(operation_id)
    if operation is None:
        return
    try:
        _raise_if_install_cancelled(operation_id)
        plan = _plan_for_operation(operation)
        _verify_ready_artifacts(plan)
        _update(
            operation_id,
            status="waiting_for_installer",
            status_message="Waiting for the official installation action",
        )
        action = install_verified_plan(plan)
        _update(operation_id, launch_method=action.method)
        _raise_if_install_cancelled(operation_id)
        _update(
            operation_id,
            status="rediscovering",
            status_message="Rediscovering the separately installed Ollama runtime",
        )
        executable = wait_for_ollama_executable(operation_id)
        apply_post_discovery_addons(plan, executable, action)
        _raise_if_install_cancelled(operation_id)
        _update(
            operation_id,
            status="service_starting",
            status_message="Starting or reconnecting to the Ollama service",
        )
        runtime = start_existing_runtime()
        if not runtime.get("running"):
            error = runtime.get("error") or {}
            raise OllamaInstallTaskError(
                str(error.get("code") or "SERVICE_UNREACHABLE"),
                str(error.get("message") or "Ollama service is unreachable"),
            )
        _update(
            operation_id,
            status="api_verifying",
            status_message="Verifying the Ollama API",
        )
        verified = get_runtime_status()
        if not verified.get("running") or not verified.get("api_compatible"):
            raise OllamaInstallTaskError(
                "API_VERIFICATION_FAILED", "Ollama API verification failed"
            )
        _update(
            operation_id,
            status="provider_registering",
            status_message="Registering the local Ollama Provider",
        )
        provider = ensure_default_ollama_provider()
        _update(
            operation_id,
            status="ready",
            progress=1.0,
            provider_id=provider["id"],
            current_artifact_id=None,
            status_message="Ollama is ready; no model is selected automatically",
            error_code=None,
        )
    except _DownloadCancelled:
        _update(
            operation_id,
            status="cancelled",
            status_message="Installation wait cancelled; external installers were not terminated",
            error_code="INSTALLER_CANCELLED",
            current_artifact_id=None,
        )
    except (OllamaInstallTaskError, OllamaInstallerError, OllamaManagementError) as exc:
        _update(
            operation_id,
            status="failed",
            status_message=exc.safe_message,
            error_code=exc.code,
            current_artifact_id=None,
        )
    except Exception:
        _update(
            operation_id,
            status="failed",
            status_message="Ollama installation failed unexpectedly",
            error_code="INTERNAL_ERROR",
            current_artifact_id=None,
        )


def _run_install_download(operation_id: str) -> None:
    operation = _row(operation_id)
    if operation is None:
        return
    try:
        if _cancel_requested(operation_id):
            raise _DownloadCancelled()
        plan = _plan_for_operation(operation)
        cache_root = Path(plan.cache_root)
        total_bytes = sum(artifact.size for artifact in plan.artifacts)
        completed_before = 0
        for artifact in plan.artifacts:
            if _cancel_requested(operation_id):
                raise _DownloadCancelled()
            target = _safe_target(cache_root, artifact.filename)
            _update(
                operation_id,
                status="downloading",
                current_artifact_id=artifact.id,
                status_message=f"Downloading {artifact.filename}",
                completed_bytes=completed_before,
                progress=completed_before / total_bytes if total_bytes else 0.0,
            )
            if not _file_matches_manifest(target, artifact):
                target.unlink(missing_ok=True)
                _download_artifact(
                    operation_id, artifact, target, completed_before, total_bytes
                )
            _update(
                operation_id,
                status="verifying",
                status_message=f"Verifying {artifact.filename}",
            )
            if not _file_matches_manifest(target, artifact):
                target.unlink(missing_ok=True)
                raise OllamaInstallTaskError(
                    "SHA256_MISMATCH", "Release package checksum verification failed"
                )
            _verify_platform_artifact(target, artifact)
            _mark_artifact_verified(operation_id, artifact.id)
            completed_before += artifact.size
            _update(
                operation_id,
                completed_bytes=completed_before,
                progress=completed_before / total_bytes if total_bytes else 1.0,
            )
        _update(
            operation_id,
            status="ready_to_launch",
            progress=1.0,
            completed_bytes=total_bytes,
            current_artifact_id=None,
            status_message="Trusted release packages are verified and ready",
            error_code=None,
        )
    except _DownloadCancelled:
        _update(
            operation_id,
            status="cancelled",
            status_message="Download cancelled",
            error_code=None,
            current_artifact_id=None,
        )
    except OllamaInstallTaskError as exc:
        _update(
            operation_id,
            status="failed",
            status_message=exc.safe_message,
            error_code=exc.code,
            current_artifact_id=None,
        )
    except requests.Timeout:
        _update(
            operation_id,
            status="failed",
            status_message="Release download timed out",
            error_code="TIMEOUT",
            current_artifact_id=None,
        )
    except requests.RequestException:
        if _cancel_requested(operation_id):
            _update(
                operation_id,
                status="cancelled",
                status_message="Download cancelled",
                error_code=None,
                current_artifact_id=None,
            )
            return
        _update(
            operation_id,
            status="failed",
            status_message="Release download connection failed",
            error_code="CONNECTION_FAILED",
            current_artifact_id=None,
        )
    except Exception:
        _update(
            operation_id,
            status="failed",
            status_message="Release download failed unexpectedly",
            error_code="INTERNAL_ERROR",
            current_artifact_id=None,
        )


def recover_interrupted_install_operations() -> None:
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE ollama_install_operations SET status='failed',"
            "error_code='INTERRUPTED',"
            "status_message='Download interrupted by application restart',"
            "current_artifact_id=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('checking','downloading','verifying',"
            "'launching_installer','waiting_for_installer','rediscovering',"
            "'service_starting','api_verifying','provider_registering')"
        )
        conn.commit()
    finally:
        conn.close()
