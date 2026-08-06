"""Ollama runtime discovery and fixed-action lifecycle management."""

from __future__ import annotations

import os
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.config import get_runtime_path
from services.database_registry import _get_registry_conn
from services.model_management import (
    ModelDiagnosticError,
    _credential_headers,
    _request_json,
    _validate_runtime_target,
)
from services.model_registry import (
    LOCAL_PROVIDER_TYPES,
    create_provider,
    create_model_profile,
    get_provider,
    list_model_profiles,
    list_providers,
    update_provider,
)
from services.ollama_observability import (
    list_external_resource_occupancy,
    mark_unseen_models,
    record_model_observation,
    record_runtime_observation,
    runtime_id_for,
)


TARGET_OLLAMA_VERSION = "0.32.0"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
_PROCESS_LOCK = threading.RLock()
_MANAGED_PROCESS: subprocess.Popen | None = None
_OPERATION_LOCK = threading.RLock()
_OPERATION_RESPONSE_LOCK = threading.RLock()
_ACTIVE_OPERATION_RESPONSES: dict[str, requests.Response] = {}
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class OllamaManagementError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


class _OperationCancelled(RuntimeError):
    pass


def _resolve_provider(provider_id: str | None = None) -> dict:
    if provider_id:
        provider = get_provider(provider_id)
        if not provider:
            raise KeyError(provider_id)
        if provider["provider_type"] not in LOCAL_PROVIDER_TYPES:
            raise OllamaManagementError(
                "NOT_OLLAMA_PROVIDER", "Provider is not a local Ollama runtime"
            )
        return provider
    return {
        "id": None,
        "display_name": "Local Ollama",
        "provider_type": "local_ollama",
        "base_url": DEFAULT_BASE_URL,
        "api_format": "ollama_chat",
        "credential_ref": None,
        "models_endpoint": "/api/tags",
    }


def _version_tuple(version: str):
    values = []
    for part in version.lstrip("v").split(".")[:3]:
        digits = "".join(character for character in part if character.isdigit())
        values.append(int(digits or 0))
    return tuple((values + [0, 0, 0])[:3])


def _compatibility(version: str):
    current = _version_tuple(version)
    target = _version_tuple(TARGET_OLLAMA_VERSION)
    if current == target:
        return "tested_target"
    if current > target:
        return "newer_api_unverified"
    return "backward_compatible_api"


