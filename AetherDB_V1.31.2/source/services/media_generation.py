"""Durable image-generation tasks with explicit media-asset approval."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.config import get_runtime_path
from services.database_registry import get_database, get_db_path, list_databases
from services.db import get_db
from services.media_assets import (
    MediaAssetError,
    get_media_asset,
    get_media_content,
    import_media_asset,
    soft_delete_media_asset,
    update_media_asset,
)
from services.model_management import (
    MAX_RESPONSE_BYTES,
    ModelDiagnosticError,
    _credential_headers,
    _validate_runtime_target,
)
from services.model_packages.registry import (
    get_installation,
    get_manifest,
    sync_catalog,
)
from services.model_registry import (
    LOCAL_PROVIDER_TYPES,
    find_bindings,
    get_model_profile,
    get_provider,
)
from services.model_runtime.manager import WorkerManagerError, get_worker_manager


DEFAULT_IMAGE_PACKAGE_ID = "aetherdb.kandinsky-2-2"
OPERATIONS = {"image.generate", "image.img2img", "image.enhance"}
SOURCE_OPERATIONS = {"image.img2img", "image.enhance"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "cancelling"}
IMAGE_MODEL_TYPES = {"image", "image_generation", "multimodal_generation"}
REQUESTED_BACKENDS = {"auto", "rocm_pytorch", "cuda"}
MAX_PROVIDER_RESPONSE_BYTES = max(MAX_RESPONSE_BYTES, 48 * 1024 * 1024)
MAX_GENERATED_IMAGE_BYTES = 32 * 1024 * 1024
PARAMETER_DEFAULTS = {
    "width": 768,
    "height": 768,
    "steps": 30,
    "guidance_scale": 4.0,
    "strength": 0.3,
}
_TASK_QUEUE: queue.Queue[tuple[str, str]] = queue.Queue()
_STATE_LOCK = threading.RLock()
_QUEUED_TASKS: set[tuple[str, str]] = set()
_WORKER_THREAD: threading.Thread | None = None


class MediaGenerationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        *,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code
        self.details = details or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _public_task(row, *, include_prompt: bool = True) -> dict:
    task = dict(row)
    task["parameters"] = _decode_json(task.pop("parameters_json", None), {})
    task["cancel_requested"] = bool(task["cancel_requested"])
    task["allow_cloud_upload"] = bool(task["allow_cloud_upload"])
    if not include_prompt:
        task.pop("prompt", None)
        task.pop("negative_prompt", None)
    return task


def _event(database_id: str, task_id: str, event_type: str, payload: dict | None = None):
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence),-1)+1 FROM media_generation_events WHERE task_id=?",
            (task_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO media_generation_events "
            "(task_id,sequence,event_type,payload_json,created_at) VALUES (?,?,?,?,?)",
            (
                task_id,
                sequence,
                event_type,
                json.dumps(payload or {}, ensure_ascii=True, sort_keys=True),
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_media_generation_events(
    database_id: str,
    task_id: str,
    *,
    after_sequence: int = -1,
    limit: int = 100,
) -> list[dict]:
    get_media_generation_task(database_id, task_id, include_prompt=False)
    conn = get_db(database_id)
    try:
        rows = conn.execute(
            "SELECT sequence,event_type,payload_json,created_at "
            "FROM media_generation_events WHERE task_id=? AND sequence>? "
            "ORDER BY sequence LIMIT ?",
            (task_id, max(-1, int(after_sequence)), max(1, min(int(limit), 500))),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "protocol_version": "1.0",
            "sequence": int(row["sequence"]),
            "event": row["event_type"],
            "task_id": task_id,
            "data": _decode_json(row["payload_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_media_generation_task(
    database_id: str,
    task_id: str,
    *,
    include_prompt: bool = True,
) -> dict:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT * FROM media_generation_tasks WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise MediaGenerationError(
            "DATABASE_NOT_READY",
            "The selected database has not been initialized",
            409,
        ) from exc
    finally:
        conn.close()
    if not row:
        raise MediaGenerationError(
            "GENERATION_TASK_NOT_FOUND",
            "Media generation task was not found",
            404,
        )
    return _public_task(row, include_prompt=include_prompt)


def list_media_generation_tasks(
    database_id: str,
    *,
    book_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    clauses = ["database_id=?"]
    params: list[object] = [database_id]
    if book_id:
        clauses.append("book_id=?")
        params.append(book_id)
    if status:
        if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
            raise MediaGenerationError("INVALID_STATUS", "Generation task status is invalid", 400)
        clauses.append("status=?")
        params.append(status)
    where = " AND ".join(clauses)
    conn = get_db(database_id)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM media_generation_tasks WHERE {where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM media_generation_tasks WHERE {where} "
            "ORDER BY created_at DESC,task_id DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(int(limit), 500)), max(0, int(offset))),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise MediaGenerationError(
            "DATABASE_NOT_READY",
            "The selected database has not been initialized",
            409,
        ) from exc
    finally:
        conn.close()
    return {
        "total": int(total),
        "tasks": [_public_task(row, include_prompt=False) for row in rows],
    }


def _validate_scope(database_id: str, book_id: str):
    if not get_database(database_id):
        raise MediaGenerationError("DATABASE_NOT_FOUND", "Database was not found", 404)
    conn = get_db(database_id)
    try:
        row = conn.execute("SELECT 1 FROM books WHERE book_id=?", (book_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        raise MediaGenerationError(
            "DATABASE_NOT_READY",
            "The selected database has not been initialized",
            409,
        ) from exc
    finally:
        conn.close()
    if not row:
        raise MediaGenerationError("BOOK_NOT_FOUND", "Book was not found", 404)


def _validate_parameters(value: dict | None) -> dict:
    supplied = value or {}
    if not isinstance(supplied, dict) or set(supplied) - set(PARAMETER_DEFAULTS):
        raise MediaGenerationError(
            "INVALID_PARAMETERS",
            "Image generation parameters are invalid",
            400,
        )
    parameters = {**PARAMETER_DEFAULTS, **supplied}
    width = parameters["width"]
    height = parameters["height"]
    steps = parameters["steps"]
    guidance = parameters["guidance_scale"]
    strength = parameters["strength"]
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or not 256 <= width <= 1024
        or not 256 <= height <= 1024
        or width % 64
        or height % 64
        or not isinstance(steps, int)
        or not 1 <= steps <= 100
        or isinstance(guidance, bool)
        or not isinstance(guidance, (int, float))
        or not 1 <= float(guidance) <= 20
        or isinstance(strength, bool)
        or not isinstance(strength, (int, float))
        or not 0.05 <= float(strength) <= 1
    ):
        raise MediaGenerationError(
            "INVALID_PARAMETERS",
            "Image generation parameters are invalid",
            400,
        )
    parameters["guidance_scale"] = float(guidance)
    parameters["strength"] = float(strength)
    return parameters


def _validate_text(value: str, *, label: str, maximum: int, required: bool) -> str:
    if not isinstance(value, str):
        raise MediaGenerationError("INVALID_PROMPT", f"{label} is invalid", 400)
    cleaned = value.strip()
    if (required and not cleaned) or len(cleaned) > maximum:
        raise MediaGenerationError("INVALID_PROMPT", f"{label} is invalid", 400)
    if any(ord(char) < 32 and char not in {"\n", "\r", "\t"} for char in cleaned):
        raise MediaGenerationError("INVALID_PROMPT", f"{label} is invalid", 400)
    return cleaned


def _native_target(package_id: str, operation: str) -> dict:
    sync_catalog()
    try:
        manifest = get_manifest(package_id, sync=False)
    except KeyError as exc:
        raise MediaGenerationError(
            "PACKAGE_UNKNOWN",
            "The selected trusted image package is not in the catalog",
            404,
        ) from exc
    if operation not in manifest.capabilities or manifest.package_kind != "image_generation":
        raise MediaGenerationError(
            "MODEL_CAPABILITY_UNSUPPORTED",
            "The selected package does not support this image task",
            409,
        )
    installation = get_installation(package_id)
    if installation is None or installation["status"] not in {"installed", "disabled"}:
        raise MediaGenerationError(
            "INSTALL_REQUIRED",
            "The selected trusted image package must be installed and verified",
            409,
            details={"package_id": package_id},
        )
    if installation["status"] == "disabled":
        raise MediaGenerationError(
            "PACKAGE_DISABLED",
            "The selected trusted image package is disabled",
            409,
        )
    return {
        "target_kind": "native_package",
        "package_id": package_id,
        "model_profile_id": None,
        "provider_id": None,
        "provider_model_name": manifest.model_family,
    }


def _external_target(
    model_profile_id: str,
    *,
    allow_cloud_upload: bool,
) -> dict:
    profile = get_model_profile(model_profile_id)
    if not profile:
        raise MediaGenerationError("MODEL_NOT_FOUND", "Model profile was not found", 404)
    provider = get_provider(profile["provider_id"])
    if not provider:
        raise MediaGenerationError("PROVIDER_NOT_FOUND", "Model provider was not found", 404)
    if not provider["enabled"] or not profile["enabled"]:
        raise MediaGenerationError(
            "MODEL_NOT_ENABLED",
            "The selected model must be explicitly enabled before use",
            409,
        )
    if provider["health_status"] in {"unhealthy", "blocked"} or profile[
        "health_status"
    ] in {"unhealthy", "blocked"}:
        raise MediaGenerationError(
            "MODEL_UNAVAILABLE",
            "The selected model is currently unavailable",
            409,
        )
    if profile["remote_status"] in {"missing", "unavailable"}:
        raise MediaGenerationError(
            "MODEL_UNAVAILABLE",
            "The selected model is not available from its external provider",
            409,
        )
    if profile["model_type"] not in IMAGE_MODEL_TYPES:
        raise MediaGenerationError(
            "MODEL_CAPABILITY_UNSUPPORTED",
            "The selected model is not confirmed for image generation",
            409,
        )
    local_provider = provider["provider_type"] in LOCAL_PROVIDER_TYPES
    if not local_provider and profile["privacy_level"] != "local_only" and not allow_cloud_upload:
        raise MediaGenerationError(
            "CLOUD_UPLOAD_CONFIRMATION_REQUIRED",
            "Cloud image generation requires explicit upload confirmation",
            409,
        )
    return {
        "target_kind": "external_provider",
        "package_id": None,
        "model_profile_id": profile["id"],
        "provider_id": provider["id"],
        "provider_model_name": profile["provider_model_name"],
    }


def _binding_target(
    *,
    database_id: str,
    book_id: str,
    session_id: str | None,
    operation: str,
    allow_cloud_upload: bool,
) -> dict | None:
    scopes = []
    if session_id:
        scopes.append(("session", session_id))
    scopes.extend(
        (
            ("book", f"{database_id}/{book_id}"),
            ("database", database_id),
            ("global", None),
        )
    )
    for scope_type, scope_id in scopes:
        bindings = find_bindings(scope_type, scope_id, operation)
        if not bindings:
            continue
        priority = bindings[0]["priority"]
        target_ids = list(
            dict.fromkeys(
                item["target_id"] for item in bindings if item["priority"] == priority
            )
        )
        eligible = []
        first_error = None
        for target_id in target_ids:
            try:
                eligible.append(
                    _external_target(
                        target_id,
                        allow_cloud_upload=allow_cloud_upload,
                    )
                )
            except MediaGenerationError as exc:
                first_error = first_error or exc
        if len(eligible) > 1:
            raise MediaGenerationError(
                "AMBIGUOUS_MODEL_ROUTE",
                "Multiple image models match this task; choose one explicitly",
                409,
                details={
                    "candidate_model_profile_ids": [
                        item["model_profile_id"] for item in eligible[:5]
                    ]
                },
            )
        if eligible:
            return eligible[0]
        raise first_error or MediaGenerationError(
            "MODEL_UNAVAILABLE",
            "The bound image model is unavailable",
            409,
        )
    return None


def _resolve_target(payload: dict, operation: str) -> dict:
    model_profile_id = payload.get("model_profile_id")
    package_id = payload.get("package_id")
    if model_profile_id and package_id:
        raise MediaGenerationError(
            "MULTIPLE_EXECUTION_TARGETS",
            "Choose either an external model or a trusted native package",
            400,
        )
    allow_cloud_upload = bool(payload.get("allow_cloud_upload", False))
    if model_profile_id:
        return _external_target(
            model_profile_id,
            allow_cloud_upload=allow_cloud_upload,
        )
    if package_id:
        return _native_target(package_id, operation)
    bound = _binding_target(
        database_id=payload["database_id"],
        book_id=payload["book_id"],
        session_id=payload.get("session_id"),
        operation=operation,
        allow_cloud_upload=allow_cloud_upload,
    )
    return bound or _native_target(DEFAULT_IMAGE_PACKAGE_ID, operation)


def _source_asset(
    database_id: str,
    book_id: str,
    operation: str,
    source_asset_id: str | None,
) -> dict | None:
    if operation in SOURCE_OPERATIONS and not source_asset_id:
        raise MediaGenerationError(
            "SOURCE_IMAGE_REQUIRED",
            "This image task requires a source image",
            400,
        )
    if operation not in SOURCE_OPERATIONS and source_asset_id:
        raise MediaGenerationError(
            "SOURCE_IMAGE_NOT_ALLOWED",
            "Text-to-image generation does not accept a source image",
            400,
        )
    if not source_asset_id:
        return None
    try:
        asset = get_media_asset(database_id, source_asset_id, include_related=False)
    except MediaAssetError as exc:
        raise MediaGenerationError(exc.code, exc.message, exc.status_code) from exc
    if asset["book_id"] != book_id or asset["modality"] != "image":
        raise MediaGenerationError(
            "INVALID_SOURCE_IMAGE",
            "Source image must belong to the selected book",
            409,
        )
    return asset


def create_media_generation_task(
    payload: dict,
    *,
    start: bool = True,
    retry_of: str | None = None,
) -> dict:
    database_id = payload["database_id"]
    book_id = payload["book_id"]
    operation = payload.get("operation", "image.generate")
    if operation not in OPERATIONS:
        raise MediaGenerationError(
            "INVALID_OPERATION",
            "Image generation operation is invalid",
            400,
        )
    _validate_scope(database_id, book_id)
    prompt = _validate_text(
        payload.get("prompt", ""),
        label="Prompt",
        maximum=6000,
        required=True,
    )
    negative_prompt = _validate_text(
        payload.get("negative_prompt", ""),
        label="Negative prompt",
        maximum=3000,
        required=False,
    )
    parameters = _validate_parameters(payload.get("parameters"))
    requested_backend = payload.get("requested_backend", "auto")
    if requested_backend not in REQUESTED_BACKENDS:
        raise MediaGenerationError(
            "INVALID_BACKEND",
            "Requested image generation backend is invalid",
            400,
        )
    seed = payload.get("seed")
    if seed is None:
        seed = secrets.randbelow(9_223_372_036_854_775_808)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 9_223_372_036_854_775_807:
        raise MediaGenerationError("INVALID_SEED", "Image generation seed is invalid", 400)
    source = _source_asset(
        database_id,
        book_id,
        operation,
        payload.get("source_asset_id"),
    )
    target = _resolve_target(payload, operation)
    task_id = f"mgen-{uuid.uuid4().hex}"
    now = _now()
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO media_generation_tasks(
                task_id,database_id,book_id,operation,status,target_kind,package_id,
                model_profile_id,provider_id,provider_model_name,prompt,prompt_hash,
                negative_prompt,parameters_json,seed,source_asset_id,requested_backend,
                allow_cloud_upload,retry_of,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                database_id,
                book_id,
                operation,
                "queued",
                target["target_kind"],
                target["package_id"],
                target["model_profile_id"],
                target["provider_id"],
                target["provider_model_name"],
                prompt,
                hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                negative_prompt,
                json.dumps(parameters, ensure_ascii=True, sort_keys=True),
                seed,
                source["asset_id"] if source else None,
                requested_backend,
                int(bool(payload.get("allow_cloud_upload", False))),
                retry_of,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO media_generation_events "
            "(task_id,sequence,event_type,payload_json,created_at) VALUES (?,0,'status',?,?)",
            (
                task_id,
                json.dumps(
                    {
                        "status": "queued",
                        "operation": operation,
                        "target_kind": target["target_kind"],
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    if start:
        _submit_task(database_id, task_id)
    return get_media_generation_task(database_id, task_id)


def _update_task(database_id: str, task_id: str, **values):
    if not values:
        return
    assignments = [f"{key}=?" for key in values]
    params = [*values.values(), _now(), database_id, task_id]
    conn = get_db(database_id)
    try:
        conn.execute(
            f"UPDATE media_generation_tasks SET {','.join(assignments)},updated_at=? "
            "WHERE database_id=? AND task_id=?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def _cancel_requested(database_id: str, task_id: str) -> bool:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM media_generation_tasks "
            "WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def _set_cancelled(database_id: str, task_id: str):
    now = _now()
    _update_task(
        database_id,
        task_id,
        status="cancelled",
        progress=1,
        completed_at=now,
        error_code=None,
        error_message=None,
    )
    _event(database_id, task_id, "cancelled", {"status": "cancelled"})
    _event(database_id, task_id, "done", {"status": "cancelled"})


def _set_failed(database_id: str, task_id: str, code: str, message: str):
    now = _now()
    _update_task(
        database_id,
        task_id,
        status="failed",
        progress=1,
        completed_at=now,
        error_code=code[:96],
        error_message=message[:512],
    )
    _event(
        database_id,
        task_id,
        "error",
        {"status": "failed", "code": code[:96], "message": message[:512]},
    )
    _event(database_id, task_id, "done", {"status": "failed"})


def _staging_path(database_id: str, task_id: str) -> Path:
    database_token = hashlib.sha256(database_id.encode("utf-8")).hexdigest()[:16]
    root = get_runtime_path(
        "app_data",
        "media_generation_staging",
        database_token,
    ).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise MediaGenerationError(
            "UNSAFE_STAGING_ROOT",
            "Image generation staging root is unsafe",
            409,
        )
    return root / f"{task_id}-{uuid.uuid4().hex}.png"


def _write_output_bytes(path: Path, data: bytes):
    if not data or len(data) > MAX_GENERATED_IMAGE_BYTES:
        raise MediaGenerationError(
            "OUTPUT_TOO_LARGE",
            "Generated image exceeds the output limit",
            409,
        )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _image_mime_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise MediaGenerationError(
        "INVALID_PROVIDER_IMAGE",
        "External image provider returned an unsupported image format",
        409,
    )


class NativeImageGenerationExecutor:
    def execute(
        self,
        task: dict,
        *,
        output_path: Path,
        source: dict | None,
        job_started,
    ) -> dict:
        payload = {
            "mode": task["operation"],
            "prompt": task["prompt"],
            "negative_prompt": task["negative_prompt"],
            "parameters": task["parameters"],
            "seed": task["seed"],
            "output_path": str(output_path),
        }
        if source is not None:
            payload["source"] = {
                "path": str(source["path"]),
                "sha256": source["sha256"],
            }
        result = get_worker_manager().execute(
            task["package_id"],
            task_id=task["task_id"],
            operation="image",
            payload=payload,
            requested_backend=task["requested_backend"],
            priority=70,
            timeout=1800,
            replica_id="generation",
            job_started=job_started,
        )
        runtime_job = get_worker_manager().get_job(result["job_id"]) or {}
        return {
            **result["result"],
            "runtime_job_id": result["job_id"],
            "device_id": runtime_job.get("device_id"),
        }


class ExternalImageGenerationExecutor:
    def execute(
        self,
        task: dict,
        *,
        output_path: Path,
        source: dict | None,
        job_started,
    ) -> dict:
        del job_started
        if source is not None:
            raise MediaGenerationError(
                "EXTERNAL_IMAGE_EDIT_UNSUPPORTED",
                "The selected external provider does not expose a verified image-edit contract",
                409,
            )
        if task["negative_prompt"]:
            raise MediaGenerationError(
                "EXTERNAL_NEGATIVE_PROMPT_UNSUPPORTED",
                "The selected external provider does not expose a verified negative-prompt contract",
                409,
            )
        provider = get_provider(task["provider_id"])
        if not provider or provider["api_format"] not in {
            "openai",
            "openai_compatible",
            "openai_images",
        }:
            raise MediaGenerationError(
                "PROVIDER_CAPABILITY_UNSUPPORTED",
                "The selected external provider has no verified image-generation API contract",
                409,
            )
        _validate_runtime_target(provider)
        payload = {
            "model": task["provider_model_name"],
            "prompt": task["prompt"],
            "n": 1,
            "size": f"{task['parameters']['width']}x{task['parameters']['height']}",
            "response_format": "b64_json",
        }
        started = time.perf_counter()
        try:
            response = requests.post(
                f"{provider['base_url'].rstrip('/')}/images/generations",
                headers={
                    "Accept": "application/json",
                    **_credential_headers(provider),
                },
                json=payload,
                timeout=(5, 300),
                allow_redirects=False,
                stream=True,
            )
        except requests.Timeout as exc:
            raise MediaGenerationError(
                "PROVIDER_TIMEOUT",
                "External image provider timed out",
                409,
            ) from exc
        except requests.RequestException as exc:
            raise MediaGenerationError(
                "PROVIDER_CONNECTION_FAILED",
                "External image provider request failed",
                409,
            ) from exc
        if 300 <= response.status_code < 400:
            response.close()
            raise MediaGenerationError(
                "PROVIDER_REDIRECT_BLOCKED",
                "External image provider redirect was blocked",
                409,
            )
        if response.status_code in {401, 403}:
            response.close()
            raise MediaGenerationError(
                "AUTH_FAILED",
                "External image provider authentication failed",
                409,
            )
        if not 200 <= response.status_code < 300:
            status_code = response.status_code
            response.close()
            raise MediaGenerationError(
                f"PROVIDER_HTTP_{status_code}",
                f"External image provider returned HTTP {status_code}",
                409,
            )
        try:
            declared_length = response.headers.get("content-length")
            if declared_length and int(declared_length) > MAX_PROVIDER_RESPONSE_BYTES:
                raise MediaGenerationError(
                    "PROVIDER_RESPONSE_TOO_LARGE",
                    "External image provider response exceeded the limit",
                    409,
                )
            chunks = []
            received = 0
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > MAX_PROVIDER_RESPONSE_BYTES:
                    raise MediaGenerationError(
                        "PROVIDER_RESPONSE_TOO_LARGE",
                        "External image provider response exceeded the limit",
                        409,
                    )
                chunks.append(chunk)
            body = json.loads(b"".join(chunks))
            encoded = body["data"][0]["b64_json"]
            image_bytes = base64.b64decode(encoded, validate=True)
        except MediaGenerationError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MediaGenerationError(
                "INVALID_PROVIDER_RESPONSE",
                "External image provider returned an invalid image response",
                409,
            ) from exc
        finally:
            response.close()
        mime_type = _image_mime_type(image_bytes)
        _write_output_bytes(output_path, image_bytes)
        return {
            "model_id": task["provider_model_name"],
            "effective_backend": "external_provider",
            "execution_provider": provider["id"],
            "output_mime_type": mime_type,
            "output_size_bytes": len(image_bytes),
            "output_digest": hashlib.sha256(image_bytes).hexdigest(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "runtime_job_id": None,
            "device_id": None,
        }


class DefaultImageGenerationExecutor:
    def __init__(self):
        self.native = NativeImageGenerationExecutor()
        self.external = ExternalImageGenerationExecutor()

    def execute(self, task: dict, **kwargs) -> dict:
        executor = self.native if task["target_kind"] == "native_package" else self.external
        return executor.execute(task, **kwargs)


def _source_for_execution(database_id: str, task: dict) -> dict | None:
    if not task.get("source_asset_id"):
        return None
    try:
        path, asset = get_media_content(database_id, task["source_asset_id"])
    except MediaAssetError as exc:
        raise MediaGenerationError(exc.code, exc.message, exc.status_code) from exc
    if asset["book_id"] != task["book_id"] or asset["modality"] != "image":
        raise MediaGenerationError(
            "INVALID_SOURCE_IMAGE",
            "Source image no longer belongs to this task scope",
            409,
        )
    return {"path": path, "sha256": asset["content_hash"]}


def run_media_generation_task(
    database_id: str,
    task_id: str,
    *,
    executor=None,
) -> dict:
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM media_generation_tasks WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone()
        if not row:
            conn.rollback()
            raise MediaGenerationError(
                "GENERATION_TASK_NOT_FOUND",
                "Media generation task was not found",
                404,
            )
        if row["status"] != "queued":
            conn.commit()
            return _public_task(row)
        if row["cancel_requested"]:
            conn.execute(
                "UPDATE media_generation_tasks SET status='cancelled',progress=1,"
                "completed_at=?,updated_at=? WHERE task_id=?",
                (_now(), _now(), task_id),
            )
            conn.commit()
            _event(database_id, task_id, "cancelled", {"status": "cancelled"})
            _event(database_id, task_id, "done", {"status": "cancelled"})
            return get_media_generation_task(database_id, task_id)
        started_at = _now()
        conn.execute(
            "UPDATE media_generation_tasks SET status='running',progress=0.05,"
            "started_at=?,error_code=NULL,error_message=NULL,updated_at=? WHERE task_id=?",
            (started_at, started_at, task_id),
        )
        conn.commit()
    finally:
        conn.close()
    _event(database_id, task_id, "status", {"status": "running", "progress": 0.05})

    task = get_media_generation_task(database_id, task_id)
    output_path = _staging_path(database_id, task_id)
    wall_started = time.perf_counter()
    try:
        source = _source_for_execution(database_id, task)

        def job_started(runtime_job_id: str):
            _update_task(
                database_id,
                task_id,
                runtime_job_id=runtime_job_id,
                progress=0.1,
            )
            _event(
                database_id,
                task_id,
                "runtime",
                {"runtime_job_id": runtime_job_id, "progress": 0.1},
            )
            return not _cancel_requested(database_id, task_id)

        result = (executor or DefaultImageGenerationExecutor()).execute(
            task,
            output_path=output_path,
            source=source,
            job_started=job_started,
        )
        if _cancel_requested(database_id, task_id):
            output_path.unlink(missing_ok=True)
            _set_cancelled(database_id, task_id)
            return get_media_generation_task(database_id, task_id)
        if not output_path.is_file() or output_path.is_symlink():
            raise MediaGenerationError(
                "OUTPUT_MISSING",
                "Image generation completed without a usable output",
                409,
            )
        output_size = output_path.stat().st_size
        if not 0 < output_size <= MAX_GENERATED_IMAGE_BYTES:
            raise MediaGenerationError(
                "OUTPUT_TOO_LARGE",
                "Generated image exceeds the output limit",
                409,
            )
        output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
        if result.get("output_digest") and result["output_digest"] != output_hash:
            raise MediaGenerationError(
                "OUTPUT_INTEGRITY_MISMATCH",
                "Generated image failed its integrity check",
                409,
            )
        _update_task(
            database_id,
            task_id,
            progress=0.85,
            effective_backend=result.get("effective_backend"),
            device_id=result.get("device_id"),
            runtime_job_id=result.get("runtime_job_id")
            or task.get("runtime_job_id"),
        )
        _event(
            database_id,
            task_id,
            "progress",
            {"status": "running", "progress": 0.85},
        )
        with output_path.open("rb") as handle:
            asset = import_media_asset(
                database_id,
                task["book_id"],
                handle,
                filename=f"{task_id}.png",
                declared_mime=result.get("output_mime_type") or "image/png",
                source_type="generated",
                created_by_task_id=task_id,
            )
        provenance = {
            "generation": {
                "task_id": task_id,
                "operation": task["operation"],
                "target_kind": task["target_kind"],
                "package_id": task.get("package_id"),
                "model_profile_id": task.get("model_profile_id"),
                "provider_id": task.get("provider_id"),
                "provider_model_name": task.get("provider_model_name"),
                "prompt_hash": task["prompt_hash"],
                "parameters": task["parameters"],
                "seed": task["seed"],
                "requested_backend": task["requested_backend"],
                "effective_backend": result.get("effective_backend"),
                "device_id": result.get("device_id"),
                "runtime_job_id": result.get("runtime_job_id"),
                "elapsed_ms": result.get("elapsed_ms"),
                "source_asset_id": task.get("source_asset_id"),
                "output_hash": asset["content_hash"],
            }
        }
        asset = update_media_asset(
            database_id,
            asset["asset_id"],
            metadata={**asset.get("metadata", {}), **provenance},
        )
        if _cancel_requested(database_id, task_id):
            soft_delete_media_asset(database_id, asset["asset_id"])
            _set_cancelled(database_id, task_id)
            return get_media_generation_task(database_id, task_id)
        elapsed_ms = result.get("elapsed_ms")
        if not isinstance(elapsed_ms, (int, float)):
            elapsed_ms = round((time.perf_counter() - wall_started) * 1000, 3)
        completed_at = _now()
        _update_task(
            database_id,
            task_id,
            status="completed",
            progress=1,
            output_asset_id=asset["asset_id"],
            output_hash=asset["content_hash"],
            effective_backend=result.get("effective_backend"),
            device_id=result.get("device_id"),
            runtime_job_id=result.get("runtime_job_id")
            or get_media_generation_task(database_id, task_id).get("runtime_job_id"),
            elapsed_ms=float(elapsed_ms),
            completed_at=completed_at,
            error_code=None,
            error_message=None,
        )
        _event(
            database_id,
            task_id,
            "result",
            {
                "status": "completed",
                "asset_id": asset["asset_id"],
                "lifecycle_status": asset["lifecycle_status"],
                "output_hash": asset["content_hash"],
                "requires_approval": True,
            },
        )
        _event(database_id, task_id, "done", {"status": "completed"})
    except WorkerManagerError as exc:
        if exc.code == "CANCELLED" or _cancel_requested(database_id, task_id):
            _set_cancelled(database_id, task_id)
        else:
            _set_failed(database_id, task_id, exc.code, exc.safe_message)
    except ModelDiagnosticError as exc:
        _set_failed(database_id, task_id, exc.code, exc.safe_message)
    except MediaGenerationError as exc:
        if exc.code == "CANCELLED" or _cancel_requested(database_id, task_id):
            _set_cancelled(database_id, task_id)
        else:
            _set_failed(database_id, task_id, exc.code, exc.safe_message)
    except (MediaAssetError, OSError, sqlite3.Error) as exc:
        code = exc.code if isinstance(exc, MediaAssetError) else "GENERATION_STORAGE_FAILED"
        message = (
            exc.message
            if isinstance(exc, MediaAssetError)
            else "Generated image could not be stored safely"
        )
        _set_failed(database_id, task_id, code, message)
    except Exception:
        _set_failed(
            database_id,
            task_id,
            "GENERATION_FAILED",
            "Image generation failed unexpectedly",
        )
    finally:
        output_path.unlink(missing_ok=True)
    return get_media_generation_task(database_id, task_id)


def cancel_media_generation_task(database_id: str, task_id: str) -> dict:
    task = get_media_generation_task(database_id, task_id, include_prompt=False)
    if task["status"] in TERMINAL_STATUSES:
        return task
    if task["status"] == "queued":
        conn = get_db(database_id)
        try:
            conn.execute(
                "UPDATE media_generation_tasks SET status='cancelled',cancel_requested=1,"
                "progress=1,completed_at=?,updated_at=? WHERE task_id=? AND status='queued'",
                (_now(), _now(), task_id),
            )
            conn.commit()
        finally:
            conn.close()
        _event(database_id, task_id, "cancelled", {"status": "cancelled"})
        _event(database_id, task_id, "done", {"status": "cancelled"})
        return get_media_generation_task(database_id, task_id, include_prompt=False)
    _update_task(
        database_id,
        task_id,
        status="cancelling",
        cancel_requested=1,
    )
    _event(database_id, task_id, "status", {"status": "cancelling"})
    if task.get("runtime_job_id"):
        try:
            get_worker_manager().cancel_job(task["runtime_job_id"])
        except (KeyError, WorkerManagerError):
            pass
    return get_media_generation_task(database_id, task_id, include_prompt=False)


def retry_media_generation_task(
    database_id: str,
    task_id: str,
    *,
    start: bool = True,
) -> dict:
    previous = get_media_generation_task(database_id, task_id)
    if previous["status"] not in {"failed", "cancelled"}:
        raise MediaGenerationError(
            "RETRY_NOT_ALLOWED",
            "Only failed or cancelled generation tasks can be retried",
            409,
        )
    return create_media_generation_task(
        {
            "database_id": previous["database_id"],
            "book_id": previous["book_id"],
            "operation": previous["operation"],
            "prompt": previous["prompt"],
            "negative_prompt": previous["negative_prompt"],
            "parameters": previous["parameters"],
            "seed": previous["seed"],
            "source_asset_id": previous["source_asset_id"],
            "package_id": previous["package_id"],
            "model_profile_id": previous["model_profile_id"],
            "requested_backend": previous["requested_backend"],
            "allow_cloud_upload": previous["allow_cloud_upload"],
        },
        start=start,
        retry_of=task_id,
    )


def _submit_task(database_id: str, task_id: str):
    global _WORKER_THREAD
    key = (database_id, task_id)
    with _STATE_LOCK:
        if key in _QUEUED_TASKS:
            return
        _QUEUED_TASKS.add(key)
        _TASK_QUEUE.put(key)
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_THREAD = threading.Thread(
                target=_worker_loop,
                name="media-generation-task-worker",
                daemon=True,
            )
            _WORKER_THREAD.start()


def _worker_loop():
    while True:
        database_id, task_id = _TASK_QUEUE.get()
        try:
            run_media_generation_task(database_id, task_id)
        except Exception:
            try:
                _set_failed(
                    database_id,
                    task_id,
                    "GENERATION_WORKER_FAILED",
                    "Image generation task worker stopped unexpectedly",
                )
            except Exception:
                pass
        finally:
            with _STATE_LOCK:
                _QUEUED_TASKS.discard((database_id, task_id))
            _TASK_QUEUE.task_done()


def recover_interrupted_media_generation_tasks() -> dict:
    interrupted: list[tuple[str, str]] = []
    queued: list[tuple[str, str]] = []
    for database in list_databases():
        database_id = database["database_id"]
        try:
            conn = sqlite3.connect(get_db_path(database_id))
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='media_generation_tasks'"
            ).fetchone()
            if not exists:
                conn.close()
                continue
            rows = conn.execute(
                "SELECT task_id,status FROM media_generation_tasks "
                "WHERE status IN ('queued','running','cancelling')"
            ).fetchall()
            for row in rows:
                if row["status"] == "queued":
                    queued.append((database_id, row["task_id"]))
                else:
                    interrupted.append((database_id, row["task_id"]))
            now = _now()
            conn.execute(
                "UPDATE media_generation_tasks SET status='failed',progress=1,"
                "error_code='PROCESS_INTERRUPTED',"
                "error_message='Image generation stopped during application restart',"
                "completed_at=?,updated_at=? WHERE status IN ('running','cancelling')",
                (now, now),
            )
            conn.commit()
            conn.close()
        except (OSError, sqlite3.Error, ValueError):
            continue
    for database_id, task_id in interrupted:
        try:
            _event(
                database_id,
                task_id,
                "error",
                {
                    "status": "failed",
                    "code": "PROCESS_INTERRUPTED",
                    "message": "Image generation stopped during application restart",
                },
            )
            _event(database_id, task_id, "done", {"status": "failed"})
        except Exception:
            pass
    for database_id, task_id in queued:
        _submit_task(database_id, task_id)
    return {"interrupted": len(interrupted), "resumed_queued": len(queued)}


def get_media_generation_status() -> dict:
    sync_catalog()
    try:
        manifest = get_manifest(DEFAULT_IMAGE_PACKAGE_ID, sync=False)
        installation = get_installation(DEFAULT_IMAGE_PACKAGE_ID)
        package = {
            "package_id": manifest.package_id,
            "package_version": manifest.package_version,
            "display_name": manifest.display_name,
            "license_id": manifest.license.license_id,
            "source_kind": manifest.source.kind,
            "installation_status": (
                installation["status"] if installation else "install_available"
            ),
            "supported_backends": list(manifest.supported_backends),
            "verification_status": "unverified_hardware",
        }
    except KeyError:
        package = {
            "package_id": DEFAULT_IMAGE_PACKAGE_ID,
            "installation_status": "catalog_missing",
            "verification_status": "unverified_hardware",
        }
    return {
        "protocol_version": "1.0",
        "operations": sorted(OPERATIONS),
        "default_native_package": package,
        "external_model_policy": {
            "approved_model_whitelist_required": False,
            "explicit_enable_required": True,
            "confirmed_image_capability_required": True,
            "native_worker_execution": False,
            "cloud_upload_confirmation_required": True,
        },
        "approval_contract": {
            "generated_lifecycle_status": "temporary",
            "binding_requires_asset_status": "approved",
        },
    }
