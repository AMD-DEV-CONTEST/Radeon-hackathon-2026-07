from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from command.labels import CommandIntent

PROFILE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class PrototypeSample:
    profile_id: str
    intent: str
    embedding: np.ndarray
    sample_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PrototypeMatch:
    intent: str
    accepted: bool
    confidence: float
    margin: float
    top_k: list[dict[str, Any]]
    logits: dict[str, float]
    reason: str
    profile_id: str | None = None
    matched_metadata: dict[str, Any] = field(default_factory=dict)
    matched_sample_path: str | None = None


def extract_roi_embedding(mouth_frames: np.ndarray, feature_dim: int = 128) -> np.ndarray:
    if feature_dim <= 0:
        raise ValueError("feature_dim must be positive")

    frames = np.asarray(mouth_frames)
    if frames.ndim == 4:
        frames = frames.mean(axis=-1)
    if frames.ndim != 3:
        raise ValueError("mouth_frames must have shape (T,H,W) or (T,H,W,C)")
    if frames.shape[0] == 0:
        raise ValueError("mouth_frames must contain at least one frame")

    normalized = frames.astype(np.float32) / 255.0
    temporal = normalized.reshape(normalized.shape[0], -1)
    diffs = np.diff(temporal, axis=0) if normalized.shape[0] > 1 else np.zeros((1, temporal.shape[1]), dtype=np.float32)

    features: list[np.ndarray] = [
        np.array(
            [
                float(normalized.mean()),
                float(normalized.std()),
                float(normalized.min()),
                float(normalized.max()),
                float(np.percentile(normalized, 10)),
                float(np.percentile(normalized, 50)),
                float(np.percentile(normalized, 90)),
                float(np.abs(diffs).mean()),
                float(np.abs(diffs).std()),
            ],
            dtype=np.float32,
        )
    ]

    frame_mean = temporal.mean(axis=1)
    frame_std = temporal.std(axis=1)
    motion = np.abs(diffs).mean(axis=1)
    features.append(_resample_1d(frame_mean, 24))
    features.append(_resample_1d(frame_std, 16))
    features.append(_resample_1d(motion, 16))

    average_frame = normalized.mean(axis=0)
    row_projection = average_frame.mean(axis=1)
    col_projection = average_frame.mean(axis=0)
    features.append(_resample_1d(row_projection, 16))
    features.append(_resample_1d(col_projection, 16))

    temporal_fft = np.abs(np.fft.rfft(frame_mean - frame_mean.mean()))
    row_fft = np.abs(np.fft.rfft(row_projection - row_projection.mean()))
    col_fft = np.abs(np.fft.rfft(col_projection - col_projection.mean()))
    features.append(_resample_1d(temporal_fft, 12))
    features.append(_resample_1d(row_fft, 10))
    features.append(_resample_1d(col_fft, 10))

    vector = np.concatenate(features).astype(np.float32)
    if vector.size < feature_dim:
        repeats = int(np.ceil(feature_dim / vector.size))
        vector = np.tile(vector, repeats)
    vector = vector[:feature_dim]
    return _unit_normalize(vector)


def save_prototype_sample(
    root: Path,
    profile_id: str,
    intent: str,
    mouth_frames: np.ndarray,
    metadata: dict[str, Any],
) -> Path:
    profile = sanitize_profile_id(profile_id)
    normalized_intent = _validate_intent(intent)
    sample_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    sample_dir = root / "profiles" / profile / normalized_intent / sample_id
    sample_dir.mkdir(parents=True, exist_ok=False)

    embedding = extract_roi_embedding(mouth_frames)
    np.save(sample_dir / "mouth_roi.npy", np.asarray(mouth_frames))
    np.save(sample_dir / "embedding.npy", embedding)

    metadata_payload = {
        "profileId": profile,
        "intent": normalized_intent,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    (sample_dir / "metadata.json").write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2))
    return sample_dir


def load_profile_prototypes(root: Path, profile_id: str) -> list[PrototypeSample]:
    profile = sanitize_profile_id(profile_id)
    profile_dir = root / "profiles" / profile
    if not profile_dir.exists():
        return []

    samples: list[PrototypeSample] = []
    for embedding_path in sorted(profile_dir.glob("*/*/embedding.npy")):
        sample_dir = embedding_path.parent
        metadata_path = sample_dir / "metadata.json"
        try:
            embedding = np.load(embedding_path).astype(np.float32)
            metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        intent = str(metadata.get("intent") or sample_dir.parent.name)
        samples.append(
            PrototypeSample(
                profile_id=profile,
                intent=intent,
                embedding=_unit_normalize(embedding),
                sample_path=sample_dir,
                metadata=metadata,
            )
        )
    return samples


