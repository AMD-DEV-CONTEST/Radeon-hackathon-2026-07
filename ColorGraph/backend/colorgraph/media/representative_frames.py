from __future__ import annotations

import math
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as functional

from colorgraph.domain.grade_graph import TimeRange
from colorgraph.media.frames import FrameExtractionError, extract_frame

REPRESENTATIVE_FRAME_VERSION = "colorgraph.representative-frames/v1"


@dataclass(frozen=True, slots=True)
class FrameQualityMetrics:
    sharpness: float
    entropy: float
    mean_luma: float
    black_ratio: float
    clipping_ratio: float
    quality_score: float


@dataclass(frozen=True, slots=True)
class FrameCandidate:
    path: Path
    time_seconds: float
    quality: FrameQualityMetrics
    accepted: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShotFrameCandidates:
    shot_index: int
    time_range: TimeRange
    requested_count: int
    candidates: tuple[FrameCandidate, ...]


@dataclass(frozen=True, slots=True)
class RepresentativeSelection:
    source_paths: list[Path]
    shot_embeddings: torch.Tensor
    metadata: list[dict[str, object]]


def _candidate_count(time_range: TimeRange) -> int:
    duration = time_range.end_seconds - time_range.start_seconds
    if duration < 2.0:
        return 3
    if duration < 6.0:
        return 5
    return 7


def candidate_timestamps(time_range: TimeRange, *, fps: float) -> list[float]:
    count = _candidate_count(time_range)
    duration = time_range.end_seconds - time_range.start_seconds
    frame_guard = max(2.0 / max(fps, 1e-3), 0.04)
    margin = min(max(duration * 0.12, frame_guard), duration * 0.28)
    first = time_range.start_seconds + margin
    last = time_range.end_seconds - margin
    if last <= first:
        midpoint = (time_range.start_seconds + time_range.end_seconds) * 0.5
        return [midpoint] * count
    return np.linspace(first, last, count, dtype=np.float64).tolist()


def measure_frame_quality(frame_path: str | Path) -> tuple[FrameQualityMetrics, tuple[str, ...]]:
    resolved = Path(frame_path).resolve()
    image = cv2.imread(str(resolved), cv2.IMREAD_COLOR)
    if image is None:
        raise FrameExtractionError(f"OpenCV could not decode representative candidate {resolved}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    histogram = cv2.calcHist([gray], [0], None, [256], [0, 256]).reshape(-1)
    probabilities = histogram / max(float(histogram.sum()), 1.0)
    populated = probabilities[probabilities > 0]
    entropy = float(-np.sum(populated * np.log2(populated)))
    mean_luma = float(gray.mean() / 255.0)
    black_ratio = float(np.mean(gray <= 10))
    clipping_ratio = float(np.mean((gray <= 2) | (gray >= 253)))

    reasons: list[str] = []
    if mean_luma <= 0.05 or black_ratio >= 0.90:
        reasons.append("black_frame")
    if entropy < 2.0:
        reasons.append("low_entropy")
    if sharpness < 18.0:
        reasons.append("blur")
    if clipping_ratio >= 0.35:
        reasons.append("severe_clipping")

    quality_score = float(
        math.log1p(sharpness)
        + entropy * 0.8
        + min(mean_luma, 1.0 - mean_luma) * 2.0
        - black_ratio * 4.0
        - clipping_ratio * 4.0
    )
    return (
        FrameQualityMetrics(
            sharpness=round(sharpness, 5),
            entropy=round(entropy, 5),
            mean_luma=round(mean_luma, 5),
            black_ratio=round(black_ratio, 5),
            clipping_ratio=round(clipping_ratio, 5),
            quality_score=round(quality_score, 5),
        ),
        tuple(reasons),
    )


def extract_representative_candidates(
    media_path: str | Path,
    shot_ranges: list[TimeRange],
    output_directory: str | Path,
    *,
    fps: float,
    frame_transform: Callable[[Path], object] | None = None,
) -> list[ShotFrameCandidates]:
    output_dir = Path(output_directory).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ShotFrameCandidates] = []
    for shot_index, time_range in enumerate(shot_ranges):
        timestamps = candidate_timestamps(time_range, fps=fps)
        candidates: list[FrameCandidate] = []
        for candidate_index, timestamp in enumerate(timestamps):
            destination = output_dir / (
                f"shot_{shot_index + 1:03d}_candidate_{candidate_index + 1:02d}.jpg"
            )
            path = extract_frame(media_path, timestamp, destination)
            if frame_transform is not None:
                frame_transform(path)
            quality, reasons = measure_frame_quality(path)
            candidates.append(
                FrameCandidate(
                    path=path,
                    time_seconds=timestamp,
                    quality=quality,
                    accepted=not reasons,
                    rejection_reasons=reasons,
                )
            )
        results.append(
            ShotFrameCandidates(
                shot_index=shot_index,
                time_range=time_range,
                requested_count=len(timestamps),
                candidates=tuple(candidates),
            )
        )
    return results


def _quality_fallback(shot: ShotFrameCandidates) -> FrameCandidate:
    midpoint = (shot.time_range.start_seconds + shot.time_range.end_seconds) * 0.5
    duration = max(shot.time_range.end_seconds - shot.time_range.start_seconds, 1e-6)
    pool = [candidate for candidate in shot.candidates if candidate.accepted]
    if not pool:
        pool = list(shot.candidates)
    return max(
        pool,
        key=lambda candidate: (
            candidate.quality.quality_score
            - abs(candidate.time_seconds - midpoint) / duration,
            -abs(candidate.time_seconds - midpoint),
        ),
    )


