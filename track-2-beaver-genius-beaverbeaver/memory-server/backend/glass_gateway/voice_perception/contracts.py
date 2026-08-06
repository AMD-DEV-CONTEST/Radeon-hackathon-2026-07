from __future__ import annotations

import hashlib
import math
from typing import Any


TERMINAL_JOB_STATUSES = frozenset(
    {
        "ready",
        "ready_no_speech",
        "ready_no_eligible_turn",
        "failed_missing_evidence",
        "failed_audio_decode",
        "failed_model",
        "failed_oom",
        "stale_model_revision",
    }
)
JOB_STATUSES = frozenset({"pending", "running", *TERMINAL_JOB_STATUSES})


class StaleVoiceModelRevisionError(RuntimeError):
    pass


class VoiceAudioDecodeError(RuntimeError):
    pass


def deterministic_voice_job_id(
    *, audio_evidence_id: str, model_revision: str, config_version: str
) -> str:
    payload = f"{audio_evidence_id}\n{model_revision}\n{config_version}".encode("utf-8")
    return "voice:" + hashlib.sha256(payload).hexdigest()


def deterministic_voice_turn_id(
    *, job_id: str, start_ms: int, end_ms: int, speaker_local_id: str
) -> str:
    payload = (
        f"{job_id}\n{int(start_ms)}\n{int(end_ms)}\n{speaker_local_id}".encode(
            "utf-8"
        )
    )
    return "speaker-turn:" + hashlib.sha256(payload).hexdigest()


def normalize_voice_turn(
    value: dict[str, Any],
    *,
    job_id: str,
    audio_evidence_id: str,
    captured_at_ms: int,
    duration_ms: int,
    model_revision: str,
    config_version: str,
) -> tuple[dict[str, Any], list[float] | None]:
    start_ms = int(value["start_ms"])
    end_ms = int(value["end_ms"])
    if start_ms < 0 or end_ms <= start_ms or end_ms > duration_ms + 100:
        raise ValueError("voice turn must fit inside source audio")
    speaker_local_id = str(value.get("speaker_local_id") or "").strip()
    if not speaker_local_id:
        raise ValueError("voice turn requires speaker_local_id")
    quality = dict(value.get("quality") or {})
    eligible = bool(quality.get("eligible_for_match"))
    reason_codes = [
        str(item) for item in quality.get("reason_codes") or [] if str(item).strip()
    ]
    embedding_values = value.get("embedding")
    embedding = (
        [float(item) for item in embedding_values]
        if isinstance(embedding_values, list)
        else None
    )
    if embedding is not None:
        if not embedding or not all(math.isfinite(item) for item in embedding):
            raise ValueError("voice embedding must contain finite values")
        norm = math.sqrt(sum(item * item for item in embedding))
        if norm <= 0:
            raise ValueError("voice embedding norm must be positive")
    if eligible and embedding is None:
        raise ValueError("eligible voice turn requires protected embedding")
    turn_id = deterministic_voice_turn_id(
        job_id=job_id,
        start_ms=start_ms,
        end_ms=end_ms,
        speaker_local_id=speaker_local_id,
    )
    public = {
        "turn_id": turn_id,
        "job_id": job_id,
        "audio_evidence_id": audio_evidence_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "speaker_local_id": speaker_local_id,
        "voice_candidate_id": None,
        "confirmed_person_id": None,
        "confidence": _optional_probability(value.get("confidence")),
        "overlap": bool(value.get("overlap", False)),
        "quality": {
            "eligible_for_match": eligible,
            "reason_codes": reason_codes,
            "speaker_activity_ms": int(quality.get("speaker_activity_ms") or 0),
            "turn_duration_ms": end_ms - start_ms,
        },
        "embedding_ref": (
            f"protected://voice-embedding/{turn_id}" if embedding is not None else None
        ),
        "asr_segment_refs": [],
        "captured_at_ms": int(captured_at_ms),
        "model_revision": model_revision,
        "config_version": config_version,
    }
    return public, embedding


def public_voice_job(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key
        not in {
            "audio_path",
            "media_path_ref",
            "turns_internal",
            "asr_result",
            "error",
        }
    }


def _optional_probability(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return result