def find_ollama_executable() -> Path | None:
    candidates = []
    from_path = shutil.which("ollama")
    if from_path:
        candidates.append(Path(from_path))
    if os.name == "nt":
        for variable in ("LOCALAPPDATA", "ProgramFiles"):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / "Programs" / "Ollama" / "ollama.exe")
                candidates.append(Path(root) / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        candidates.extend(
            [
                Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                Path.home() / "Applications/Ollama.app/Contents/Resources/ollama",
                Path("/opt/homebrew/bin/ollama"),
                Path("/usr/local/bin/ollama"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/local/bin/ollama"),
                Path("/usr/bin/ollama"),
                Path.home() / ".local/bin/ollama",
            ]
        )

    managed_parent = get_runtime_path("app_data", "external", "ollama")
    if managed_parent.is_dir():
        executable_name = "ollama.exe" if os.name == "nt" else "ollama"
        for managed_root in sorted(managed_parent.iterdir(), reverse=True):
            if managed_root.is_dir() and not managed_root.is_symlink():
                candidates.append(managed_root / executable_name)
                candidates.append(managed_root / "bin" / executable_name)

    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and resolved.name.lower() in {"ollama", "ollama.exe"}:
            return resolved
    return None


def ensure_default_ollama_provider() -> dict:
    matching = next(
        (
            provider
            for provider in list_providers()
            if provider["provider_type"] in LOCAL_PROVIDER_TYPES
            and provider["base_url"].rstrip("/") == DEFAULT_BASE_URL
        ),
        None,
    )
    if matching:
        provider = update_provider(
            matching["id"],
            {
                "enabled": True,
                "api_format": "ollama_chat",
                "models_endpoint": "/api/tags",
                "supports_model_discovery": True,
            },
        )
    else:
        provider_id = "ollama-local-default"
        occupied = get_provider(provider_id)
        if occupied:
            raise OllamaManagementError(
                "PROVIDER_ID_CONFLICT",
                "The default Ollama Provider id is already in use",
            )
        provider = create_provider(
            {
                "id": provider_id,
                "display_name": "Local Ollama",
                "provider_type": "local_ollama",
                "base_url": DEFAULT_BASE_URL,
                "api_format": "ollama_chat",
                "credential_ref": None,
                "models_endpoint": "/api/tags",
                "enabled": True,
                "supports_model_discovery": True,
            }
        )
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE model_providers SET health_status='healthy',"
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (provider["id"],),
        )
        conn.commit()
    finally:
        conn.close()
    return get_provider(provider["id"])


def _is_managed_running() -> bool:
    with _PROCESS_LOCK:
        return _MANAGED_PROCESS is not None and _MANAGED_PROCESS.poll() is None


def _safe_model(
    item: dict,
    loaded_by_name: dict[str, dict],
    profile_by_name: dict,
    observation: dict | None = None,
):
    name = str(item.get("name") or item.get("model") or "")
    loaded = loaded_by_name.get(name) or loaded_by_name.get(
        str(item.get("model") or "")
    )
    details = {
        **(item.get("details") or {}),
        **((loaded or {}).get("details") or {}),
    }
    profile = profile_by_name.get(name) or profile_by_name.get(str(item.get("model") or ""))
    remote_status = profile.get("remote_status") if profile else None
    return {
        "name": name,
        "model": str(item.get("model") or name),
        "digest": str(item.get("digest") or ""),
        "size": int(item.get("size") or 0),
        "modified_at": item.get("modified_at"),
        "format": details.get("format"),
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "quantization_level": details.get("quantization_level"),
        "installed": True,
        "loaded": loaded is not None,
        "size_vram": int((loaded or {}).get("size_vram") or 0),
        "context_length": (loaded or {}).get("context_length"),
        "expires_at": (loaded or {}).get("expires_at"),
        "model_profile_id": profile.get("id") if profile else None,
        "enabled": bool(profile.get("enabled")) if profile else False,
        "deployment_boundary": "external_ollama",
        "native_package_managed": False,
        "discovery_status": (
            observation.get("discovery_status")
            if observation
            else "DETECTED"
        ),
        "previous_digest": (
            observation.get("previous_digest") if observation else None
        ),
        "reported_capabilities": (
            observation.get("reported_capabilities") if observation else []
        ),
        "capability_status": (
            "reported"
            if remote_status == "available"
            else "unverified"
            if remote_status == "available_unverified"
            else "not_registered"
        ),
    }


def _profile_id(provider_id: str, model_name: str) -> str:
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:20]
    return f"{provider_id}:ollama:{digest}"


def _capability_profile(show_payload: dict | None) -> dict:
    if not isinstance(show_payload, dict):
        return {
            "model_type": "text",
            "context_length": None,
            "supports_streaming": False,
            "supports_tools": False,
            "supports_json_mode": False,
            "known": False,
        }
    capabilities = {
        str(value).strip().lower()
        for value in show_payload.get("capabilities", [])
        if isinstance(value, str) and len(value) <= 64
    }
    model_info = show_payload.get("model_info")
    context_lengths = []
    if isinstance(model_info, dict):
        for key, value in model_info.items():
            if str(key).endswith(".context_length") and isinstance(value, int):
                if 0 < value <= 10_000_000:
                    context_lengths.append(value)
    known = bool(capabilities)
    return {
        "model_type": "embedding" if "embedding" in capabilities else "text",
        "context_length": max(context_lengths) if context_lengths else None,
        "supports_streaming": "completion" in capabilities,
        "supports_tools": "tools" in capabilities,
        "supports_json_mode": False,
        "known": known,
    }


