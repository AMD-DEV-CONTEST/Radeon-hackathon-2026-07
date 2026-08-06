"""Model-neutral audio assets, task planning, review, and provenance contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import unicodedata
import uuid
import wave
from datetime import datetime, timezone

from services.database_registry import get_database
from services.db import get_db
from services.media_assets import MediaAssetError, get_media_asset, get_media_content
from services.model_packages.registry import get_manifest
from services.model_packages.registry import get_package_for_model_profile
from services.model_execution.requests import ModelTaskRequest
from services.model_registry import get_model_profile, get_provider
from services.model_routing import RouteStatus, UniqueModelRouter


OPERATIONS = {
    "audio.tts.chapter",
    "audio.tts.segment",
    "audio.asr.transcribe",
    "audio.preview",
    "audio.enhance",
    "audio.merge",
}
CAPABILITY_BY_OPERATION = {
    "audio.tts.chapter": "audio.tts",
    "audio.tts.segment": "audio.tts",
    "audio.asr.transcribe": "audio.asr",
    "audio.preview": "audio.preview",
    "audio.enhance": "audio.enhance",
    "audio.merge": "audio.merge",
}
MODEL_TYPES_BY_CAPABILITY = {
    "audio.tts": {"audio", "tts", "text_to_speech", "audio_generation", "multimodal_audio"},
    "audio.asr": {"audio", "asr", "speech_to_text", "transcription", "multimodal_audio"},
    "audio.preview": {"audio", "audio_processing", "multimodal_audio"},
    "audio.enhance": {"audio", "audio_enhancement", "audio_processing", "multimodal_audio"},
    "audio.merge": {"audio", "audio_processing", "multimodal_audio"},
}
TASK_STATUSES = {
    "planned",
    "in_progress",
    "pending_review",
    "completed",
    "cancelled",
    "failed",
    "outdated",
}
TERMINAL_TASK_STATUSES = {"completed", "cancelled", "failed", "outdated"}
MAX_SEGMENT_CHARS = 800
MAX_SEGMENTS = 2_000
MAX_SOURCE_TEXT_CHARS = 1_500_000
NORMALIZATION_VERSION = "aetherdb-tts-normalize-v1"
DEFAULT_TTS_EXECUTION_CONFIG = {
    "speed": 1.0,
    "segment_pause_ms": 120,
    "peak_target": 0.89,
}
KOKORO_BASELINE_PACKAGE_ID = "aetherdb.kokoro-82m"
KOKORO_BASELINE_VOICE_LOCALES = {
    "af_heart": {"en", "en-us"},
    "bf_emma": {"en", "en-gb"},
    "zf_xiaobei": {"zh", "zh-cn"},
}
OUTPUT_KINDS_BY_OPERATION = {
    "audio.tts.chapter": {"segment", "final", "merged"},
    "audio.tts.segment": {"segment", "final"},
    "audio.asr.transcribe": set(),
    "audio.preview": {"preview"},
    "audio.enhance": {"enhanced"},
    "audio.merge": {"merged", "final"},
}


class AudioContractError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _decode_json(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def _json_object(value: dict | None) -> str:
    try:
        encoded = json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise AudioContractError("INVALID_METADATA", "Metadata must be JSON serializable", 400) from exc
    if len(encoded.encode("utf-8")) > 16 * 1024:
        raise AudioContractError("METADATA_TOO_LARGE", "Metadata exceeds 16 KiB", 400)
    return encoded


def _clean_label(value: str, field: str, *, max_length: int) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_length or re.search(r"[\x00-\x1f\x7f]", cleaned):
        raise AudioContractError("INVALID_AUDIO_LABEL", f"Invalid {field}", 400)
    return cleaned


def _validate_scope(database_id: str, book_id: str) -> None:
    if not get_database(database_id):
        raise AudioContractError("DATABASE_NOT_FOUND", "Database was not found", 404)
    conn = get_db(database_id)
    try:
        row = conn.execute("SELECT 1 FROM books WHERE book_id=?", (book_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        raise AudioContractError(
            "DATABASE_NOT_READY",
            "The selected database has not been initialized",
            409,
        ) from exc
    finally:
        conn.close()
    if not row:
        raise AudioContractError("BOOK_NOT_FOUND", "Book was not found", 404)


def _validate_audio_asset(
    database_id: str,
    book_id: str,
    asset_id: str,
    *,
    require_approved: bool = False,
) -> dict:
    try:
        asset = get_media_asset(database_id, asset_id, include_related=False)
    except MediaAssetError as exc:
        raise AudioContractError(exc.code, exc.message, exc.status_code) from exc
    if asset["book_id"] != book_id or asset["modality"] != "audio":
        raise AudioContractError(
            "AUDIO_ASSET_SCOPE_MISMATCH",
            "The audio asset does not belong to the selected book",
            404,
        )
    if asset["lifecycle_status"] in {"soft_deleted", "rejected", "archived"}:
        raise AudioContractError("AUDIO_ASSET_UNAVAILABLE", "The audio asset is unavailable", 409)
    if require_approved and asset["lifecycle_status"] != "approved":
        raise AudioContractError(
            "REFERENCE_AUDIO_NOT_APPROVED",
            "Reference audio must be approved before it can define a voice profile",
            409,
        )
    return asset


def _validate_external_model(model_profile_id: str, capability: str) -> dict:
    profile = get_model_profile(model_profile_id)
    if not profile:
        raise AudioContractError("MODEL_PROFILE_NOT_FOUND", "Model profile was not found", 404)
    provider = get_provider(profile["provider_id"])
    if not profile["enabled"] or not provider or not provider["enabled"]:
        raise AudioContractError(
            "MODEL_PROFILE_DISABLED",
            "The selected external model profile is disabled",
            409,
        )
    if capability == "audio.tts" and provider["provider_type"] in {
        "local",
        "local_ollama",
        "ollama",
    }:
        raise AudioContractError(
            "OLLAMA_TTS_UNSUPPORTED",
            "Ollama does not expose the TTS input/output contract required by AetherDB",
            409,
        )
    model_type = str(profile.get("model_type") or "").strip().lower()
    if model_type not in MODEL_TYPES_BY_CAPABILITY[capability]:
        raise AudioContractError(
            "MODEL_CAPABILITY_UNCONFIRMED",
            "The selected model profile has not confirmed the required audio capability",
            409,
        )
    return profile


def _resolve_tts_target(
    *,
    database_id: str,
    book_id: str,
    chapter_id: str | None,
    operation: str,
    task_id: str,
    voice: dict,
    model_profile_id: str | None,
    package_id: str | None,
) -> tuple[str, str, object, str]:
    selected_profile_id = model_profile_id
    selected_package_id = package_id
    package_manifest = None

    if selected_package_id:
        package_manifest = _validate_native_package(selected_package_id, operation)
        if not package_manifest.model_profile_id:
            raise AudioContractError(
                "AUDIO_PACKAGE_ROUTE_MISSING",
                "The selected TTS package is not registered with the model router",
                409,
            )
        selected_profile_id = package_manifest.model_profile_id

    if voice["voice_kind"] == "native_voice":
        voice_manifest = _validate_native_package(voice["package_id"], operation)
        if not voice_manifest.model_profile_id:
            raise AudioContractError(
                "AUDIO_PACKAGE_ROUTE_MISSING",
                "The selected native voice package is not registered with the model router",
                409,
            )
        if selected_package_id and selected_package_id != voice["package_id"]:
            raise AudioContractError(
                "VOICE_EXECUTION_TARGET_MISMATCH",
                "Native voices must use the package stored by the voice profile",
                409,
            )
        if selected_profile_id and selected_profile_id != voice_manifest.model_profile_id:
            raise AudioContractError(
                "VOICE_EXECUTION_TARGET_MISMATCH",
                "Native voices must use their AetherDB-routed model profile",
                409,
            )
        selected_package_id = voice["package_id"]
        selected_profile_id = voice_manifest.model_profile_id
        package_manifest = voice_manifest
    elif voice["voice_kind"] == "provider_voice":
        if selected_package_id:
            raise AudioContractError(
                "VOICE_EXECUTION_TARGET_MISMATCH",
                "Provider voices cannot be executed by a native package",
                409,
            )
        if selected_profile_id and selected_profile_id != voice["model_profile_id"]:
            raise AudioContractError(
                "VOICE_EXECUTION_TARGET_MISMATCH",
                "Provider voices must use the model profile stored by the voice profile",
                409,
            )
        selected_profile_id = voice["model_profile_id"]
    if voice["voice_kind"] != "native_voice":
        raise AudioContractError(
            "TTS_VOICE_EXECUTOR_UNAVAILABLE",
            "The current AetherDB audio Worker supports routed native package voices only",
            409,
        )

    request = ModelTaskRequest(
        task_id=task_id,
        task_type=operation,
        database_id=database_id,
        book_id=book_id,
        chapter_id=chapter_id,
        messages=(
            {
                "role": "system",
                "content": "Resolve an AetherDB audio worker target without source text.",
            },
        ),
        user_selected_model_id=selected_profile_id,
        privacy_level="local_only",
        max_cost_level="medium",
        requires_json=False,
        requires_streaming=False,
        metadata={"ui_source": "audio_workbench"},
    )
    route = UniqueModelRouter().resolve(request)
    if route.status is not RouteStatus.RESOLVED:
        candidate_ids = ",".join(
            candidate.model_profile_id for candidate in route.candidates
        )
        code = {
            RouteStatus.AMBIGUOUS: "AUDIO_ROUTE_AMBIGUOUS",
            RouteStatus.BLOCKED: "AUDIO_ROUTE_BLOCKED",
            RouteStatus.UNAVAILABLE: "AUDIO_ROUTE_UNAVAILABLE",
        }.get(route.status, "AUDIO_ROUTE_UNAVAILABLE")
        message = f"TTS model route is {route.status.value}: {route.reason}"
        if candidate_ids:
            message = f"{message}; candidates={candidate_ids}"
        raise AudioContractError(code, message, 409)

    selected_profile_id = route.selected_model_profile_id
    profile = get_model_profile(selected_profile_id)
    provider = get_provider(profile["provider_id"]) if profile else None
    if not profile or not provider:
        raise AudioContractError(
            "AUDIO_ROUTE_UNAVAILABLE",
            "The routed TTS model profile is unavailable",
            409,
        )
    if provider["provider_type"] in {"local", "local_ollama", "ollama"}:
        raise AudioContractError(
            "OLLAMA_TTS_UNSUPPORTED",
            "Ollama does not expose the TTS input/output contract required by AetherDB",
            409,
        )
    if provider["provider_type"] != "aetherdb_worker":
        raise AudioContractError(
            "TTS_PROVIDER_EXECUTOR_UNAVAILABLE",
            "The selected TTS provider does not yet have an AetherDB audio executor",
            409,
        )
    routed_package = get_package_for_model_profile(selected_profile_id)
    if not routed_package:
        raise AudioContractError(
            "AUDIO_PACKAGE_ROUTE_MISSING",
            "The routed TTS profile is not backed by a trusted model package",
            409,
        )
    selected_package_id = routed_package["package_id"]
    package_manifest = _validate_native_package(selected_package_id, operation)
    return selected_profile_id, selected_package_id, package_manifest, route.reason


def _validate_native_package(package_id: str, operation: str):
    try:
        manifest = get_manifest(package_id)
    except KeyError as exc:
        raise AudioContractError(
            "AUDIO_PACKAGE_NOT_TRUSTED",
            "The native audio package is not in the trusted AetherDB catalog",
            404,
        ) from exc
    if operation not in set(manifest.capabilities):
        raise AudioContractError(
            "AUDIO_PACKAGE_CAPABILITY_MISMATCH",
            "The trusted package does not declare this audio operation",
            409,
        )
    return manifest


def _native_package_voices(package_id: str) -> set[str]:
    manifest = _validate_native_package(package_id, "audio.tts.segment")
    voices = {
        item.path.rsplit("/", 1)[-1].removesuffix(".pt")
        for item in manifest.files
        if item.role == "voice" and item.path.startswith("voices/")
    }
    if package_id == KOKORO_BASELINE_PACKAGE_ID:
        return voices & set(KOKORO_BASELINE_VOICE_LOCALES)
    return voices


def _native_voice_supports_locale(
    package_id: str,
    package_voice_name: str,
    locale: str,
) -> bool:
    if package_id != KOKORO_BASELINE_PACKAGE_ID:
        return True
    normalized = locale.strip().lower().replace("_", "-")
    primary = normalized.split("-", 1)[0]
    allowed = KOKORO_BASELINE_VOICE_LOCALES.get(package_voice_name, set())
    return normalized in allowed or primary in allowed


def _normalize_execution_config(value: dict | None) -> dict:
    raw = value or {}
    speed = float(raw.get("speed", DEFAULT_TTS_EXECUTION_CONFIG["speed"]))
    pause_ms = int(
        raw.get("segment_pause_ms", DEFAULT_TTS_EXECUTION_CONFIG["segment_pause_ms"])
    )
    peak_target = float(
        raw.get("peak_target", DEFAULT_TTS_EXECUTION_CONFIG["peak_target"])
    )
    if not 0.5 <= speed <= 2.0:
        raise AudioContractError("INVALID_TTS_SPEED", "TTS speed must be between 0.5 and 2.0", 400)
    if not 0 <= pause_ms <= 2_000:
        raise AudioContractError(
            "INVALID_SEGMENT_PAUSE",
            "TTS segment pause must be between 0 and 2000 milliseconds",
            400,
        )
    if not 0.1 <= peak_target <= 0.99:
        raise AudioContractError(
            "INVALID_PEAK_TARGET",
            "Audio peak target must be between 0.1 and 0.99",
            400,
        )
    return {
        "speed": round(speed, 4),
        "segment_pause_ms": pause_ms,
        "peak_target": round(peak_target, 4),
    }


def normalize_tts_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[\t\f\v ]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def get_audio_contract_status() -> dict:
    evidence = {"rocm_verified": False, "cuda_verified": False, "cpu_verified": False}
    try:
        from services.database_registry import _get_registry_conn

        conn = _get_registry_conn()
        rows = conn.execute(
            "SELECT backend,verification_status FROM model_runtime_evidence "
            "WHERE package_id='aetherdb.kokoro-82m'"
        ).fetchall()
        conn.close()
        evidence["rocm_verified"] = any(
            row["verification_status"] == "VERIFIED_ROCM" for row in rows
        )
        evidence["cuda_verified"] = any(
            row["verification_status"] == "VERIFIED_CUDA" for row in rows
        )
        evidence["cpu_verified"] = any(
            row["backend"] == "cpu" and row["verification_status"] == "TESTED"
            for row in rows
        )
    except (OSError, sqlite3.Error):
        pass
    return {
        "status": "execution_ready",
        "asset_management_available_without_model": True,
        "execution_implemented": True,
        "default_audio_model": None,
        "default_audio_embedding_model": None,
        "model_selection": {
            "mode": "per_task",
            "automatic_substitution": False,
            "lightweight_baseline_package_id": "aetherdb.kokoro-82m",
            "competition_candidate": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        },
        "operations": sorted(OPERATIONS),
        "capability_slots": [
            "audio.tts",
            "audio.asr",
            "audio.preview",
            "audio.enhance",
            "audio.merge",
            "audio.embedding",
        ],
        "waveform": {
            "format": "normalized_peak_envelope",
            "supported_input": "PCM WAV",
            "min_points": 32,
            "max_points": 4096,
        },
        "privacy": {
            "raw_audio_local_by_default": True,
            "cloud_upload_requires_future_explicit_consent": True,
            "reference_voice_requires_approved_asset_and_consent": True,
        },
        "routing": {
            "mode": "aetherdb_unique_model_router",
            "external_user_models_allowed": False,
            "approved_model_whitelist": False,
            "native_worker_trusted_packages_only": True,
            "native_package_selected_per_task": True,
            "ollama_tts_supported": False,
            "reason": (
                "Ollama has no stable TTS input/output contract; TTS resolves to "
                "AetherDB audio Worker model profiles"
            ),
        },
        "execution": {
            "api_process_loads_model_weights": False,
            "persistent_segment_tasks": True,
            "completed_segments_survive_retry": True,
            "segment_timeout_seconds": 180,
            "worker_slice_absolute_limit_seconds": 1800,
            "chapter_request_waits_for_completion": False,
        },
        "hardware_evidence": {
            **evidence,
            "quality_verified": False,
            "reason": (
                "Backend flags require recorded Worker probes; audio quality requires "
                "separate bilingual human review"
            ),
        },
    }


def _public_voice(row) -> dict:
    profile = dict(row)
    profile["consent_confirmed"] = bool(profile["consent_confirmed"])
    profile["enabled"] = bool(profile["enabled"])
    profile["metadata"] = _decode_json(profile.pop("metadata_json", None), {})
    if profile.get("package_id"):
        # Older databases retain provider_voice in the constrained storage
        # column. The package fields are authoritative for the public contract.
        profile["voice_kind"] = "native_voice"
    return profile


def create_voice_profile(payload: dict) -> dict:
    database_id = payload["database_id"]
    book_id = payload["book_id"]
    _validate_scope(database_id, book_id)
    voice_kind = payload["voice_kind"]
    model_profile_id = payload.get("model_profile_id")
    name = _clean_label(payload["name"], "voice profile name", max_length=100)
    locale = _clean_label(payload.get("locale", "und"), "voice profile locale", max_length=40)
    provider_voice_name = (
        _clean_label(
            payload["provider_voice_name"],
            "provider voice name",
            max_length=256,
        )
        if payload.get("provider_voice_name")
        else None
    )
    reference_asset_id = payload.get("reference_asset_id")
    package_id = payload.get("package_id")
    package_voice_name = (
        _clean_label(
            payload["package_voice_name"],
            "package voice name",
            max_length=128,
        )
        if payload.get("package_voice_name")
        else None
    )
    consent_confirmed = bool(payload.get("consent_confirmed", False))
    if voice_kind == "provider_voice":
        if not model_profile_id or not provider_voice_name:
            raise AudioContractError(
                "PROVIDER_VOICE_INCOMPLETE",
                "Provider voices require a model profile and provider voice name",
                400,
            )
        _validate_external_model(model_profile_id, "audio.tts")
        if reference_asset_id:
            raise AudioContractError(
                "PROVIDER_VOICE_REFERENCE_FORBIDDEN",
                "Provider voices do not accept a local reference asset",
                400,
            )
        if package_id or package_voice_name:
            raise AudioContractError(
                "PROVIDER_VOICE_PACKAGE_FORBIDDEN",
                "Provider voices cannot bind a native model package",
                400,
            )
    elif voice_kind == "local_reference":
        if not reference_asset_id or not consent_confirmed:
            raise AudioContractError(
                "REFERENCE_VOICE_CONSENT_REQUIRED",
                "A local reference voice requires an approved audio asset and explicit consent",
                409,
            )
        _validate_audio_asset(database_id, book_id, reference_asset_id, require_approved=True)
        if provider_voice_name:
            raise AudioContractError(
                "REFERENCE_VOICE_PROVIDER_NAME_FORBIDDEN",
                "Local reference voices do not use a provider voice name",
                400,
            )
        if model_profile_id:
            _validate_external_model(model_profile_id, "audio.tts")
        if package_id or package_voice_name:
            raise AudioContractError(
                "REFERENCE_VOICE_PACKAGE_FORBIDDEN",
                "Reference voices cannot bind a fixed native package voice",
                400,
            )
    elif voice_kind == "native_voice":
        if (
            not package_id
            or not package_voice_name
            or model_profile_id
            or provider_voice_name
            or reference_asset_id
            or consent_confirmed
        ):
            raise AudioContractError(
                "NATIVE_VOICE_INCOMPLETE",
                "Native voices require only a package id and package voice name",
                400,
            )
        voices = _native_package_voices(package_id)
        if package_voice_name not in voices:
            raise AudioContractError(
                "NATIVE_VOICE_NOT_DECLARED",
                "The selected native voice is not declared by this package",
                409,
            )
        if not _native_voice_supports_locale(package_id, package_voice_name, locale):
            raise AudioContractError(
                "NATIVE_VOICE_LOCALE_MISMATCH",
                "The selected native voice does not support this locale",
                409,
            )
    else:
        raise AudioContractError("INVALID_VOICE_KIND", "Unsupported voice profile kind", 400)

    now = _now()
    voice_profile_id = _id("voice")
    conn = get_db(database_id)
    try:
        conn.execute(
            """INSERT INTO audio_voice_profiles(
                voice_profile_id,database_id,book_id,name,locale,voice_kind,
                model_profile_id,provider_voice_name,reference_asset_id,
                consent_confirmed,enabled,metadata_json,created_at,updated_at,
                package_id,package_voice_name
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                voice_profile_id,
                database_id,
                book_id,
                name,
                locale,
                "provider_voice" if voice_kind == "native_voice" else voice_kind,
                model_profile_id,
                provider_voice_name,
                reference_asset_id,
                int(consent_confirmed),
                int(payload.get("enabled", True)),
                _json_object(payload.get("metadata")),
                now,
                now,
                package_id,
                package_voice_name,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM audio_voice_profiles WHERE voice_profile_id=?",
            (voice_profile_id,),
        ).fetchone()
    finally:
        conn.close()
    return _public_voice(row)