def quality_representative_sources(
    candidate_sets: list[ShotFrameCandidates],
) -> list[Path]:
    return [_quality_fallback(shot).path for shot in candidate_sets]


def embedding_candidate_paths(
    candidate_sets: list[ShotFrameCandidates],
) -> tuple[list[Path], list[list[FrameCandidate]]]:
    flattened: list[Path] = []
    per_shot: list[list[FrameCandidate]] = []
    for shot in candidate_sets:
        candidates = [candidate for candidate in shot.candidates if candidate.accepted]
        if not candidates:
            candidates = [_quality_fallback(shot)]
        per_shot.append(candidates)
        flattened.extend(candidate.path for candidate in candidates)
    return flattened, per_shot


def _candidate_payload(candidate: FrameCandidate) -> dict[str, object]:
    return {
        "path": str(candidate.path),
        "time_seconds": round(candidate.time_seconds, 6),
        "accepted": candidate.accepted,
        "rejection_reasons": list(candidate.rejection_reasons),
        "quality": {
            "sharpness": candidate.quality.sharpness,
            "entropy": candidate.quality.entropy,
            "mean_luma": candidate.quality.mean_luma,
            "black_ratio": candidate.quality.black_ratio,
            "clipping_ratio": candidate.quality.clipping_ratio,
            "score": candidate.quality.quality_score,
        },
    }


def representative_metadata(
    candidate_sets: list[ShotFrameCandidates],
    source_paths: list[Path],
    *,
    method: str,
    medoid_similarities: list[float | None] | None = None,
) -> list[dict[str, object]]:
    similarities = medoid_similarities or [None] * len(candidate_sets)
    metadata: list[dict[str, object]] = []
    for shot, source_path, similarity in zip(
        candidate_sets,
        source_paths,
        similarities,
        strict=True,
    ):
        metadata.append(
            {
                "version": REPRESENTATIVE_FRAME_VERSION,
                "selection_method": method,
                "requested_count": shot.requested_count,
                "accepted_count": sum(candidate.accepted for candidate in shot.candidates),
                "selected_source_path": str(source_path),
                "medoid_mean_similarity": similarity,
                "candidates": [
                    _candidate_payload(candidate) for candidate in shot.candidates
                ],
            }
        )
    return metadata


def select_cosine_medoids(
    candidate_sets: list[ShotFrameCandidates],
    embeddings: torch.Tensor,
) -> RepresentativeSelection:
    flattened, per_shot = embedding_candidate_paths(candidate_sets)
    if embeddings.ndim != 2 or embeddings.shape[0] != len(flattened):
        raise ValueError("embeddings must contain one row per viable representative candidate")
    normalized = functional.normalize(embeddings.float(), dim=-1)

    source_paths: list[Path] = []
    shot_embeddings: list[torch.Tensor] = []
    medoid_similarities: list[float] = []
    offset = 0
    for shot, candidates in zip(candidate_sets, per_shot, strict=True):
        shot_values = normalized[offset : offset + len(candidates)]
        offset += len(candidates)
        if len(candidates) == 1:
            medoid_index = 0
            mean_similarities = torch.ones(1, dtype=torch.float32)
        else:
            pairwise = shot_values @ shot_values.T
            mean_similarities = (pairwise.sum(dim=1) - 1.0) / (len(candidates) - 1)
            midpoint = (shot.time_range.start_seconds + shot.time_range.end_seconds) * 0.5
            centrality = torch.asarray(
                [
                    -abs(candidate.time_seconds - midpoint) * 1e-7
                    for candidate in candidates
                ],
                dtype=torch.float32,
            )
            medoid_index = int(torch.argmax(mean_similarities + centrality).item())

        medoid = shot_values[medoid_index]
        similarities = shot_values @ medoid
        median_similarity = torch.median(similarities)
        mad = torch.median(torch.abs(similarities - median_similarity))
        cutoff = max(float(median_similarity - 2.5 * mad), 0.5)
        keep = similarities >= cutoff
        if not bool(torch.any(keep)):
            keep[medoid_index] = True
        weights = torch.clamp(similarities[keep], min=0.05)
        robust_mean = functional.normalize(
            (shot_values[keep] * weights[:, None]).sum(dim=0),
            dim=0,
        )

        source_paths.append(candidates[medoid_index].path)
        shot_embeddings.append(robust_mean)
        medoid_similarities.append(round(float(mean_similarities[medoid_index]), 6))

    return RepresentativeSelection(
        source_paths=source_paths,
        shot_embeddings=torch.stack(shot_embeddings) if shot_embeddings else torch.empty((0, 0)),
        metadata=representative_metadata(
            candidate_sets,
            source_paths,
            method="cosine_medoid_with_robust_mean_embedding",
            medoid_similarities=medoid_similarities,
        ),
    )


def materialize_representatives(
    candidate_sets: list[ShotFrameCandidates],
    source_paths: list[Path],
) -> list[Path]:
    if len(candidate_sets) != len(source_paths):
        raise ValueError("one representative source path is required per shot")
    representatives: list[Path] = []
    for shot, source_path in zip(candidate_sets, source_paths, strict=True):
        destination = source_path.parent / f"shot_{shot.shot_index + 1:03d}.jpg"
        shutil.copy2(source_path, destination)
        representatives.append(destination)
    return representatives
