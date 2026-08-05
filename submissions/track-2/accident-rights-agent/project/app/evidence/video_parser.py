"""Short-video key-frame extraction and deterministic quality filtering."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evidence.errors import DependencyUnavailable, UnsupportedEvidence
from app.schemas.evidence import EvidenceNode, SourceFile


@dataclass
class FrameCandidate:
    frame_index: int
    timestamp_seconds: float
    image: Any
    blur_score: float
    brightness: float
    scene_delta: float
    perceptual_hash: int
    quality_warning: str = ""


@dataclass(frozen=True)
class ParsedVideo:
    nodes: tuple[EvidenceNode, ...]
    frame_paths: tuple[Path, ...]
    metadata: dict[str, Any]
    rejected_counts: dict[str, int]


def parse_video(
    source: SourceFile,
    path: Path,
    derived_dir: Path,
    *,
    max_frames: int = 24,
    fixed_interval_seconds: float = 1.5,
    scan_interval_seconds: float = 0.25,
    scene_threshold: float = 18.0,
    min_blur_score: float = 20.0,
    min_brightness: float = 12.0,
    max_brightness: float = 245.0,
    duplicate_hamming: int = 5,
) -> ParsedVideo:
    try:
        import cv2
    except ImportError as exc:
        raise DependencyUnavailable(
            "OpenCV is required for video parsing. "
            "Install the project 'evidence' extra."
        ) from exc

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise UnsupportedEvidence(f"OpenCV cannot decode video {path.name}.")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or frame_count <= 0:
        capture.release()
        raise UnsupportedEvidence("Video lacks a valid FPS or frame count.")
    duration = frame_count / fps
    scan_step = max(1, round(fps * scan_interval_seconds))
    fixed_step = max(1, round(fps * fixed_interval_seconds))
    candidates: list[FrameCandidate] = []
    previous_small = None
    index = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index % scan_step != 0 and index not in {0, frame_count - 1}:
                index += 1
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)
            scene_delta = (
                0.0
                if previous_small is None
                else float(cv2.absdiff(small, previous_small).mean())
            )
            previous_small = small
            if index % fixed_step != 0 and scene_delta < scene_threshold:
                index += 1
                continue

            candidates.append(
                FrameCandidate(
                    frame_index=index,
                    timestamp_seconds=index / fps,
                    image=frame.copy(),
                    blur_score=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                    brightness=float(gray.mean()),
                    scene_delta=scene_delta,
                    perceptual_hash=_difference_hash(gray, cv2),
                )
            )
            index += 1
    finally:
        capture.release()

    if not candidates:
        raise UnsupportedEvidence("No decodable video frames were found.")

    accepted: list[FrameCandidate] = []
    rejected = {"blur": 0, "brightness": 0, "duplicate": 0}
    for candidate in candidates:
        if candidate.brightness < min_brightness or candidate.brightness > max_brightness:
            rejected["brightness"] += 1
            continue
        if candidate.blur_score < min_blur_score:
            rejected["blur"] += 1
            continue
        if any(
            hamming_distance(candidate.perceptual_hash, item.perceptual_hash)
            <= duplicate_hamming
            for item in accepted[-4:]
        ):
            rejected["duplicate"] += 1
            continue
        accepted.append(candidate)

    if not accepted:
        best = max(candidates, key=lambda item: (item.blur_score, item.scene_delta))
        best.quality_warning = "all_candidates_failed_quality_filters"
        accepted = [best]

    accepted = _limit_with_temporal_coverage(accepted, max_frames)
    frame_dir = derived_dir / "video" / source.source_id
    frame_dir.mkdir(parents=True, exist_ok=True)
    nodes: list[EvidenceNode] = []
    paths: list[Path] = []
    for ordinal, candidate in enumerate(accepted, start=1):
        filename = (
            f"frame_{ordinal:04d}_t{candidate.timestamp_seconds:09.3f}.jpg"
        )
        destination = frame_dir / filename
        ok, encoded = cv2.imencode(".jpg", candidate.image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise UnsupportedEvidence(f"Failed to encode key frame {ordinal}.")
        destination.write_bytes(encoded.tobytes())
        digest = hashlib.sha256(encoded.tobytes()).hexdigest()
        paths.append(destination)
        nodes.append(
            EvidenceNode(
                node_id=f"NODE-{source.source_id[4:]}-F{ordinal:04d}",
                case_id=source.case_id,
                source_id=source.source_id,
                node_type="video_frame",
                locator={
                    "source_path": source.stored_path,
                    "frame_index": candidate.frame_index,
                    "timestamp_seconds": round(candidate.timestamp_seconds, 3),
                    "derived_path": destination.relative_to(derived_dir.parent).as_posix(),
                },
                content_sha256=digest,
                confidence=1.0,
                extraction_method="opencv_keyframe",
                metadata={
                    "blur_score": round(candidate.blur_score, 3),
                    "brightness": round(candidate.brightness, 3),
                    "scene_delta": round(candidate.scene_delta, 3),
                    "quality_warning": candidate.quality_warning,
                },
            )
        )

    return ParsedVideo(
        nodes=tuple(nodes),
        frame_paths=tuple(paths),
        metadata={
            "fps": fps,
            "frame_count": frame_count,
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "candidate_count": len(candidates),
            "accepted_count": len(accepted),
        },
        rejected_counts=rejected,
    )


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _difference_hash(gray: Any, cv2: Any) -> int:
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    differences = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in differences.flatten():
        value = (value << 1) | int(bit)
    return value


def _limit_with_temporal_coverage(
    candidates: list[FrameCandidate], limit: int
) -> list[FrameCandidate]:
    if limit <= 0:
        raise ValueError("max_frames must be positive.")
    ordered = sorted(candidates, key=lambda item: item.frame_index)
    if len(ordered) <= limit:
        return ordered
    if limit == 1:
        return [max(ordered, key=lambda item: (item.scene_delta, item.blur_score))]
    selected_indexes = {
        round(position * (len(ordered) - 1) / (limit - 1))
        for position in range(limit)
    }
    return [ordered[index] for index in sorted(selected_indexes)]