def match_prototypes(
    embedding: np.ndarray,
    samples: Sequence[PrototypeSample],
    confidence_threshold: float,
    margin_threshold: float,
) -> PrototypeMatch:
    if not samples:
        return PrototypeMatch(
            intent=CommandIntent.UNKNOWN.value,
            accepted=False,
            confidence=0.0,
            margin=0.0,
            top_k=[],
            logits={},
            reason="no_prototypes",
        )

    query = _unit_normalize(np.asarray(embedding, dtype=np.float32))
    grouped_scores: dict[str, list[float]] = {}
    best_sample_by_intent: dict[str, tuple[float, PrototypeSample]] = {}
    for sample in samples:
        sample_embedding = _unit_normalize(sample.embedding.astype(np.float32))
        score = _cosine_similarity_01(query, sample_embedding)
        grouped_scores.setdefault(sample.intent, []).append(score)
        current = best_sample_by_intent.get(sample.intent)
        if current is None or score > current[0]:
            best_sample_by_intent[sample.intent] = (score, sample)

    logits = {intent: float(np.mean(scores)) for intent, scores in grouped_scores.items()}
    ranked = sorted(logits.items(), key=lambda item: item[1], reverse=True)
    top_k = [{"intent": intent, "confidence": round(score, 6)} for intent, score in ranked[:3]]
    best_intent, confidence = ranked[0]
    best_sample = best_sample_by_intent.get(best_intent, (0.0, None))[1]
    matched_metadata = dict(best_sample.metadata) if best_sample is not None else {}
    matched_sample_path = str(best_sample.sample_path) if best_sample is not None and best_sample.sample_path else None
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = max(0.0, confidence - second)

    if confidence < confidence_threshold:
        return PrototypeMatch(
            intent=CommandIntent.UNKNOWN.value,
            accepted=False,
            confidence=round(confidence, 6),
            margin=round(margin, 6),
            top_k=top_k,
            logits={key: round(value, 6) for key, value in logits.items()},
            reason="confidence_below_threshold",
        )
    if margin < margin_threshold:
        return PrototypeMatch(
            intent=CommandIntent.UNKNOWN.value,
            accepted=False,
            confidence=round(confidence, 6),
            margin=round(margin, 6),
            top_k=top_k,
            logits={key: round(value, 6) for key, value in logits.items()},
            reason="margin_below_threshold",
        )
    if best_intent == CommandIntent.UNKNOWN.value:
        return PrototypeMatch(
            intent=CommandIntent.UNKNOWN.value,
            accepted=False,
            confidence=round(confidence, 6),
            margin=round(margin, 6),
            top_k=top_k,
            logits={key: round(value, 6) for key, value in logits.items()},
            reason="prototype_predicted_unknown",
        )

    return PrototypeMatch(
        intent=best_intent,
        accepted=True,
        confidence=round(confidence, 6),
        margin=round(margin, 6),
        top_k=top_k,
        logits={key: round(value, 6) for key, value in logits.items()},
        reason="accepted",
        matched_metadata=matched_metadata,
        matched_sample_path=matched_sample_path,
    )


def sanitize_profile_id(profile_id: str) -> str:
    cleaned = PROFILE_ID_PATTERN.sub("-", str(profile_id).strip())[:128].strip(".-")
    if not cleaned:
        raise ValueError("profile_id is required")
    return cleaned


def _validate_intent(intent: str) -> str:
    valid = {item.value for item in CommandIntent}
    if intent not in valid:
        raise ValueError(f"unknown command intent: {intent}")
    return intent


def _resample_1d(values: np.ndarray, size: int) -> np.ndarray:
    source = np.asarray(values, dtype=np.float32).reshape(-1)
    if source.size == 0:
        return np.zeros(size, dtype=np.float32)
    if source.size == 1:
        return np.full(size, float(source[0]), dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, source.size)
    x_new = np.linspace(0.0, 1.0, size)
    return np.interp(x_new, x_old, source).astype(np.float32)


def _unit_normalize(vector: np.ndarray) -> np.ndarray:
    normalized = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(normalized))
    if norm <= 1e-8:
        normalized = np.zeros_like(normalized, dtype=np.float32)
        normalized[0] = 1.0
        return normalized
    return (normalized / norm).astype(np.float32)


def _cosine_similarity_01(a: np.ndarray, b: np.ndarray) -> float:
    length = min(a.size, b.size)
    if length == 0:
        return 0.0
    cosine = float(np.dot(a[:length], b[:length]))
    cosine = max(-1.0, min(1.0, cosine))
    return (cosine + 1.0) / 2.0
