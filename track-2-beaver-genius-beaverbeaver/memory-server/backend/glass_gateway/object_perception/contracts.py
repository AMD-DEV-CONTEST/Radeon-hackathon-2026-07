from __future__ import annotations

import hashlib
from typing import Any


TERMINAL_JOB_STATUSES = frozenset({"ready", "ready_empty", "failed", "stale"})
JOB_STATUSES = frozenset({"pending", "running", *TERMINAL_JOB_STATUSES})


def deterministic_job_id(
    *,
    model_version: str,
    evidence_id: str,
    vocabulary_hash: str,
) -> str:
    payload = f"{model_version}\n{evidence_id}\n{vocabulary_hash}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_detection(
    value: dict[str, Any],
    *,
    input_width: int | None,
    input_height: int | None,
) -> dict[str, Any]:
    label = str(value.get("label") or value.get("label_raw") or "").strip()
    if not label:
        raise ValueError("detection label is required")
    confidence = float(value.get("confidence"))
    if not 0 <= confidence <= 1:
        raise ValueError("detection confidence must be between 0 and 1")
    bbox = value.get("bbox_xyxy")
    normalized_bbox = None
    raw_bbox = None
    if bbox is not None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ValueError("bbox_xyxy must contain four values")
        raw_bbox = [float(item) for item in bbox]
        x1, y1, x2, y2 = raw_bbox
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("invalid bbox_xyxy")
        if input_width and input_height:
            normalized_bbox = [
                round(max(0.0, min(1.0, x1 / input_width)), 6),
                round(max(0.0, min(1.0, y1 / input_height)), 6),
                round(max(0.0, min(1.0, x2 / input_width)), 6),
                round(max(0.0, min(1.0, y2 / input_height)), 6),
            ]
    return {
        "label": label,
        "prompt": str(value.get("prompt") or label),
        "confidence": confidence,
        "bbox_xyxy": raw_bbox,
        "bbox_normalized": normalized_bbox,
        "attributes": dict(value.get("attributes") or {}),
    }