def _upsert_synced_profile(
    provider_id: str,
    model_name: str,
    capability: dict,
    *,
    tag_payload: dict | None = None,
    show_payload: dict | None = None,
) -> dict:
    existing = next(
        (
            profile
            for profile in list_model_profiles(provider_id)
            if profile["provider_model_name"] == model_name
        ),
        None,
    )
    created_new = existing is None
    if existing is None:
        try:
            existing = create_model_profile(
                {
                    "id": _profile_id(provider_id, model_name),
                    "provider_id": provider_id,
                    "provider_model_name": model_name,
                    "display_name": model_name,
                    "model_type": capability["model_type"],
                    "enabled": False,
                    "context_length": capability["context_length"],
                    "supports_streaming": capability["supports_streaming"],
                    "supports_tools": capability["supports_tools"],
                    "supports_json_mode": capability["supports_json_mode"],
                    "cost_level": "local",
                    "privacy_level": "local_only",
                }
            )
        except sqlite3.IntegrityError:
            existing = next(
                profile
                for profile in list_model_profiles(provider_id)
                if profile["provider_model_name"] == model_name
            )
    # Presence in /api/tags proves that Ollama has the user-deployed model. A
    # failed or older /api/show response means capabilities are unverified, not
    # that AetherDB should reject a model the user explicitly selected.
    remote_status = "available" if capability["known"] else "available_unverified"
    conn = _get_registry_conn()
    try:
        if capability["known"] or created_new:
            conn.execute(
                "UPDATE model_profiles SET model_type=?,context_length=?,"
                "supports_streaming=?,supports_tools=?,supports_json_mode=?,"
                "health_status='unknown',remote_status=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (
                    capability["model_type"],
                    capability["context_length"],
                    int(capability["supports_streaming"]),
                    int(capability["supports_tools"]),
                    int(capability["supports_json_mode"]),
                    remote_status,
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                "UPDATE model_profiles SET health_status='unknown',remote_status=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (remote_status, existing["id"]),
            )
        conn.commit()
    finally:
        conn.close()
    profile = next(
        profile
        for profile in list_model_profiles(provider_id)
        if profile["id"] == existing["id"]
    )
    provider = _resolve_provider(provider_id)
    observation = record_model_observation(
        provider,
        model_name,
        tag_payload=tag_payload,
        show_payload=show_payload,
        profile=profile,
    )
    if observation["discovery_status"] == "DIGEST_CHANGED":
        conn = _get_registry_conn()
        try:
            conn.execute(
                "UPDATE model_profiles SET health_status='unknown',"
                "remote_status='available_unverified',updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (profile["id"],),
            )
            conn.commit()
        finally:
            conn.close()
        profile = next(
            item
            for item in list_model_profiles(provider_id)
            if item["id"] == profile["id"]
        )
    return {**profile, "ollama_observation": observation}


def sync_ollama_model_profile(
    provider_id: str,
    model_name: str,
    *,
    tag_payload: dict | None = None,
) -> dict:
    _validate_model_name(model_name)
    provider = _resolve_provider(provider_id)
    try:
        show_payload = _request_json(
            provider,
            "POST",
            "/api/show",
            {"model": model_name, "verbose": False},
        )
    except ModelDiagnosticError:
        show_payload = None
    capability = _capability_profile(show_payload)
    return _upsert_synced_profile(
        provider_id,
        model_name,
        capability,
        tag_payload=tag_payload,
        show_payload=show_payload,
    )


def sync_ollama_model_profiles(provider_id: str) -> dict:
    provider = _resolve_provider(provider_id)
    payload = _request_json(provider, "GET", "/api/tags")
    raw_models = payload.get("models", [])
    if not isinstance(raw_models, list):
        raise OllamaManagementError(
            "INVALID_RESPONSE", "Ollama returned an invalid model list"
        )
    names = []
    profiles = []
    truncated = len(raw_models) > 500
    for item in raw_models[:500]:
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("name") or item.get("model") or "")
        try:
            _validate_model_name(model_name)
        except OllamaManagementError:
            continue
        if model_name in names:
            continue
        names.append(model_name)
        profiles.append(
            sync_ollama_model_profile(
                provider_id,
                model_name,
                tag_payload=item,
            )
        )

    conn = _get_registry_conn()
    try:
        if truncated:
            pass
        elif names:
            placeholders = ",".join("?" for _ in names)
            conn.execute(
                "UPDATE model_profiles SET enabled=0,health_status='unknown',"
                "remote_status='missing',updated_at=CURRENT_TIMESTAMP "
                f"WHERE provider_id=? AND provider_model_name NOT IN ({placeholders})",
                (provider_id, *names),
            )
        else:
            conn.execute(
                "UPDATE model_profiles SET enabled=0,health_status='unknown',"
                "remote_status='missing',updated_at=CURRENT_TIMESTAMP WHERE provider_id=?",
                (provider_id,),
            )
        conn.commit()
    finally:
        conn.close()
    mark_unseen_models(provider, names, complete=not truncated)
    return {
        "provider_id": provider_id,
        "installed_model_count": len(names),
        "profiles": profiles,
    }


