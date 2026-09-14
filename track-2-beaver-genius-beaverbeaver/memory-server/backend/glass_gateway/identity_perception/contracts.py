from __future__ import annotations

import hashlib
from typing import Any


TERMINAL_JOB_STATUSES = frozenset(
    {
        "ready",
        "ready_no_face",
        "failed_missing_evidence",
        "failed_model",
        "failed_oom",
        "stale_model_revision",
    }
)
JOB_STATUSES = frozenset({"pending", "running", *TERMINAL_JOB_STATUSES})


class StaleModelRevisionError(RuntimeError):
    pass


def deterministic_face_job_id(
    *,
    evidence_id: str,
    model_revision: str,
    config_version: str,
) -> str:
    payload = f"{evidence_id}\n{model_revision}\n{config_version}".encode("utf-8")
    return "face:" + hashlib.sha256(payload).hexdigest()


def deterministic_observation_id(
    *,
    job_id: str,
    face_index: int,
    bbox_normalized: list[float],
) -> str:
    bbox_key = ",".join(f"{float(value):.6f}" for value in bbox_normalized)
    payload = f"{job_id}\n{int(face_index)}\n{bbox_key}".encode("utf-8")
    return "faceobs:" + hashlib.sha256(payload).hexdigest()


def normalize_face_observation(
    value: dict[str, Any],
    *,
    job_id: str,
    evidence_id: str,
    captured_at_ms: int,
    model_revision: str,
    config_version: str,
    input_width: int,
    input_height: int,
) -> tuple[dict[str, Any], list[float]]:
    face_index = int(value.get("face_index", 0))
    bbox = value.get("bbox_xyxy")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("face bbox_xyxy must contain four values")
    x1, y1, x2, y2 = [float(item) for item in bbox]
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise ValueError("invalid face bbox_xyxy")
    if input_width <= 0 or input_height <= 0:
        raise ValueError("positive face input dimensions are required")
    bbox_normalized = [
        round(max(0.0, min(1.0, x1 / input_width)), 6),
        round(max(0.0, min(1.0, y1 / input_height)), 6),
        round(max(0.0, min(1.0, x2 / input_width)), 6),
        round(max(0.0, min(1.0, y2 / input_height)), 6),
    ]
    detection_score = float(value.get("detection_score", 0.0))
    if not 0.0 <= detection_score <= 1.0:
        raise ValueError("face detection_score must be between 0 and 1")
    quality = dict(value.get("quality") or {})
    eligible = bool(quality.get("eligible_for_match"))
    reason_codes = [
        str(item)
        for item in quality.get("reason_codes") or []
        if str(item).strip()
    ]
    embedding = [
        float(item)
        for item in value.get("embedding") or []
        if isinstance(item, (int, float))
    ]
    if not embedding:
        raise ValueError("face embedding is required for a detected face")
    observation_id = deterministic_observation_id(
        job_id=job_id,
        face_index=face_index,
        bbox_normalized=bbox_normalized,
    )
    public = {
        "observation_id": observation_id,
        "job_id": job_id,
        "evidence_id": evidence_id,
        "face_index": face_index,
        "bbox": bbox_normalized,
        "detection_score": detection_score,
        "quality": {
            "eligible_for_match": eligible,
            "reason_codes": reason_codes,
            "face_area_pixels": quality.get("face_area_pixels"),
            "face_frame_ratio": quality.get("face_frame_ratio"),
            "laplacian_variance": quality.get("laplacian_variance"),
            "five_landmarks_available": quality.get("five_landmarks_available"),
            "yaw_degrees": quality.get("yaw_degrees"),
            "pitch_degrees": quality.get("pitch_degrees"),
            "roll_degrees": quality.get("roll_degrees"),
            "pose_bucket": quality.get("pose_bucket") or "unknown",
        },
        "embedding_ref": f"protected://face-embedding/{observation_id}",
        "candidate_id": None,
        "confirmed_person_id": None,
        "match_confidence": None,
        "captured_at_ms": int(captured_at_ms),
        "model_revision": model_revision,
        "config_version": config_version,
    }
    return public, embedding


def public_job(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"image_path", "media_path_ref", "observations_internal"}
    }