def get_voice_profile(database_id: str, voice_profile_id: str) -> dict:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT * FROM audio_voice_profiles WHERE database_id=? AND voice_profile_id=?",
            (database_id, voice_profile_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise AudioContractError("VOICE_PROFILE_NOT_FOUND", "Voice profile was not found", 404)
    return _public_voice(row)


def list_voice_profiles(
    database_id: str,
    *,
    book_id: str | None = None,
    enabled: bool | None = None,
) -> list[dict]:
    clauses = ["database_id=?"]
    params: list[object] = [database_id]
    if book_id:
        clauses.append("book_id=?")
        params.append(book_id)
    if enabled is not None:
        clauses.append("enabled=?")
        params.append(int(enabled))
    conn = get_db(database_id)
    try:
        rows = conn.execute(
            f"SELECT * FROM audio_voice_profiles WHERE {' AND '.join(clauses)} "
            "ORDER BY name,voice_profile_id",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_public_voice(row) for row in rows]


def update_voice_profile(
    database_id: str,
    voice_profile_id: str,
    updates: dict,
) -> dict:
    current = get_voice_profile(database_id, voice_profile_id)
    mutable = {"name", "locale", "enabled", "metadata"}
    clean = {key: value for key, value in updates.items() if key in mutable and value is not None}
    if not clean:
        return current
    columns: list[str] = []
    values: list[object] = []
    for key, value in clean.items():
        if key == "metadata":
            columns.append("metadata_json=?")
            values.append(_json_object(value))
        elif key == "enabled":
            columns.append("enabled=?")
            values.append(int(value))
        else:
            columns.append(f"{key}=?")
            values.append(
                _clean_label(
                    str(value),
                    "voice profile name" if key == "name" else "voice profile locale",
                    max_length=100 if key == "name" else 40,
                )
            )
    columns.append("updated_at=?")
    values.extend([_now(), database_id, voice_profile_id])
    conn = get_db(database_id)
    try:
        conn.execute(
            f"UPDATE audio_voice_profiles SET {','.join(columns)} "
            "WHERE database_id=? AND voice_profile_id=?",
            values,
        )
        conn.commit()
    finally:
        conn.close()
    return get_voice_profile(database_id, voice_profile_id)


def _chapter_source(database_id: str, book_id: str, chapter_id: str) -> tuple[str, str]:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT content,updated_at FROM chapters "
            "WHERE chapter_id=? AND book_id=? AND is_active=1",
            (chapter_id, book_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise AudioContractError("CHAPTER_NOT_FOUND", "Chapter was not found", 404)
    text = row["content"] or ""
    if not text.strip():
        raise AudioContractError("CHAPTER_TEXT_EMPTY", "Chapter text is empty", 409)
    return text, str(row["updated_at"] or "unversioned")


def _split_text(text: str) -> list[dict]:
    if not text.strip():
        raise AudioContractError("SOURCE_TEXT_EMPTY", "Source text is empty", 400)
    if "\x00" in text:
        raise AudioContractError("SOURCE_TEXT_INVALID", "Source text contains a null byte", 400)
    if len(text) > MAX_SOURCE_TEXT_CHARS:
        raise AudioContractError("SOURCE_TEXT_TOO_LARGE", "Source text is too large", 413)
    segments: list[dict] = []
    start = 0
    punctuation = "。！？!?；;\n"
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text):
            break
        limit = min(start + MAX_SEGMENT_CHARS, len(text))
        end = limit
        if limit < len(text):
            floor = start + MAX_SEGMENT_CHARS // 2
            candidates = [text.rfind(mark, floor, limit) for mark in punctuation]
            boundary = max(candidates)
            if boundary >= floor:
                end = boundary + 1
        while end > start and text[end - 1].isspace():
            end -= 1
        source = text[start:end]
        if source:
            segments.append(
                {
                    "segment_index": len(segments),
                    "source_text": source,
                    "source_text_hash": _hash_text(source),
                    "char_start": start,
                    "char_end": end,
                }
            )
        start = max(end, limit if end <= start else end)
        if len(segments) > MAX_SEGMENTS:
            raise AudioContractError("TOO_MANY_AUDIO_SEGMENTS", "Source text creates too many segments", 413)
    return segments


def create_pronunciation_entry(payload: dict) -> dict:
    database_id = payload["database_id"]
    book_id = payload["book_id"]
    _validate_scope(database_id, book_id)
    locale = _clean_label(payload.get("locale") or "und", "locale", max_length=40)
    term = _clean_label(payload["term"], "pronunciation term", max_length=160)
    pronunciation = _clean_label(
        payload["pronunciation"],
        "pronunciation value",
        max_length=512,
    )
    entry_kind = payload.get("entry_kind", "replacement")
    if entry_kind not in {"replacement", "kokoro_phoneme"}:
        raise AudioContractError(
            "INVALID_PRONUNCIATION_KIND",
            "Unsupported pronunciation entry kind",
            400,
        )
    if entry_kind == "kokoro_phoneme" and not locale.lower().startswith("en"):
        raise AudioContractError(
            "PHONEME_LOCALE_UNSUPPORTED",
            "Kokoro phoneme markup is supported only for English voice profiles",
            409,
        )
    now = _now()
    entry_id = _id("pronunciation")
    conn = get_db(database_id)
    try:
        conn.execute(
            """INSERT INTO audio_pronunciation_entries(
                entry_id,database_id,book_id,locale,term,pronunciation,
                entry_kind,enabled,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                entry_id,
                database_id,
                book_id,
                locale,
                term,
                pronunciation,
                entry_kind,
                int(payload.get("enabled", True)),
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM audio_pronunciation_entries WHERE entry_id=?",
            (entry_id,),
        ).fetchone()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise AudioContractError(
            "PRONUNCIATION_ENTRY_EXISTS",
            "A pronunciation entry already exists for this locale and term",
            409,
        ) from exc
    finally:
        conn.close()
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    return result


def list_pronunciation_entries(
    database_id: str,
    *,
    book_id: str,
    locale: str | None = None,
    enabled: bool | None = None,
) -> list[dict]:
    _validate_scope(database_id, book_id)
    clauses = ["database_id=?", "book_id=?"]
    params: list[object] = [database_id, book_id]
    if locale:
        clauses.append("locale=?")
        params.append(locale)
    if enabled is not None:
        clauses.append("enabled=?")
        params.append(int(enabled))
    conn = get_db(database_id)
    try:
        rows = conn.execute(
            f"SELECT * FROM audio_pronunciation_entries "
            f"WHERE {' AND '.join(clauses)} ORDER BY locale,term,entry_id",
            params,
        ).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        result.append(item)
    return result


def update_pronunciation_entry(
    database_id: str,
    entry_id: str,
    updates: dict,
) -> dict:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT * FROM audio_pronunciation_entries "
            "WHERE database_id=? AND entry_id=?",
            (database_id, entry_id),
        ).fetchone()
        if not row:
            raise AudioContractError(
                "PRONUNCIATION_ENTRY_NOT_FOUND",
                "Pronunciation entry was not found",
                404,
            )
        locale = _clean_label(
            str(updates.get("locale", row["locale"])),
            "locale",
            max_length=40,
        )
        term = _clean_label(
            str(updates.get("term", row["term"])),
            "pronunciation term",
            max_length=160,
        )
        pronunciation = _clean_label(
            str(updates.get("pronunciation", row["pronunciation"])),
            "pronunciation value",
            max_length=512,
        )
        entry_kind = updates.get("entry_kind", row["entry_kind"])
        if entry_kind not in {"replacement", "kokoro_phoneme"}:
            raise AudioContractError(
                "INVALID_PRONUNCIATION_KIND",
                "Unsupported pronunciation entry kind",
                400,
            )
        if entry_kind == "kokoro_phoneme" and not locale.lower().startswith("en"):
            raise AudioContractError(
                "PHONEME_LOCALE_UNSUPPORTED",
                "Kokoro phoneme markup is supported only for English voice profiles",
                409,
            )
        conn.execute(
            """UPDATE audio_pronunciation_entries
                  SET locale=?,term=?,pronunciation=?,entry_kind=?,enabled=?,
                      updated_at=?
                WHERE database_id=? AND entry_id=?""",
            (
                locale,
                term,
                pronunciation,
                entry_kind,
                int(updates.get("enabled", bool(row["enabled"]))),
                _now(),
                database_id,
                entry_id,
            ),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM audio_pronunciation_entries WHERE entry_id=?",
            (entry_id,),
        ).fetchone()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise AudioContractError(
            "PRONUNCIATION_ENTRY_EXISTS",
            "A pronunciation entry already exists for this locale and term",
            409,
        ) from exc
    finally:
        conn.close()
    result = dict(updated)
    result["enabled"] = bool(result["enabled"])
    return result


def delete_pronunciation_entry(database_id: str, entry_id: str) -> dict:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT book_id FROM audio_pronunciation_entries "
            "WHERE database_id=? AND entry_id=?",
            (database_id, entry_id),
        ).fetchone()
        if not row:
            raise AudioContractError(
                "PRONUNCIATION_ENTRY_NOT_FOUND",
                "Pronunciation entry was not found",
                404,
            )
        conn.execute(
            "DELETE FROM audio_pronunciation_entries "
            "WHERE database_id=? AND entry_id=?",
            (database_id, entry_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "entry_id": entry_id, "book_id": row["book_id"]}


def _pronunciation_snapshot(
    database_id: str,
    book_id: str,
    locale: str,
) -> tuple[list[dict], str]:
    conn = get_db(database_id)
    try:
        rows = conn.execute(
            """SELECT entry_id,locale,term,pronunciation,entry_kind,updated_at
                 FROM audio_pronunciation_entries
                WHERE database_id=? AND book_id=? AND enabled=1
                  AND locale IN (?, 'und')
                ORDER BY CASE WHEN locale=? THEN 0 ELSE 1 END,term,entry_id""",
            (database_id, book_id, locale, locale),
        ).fetchall()
    finally:
        conn.close()
    by_term: dict[str, dict] = {}
    for row in rows:
        item = dict(row)
        by_term.setdefault(item["term"], item)
    snapshot = sorted(by_term.values(), key=lambda item: (item["term"], item["entry_id"]))
    encoded = json.dumps(
        snapshot,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return snapshot, _hash_text(encoded)


def apply_pronunciation_snapshot(text: str, snapshot: list[dict]) -> str:
    rendered = normalize_tts_text(text)
    for entry in sorted(
        snapshot,
        key=lambda item: (-len(item["term"]), item["term"], item["entry_id"]),
    ):
        replacement = entry["pronunciation"]
        if entry["entry_kind"] == "kokoro_phoneme":
            replacement = f"[{entry['term']}](/{entry['pronunciation']}/)"
        rendered = rendered.replace(entry["term"], replacement)
    return rendered


def _public_task(row) -> dict:
    task = dict(row)
    task["storage_model_profile_id"] = task.get("model_profile_id")
    task["model_profile_id"] = (
        task.get("route_model_profile_id") or task.get("model_profile_id")
    )
    task["input_asset_ids"] = _decode_json(task.pop("input_asset_ids_json", None), [])
    task["execution_config"] = _decode_json(
        task.pop("execution_config_json", None),
        DEFAULT_TTS_EXECUTION_CONFIG,
    )
    snapshot = _decode_json(task.pop("dictionary_snapshot_json", None), [])
    task["dictionary_entry_count"] = len(snapshot)
    task["cancel_requested"] = bool(task.get("cancel_requested", False))
    task["progress"] = float(task.get("progress") or 0)
    return task


def append_audio_task_event(
    database_id: str,
    task_id: str,
    event_type: str,
    payload: dict | None = None,
) -> dict:
    safe_payload = dict(payload or {})
    safe_payload.pop("source_text", None)
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute(
            "SELECT 1 FROM audio_tasks WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone():
            raise AudioContractError("AUDIO_TASK_NOT_FOUND", "Audio task was not found", 404)
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM audio_task_events WHERE task_id=?",
            (task_id,),
        ).fetchone()[0]
        event = {
            "event_id": _id("audio-event"),
            "task_id": task_id,
            "sequence": int(sequence),
            "event_type": _clean_label(event_type, "event type", max_length=80),
            "payload_json": _json_object(safe_payload),
            "created_at": _now(),
        }
        conn.execute(
            """INSERT INTO audio_task_events(
                event_id,task_id,sequence,event_type,payload_json,created_at
            ) VALUES (?,?,?,?,?,?)""",
            tuple(event.values()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    event["payload"] = _decode_json(event.pop("payload_json"), {})
    return event


def list_audio_task_events(
    database_id: str,
    task_id: str,
    *,
    after_sequence: int = 0,
    limit: int = 500,
) -> list[dict]:
    conn = get_db(database_id)
    try:
        if not conn.execute(
            "SELECT 1 FROM audio_tasks WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone():
            raise AudioContractError("AUDIO_TASK_NOT_FOUND", "Audio task was not found", 404)
        rows = conn.execute(
            "SELECT * FROM audio_task_events WHERE task_id=? AND sequence>? "
            "ORDER BY sequence LIMIT ?",
            (task_id, max(0, after_sequence), max(1, min(limit, 2_000))),
        ).fetchall()
    finally:
        conn.close()
    events = []
    for row in rows:
        event = dict(row)
        event["payload"] = _decode_json(event.pop("payload_json"), {})
        events.append(event)
    return events


def _mark_task_outdated(conn, task_id: str) -> None:
    conn.execute(
        "UPDATE audio_tasks SET status='outdated',updated_at=? "
        "WHERE task_id=? AND status NOT IN ('cancelled','failed','outdated')",
        (_now(), task_id),
    )
    conn.execute(
        "UPDATE audio_task_segments SET status='outdated',updated_at=? "
        "WHERE task_id=? AND status NOT IN ('cancelled','failed','outdated')",
        (_now(), task_id),
    )
    conn.execute(
        "UPDATE audio_task_results SET approval_status='outdated' "
        "WHERE task_id=? AND approval_status!='outdated'",
        (task_id,),
    )
    conn.execute(
        "UPDATE audio_asset_outputs SET freshness='outdated' WHERE task_id=?",
        (task_id,),
    )


def _refresh_task(database_id: str, task_id: str) -> None:
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM audio_tasks WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone()
        if not row:
            raise AudioContractError("AUDIO_TASK_NOT_FOUND", "Audio task was not found", 404)
        if row["chapter_id"] and row["source_text_hash"] and row["status"] != "outdated":
            chapter = conn.execute(
                "SELECT content FROM chapters WHERE chapter_id=? AND book_id=?",
                (row["chapter_id"], row["book_id"]),
            ).fetchone()
            if chapter and _hash_text(chapter["content"] or "") != row["source_text_hash"]:
                _mark_task_outdated(conn, task_id)
                row = conn.execute(
                    "SELECT * FROM audio_tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
        if row["output_asset_id"] and row["status"] in {"pending_review", "completed"}:
            output_asset = conn.execute(
                "SELECT lifecycle_status FROM media_assets WHERE asset_id=?",
                (row["output_asset_id"],),
            ).fetchone()
            if not output_asset or output_asset["lifecycle_status"] == "soft_deleted":
                conn.execute(
                    "UPDATE audio_tasks SET status='failed',error_code='OUTPUT_UNAVAILABLE',"
                    "error_message='The audio output is unavailable',updated_at=? WHERE task_id=?",
                    (_now(), task_id),
                )
                row = conn.execute(
                    "SELECT * FROM audio_tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
        if row["status"] == "pending_review":
            if row["operation"] == "audio.asr.transcribe":
                approved = conn.execute(
                    "SELECT 1 FROM audio_task_results "
                    "WHERE task_id=? AND approval_status='approved' LIMIT 1",
                    (task_id,),
                ).fetchone()
                if approved:
                    conn.execute(
                        "UPDATE audio_tasks SET status='completed',completed_at=?,updated_at=? "
                        "WHERE task_id=?",
                        (_now(), _now(), task_id),
                    )
            elif row["output_asset_id"]:
                asset = conn.execute(
                    "SELECT lifecycle_status FROM media_assets WHERE asset_id=?",
                    (row["output_asset_id"],),
                ).fetchone()
                if asset and asset["lifecycle_status"] == "approved":
                    conn.execute(
                        "UPDATE audio_tasks SET status='completed',completed_at=?,updated_at=? "
                        "WHERE task_id=?",
                        (_now(), _now(), task_id),
                    )
                elif asset and asset["lifecycle_status"] == "rejected":
                    conn.execute(
                        "UPDATE audio_tasks SET status='failed',error_code='OUTPUT_REJECTED',"
                        "error_message='The audio output was rejected',updated_at=? WHERE task_id=?",
                        (_now(), task_id),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_audio_task(payload: dict) -> dict:
    database_id = payload["database_id"]
    book_id = payload["book_id"]
    operation = payload["operation"]
    _validate_scope(database_id, book_id)
    if operation not in OPERATIONS:
        raise AudioContractError("INVALID_AUDIO_OPERATION", "Unsupported audio operation", 400)
    task_id = _id("audio-task")
    capability = CAPABILITY_BY_OPERATION[operation]
    model_profile_id = payload.get("model_profile_id")
    package_id = payload.get("package_id")
    package_manifest = None
    route_reason = None
    if model_profile_id and package_id:
        raise AudioContractError("MULTIPLE_EXECUTION_TARGETS", "Choose one execution target", 400)
    target_kind = "unresolved"
    if model_profile_id and not operation.startswith("audio.tts"):
        _validate_external_model(model_profile_id, capability)
        target_kind = "external_provider"
    elif package_id and not operation.startswith("audio.tts"):
        package_manifest = _validate_native_package(package_id, operation)
        target_kind = "native_package"

    voice_profile_id = payload.get("voice_profile_id")
    chapter_id = payload.get("chapter_id")
    source_text = payload.get("source_text") or ""
    source_revision = payload.get("source_revision")
    source_asset_ids = list(dict.fromkeys(payload.get("source_asset_ids") or []))
    segments: list[dict] = []
    if operation == "audio.tts.chapter":
        if not chapter_id or source_text or source_asset_ids:
            raise AudioContractError(
                "INVALID_TTS_CHAPTER_SOURCE",
                "Chapter TTS requires one chapter_id and no client text or source assets",
                400,
            )
        source_text, source_revision = _chapter_source(database_id, book_id, chapter_id)
        segments = _split_text(source_text)
    elif operation == "audio.tts.segment":
        if source_asset_ids or not source_text.strip():
            raise AudioContractError(
                "INVALID_TTS_SEGMENT_SOURCE",
                "Segment TTS requires source_text and no source assets",
                400,
            )
        if chapter_id:
            _, current_revision = _chapter_source(database_id, book_id, chapter_id)
            source_revision = source_revision or current_revision
        segments = _split_text(source_text)
        if len(segments) != 1:
            raise AudioContractError(
                "TTS_SEGMENT_TOO_LARGE",
                f"Segment TTS accepts at most {MAX_SEGMENT_CHARS} characters",
                413,
            )
    elif operation in {"audio.asr.transcribe", "audio.preview", "audio.enhance"}:
        if len(source_asset_ids) != 1 or source_text or voice_profile_id:
            raise AudioContractError(
                "INVALID_AUDIO_SOURCE",
                "This operation requires exactly one source audio asset",
                400,
            )
    elif operation == "audio.merge":
        if not 2 <= len(source_asset_ids) <= 64 or source_text or voice_profile_id:
            raise AudioContractError(
                "INVALID_AUDIO_MERGE_SOURCE",
                "Audio merge requires between 2 and 64 source audio assets",
                400,
            )

    if operation.startswith("audio.tts"):
        if not voice_profile_id:
            raise AudioContractError("VOICE_PROFILE_REQUIRED", "TTS requires a voice profile", 400)
        voice = get_voice_profile(database_id, voice_profile_id)
        if voice["book_id"] != book_id or not voice["enabled"]:
            raise AudioContractError("VOICE_PROFILE_UNAVAILABLE", "Voice profile is unavailable", 409)
        (
            model_profile_id,
            package_id,
            package_manifest,
            route_reason,
        ) = _resolve_tts_target(
            database_id=database_id,
            book_id=book_id,
            chapter_id=chapter_id,
            operation=operation,
            task_id=task_id,
            voice=voice,
            model_profile_id=model_profile_id,
            package_id=package_id,
        )
        target_kind = "native_package"

    for asset_id in source_asset_ids:
        _validate_audio_asset(database_id, book_id, asset_id)

    execution_config = (
        _normalize_execution_config(payload.get("execution_config"))
        if operation.startswith("audio.tts")
        else {}
    )
    dictionary_snapshot: list[dict] = []
    dictionary_hash = None
    voice_locale = "und"
    if operation.startswith("audio.tts"):
        voice_locale = voice["locale"]
        dictionary_snapshot, dictionary_hash = _pronunciation_snapshot(
            database_id,
            book_id,
            voice_locale,
        )
    if package_id and package_manifest is None:
        package_manifest = _validate_native_package(package_id, operation)

    whole_source_hash = _hash_text(source_text) if source_text else None
    now = _now()
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO audio_tasks(
                task_id,database_id,book_id,operation,required_capability,status,
                target_kind,chapter_id,source_revision,source_text_hash,
                input_asset_ids_json,voice_profile_id,model_profile_id,package_id,
                requested_backend,created_at,updated_at,progress,cancel_requested,
                execution_config_json,dictionary_snapshot_json,dictionary_hash,
                normalization_version,model_package_version,model_revision,
                route_model_profile_id
            ) VALUES (?,?,?,?,?,'planned',?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?,?,?,?,?)""",
            (
                task_id,
                database_id,
                book_id,
                operation,
                capability,
                target_kind,
                chapter_id,
                source_revision,
                whole_source_hash,
                json.dumps(source_asset_ids, ensure_ascii=True),
                voice_profile_id,
                model_profile_id if target_kind == "external_provider" else None,
                package_id,
                payload.get("requested_backend", "auto"),
                now,
                now,
                json.dumps(execution_config, ensure_ascii=True, sort_keys=True),
                json.dumps(dictionary_snapshot, ensure_ascii=True, sort_keys=True),
                dictionary_hash,
                NORMALIZATION_VERSION,
                package_manifest.package_version if package_manifest else None,
                package_manifest.source.revision if package_manifest else None,
                model_profile_id,
            ),
        )
        for segment in segments:
            normalized_text = apply_pronunciation_snapshot(
                segment["source_text"],
                dictionary_snapshot,
            )
            deterministic_payload = {
                "source_text_hash": segment["source_text_hash"],
                "normalized_text_hash": _hash_text(normalized_text),
                "normalization_version": NORMALIZATION_VERSION,
                "dictionary_hash": dictionary_hash,
                "voice_profile_id": voice_profile_id,
                "voice_locale": voice_locale,
                "model_profile_id": model_profile_id,
                "package_id": package_id,
                "package_version": (
                    package_manifest.package_version if package_manifest else None
                ),
                "model_revision": (
                    package_manifest.source.revision if package_manifest else None
                ),
                "execution_config": execution_config,
            }
            deterministic_key = _hash_text(
                json.dumps(
                    deterministic_payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            conn.execute(
                """INSERT INTO audio_task_segments(
                    segment_id,task_id,segment_index,source_text,source_text_hash,
                    char_start,char_end,status,created_at,updated_at,
                    deterministic_key,normalized_text_hash
                ) VALUES (?,?,?,?,?,?,?,'planned',?,?,?,?)""",
                (
                    _id("audio-segment"),
                    task_id,
                    segment["segment_index"],
                    segment["source_text"],
                    segment["source_text_hash"],
                    segment["char_start"],
                    segment["char_end"],
                    now,
                    now,
                    deterministic_key,
                    _hash_text(normalized_text),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    append_audio_task_event(
        database_id,
        task_id,
        "queued" if target_kind == "native_package" else "planned",
        {
            "status": "planned",
            "target_kind": target_kind,
            "segment_count": len(segments),
            "model_profile_id": model_profile_id,
            "package_id": package_id,
            "route_reason": route_reason,
        },
    )
    if (
        target_kind == "native_package"
        and operation in {"audio.tts.chapter", "audio.tts.segment"}
        and payload.get("start_execution", True)
    ):
        from services.tts_execution import enqueue_audio_task

        enqueue_audio_task(database_id, task_id)
    return get_audio_task(database_id, task_id, include_source_text=False)


def get_audio_task(
    database_id: str,
    task_id: str,
    *,
    include_source_text: bool = False,
    include_result_text: bool = False,
) -> dict:
    _refresh_task(database_id, task_id)
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT * FROM audio_tasks WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone()
        segment_columns = (
            "*" if include_source_text else
            "segment_id,task_id,segment_index,source_text_hash,char_start,char_end,"
            "status,output_asset_id,duration_ms,attempts,error_code,error_message,"
            "deterministic_key,normalized_text_hash,runtime_job_id,effective_backend,"
            "generated_at,created_at,updated_at"
        )
        segments = conn.execute(
            f"SELECT {segment_columns} FROM audio_task_segments "
            "WHERE task_id=? ORDER BY segment_index",
            (task_id,),
        ).fetchall()
        result_columns = (
            "*" if include_result_text else
            "result_id,task_id,segment_id,result_type,content_hash,metadata_json,"
            "approval_status,created_at,reviewed_at"
        )
        results = conn.execute(
            f"SELECT {result_columns} FROM audio_task_results "
            "WHERE task_id=? ORDER BY created_at,result_id",
            (task_id,),
        ).fetchall()
        outputs = conn.execute(
            "SELECT * FROM audio_asset_outputs WHERE task_id=? ORDER BY created_at,output_id",
            (task_id,),
        ).fetchall()
    finally:
        conn.close()
    if not row:
        raise AudioContractError("AUDIO_TASK_NOT_FOUND", "Audio task was not found", 404)
    task = _public_task(row)
    task["segments"] = [dict(segment) for segment in segments]
    task["results"] = []
    for result in results:
        item = dict(result)
        item["metadata"] = _decode_json(item.pop("metadata_json", None), {})
        task["results"].append(item)
    task["outputs"] = [dict(output) for output in outputs]
    return task


def list_audio_tasks(
    database_id: str,
    *,
    book_id: str | None = None,
    chapter_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    if status and status not in TASK_STATUSES:
        raise AudioContractError("INVALID_AUDIO_TASK_STATUS", "Invalid audio task status", 400)
    clauses = ["database_id=?"]
    params: list[object] = [database_id]
    if book_id:
        clauses.append("book_id=?")
        params.append(book_id)
    if chapter_id:
        clauses.append("chapter_id=?")
        params.append(chapter_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    conn = get_db(database_id)
    try:
        now = _now()
        conn.execute(
            """UPDATE audio_tasks
                  SET status='completed',completed_at=?,updated_at=?
                WHERE database_id=? AND status='pending_review'
                  AND (
                    (
                      operation='audio.asr.transcribe'
                      AND EXISTS(
                        SELECT 1 FROM audio_task_results r
                         WHERE r.task_id=audio_tasks.task_id
                           AND r.approval_status='approved'
                      )
                    )
                    OR
                    (
                      operation!='audio.asr.transcribe'
                      AND output_asset_id IN (
                        SELECT asset_id FROM media_assets WHERE lifecycle_status='approved'
                      )
                    )
                  )""",
            (now, now, database_id),
        )
        conn.commit()
        total = conn.execute(
            f"SELECT COUNT(*) FROM audio_tasks WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM audio_tasks WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC,task_id LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
    finally:
        conn.close()
    return {"tasks": [_public_task(row) for row in rows], "total": total}


def cancel_audio_task(database_id: str, task_id: str) -> dict:
    task = get_audio_task(database_id, task_id)
    if task["status"] in TERMINAL_TASK_STATUSES:
        if task["status"] == "cancelled":
            return task
        raise AudioContractError("AUDIO_TASK_TERMINAL", "Completed or stale audio tasks cannot be cancelled", 409)
    now = _now()
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE audio_tasks SET status='cancelled',cancel_requested=1,"
            "progress=CASE WHEN progress<1 THEN progress ELSE 1 END,updated_at=? "
            "WHERE task_id=?",
            (now, task_id),
        )
        conn.execute(
            "UPDATE audio_task_segments SET status='cancelled',updated_at=? "
            "WHERE task_id=? AND status='planned'",
            (now, task_id),
        )
        conn.commit()
    finally:
        conn.close()
    if task.get("runtime_job_id"):
        try:
            from services.model_runtime.manager import get_worker_manager

            get_worker_manager().cancel_job(task["runtime_job_id"])
        except (KeyError, RuntimeError):
            pass
    append_audio_task_event(
        database_id,
        task_id,
        "cancelled",
        {"status": "cancelled"},
    )
    return get_audio_task(database_id, task_id)


def retry_failed_audio_task(database_id: str, task_id: str) -> dict:
    task = get_audio_task(database_id, task_id)
    if task["target_kind"] != "native_package" or task["operation"] not in {
        "audio.tts.chapter",
        "audio.tts.segment",
    }:
        raise AudioContractError(
            "AUDIO_RETRY_NOT_EXECUTABLE",
            "Only native TTS execution tasks can be retried by this worker",
            409,
        )
    if task["status"] != "failed":
        raise AudioContractError(
            "AUDIO_TASK_NOT_FAILED",
            "Only failed audio tasks can retry failed segments",
            409,
        )
    failed = [item for item in task["segments"] if item["status"] == "failed"]
    if not failed:
        raise AudioContractError(
            "NO_FAILED_AUDIO_SEGMENTS",
            "The audio task has no failed segments",
            409,
        )
    now = _now()
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "UPDATE audio_task_segments SET status='planned',error_code=NULL,"
            "error_message=NULL,runtime_job_id=NULL,updated_at=? "
            "WHERE task_id=? AND segment_id=? AND status='failed'",
            ((now, task_id, item["segment_id"]) for item in failed),
        )
        completed = conn.execute(
            "SELECT COUNT(*) FROM audio_task_segments "
            "WHERE task_id=? AND status='completed'",
            (task_id,),
        ).fetchone()[0]
        total = max(1, len(task["segments"]))
        conn.execute(
            "UPDATE audio_tasks SET status='planned',cancel_requested=0,"
            "progress=?,runtime_job_id=NULL,error_code=NULL,error_message=NULL,"
            "completed_at=NULL,heartbeat_at=?,updated_at=? WHERE task_id=?",
            (completed / total, now, now, task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    append_audio_task_event(
        database_id,
        task_id,
        "retry",
        {
            "status": "planned",
            "failed_segment_count": len(failed),
            "completed_segment_count": completed,
        },
    )
    from services.tts_execution import enqueue_audio_task

    enqueue_audio_task(database_id, task_id)
    return get_audio_task(database_id, task_id)


def register_audio_output(database_id: str, task_id: str, payload: dict) -> dict:
    task = get_audio_task(database_id, task_id)
    if task["status"] in TERMINAL_TASK_STATUSES:
        raise AudioContractError("AUDIO_TASK_TERMINAL", "This audio task no longer accepts outputs", 409)
    if payload["output_kind"] not in OUTPUT_KINDS_BY_OPERATION[task["operation"]]:
        raise AudioContractError(
            "AUDIO_OUTPUT_KIND_MISMATCH",
            "The output kind is not valid for this audio operation",
            400,
        )
    asset = _validate_audio_asset(database_id, task["book_id"], payload["asset_id"])
    segment_id = payload.get("segment_id")
    segment_source_hash = task["source_text_hash"]
    if segment_id:
        segment = next((item for item in task["segments"] if item["segment_id"] == segment_id), None)
        if not segment:
            raise AudioContractError("AUDIO_SEGMENT_NOT_FOUND", "Audio task segment was not found", 404)
        segment_source_hash = segment["source_text_hash"]
    elif payload["output_kind"] == "segment":
        raise AudioContractError("AUDIO_SEGMENT_REQUIRED", "Segment output requires segment_id", 400)
    duration_ms = round(float(asset.get("metadata", {}).get("duration_seconds", 0)) * 1000)
    output_id = _id("audio-output")
    now = _now()
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO audio_asset_outputs(
                output_id,task_id,segment_id,asset_id,output_kind,source_text_hash,
                source_revision,voice_profile_id,freshness,created_at
            ) VALUES (?,?,?,?,?,?,?,?, 'current',?)""",
            (
                output_id,
                task_id,
                segment_id,
                asset["asset_id"],
                payload["output_kind"],
                segment_source_hash,
                task["source_revision"],
                task["voice_profile_id"],
                now,
            ),
        )
        if segment_id:
            conn.execute(
                "UPDATE audio_task_segments SET status='completed',output_asset_id=?,"
                "duration_ms=?,updated_at=? WHERE segment_id=? AND task_id=?",
                (asset["asset_id"], duration_ms, now, segment_id, task_id),
            )
        is_final = payload["output_kind"] in {"preview", "final", "merged", "enhanced"}
        if task["operation"] == "audio.tts.segment" and payload["output_kind"] == "segment":
            is_final = True
        if is_final:
            conn.execute(
                "UPDATE audio_tasks SET status='pending_review',output_asset_id=?,updated_at=? "
                "WHERE task_id=?",
                (asset["asset_id"], now, task_id),
            )
        else:
            conn.execute(
                "UPDATE audio_tasks SET status='in_progress',updated_at=? WHERE task_id=?",
                (now, task_id),
            )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise AudioContractError("AUDIO_OUTPUT_EXISTS", "This audio output is already registered", 409) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_audio_task(database_id, task_id)


def register_audio_result(database_id: str, task_id: str, payload: dict) -> dict:
    task = get_audio_task(database_id, task_id)
    if task["status"] in TERMINAL_TASK_STATUSES:
        raise AudioContractError("AUDIO_TASK_TERMINAL", "This audio task no longer accepts results", 409)
    if task["operation"] != "audio.asr.transcribe":
        raise AudioContractError(
            "AUDIO_TEXT_RESULT_NOT_SUPPORTED",
            "Only ASR tasks accept transcript results in this contract",
            409,
        )
    if payload.get("segment_id"):
        segment = next(
            (item for item in task["segments"] if item["segment_id"] == payload["segment_id"]),
            None,
        )
        if not segment:
            raise AudioContractError("AUDIO_SEGMENT_NOT_FOUND", "Audio task segment was not found", 404)
    content = payload.get("content_text", "")
    if not content.strip():
        raise AudioContractError("AUDIO_RESULT_EMPTY", "Transcript result is empty", 400)
    if "\x00" in content:
        raise AudioContractError("AUDIO_RESULT_INVALID", "Transcript contains a null byte", 400)
    result_id = _id("audio-result")
    now = _now()
    conn = get_db(database_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO audio_task_results(
                result_id,task_id,segment_id,result_type,content_text,content_hash,
                metadata_json,approval_status,created_at
            ) VALUES (?,?,?,?,?,?,?,'pending_review',?)""",
            (
                result_id,
                task_id,
                payload.get("segment_id"),
                payload.get("result_type", "transcript"),
                content,
                _hash_text(content),
                _json_object(payload.get("metadata")),
                now,
            ),
        )
        conn.execute(
            "UPDATE audio_tasks SET status='pending_review',updated_at=? WHERE task_id=?",
            (now, task_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_audio_task(database_id, task_id, include_result_text=True)


def review_audio_result(
    database_id: str,
    result_id: str,
    *,
    approved: bool,
) -> dict:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT r.*,t.database_id FROM audio_task_results r "
            "JOIN audio_tasks t ON t.task_id=r.task_id "
            "WHERE t.database_id=? AND r.result_id=?",
            (database_id, result_id),
        ).fetchone()
        if not row:
            raise AudioContractError("AUDIO_RESULT_NOT_FOUND", "Audio result was not found", 404)
        if row["approval_status"] == "outdated":
            raise AudioContractError("AUDIO_RESULT_OUTDATED", "Outdated audio results cannot be approved", 409)
        status = "approved" if approved else "rejected"
        conn.execute(
            "UPDATE audio_task_results SET approval_status=?,reviewed_at=? WHERE result_id=?",
            (status, _now(), result_id),
        )
        if approved:
            conn.execute(
                "UPDATE audio_tasks SET status='completed',completed_at=?,updated_at=? "
                "WHERE task_id=? AND status!='outdated'",
                (_now(), _now(), row["task_id"]),
            )
        else:
            conn.execute(
                "UPDATE audio_tasks SET status='failed',error_code='RESULT_REJECTED',"
                "error_message='The audio result was rejected',updated_at=? WHERE task_id=?",
                (_now(), row["task_id"]),
            )
        conn.commit()
        task_id = row["task_id"]
    finally:
        conn.close()
    return get_audio_task(database_id, task_id, include_result_text=True)


def get_audio_asset_contract(database_id: str, asset_id: str) -> dict:
    try:
        asset = get_media_asset(database_id, asset_id, include_related=True)
    except MediaAssetError as exc:
        raise AudioContractError(exc.code, exc.message, exc.status_code) from exc
    if asset["modality"] != "audio":
        raise AudioContractError("NOT_AUDIO_ASSET", "The selected media asset is not audio", 415)
    conn = get_db(database_id)
    try:
        outputs = [
            dict(row)
            for row in conn.execute(
                "SELECT output_id,task_id,segment_id,output_kind,source_text_hash,"
                "source_revision,voice_profile_id,freshness,created_at "
                "FROM audio_asset_outputs WHERE asset_id=? ORDER BY created_at,output_id",
                (asset_id,),
            )
        ]
    finally:
        conn.close()
    return {
        "asset": asset,
        "audio": {
            "duration_ms": round(float(asset.get("metadata", {}).get("duration_seconds", 0)) * 1000),
            "sample_rate": asset.get("metadata", {}).get("sample_rate"),
            "channels": asset.get("metadata", {}).get("channels"),
            "waveform_available": asset["mime_type"] == "audio/wav",
            "outdated": any(item["freshness"] == "outdated" for item in outputs),
            "outputs": outputs,
        },
    }


def _sample_peak(raw: bytes, sample_width: int) -> float:
    if not raw:
        return 0.0
    if sample_width == 1:
        return max(abs(value - 128) for value in raw) / 128.0
    if sample_width == 2:
        peak = max((abs(value[0]) for value in struct.iter_unpack("<h", raw)), default=0)
        return peak / 32768.0
    if sample_width == 3:
        peak = 0
        for offset in range(0, len(raw) - 2, 3):
            value = int.from_bytes(raw[offset : offset + 3], "little", signed=True)
            peak = max(peak, abs(value))
        return peak / 8_388_608.0
    if sample_width == 4:
        peak = max((abs(value[0]) for value in struct.iter_unpack("<i", raw)), default=0)
        return peak / 2_147_483_648.0
    raise AudioContractError("WAVEFORM_SAMPLE_WIDTH_UNSUPPORTED", "Unsupported PCM sample width", 422)


def get_audio_waveform(database_id: str, asset_id: str, *, points: int = 512) -> dict:
    try:
        path, asset = get_media_content(database_id, asset_id)
    except MediaAssetError as exc:
        raise AudioContractError(exc.code, exc.message, exc.status_code) from exc
    if asset["modality"] != "audio":
        raise AudioContractError("NOT_AUDIO_ASSET", "The selected media asset is not audio", 415)
    if asset["mime_type"] != "audio/wav":
        raise AudioContractError(
            "WAVEFORM_DECODER_UNAVAILABLE",
            "Waveform extraction currently supports PCM WAV assets",
            422,
        )
    points = max(32, min(int(points), 4096))
    try:
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise AudioContractError(
                    "WAVEFORM_CODEC_UNSUPPORTED",
                    "Waveform extraction requires uncompressed PCM WAV",
                    422,
                )
            frame_count = source.getnframes()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            bucket_count = min(points, max(1, frame_count))
            frames_per_bucket = max(1, math.ceil(frame_count / bucket_count))
            peaks: list[float] = []
            while len(peaks) < bucket_count:
                raw = source.readframes(frames_per_bucket)
                if not raw:
                    break
                peaks.append(round(min(1.0, _sample_peak(raw, sample_width)), 6))
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioContractError("INVALID_WAV", "The WAV asset could not be decoded", 422) from exc
    duration_ms = round(frame_count * 1000 / sample_rate) if sample_rate else 0
    return {
        "asset_id": asset_id,
        "format": "normalized_peak_envelope",
        "points": peaks,
        "point_count": len(peaks),
        "duration_ms": duration_ms,
        "sample_rate": sample_rate,
        "channels": channels,
        "source_hash": asset["content_hash"],
    }