def get_runtime_status(provider_id: str | None = None):
    provider = _resolve_provider(provider_id)
    executable = find_ollama_executable()
    ownership = "aetherdb_managed" if _is_managed_running() else "external"
    runtime_id = runtime_id_for(provider)
    try:
        version_payload = _request_json(provider, "GET", "/api/version")
        version = str(version_payload.get("version") or "unknown")
        installed_payload = _request_json(provider, "GET", "/api/tags")
        loaded_payload = _request_json(provider, "GET", "/api/ps")
        raw_installed = installed_payload.get("models", [])
        raw_loaded = loaded_payload.get("models", [])
        if not isinstance(raw_installed, list) or not isinstance(raw_loaded, list):
            raise OllamaManagementError(
                "INVALID_RESPONSE",
                "Ollama returned an invalid model or process list",
            )
        loaded_by_name = {}
        for item in raw_loaded[:500]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "")
            if name:
                loaded_by_name[name] = item
        profile_by_name = {
            profile["provider_model_name"]: profile
            for profile in list_model_profiles(provider_id)
        } if provider_id else {}
        models = []
        observed_names = []
        for item in raw_installed[:500]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "")
            try:
                _validate_model_name(name)
            except OllamaManagementError:
                continue
            if name in observed_names:
                continue
            observed_names.append(name)
            profile = profile_by_name.get(name)
            observation = record_model_observation(
                provider,
                name,
                tag_payload=item,
                loaded_payload=loaded_by_name.get(name, {}),
                profile=profile,
            )
            models.append(
                _safe_model(
                    item,
                    loaded_by_name,
                    profile_by_name,
                    observation,
                )
            )
        mark_unseen_models(
            provider,
            observed_names,
            complete=len(raw_installed) <= 500,
        )
        runtime_observation = record_runtime_observation(
            provider,
            ownership=ownership,
            state="ready",
            installed=executable is not None,
            running=True,
            api_compatible=True,
            version=version,
            compatibility=_compatibility(version),
        )
        return {
            "protocol_version": "1.0",
            "runtime_id": runtime_id,
            "provider_id": provider_id,
            "base_url": provider["base_url"],
            "installed": executable is not None,
            "running": True,
            "managed": _is_managed_running(),
            "ownership": ownership,
            "version": version,
            "target_version": TARGET_OLLAMA_VERSION,
            "compatibility": _compatibility(version),
            "api_compatible": True,
            "installed_model_count": len(models),
            "loaded_model_count": sum(1 for item in models if item["loaded"]),
            "models": models,
            "runtime_observation": runtime_observation,
            "external_occupancy": (
                [
                    item
                    for item in list_external_resource_occupancy()
                    if item.get("runtime_id") == runtime_id
                ]
                if ownership == "external"
                else []
            ),
            "error": None,
        }
    except (ModelDiagnosticError, OllamaManagementError) as exc:
        error = {"code": exc.code, "message": exc.safe_message}
        runtime_observation = record_runtime_observation(
            provider,
            ownership=ownership,
            state="unavailable",
            installed=executable is not None,
            running=False,
            api_compatible=False,
            version=None,
            compatibility="unavailable",
            error=error,
        )
        return {
            "protocol_version": "1.0",
            "runtime_id": runtime_id,
            "provider_id": provider_id,
            "base_url": provider["base_url"],
            "installed": executable is not None,
            "running": False,
            "managed": _is_managed_running(),
            "ownership": ownership,
            "version": None,
            "target_version": TARGET_OLLAMA_VERSION,
            "compatibility": "unavailable",
            "api_compatible": False,
            "installed_model_count": 0,
            "loaded_model_count": 0,
            "models": [],
            "runtime_observation": runtime_observation,
            "external_occupancy": [],
            "error": error,
        }


def _loopback_host(provider: dict):
    parsed = urlparse(provider["base_url"])
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise OllamaManagementError(
            "REMOTE_START_BLOCKED", "Only a loopback Ollama runtime can be started locally"
        )
    return parsed


