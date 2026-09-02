"""Persistent segmented TTS execution outside the FastAPI process."""

from __future__ import annotations

import array
import hashlib
import json
import os
import queue
import sqlite3
import sys
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_runtime_path
from services.audio_contract import (
    AudioContractError,
    append_audio_task_event,
    apply_pronunciation_snapshot,
    get_audio_task,
    get_voice_profile,
    register_audio_output,
)
from services.database_registry import list_databases
from services.db import get_db
from services.media_assets import (
    MediaAssetError,
    get_media_content,
    import_media_asset,
    update_media_asset,
)
from services.model_runtime.manager import (
    WorkerManagerError,
    get_worker_manager,
)


SEGMENT_TIMEOUT_SECONDS = 180
RUN_SLICE_SECONDS = 30 * 60
MAX_WAV_BYTES = 256 * 1024 * 1024
_QUEUE: queue.Queue[tuple[str, str]] = queue.Queue()
_STATE_LOCK = threading.RLock()
_RUN_LOCK = threading.Lock()
_RUNNING: set[tuple[str, str]] = set()
_WORKER_THREAD: threading.Thread | None = None


class TTSExecutionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _staging_root(database_id: str, task_id: str) -> Path:
    root = get_runtime_path(
        "app_data",
        "tts_staging",
        database_id,
        task_id,
    ).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise TTSExecutionError(
            "UNSAFE_TTS_STAGING",
            "TTS staging root cannot be a symbolic link",
        )
    return root


def _staging_path(database_id: str, task_id: str, name: str) -> Path:
    root = _staging_root(database_id, task_id)
    candidate = (root / name).resolve()
    if root not in candidate.parents or candidate.suffix.lower() != ".wav":
        raise TTSExecutionError("UNSAFE_TTS_STAGING", "Invalid TTS staging path")
    candidate.unlink(missing_ok=True)
    return candidate


