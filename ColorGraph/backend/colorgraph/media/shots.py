from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from colorgraph.domain.grade_graph import TimeRange
from colorgraph.media.probe import probe_media

PYSCENEDETECT_VERSION = "0.7.1"
PYSCENEDETECT_SOURCE_REVISION = "6ebb72392de8acfb6c539bf15d0aa912ce7ab6b2"
PYSCENEDETECT_LICENSE_ID = "BSD-3-Clause"
PYSCENEDETECT_WHEEL_SHA256 = "0594131cf2da278ac9f9442e1ce2a8fe6ccb25ab83a0899f349784e688d304c6"


class ShotDetectionError(RuntimeError):
    pass


def _frame_signature(frame: np.ndarray) -> tuple[np.ndarray, float]:
    small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
    histogram = cv2.normalize(histogram, histogram).flatten()
    luma = float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean()) / 255.0
    return histogram, luma


def _signature_distance(
    previous: tuple[np.ndarray, float],
    current: tuple[np.ndarray, float],
) -> float:
    histogram_score = 1.0 - float(cv2.compareHist(previous[0], current[0], cv2.HISTCMP_CORREL))
    luma_score = abs(previous[1] - current[1])
    return max(0.0, histogram_score) * 0.78 + luma_score * 0.22


def detect_shot_ranges(
    path: str | Path,
    *,
    threshold: float = 0.36,
    minimum_shot_seconds: float = 0.8,
    sample_fps: float = 8.0,
) -> list[TimeRange]:
    media = probe_media(path)
    capture = cv2.VideoCapture(media.path)
    if not capture.isOpened():
        raise ShotDetectionError(f"OpenCV could not open {media.path}")

    sample_interval = max(1, round(media.fps / sample_fps))
    minimum_frames = max(1, round(minimum_shot_seconds * media.fps))
    cuts: list[int] = [0]
    previous_signature: tuple[np.ndarray, float] | None = None
    frame_index = 0

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_index % sample_interval:
                frame_index += 1
                continue

            signature = _frame_signature(frame)
            if previous_signature is not None:
                distance = _signature_distance(previous_signature, signature)
                if distance >= threshold and frame_index - cuts[-1] >= minimum_frames:
                    cuts.append(frame_index)
            previous_signature = signature
            frame_index += 1
    finally:
        capture.release()

    final_frame = media.frame_count or max(frame_index, 1)
    if final_frame - cuts[-1] < minimum_frames and len(cuts) > 1:
        cuts.pop()
    cuts.append(final_frame)

    ranges = [
        TimeRange(
            start_seconds=min(start / media.fps, media.duration_seconds),
            end_seconds=min(end / media.fps, media.duration_seconds),
        )
        for start, end in zip(cuts, cuts[1:], strict=False)
        if end > start and min(end / media.fps, media.duration_seconds) > start / media.fps
    ]
    if not ranges:
        ranges = [TimeRange(start_seconds=0, end_seconds=max(media.duration_seconds, 0.001))]
    return ranges


def detect_shot_ranges_pyscenedetect(
    path: str | Path,
    *,
    adaptive_threshold: float = 3.0,
    minimum_content_value: float = 15.0,
    minimum_shot_seconds: float = 0.8,
) -> list[TimeRange]:
    """Run the explicit PySceneDetect Adaptive CPU fallback.

    This path is intentionally separate from :func:`detect_shot_ranges` so
    installing or upgrading the fallback cannot silently change existing
    projects.
    """
    if adaptive_threshold <= 0:
        raise ValueError("adaptive_threshold must be positive")
    if minimum_content_value < 0:
        raise ValueError("minimum_content_value must be non-negative")
    if minimum_shot_seconds <= 0:
        raise ValueError("minimum_shot_seconds must be positive")

    from scenedetect import AdaptiveDetector, detect

    media = probe_media(path)
    minimum_frames = max(1, round(minimum_shot_seconds * media.fps))
    try:
        scenes = detect(
            media.path,
            AdaptiveDetector(
                adaptive_threshold=adaptive_threshold,
                min_scene_len=minimum_frames,
                min_content_val=minimum_content_value,
            ),
            show_progress=False,
        )
    except Exception as exc:
        raise ShotDetectionError(
            f"PySceneDetect Adaptive could not process {media.path}: {exc}"
        ) from exc

    ranges = [
        TimeRange(
            start_seconds=max(0.0, float(start.seconds)),
            end_seconds=min(
                media.duration_seconds,
                float(end.seconds),
            ),
        )
        for start, end in scenes
        if end.seconds > start.seconds
    ]
    if not ranges:
        return [
            TimeRange(
                start_seconds=0,
                end_seconds=max(media.duration_seconds, 0.001),
            )
        ]
    return ranges


def pyscenedetect_boundary_frames(
    ranges: list[TimeRange],
    *,
    fps: float,
) -> list[int]:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return sorted({max(0, round(shot.start_seconds * fps)) for shot in ranges[1:]})