def start_existing_runtime(provider_id: str | None = None):
    global _MANAGED_PROCESS
    provider = _resolve_provider(provider_id)
    current = get_runtime_status(provider_id)
    if current["running"]:
        return current

    executable = find_ollama_executable()
    if executable is None:
        raise OllamaManagementError(
            "OLLAMA_NOT_INSTALLED", "No existing Ollama installation was found"
        )
    parsed = _loopback_host(provider)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = f"{host}:{port}"
    managed_parent = get_runtime_path("app_data", "external", "ollama").resolve()
    try:
        executable.resolve().relative_to(managed_parent)
    except ValueError:
        pass
    else:
        install_root = executable.parent.parent if executable.parent.name == "bin" else executable.parent
        library_root = install_root / "lib" / "ollama"
        if library_root.is_dir():
            variable = "PATH" if os.name == "nt" else "LD_LIBRARY_PATH"
            previous = environment.get(variable, "")
            environment[variable] = str(library_root) + (os.pathsep + previous if previous else "")
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    with _PROCESS_LOCK:
        if _MANAGED_PROCESS is not None and _MANAGED_PROCESS.poll() is None:
            return get_runtime_status(provider_id)
        _MANAGED_PROCESS = subprocess.Popen(
            [str(executable), "serve"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with _PROCESS_LOCK:
            process = _MANAGED_PROCESS
        if process is None or process.poll() is not None:
            shutdown_managed_runtime()
            raise OllamaManagementError(
                "OLLAMA_START_FAILED", "Ollama exited before becoming ready"
            )
        status = get_runtime_status(provider_id)
        if status["running"]:
            return status
        time.sleep(0.25)

    shutdown_managed_runtime()
    raise OllamaManagementError(
        "OLLAMA_START_TIMEOUT", "Ollama did not become ready within 20 seconds"
    )


def shutdown_managed_runtime():
    global _MANAGED_PROCESS
    with _PROCESS_LOCK:
        process = _MANAGED_PROCESS
        _MANAGED_PROCESS = None
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def stop_managed_runtime(provider_id: str | None = None):
    if not _is_managed_running():
        raise OllamaManagementError(
            "EXTERNAL_RUNTIME_CONTROL_BLOCKED",
            "AetherDB cannot stop an Ollama runtime it did not start",
        )
    shutdown_managed_runtime()
    status = get_runtime_status(provider_id)
    return {
        "stopped": not status["running"],
        "runtime_id": status["runtime_id"],
        "ownership": status["ownership"],
        "runtime": status,
    }


def _validate_model_name(model_name: str):
    if not MODEL_NAME_PATTERN.fullmatch(model_name):
        raise OllamaManagementError("INVALID_MODEL_NAME", "Invalid Ollama model name")


def _operation_row(operation_id: str):
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT * FROM ollama_operations WHERE id=?", (operation_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["cancel_requested"] = bool(result.get("cancel_requested"))
        return result
    finally:
        conn.close()


def _update_operation(operation_id: str, **updates):
    allowed = {
        "status",
        "progress",
        "completed_bytes",
        "total_bytes",
        "status_message",
        "error_code",
        "cancel_requested",
    }
    clean = {key: value for key, value in updates.items() if key in allowed}
    if not clean:
        return
    columns = ",".join(f"{key}=?" for key in clean)
    conn = _get_registry_conn()
    try:
        conn.execute(
            f"UPDATE ollama_operations SET {columns},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (*clean.values(), operation_id),
        )
        conn.commit()
    finally:
        conn.close()


def _normalize_pull_status(value) -> str:
    status = str(value or "").lower()
    if status == "success":
        return "success"
    if "verif" in status:
        return "verifying"
    if "manifest" in status:
        return "manifest"
    if "pull" in status or "download" in status:
        return "downloading"
    if "write" in status:
        return "finalizing"
    return "working"


def _start_background_thread(target, args, name):
    threading.Thread(target=target, args=args, name=name, daemon=True).start()


def _run_pull_operation(operation_id: str):
    operation = _operation_row(operation_id)
    if not operation:
        return
    provider = _resolve_provider(operation["provider_id"])
    if operation.get("cancel_requested"):
        _update_operation(
            operation_id,
            status="cancelled",
            status_message="Model pull cancelled",
            error_code=None,
        )
        return
    _update_operation(operation_id, status="running", status_message="connecting")
    response = None
    try:
        _validate_runtime_target(provider)
        response = requests.request(
            "POST",
            f"{provider['base_url'].rstrip('/')}/api/pull",
            headers={"Accept": "application/x-ndjson", **_credential_headers(provider)},
            json={"model": operation["model_name"], "stream": True, "insecure": False},
            timeout=(5, 120),
            allow_redirects=False,
            stream=True,
        )
        if 300 <= response.status_code < 400:
            raise ModelDiagnosticError("REDIRECT_BLOCKED", "Ollama redirect was blocked")
        if not 200 <= response.status_code < 300:
            raise ModelDiagnosticError(
                f"HTTP_{response.status_code}", f"Ollama returned HTTP {response.status_code}"
            )

        with _OPERATION_RESPONSE_LOCK:
            _ACTIVE_OPERATION_RESPONSES[operation_id] = response

        saw_success = False
        for raw_line in response.iter_lines():
            if _operation_cancel_requested(operation_id):
                raise _OperationCancelled()
            if not raw_line:
                continue
            if len(raw_line) > 64 * 1024:
                raise ModelDiagnosticError("EVENT_TOO_LARGE", "Ollama progress event was too large")
            try:
                event = json.loads(raw_line)
            except ValueError as exc:
                raise ModelDiagnosticError("INVALID_RESPONSE", "Ollama returned invalid progress JSON") from exc
            if not isinstance(event, dict):
                raise ModelDiagnosticError("INVALID_RESPONSE", "Ollama progress event was invalid")
            completed = max(0, int(event.get("completed") or 0))
            total = max(0, int(event.get("total") or 0))
            progress = min(1.0, completed / total) if total else 0.0
            status_message = _normalize_pull_status(event.get("status"))
            saw_success = saw_success or status_message == "success"
            _update_operation(
                operation_id,
                progress=progress,
                completed_bytes=completed,
                total_bytes=total,
                status_message=status_message,
            )
        if _operation_cancel_requested(operation_id):
            raise _OperationCancelled()
        if not saw_success:
            raise ModelDiagnosticError("INCOMPLETE", "Ollama pull ended without success")
        sync_warning = None
        if operation["provider_id"]:
            _update_operation(operation_id, status_message="syncing_profile")
            try:
                sync_ollama_model_profile(
                    operation["provider_id"], operation["model_name"]
                )
            except Exception:
                sync_warning = "PROFILE_SYNC_FAILED"
        _update_operation(
            operation_id,
            status="completed",
            progress=1.0,
            status_message="success" if sync_warning is None else "success_profile_sync_pending",
            error_code=sync_warning,
        )
    except _OperationCancelled:
        _update_operation(
            operation_id,
            status="cancelled",
            status_message="Model pull cancelled",
            error_code=None,
        )
    except ModelDiagnosticError as exc:
        _update_operation(
            operation_id,
            status="failed",
            status_message=exc.safe_message,
            error_code=exc.code,
        )
    except requests.Timeout:
        _update_operation(
            operation_id,
            status="failed",
            status_message="Ollama pull timed out",
            error_code="TIMEOUT",
        )
    except requests.RequestException:
        if _operation_cancel_requested(operation_id):
            _update_operation(
                operation_id,
                status="cancelled",
                status_message="Model pull cancelled",
                error_code=None,
            )
            return
        _update_operation(
            operation_id,
            status="failed",
            status_message="Ollama pull connection failed",
            error_code="CONNECTION_FAILED",
        )
    except Exception:
        _update_operation(
            operation_id,
            status="failed",
            status_message="Ollama pull failed unexpectedly",
            error_code="INTERNAL_ERROR",
        )
    finally:
        with _OPERATION_RESPONSE_LOCK:
            _ACTIVE_OPERATION_RESPONSES.pop(operation_id, None)
        if response is not None:
            close = getattr(response, "close", None)
            if close:
                close()


def _operation_cancel_requested(operation_id: str) -> bool:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM ollama_operations WHERE id=?",
            (operation_id,),
        ).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def start_pull_operation(
    model_name: str, provider_id: str | None = None, retry_of: str | None = None,
):
    _validate_model_name(model_name)
    _resolve_provider(provider_id)
    with _OPERATION_LOCK:
        conn = _get_registry_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ollama_operations WHERE operation='pull' "
                "AND COALESCE(provider_id,'')=COALESCE(?,'') AND model_name=? "
                "AND status IN ('queued','running') "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (provider_id, model_name),
            ).fetchone()
            if existing:
                conn.commit()
                result = dict(existing)
                result["cancel_requested"] = bool(result.get("cancel_requested"))
                return result
            operation_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO ollama_operations "
                "(id,provider_id,operation,model_name,status,status_message,retry_of) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    operation_id,
                    provider_id,
                    "pull",
                    model_name,
                    "queued",
                    "queued",
                    retry_of,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    _start_background_thread(
        _run_pull_operation,
        (operation_id,),
        f"ollama-pull-{operation_id[:8]}",
    )
    return _operation_row(operation_id)


