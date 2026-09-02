from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from colorgraph.evaluation.shot_shadow import (
    ShotDatasetEvidence,
    ShotEvaluationItem,
    ShotEvent,
    ShotModelArtifacts,
    ShotModelRun,
    ShotShadowBundle,
    capture_shot_model_observations,
    capture_shot_model_observations_file,
)
from colorgraph.media.shots import PYSCENEDETECT_SOURCE_REVISION


def _write_hard_cut_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (96, 64),
    )
    assert writer.isOpened()
    for frame_index in range(60):
        if frame_index < 30:
            frame = np.full((64, 96, 3), (180, 35, 25), dtype=np.uint8)
            cv2.circle(frame, (72, 32), 18, (20, 220, 220), -1)
        else:
            frame = np.full((64, 96, 3), (25, 210, 35), dtype=np.uint8)
            cv2.rectangle(frame, (8, 8), (52, 56), (220, 20, 210), -1)
        writer.write(frame)
    writer.release()


def _bundle(media_path: Path) -> ShotShadowBundle:
    media_sha256 = hashlib.sha256(media_path.read_bytes()).hexdigest()
    common_artifacts = {
        "code_url": "https://example.com/colorgraph",
        "code_license_id": "MIT",
        "code_commercial_use_allowed": True,
        "weights_required": False,
    }
    return ShotShadowBundle(
        created_at=datetime.now(UTC),
        dataset=ShotDatasetEvidence(
            evidence_class="engineering_fixture",
            test_frozen_at=datetime.now(UTC),
            annotation_guideline_version="shot-observation-test/v1",
        ),
        items=[
            ShotEvaluationItem(
                item_id="hard-cut",
                source_group_id="hard-cut",
                media_origin="procedural",
                media_sha256=media_sha256,
                annotation_sha256="a" * 64,
                frame_count=60,
                fps=10,
                events=[
                    ShotEvent(
                        event_id="hard",
                        kind="hard_cut",
                        start_frame=30,
                        end_frame=30,
                    )
                ],
            )
        ],
        runs=[
            ShotModelRun(
                model_id="current_detector",
                status="blocked",
                artifacts=ShotModelArtifacts(
                    **common_artifacts,
                    source_revision="b" * 40,
                ),
                blocker="runtime observation not captured",
            ),
            ShotModelRun(
                model_id="pyscenedetect_adaptive",
                status="blocked",
                artifacts=ShotModelArtifacts(
                    code_url="https://github.com/Breakthrough/PySceneDetect",
                    code_license_id="BSD-3-Clause",
                    code_commercial_use_allowed=True,
                    source_revision=PYSCENEDETECT_SOURCE_REVISION,
                    weights_required=False,
                ),
                blocker="runtime observation not captured",
            ),
        ],
    )


def test_capture_cpu_fallback_observations_are_measured_and_mergeable(
    tmp_path: Path,
) -> None:
    media_path = tmp_path / "hard-cut.avi"
    _write_hard_cut_video(media_path)
    source_bundle = _bundle(media_path)

    current = capture_shot_model_observations(
        source_bundle,
        model_id="current_detector",
        media_paths={"hard-cut": media_path},
    )
    current_run = next(
        item for item in current.runs if item.model_id == "current_detector"
    )
    assert current_run.status == "completed"
    assert current_run.observations[0].predicted_boundaries == [30]
    assert current_run.observations[0].elapsed_seconds > 0
    assert current_run.observations[0].peak_cpu_memory_mb > 0
    assert source_bundle.runs[0].status == "blocked"

    input_path = tmp_path / "current.json"
    output_path = tmp_path / "both.json"
    input_path.write_text(
        current.model_dump_json(indent=2),
        encoding="utf-8",
    )
    captured = capture_shot_model_observations_file(
        input_path,
        output_path,
        model_id="pyscenedetect_adaptive",
        media_paths={"hard-cut": media_path},
    )
    pyscene_run = next(
        item
        for item in captured.runs
        if item.model_id == "pyscenedetect_adaptive"
    )

    assert output_path.is_file()
    assert pyscene_run.status == "completed"
    assert pyscene_run.observations[0].predicted_boundaries == [30]
    assert all(item.status == "completed" for item in captured.runs)


def test_capture_rejects_media_that_does_not_match_frozen_sha(
    tmp_path: Path,
) -> None:
    media_path = tmp_path / "hard-cut.avi"
    _write_hard_cut_video(media_path)
    bundle = _bundle(media_path)
    media_path.write_bytes(media_path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        capture_shot_model_observations(
            bundle,
            model_id="current_detector",
            media_paths={"hard-cut": media_path},
        )


def test_internal_detector_accepts_a_frozen_workspace_source() -> None:
    artifacts = ShotModelArtifacts(
        code_url="workspace://backend/colorgraph/media/shots.py",
        code_license_id="user-authorized-project-code-use",
        code_commercial_use_allowed=True,
        source_revision="c" * 40,
        weights_required=False,
    )

    assert artifacts.code_url.startswith("workspace://")
