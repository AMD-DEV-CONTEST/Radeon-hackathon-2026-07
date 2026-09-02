from pathlib import Path

import cv2
import numpy as np
import pytest

from colorgraph.media.shots import (
    PYSCENEDETECT_LICENSE_ID,
    PYSCENEDETECT_SOURCE_REVISION,
    PYSCENEDETECT_VERSION,
    PYSCENEDETECT_WHEEL_SHA256,
    detect_shot_ranges_pyscenedetect,
    pyscenedetect_boundary_frames,
)


def _write_video(path: Path, *, hard_cut: bool) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (96, 64),
    )
    assert writer.isOpened()
    for frame_index in range(60):
        if hard_cut and frame_index >= 30:
            frame = np.full((64, 96, 3), (25, 210, 35), dtype=np.uint8)
            cv2.rectangle(frame, (8, 8), (52, 56), (220, 20, 210), -1)
        else:
            frame = np.full((64, 96, 3), (180, 35, 25), dtype=np.uint8)
            cv2.circle(frame, (72, 32), 18, (20, 220, 220), -1)
        writer.write(frame)
    writer.release()


def test_pyscenedetect_adaptive_fallback_detects_a_hard_cut(
    tmp_path: Path,
) -> None:
    source = tmp_path / "hard-cut.avi"
    _write_video(source, hard_cut=True)

    ranges = detect_shot_ranges_pyscenedetect(
        source,
        adaptive_threshold=1.5,
        minimum_content_value=8,
        minimum_shot_seconds=0.5,
    )
    boundaries = pyscenedetect_boundary_frames(ranges, fps=10)

    assert len(ranges) == 2
    assert boundaries == [30]


def test_pyscenedetect_no_cut_returns_the_full_media_range(
    tmp_path: Path,
) -> None:
    source = tmp_path / "single-shot.avi"
    _write_video(source, hard_cut=False)

    ranges = detect_shot_ranges_pyscenedetect(
        source,
        minimum_shot_seconds=0.5,
    )

    assert len(ranges) == 1
    assert ranges[0].start_seconds == 0
    assert ranges[0].end_seconds == pytest.approx(6.0, abs=0.05)


def test_pyscenedetect_dependency_identity_is_frozen() -> None:
    assert PYSCENEDETECT_VERSION == "0.7.1"
    assert PYSCENEDETECT_LICENSE_ID == "BSD-3-Clause"
    assert len(PYSCENEDETECT_SOURCE_REVISION) == 40
    assert len(PYSCENEDETECT_WHEEL_SHA256) == 64