def get_operation(operation_id: str):
    return _operation_row(operation_id)


def list_operations(limit: int = 20):
    conn = _get_registry_conn()
    try:
        return [
            {**dict(row), "cancel_requested": bool(row["cancel_requested"])}
            for row in conn.execute(
                "SELECT * FROM ollama_operations ORDER BY created_at DESC,id DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            )
        ]
    finally:
        conn.close()


def cancel_operation(operation_id: str):
    operation = _operation_row(operation_id)
    if not operation:
        raise KeyError(operation_id)
    if operation["operation"] != "pull":
        raise OllamaManagementError(
            "CANCEL_NOT_ALLOWED", "Only model pull operations can be cancelled"
        )
    if operation["status"] in {"completed", "failed", "cancelled"}:
        if operation["status"] == "completed":
            raise OllamaManagementError(
                "CANCEL_NOT_ALLOWED", "A completed model pull cannot be cancelled"
            )
        return operation
    _update_operation(
        operation_id,
        cancel_requested=1,
        status_message="cancellation_requested",
    )
    with _OPERATION_RESPONSE_LOCK:
        response = _ACTIVE_OPERATION_RESPONSES.get(operation_id)
    if response is not None:
        close = getattr(response, "close", None)
        if close:
            close()
    if operation["status"] == "queued":
        _update_operation(
            operation_id,
            status="cancelled",
            status_message="Model pull cancelled",
            error_code=None,
        )
    return _operation_row(operation_id)


def retry_operation(operation_id: str):
    operation = _operation_row(operation_id)
    if not operation:
        raise KeyError(operation_id)
    if operation["operation"] != "pull" or operation["status"] != "failed":
        raise OllamaManagementError(
            "RETRY_NOT_ALLOWED", "Only failed pull operations can be retried"
        )
    return start_pull_operation(
        operation["model_name"], operation["provider_id"], retry_of=operation_id
    )


def set_model_loaded(model_name: str, loaded: bool, provider_id: str | None = None):
    _validate_model_name(model_name)
    if not _is_managed_running():
        raise OllamaManagementError(
            "EXTERNAL_RUNTIME_CONTROL_BLOCKED",
            "AetherDB cannot change model residency in an Ollama runtime it did not start",
        )
    provider = _resolve_provider(provider_id)
    _request_json(
        provider,
        "POST",
        "/api/generate",
        {
            "model": model_name,
            "prompt": "",
            "stream": False,
            "keep_alive": -1 if loaded else 0,
        },
    )
    return {
        "provider_id": provider_id,
        "model": model_name,
        "loaded": loaded,
        "status": "loaded" if loaded else "unloaded",
    }


def delete_model_file(
    model_name: str, confirm_model: str, provider_id: str | None = None,
):
    _validate_model_name(model_name)
    if confirm_model != model_name:
        raise OllamaManagementError(
            "CONFIRMATION_MISMATCH", "Model deletion confirmation does not match"
        )
    if not _is_managed_running():
        raise OllamaManagementError(
            "EXTERNAL_RUNTIME_CONTROL_BLOCKED",
            "AetherDB cannot delete models from an Ollama runtime it did not start",
        )
    provider = _resolve_provider(provider_id)
    _request_json(provider, "DELETE", "/api/delete", {"model": model_name})
    if provider_id:
        conn = _get_registry_conn()
        try:
            conn.execute(
                "UPDATE model_profiles SET enabled=0,health_status='unknown',remote_status='missing',"
                "updated_at=CURRENT_TIMESTAMP WHERE provider_id=? AND provider_model_name=?",
                (provider_id, model_name),
            )
            conn.commit()
        finally:
            conn.close()
    return {
        "provider_id": provider_id,
        "model": model_name,
        "deleted": True,
        "profile_deleted": False,
    }


def recover_interrupted_operations():
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE ollama_operations SET status='cancelled',error_code=NULL,"
            "status_message='Model pull cancelled before application restart',"
            "updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running') "
            "AND cancel_requested=1"
        )
        conn.execute(
            "UPDATE ollama_operations SET status='failed',error_code='INTERRUPTED',"
            "status_message='Operation interrupted by application restart',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('queued','running') AND cancel_requested=0"
        )
        conn.commit()
    finally:
        conn.close()