def _raw_execution_state(database_id: str, task_id: str) -> dict:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT dictionary_snapshot_json,execution_config_json,status,"
            "cancel_requested,source_text_hash FROM audio_tasks "
            "WHERE database_id=? AND task_id=?",
            (database_id, task_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise TTSExecutionError("AUDIO_TASK_NOT_FOUND", "Audio task was not found")
    return {
        "dictionary_snapshot": json.loads(row["dictionary_snapshot_json"] or "[]"),
        "execution_config": json.loads(row["execution_config_json"] or "{}"),
        "status": row["status"],
        "cancel_requested": bool(row["cancel_requested"]),
        "source_text_hash": row["source_text_hash"],
    }


def _set_task_state(database_id: str, task_id: str, **fields) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "progress",
        "cancel_requested",
        "heartbeat_at",
        "runtime_job_id",
        "effective_backend",
        "output_asset_id",
        "error_code",
        "error_message",
        "completed_at",
    }
    if not set(fields) <= allowed:
        raise ValueError("Unsupported audio task update")
    columns = [f"{key}=?" for key in fields]
    values = list(fields.values())
    columns.append("updated_at=?")
    values.extend([_now(), task_id])
    conn = get_db(database_id)
    try:
        conn.execute(
            f"UPDATE audio_tasks SET {','.join(columns)} WHERE task_id=?",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def _set_segment_state(database_id: str, segment_id: str, **fields) -> None:
    allowed = {
        "status",
        "output_asset_id",
        "duration_ms",
        "attempts",
        "error_code",
        "error_message",
        "runtime_job_id",
        "effective_backend",
        "generated_at",
    }
    if not fields or not set(fields) <= allowed:
        raise ValueError("Unsupported audio segment update")
    columns = [f"{key}=?" for key in fields]
    values = list(fields.values())
    columns.append("updated_at=?")
    values.extend([_now(), segment_id])
    conn = get_db(database_id)
    try:
        conn.execute(
            f"UPDATE audio_task_segments SET {','.join(columns)} "
            "WHERE segment_id=?",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def _cancelled_or_outdated(database_id: str, task_id: str) -> str | None:
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT status,cancel_requested FROM audio_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return "missing"
    if row["status"] == "outdated":
        return "outdated"
    if row["status"] == "cancelled" or row["cancel_requested"]:
        return "cancelled"
    return None


def _validate_wav(path: Path, expected_pcm_digest: str | None = None) -> dict:
    if not path.is_file() or path.is_symlink():
        raise TTSExecutionError("TTS_OUTPUT_MISSING", "TTS Worker produced no WAV output")
    if not 44 < path.stat().st_size <= MAX_WAV_BYTES:
        raise TTSExecutionError(
            "TTS_OUTPUT_SIZE_INVALID",
            "TTS WAV output is empty or exceeds the media limit",
        )
    digest = hashlib.sha256()
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            if channels != 1 or sample_width != 2 or sample_rate != 24_000:
                raise TTSExecutionError(
                    "TTS_OUTPUT_FORMAT_INVALID",
                    "TTS Worker output must be mono 24 kHz PCM16 WAV",
                )
            remaining = frame_count
            while remaining:
                frames = handle.readframes(min(remaining, 65_536))
                if not frames:
                    break
                digest.update(frames)
                remaining -= len(frames) // (channels * sample_width)
    except (wave.Error, OSError) as exc:
        raise TTSExecutionError(
            "TTS_OUTPUT_FORMAT_INVALID",
            "TTS Worker output is not a readable PCM WAV file",
        ) from exc
    if frame_count <= 0:
        raise TTSExecutionError("TTS_OUTPUT_EMPTY", "TTS Worker output contains no samples")
    if expected_pcm_digest and digest.hexdigest() != expected_pcm_digest:
        raise TTSExecutionError(
            "TTS_OUTPUT_INTEGRITY_MISMATCH",
            "TTS Worker output failed its integrity check",
        )
    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frame_count": frame_count,
        "duration_ms": round(frame_count / sample_rate * 1000),
        "pcm_sha256": digest.hexdigest(),
    }


class NativeTTSExecutor:
    def execute(
        self,
        task: dict,
        segment: dict,
        *,
        text: str,
        voice: dict,
        output_path: Path,
        job_started,
    ) -> dict:
        response = get_worker_manager().execute(
            task["package_id"],
            task_id=task["task_id"],
            operation="audio",
            payload={
                "action": "tts",
                "text": text,
                "locale": voice["locale"],
                "voice_name": voice["package_voice_name"],
                "speed": task["execution_config"]["speed"],
                "output_path": str(output_path),
            },
            requested_backend=task["requested_backend"],
            priority=60,
            timeout=SEGMENT_TIMEOUT_SECONDS,
            job_started=job_started,
        )
        return {
            **response["result"],
            "runtime_job_id": response["job_id"],
        }


def _import_segment_output(
    database_id: str,
    task: dict,
    segment: dict,
    voice: dict,
    output_path: Path,
    runtime: dict,
) -> dict:
    wav = _validate_wav(output_path, runtime.get("output_digest"))
    with output_path.open("rb") as handle:
        asset = import_media_asset(
            database_id,
            task["book_id"],
            handle,
            filename=f"{task['task_id']}-{segment['segment_index']:04d}.wav",
            declared_mime="audio/wav",
            source_type="generated",
            created_by_task_id=task["task_id"],
        )
    metadata = {
        **asset.get("metadata", {}),
        "tts_generation": {
            "task_id": task["task_id"],
            "segment_id": segment["segment_id"],
            "segment_index": segment["segment_index"],
            "deterministic_key": segment["deterministic_key"],
            "source_text_hash": segment["source_text_hash"],
            "normalized_text_hash": segment["normalized_text_hash"],
            "dictionary_hash": task.get("dictionary_hash"),
            "normalization_version": task.get("normalization_version"),
            "voice_profile_id": task["voice_profile_id"],
            "package_id": task["package_id"],
            "package_version": task.get("model_package_version"),
            "model_revision": task.get("model_revision"),
            "requested_backend": task["requested_backend"],
            "effective_backend": runtime.get("effective_backend"),
            "runtime_job_id": runtime.get("runtime_job_id"),
            "sample_rate": wav["sample_rate"],
            "duration_ms": wav["duration_ms"],
            "pcm_sha256": wav["pcm_sha256"],
        },
    }
    return update_media_asset(
        database_id,
        asset["asset_id"],
        metadata=metadata,
    )


def _chapter_asset_scope(database_id: str, task: dict) -> dict:
    chapter_id = task.get("chapter_id")
    if not chapter_id:
        return {}
    scope = {"chapter_id": chapter_id}
    try:
        from services.chapter_localization import (
            chapter_with_localization,
            ensure_chapter_localizations,
        )

        conn = get_db(database_id)
        try:
            ensure_chapter_localizations(conn, database_id=database_id)
            chapter = chapter_with_localization(conn, chapter_id)
            if chapter:
                scope.update(
                    {
                        "content_group_id": chapter.get("content_group_id"),
                        "language_code": chapter.get("language_code"),
                        "content_hash": chapter.get("content_hash"),
                    }
                )
        finally:
            conn.close()
    except Exception:
        pass
    return {key: value for key, value in scope.items() if value}


def _read_pcm_chunks(handle, *, frames_per_chunk: int = 65_536):
    while True:
        payload = handle.readframes(frames_per_chunk)
        if not payload:
            return
        samples = array.array("h")
        samples.frombytes(payload)
        if sys.byteorder != "little":
            samples.byteswap()
        yield samples


def _merge_segments(
    database_id: str,
    task: dict,
    segments: list[dict],
    output_path: Path,
) -> dict:
    sources = []
    peak = 0
    for segment in segments:
        if not segment.get("output_asset_id"):
            raise TTSExecutionError(
                "TTS_SEGMENT_OUTPUT_MISSING",
                "A completed TTS segment has no media output",
            )
        path, asset = get_media_content(database_id, segment["output_asset_id"])
        if asset["book_id"] != task["book_id"] or asset["modality"] != "audio":
            raise TTSExecutionError(
                "TTS_SEGMENT_SCOPE_MISMATCH",
                "A TTS segment output no longer belongs to this task",
            )
        with wave.open(str(path), "rb") as handle:
            if (
                handle.getnchannels() != 1
                or handle.getsampwidth() != 2
                or handle.getframerate() != 24_000
            ):
                raise TTSExecutionError(
                    "TTS_SEGMENT_FORMAT_MISMATCH",
                    "TTS segment formats must match before merge",
                )
            for samples in _read_pcm_chunks(handle):
                if samples:
                    peak = max(peak, max(abs(value) for value in samples))
        sources.append(path)
    peak_target = float(task["execution_config"]["peak_target"])
    scale = min(1.0, (32767 * peak_target) / peak) if peak else 1.0
    pause_frames = round(
        24_000 * int(task["execution_config"]["segment_pause_ms"]) / 1000
    )
    silence = b"\x00\x00" * pause_frames
    pcm_digest = hashlib.sha256()
    with wave.open(str(output_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24_000)
        for index, path in enumerate(sources):
            with wave.open(str(path), "rb") as source:
                for samples in _read_pcm_chunks(source):
                    if scale != 1.0:
                        samples = array.array(
                            "h",
                            (
                                max(-32768, min(32767, round(value * scale)))
                                for value in samples
                            ),
                        )
                    if sys.byteorder != "little":
                        samples.byteswap()
                    payload = samples.tobytes()
                    target.writeframesraw(payload)
                    pcm_digest.update(payload)
            if index + 1 < len(sources) and silence:
                target.writeframesraw(silence)
                pcm_digest.update(silence)
    wav = _validate_wav(output_path, pcm_digest.hexdigest())
    wav["normalization"] = "deterministic_peak"
    wav["peak_target"] = peak_target
    wav["segment_pause_ms"] = int(task["execution_config"]["segment_pause_ms"])
    return wav


def _import_merged_output(
    database_id: str,
    task: dict,
    output_path: Path,
    wav: dict,
) -> dict:
    with output_path.open("rb") as handle:
        asset = import_media_asset(
            database_id,
            task["book_id"],
            handle,
            filename=f"{task['task_id']}-merged.wav",
            declared_mime="audio/wav",
            source_type="generated",
            created_by_task_id=task["task_id"],
        )
    metadata = {
        **asset.get("metadata", {}),
        "tts_merge": {
            "task_id": task["task_id"],
            "source_text_hash": task["source_text_hash"],
            "dictionary_hash": task.get("dictionary_hash"),
            "voice_profile_id": task["voice_profile_id"],
            "package_id": task["package_id"],
            "package_version": task.get("model_package_version"),
            "model_revision": task.get("model_revision"),
            "normalization": wav["normalization"],
            "peak_target": wav["peak_target"],
            "segment_pause_ms": wav["segment_pause_ms"],
            "sample_rate": wav["sample_rate"],
            "duration_ms": wav["duration_ms"],
            "pcm_sha256": wav["pcm_sha256"],
            "requires_approval": True,
        },
        "chapter_asset": _chapter_asset_scope(database_id, task),
    }
    return update_media_asset(
        database_id,
        asset["asset_id"],
        metadata=metadata,
    )


def _fail_task(
    database_id: str,
    task_id: str,
    code: str,
    message: str,
    *,
    segment_id: str | None = None,
) -> dict:
    if segment_id:
        task = get_audio_task(database_id, task_id)
        segment = next(
            (item for item in task["segments"] if item["segment_id"] == segment_id),
            None,
        )
        attempts = int(segment.get("attempts") or 0) if segment else 0
        _set_segment_state(
            database_id,
            segment_id,
            status="failed",
            attempts=attempts,
            error_code=code[:96],
            error_message=message[:512],
        )
    _set_task_state(
        database_id,
        task_id,
        status="failed",
        error_code=code[:96],
        error_message=message[:512],
        heartbeat_at=_now(),
    )
    append_audio_task_event(
        database_id,
        task_id,
        "error",
        {"status": "failed", "code": code, "segment_id": segment_id},
    )
    append_audio_task_event(
        database_id,
        task_id,
        "done",
        {"status": "failed"},
    )
    return get_audio_task(database_id, task_id)


def run_audio_task(
    database_id: str,
    task_id: str,
    *,
    executor=None,
) -> dict:
    with _RUN_LOCK:
        task = get_audio_task(database_id, task_id, include_source_text=True)
        if task["status"] not in {"planned", "in_progress"}:
            return task
        if task["target_kind"] != "native_package" or task["operation"] not in {
            "audio.tts.chapter",
            "audio.tts.segment",
        }:
            return _fail_task(
                database_id,
                task_id,
                "TTS_TARGET_NOT_EXECUTABLE",
                "This persistent executor accepts native TTS package tasks only",
            )
        state = _raw_execution_state(database_id, task_id)
        if state["cancel_requested"]:
            return get_audio_task(database_id, task_id)
        voice = get_voice_profile(database_id, task["voice_profile_id"])
        if (
            voice["voice_kind"] != "native_voice"
            or voice["package_id"] != task["package_id"]
        ):
            return _fail_task(
                database_id,
                task_id,
                "TTS_VOICE_TARGET_MISMATCH",
                "The native voice no longer matches this TTS package",
            )
        _set_task_state(
            database_id,
            task_id,
            status="in_progress",
            heartbeat_at=_now(),
            error_code=None,
            error_message=None,
        )
        append_audio_task_event(
            database_id,
            task_id,
            "status",
            {"status": "in_progress", "progress": task["progress"]},
        )
        deadline = time.monotonic() + RUN_SLICE_SECONDS
        native = executor or NativeTTSExecutor()
        for segment in task["segments"]:
            if segment["status"] == "completed":
                continue
            if segment["status"] != "planned":
                return _fail_task(
                    database_id,
                    task_id,
                    "TTS_SEGMENT_NOT_RETRYABLE",
                    "A failed segment must be explicitly retried",
                    segment_id=segment["segment_id"],
                )
            if time.monotonic() >= deadline:
                _set_task_state(
                    database_id,
                    task_id,
                    status="planned",
                    heartbeat_at=_now(),
                )
                append_audio_task_event(
                    database_id,
                    task_id,
                    "yielded",
                    {
                        "status": "planned",
                        "reason": "RUN_SLICE_LIMIT",
                        "absolute_slice_seconds": RUN_SLICE_SECONDS,
                    },
                )
                return get_audio_task(database_id, task_id)
            stopped = _cancelled_or_outdated(database_id, task_id)
            if stopped:
                return get_audio_task(database_id, task_id)
            normalized = apply_pronunciation_snapshot(
                segment["source_text"],
                state["dictionary_snapshot"],
            )
            normalized_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if normalized_hash != segment["normalized_text_hash"]:
                return _fail_task(
                    database_id,
                    task_id,
                    "TTS_DETERMINISM_MISMATCH",
                    "The persisted TTS preprocessing snapshot no longer matches",
                    segment_id=segment["segment_id"],
                )
            output_path = _staging_path(
                database_id,
                task_id,
                f"segment-{segment['segment_index']:04d}.wav",
            )
            attempt = int(segment.get("attempts") or 0) + 1
            _set_segment_state(
                database_id,
                segment["segment_id"],
                attempts=attempt,
                error_code=None,
                error_message=None,
            )

            def job_started(runtime_job_id: str):
                _set_task_state(
                    database_id,
                    task_id,
                    runtime_job_id=runtime_job_id,
                    heartbeat_at=_now(),
                )
                _set_segment_state(
                    database_id,
                    segment["segment_id"],
                    runtime_job_id=runtime_job_id,
                )
                append_audio_task_event(
                    database_id,
                    task_id,
                    "runtime",
                    {
                        "segment_id": segment["segment_id"],
                        "segment_index": segment["segment_index"],
                        "runtime_job_id": runtime_job_id,
                    },
                )
                return _cancelled_or_outdated(database_id, task_id) is None

            try:
                runtime = native.execute(
                    task,
                    segment,
                    text=normalized,
                    voice=voice,
                    output_path=output_path,
                    job_started=job_started,
                )
                stopped = _cancelled_or_outdated(database_id, task_id)
                if stopped:
                    output_path.unlink(missing_ok=True)
                    return get_audio_task(database_id, task_id)
                asset = _import_segment_output(
                    database_id,
                    task,
                    segment,
                    voice,
                    output_path,
                    runtime,
                )
                register_audio_output(
                    database_id,
                    task_id,
                    {
                        "asset_id": asset["asset_id"],
                        "segment_id": segment["segment_id"],
                        "output_kind": "segment",
                    },
                )
                _set_segment_state(
                    database_id,
                    segment["segment_id"],
                    attempts=attempt,
                    runtime_job_id=runtime.get("runtime_job_id"),
                    effective_backend=runtime.get("effective_backend"),
                    generated_at=_now(),
                    error_code=None,
                    error_message=None,
                )
                current = get_audio_task(database_id, task_id)
                completed = sum(
                    item["status"] == "completed" for item in current["segments"]
                )
                progress = completed / max(1, len(current["segments"]))
                _set_task_state(
                    database_id,
                    task_id,
                    status=(
                        "in_progress"
                        if task["operation"] == "audio.tts.chapter"
                        else current["status"]
                    ),
                    progress=progress,
                    effective_backend=runtime.get("effective_backend"),
                    heartbeat_at=_now(),
                )
                append_audio_task_event(
                    database_id,
                    task_id,
                    "progress",
                    {
                        "status": (
                            "in_progress"
                            if task["operation"] == "audio.tts.chapter"
                            else current["status"]
                        ),
                        "progress": progress,
                        "completed_segments": completed,
                        "total_segments": len(current["segments"]),
                        "segment_id": segment["segment_id"],
                    },
                )
            except WorkerManagerError as exc:
                return _fail_task(
                    database_id,
                    task_id,
                    exc.code,
                    exc.safe_message,
                    segment_id=segment["segment_id"],
                )
            except (TTSExecutionError, AudioContractError) as exc:
                return _fail_task(
                    database_id,
                    task_id,
                    exc.code,
                    getattr(exc, "safe_message", str(exc)),
                    segment_id=segment["segment_id"],
                )
            except (MediaAssetError, OSError, sqlite3.Error, ValueError, wave.Error) as exc:
                return _fail_task(
                    database_id,
                    task_id,
                    getattr(exc, "code", "TTS_STORAGE_FAILED"),
                    getattr(exc, "message", "Generated TTS audio could not be stored safely"),
                    segment_id=segment["segment_id"],
                )
            except Exception:
                return _fail_task(
                    database_id,
                    task_id,
                    "TTS_EXECUTION_FAILED",
                    "TTS execution failed unexpectedly",
                    segment_id=segment["segment_id"],
                )
            finally:
                output_path.unlink(missing_ok=True)

        current = get_audio_task(database_id, task_id)
        if task["operation"] == "audio.tts.chapter":
            final_path = _staging_path(database_id, task_id, "merged.wav")
            try:
                wav = _merge_segments(
                    database_id,
                    current,
                    current["segments"],
                    final_path,
                )
                asset = _import_merged_output(database_id, current, final_path, wav)
                current = register_audio_output(
                    database_id,
                    task_id,
                    {"asset_id": asset["asset_id"], "output_kind": "merged"},
                )
            except (TTSExecutionError, MediaAssetError, AudioContractError) as exc:
                return _fail_task(
                    database_id,
                    task_id,
                    getattr(exc, "code", "TTS_MERGE_FAILED"),
                    getattr(
                        exc,
                        "safe_message",
                        getattr(exc, "message", "TTS chapter merge failed"),
                    ),
                )
            except (OSError, sqlite3.Error, wave.Error, ValueError):
                return _fail_task(
                    database_id,
                    task_id,
                    "TTS_MERGE_FAILED",
                    "TTS chapter merge failed safely",
                )
            finally:
                final_path.unlink(missing_ok=True)
        _set_task_state(
            database_id,
            task_id,
            status="pending_review",
            progress=1.0,
            heartbeat_at=_now(),
            error_code=None,
            error_message=None,
        )
        append_audio_task_event(
            database_id,
            task_id,
            "result",
            {
                "status": "pending_review",
                "output_asset_id": current.get("output_asset_id"),
                "requires_approval": True,
            },
        )
        append_audio_task_event(
            database_id,
            task_id,
            "done",
            {"status": "pending_review"},
        )
        return get_audio_task(database_id, task_id)


def _worker_loop() -> None:
    while True:
        database_id, task_id = _QUEUE.get()
        key = (database_id, task_id)
        result = None
        try:
            result = run_audio_task(database_id, task_id)
        except Exception:
            try:
                _fail_task(
                    database_id,
                    task_id,
                    "TTS_BACKGROUND_WORKER_FAILED",
                    "TTS background execution failed unexpectedly",
                )
            except Exception:
                pass
        finally:
            with _STATE_LOCK:
                _RUNNING.discard(key)
            _QUEUE.task_done()
        if result and result.get("status") == "planned":
            enqueue_audio_task(database_id, task_id)


def enqueue_audio_task(database_id: str, task_id: str) -> None:
    global _WORKER_THREAD
    key = (database_id, task_id)
    with _STATE_LOCK:
        if key in _RUNNING:
            return
        _RUNNING.add(key)
        _QUEUE.put(key)
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_THREAD = threading.Thread(
                target=_worker_loop,
                name="tts-task-worker",
                daemon=True,
            )
            _WORKER_THREAD.start()


def recover_interrupted_audio_tasks() -> dict:
    recovered = 0
    queued = 0
    for database in list_databases():
        database_id = database["database_id"]
        conn = None
        try:
            conn = get_db(database_id)
            now = _now()
            conn.execute("BEGIN IMMEDIATE")
            interrupted = conn.execute(
                "SELECT task_id FROM audio_tasks "
                "WHERE target_kind='native_package' "
                "AND operation IN ('audio.tts.chapter','audio.tts.segment') "
                "AND status='in_progress'"
            ).fetchall()
            for row in interrupted:
                conn.execute(
                    "UPDATE audio_tasks SET status='planned',runtime_job_id=NULL,"
                    "error_code='INTERRUPTED',"
                    "error_message='TTS task resumed after restart',"
                    "heartbeat_at=?,updated_at=? WHERE task_id=?",
                    (now, now, row["task_id"]),
                )
            pending = conn.execute(
                "SELECT task_id FROM audio_tasks "
                "WHERE target_kind='native_package' "
                "AND operation IN ('audio.tts.chapter','audio.tts.segment') "
                "AND status='planned' AND cancel_requested=0"
            ).fetchall()
            conn.commit()
        except (OSError, sqlite3.Error, KeyError):
            try:
                conn.rollback()
            except Exception:
                pass
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
        recovered += len(interrupted)
        for row in pending:
            enqueue_audio_task(database_id, row["task_id"])
            queued += 1
    return {"recovered": recovered, "queued": queued}
