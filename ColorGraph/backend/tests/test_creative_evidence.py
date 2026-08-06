from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import torch

from colorgraph.agent.creative_contracts import ContextBudget
from colorgraph.agent.creative_evidence import (
    EVIDENCE_BUNDLE_VERSION,
    AudioAvailability,
    MotionClassification,
    build_project_evidence_pack,
)
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import ColorSpace, MediaInfo, TimeRange
from colorgraph.grading.color import (
    SONY_SLOG3_SGAMUT3CINE,
    linear_rec709_to_slog3,
)
from colorgraph.services.graph_builder import build_initial_graph

FIXED_TIME = datetime(2026, 7, 29, 9, tzinfo=UTC)


def _write_evidence_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (64, 36),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV MJPEG writer is unavailable")
    x = np.linspace(35, 205, 64, dtype=np.uint8)
    background = np.broadcast_to(x, (36, 64)).copy()
    try:
        for frame_index in range(20):
            if frame_index < 10:
                blue = background
            else:
                rng = np.random.default_rng(frame_index)
                blue = background.copy()
                moving = rng.integers(
                    65,
                    220,
                    size=(36, 32),
                    dtype=np.uint8,
                )
                blue[:, 16:48] = np.roll(
                    moving,
                    shift=(frame_index - 10) * 2,
                    axis=0,
                )
            rgb = np.stack(
                (
                    np.flip(background, axis=1),
                    background,
                    blue,
                ),
                axis=2,
            )
            writer.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    finally:
        writer.release()


def _cross_scene_graph(source: Path):
    return build_initial_graph(
        project_id="creative-evidence",
        project_name="Creative Evidence",
        media=MediaInfo(
            path=str(source),
            duration_seconds=2,
            width=64,
            height=36,
            fps=10,
            frame_count=20,
            codec="mjpeg",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=1),
            TimeRange(start_seconds=1, end_seconds=2),
        ],
        representative_frames=[
            Path("shot-1.jpg"),
            Path("shot-2.jpg"),
        ],
        scene_groups=[[0], [1]],
    )


def _budget(maximum_images: int = 4) -> ContextBudget:
    return ContextBudget(
        maximum_images=maximum_images,
        maximum_image_edge=256,
        maximum_audio_seconds=10.0,
        maximum_tokens=8_000,
        maximum_context_bytes=8_000_000,
    )


def test_cross_scene_evidence_is_reproducible_traceable_and_audio_explicit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "two-scenes.avi"
    _write_evidence_video(source)
    graph = _cross_scene_graph(source)
    backend = TorchComputeBackend("cpu")

    first = build_project_evidence_pack(
        source=source,
        graph=graph,
        output_root=tmp_path / "evidence-a",
        backend=backend,
        budget=_budget(),
        created_at=FIXED_TIME,
    )
    second = build_project_evidence_pack(
        source=source,
        graph=graph,
        output_root=tmp_path / "evidence-b",
        backend=backend,
        budget=_budget(),
        created_at=FIXED_TIME,
    )

    assert first.evidence_bundle_digest == second.evidence_bundle_digest
    assert first.evidence_bundle == second.evidence_bundle
    assert len(first.evidence_bundle.scenes) == 2
    assert len(first.evidence_bundle.shots) == 2
    assert all(
        packet.audio.status == AudioAvailability.NO_TRACK
        for packet in first.evidence_bundle.shots
    )
    assert all(
        packet.audio.transcription_status == "not_requested"
        and packet.audio.cloud_uploaded is False
        for packet in first.evidence_bundle.shots
    )
    assert (
        first.evidence_bundle.shots[0].motion.classification
        == MotionClassification.STATIC
    )
    assert (
        first.evidence_bundle.shots[1].motion.object_residual_p90
        > first.evidence_bundle.shots[0].motion.object_residual_p90
    )
    known_evidence = {
        item.evidence_id
        for item in first.context_pack.evidence
    }
    for packet in first.evidence_bundle.shots:
        assert set(packet.supporting_evidence_ids) <= known_evidence
        assert set(packet.counterevidence_ids) <= known_evidence
    assert all(
        artifact.display_transform_applied
        and artifact.physical_statistics_separate
        for artifact in first.evidence_bundle.artifacts
    )
    assert len(
        [
            artifact
            for artifact in first.evidence_bundle.artifacts
            if artifact.kind.value == "contact_sheet"
        ]
    ) == 2
    assert first.context_pack.evidence_bundle_schema_version == (
        EVIDENCE_BUNDLE_VERSION
    )
    assert (
        first.context_pack.evidence_bundle_digest
        == first.evidence_bundle_digest
    )


def test_evidence_budget_records_omissions_without_dropping_shot_packets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "budget.avi"
    _write_evidence_video(source)
    graph = _cross_scene_graph(source)

    result = build_project_evidence_pack(
        source=source,
        graph=graph,
        output_root=tmp_path / "budget-evidence",
        backend=TorchComputeBackend("cpu"),
        budget=_budget(maximum_images=1),
        created_at=FIXED_TIME,
    )

    assert len(result.evidence_bundle.model_input_evidence_ids) == 1
    assert result.evidence_bundle.omitted_candidate_ids
    assert result.evidence_bundle.omission_reason is not None
    assert result.context_pack.omitted_evidence_ids == (
        result.evidence_bundle.omitted_candidate_ids
    )
    assert len(result.evidence_bundle.shots) == 2
    assert all(
        packet.measurement_evidence_ids
        for packet in result.evidence_bundle.shots
    )


def _write_slog_snow_video(path: Path) -> None:
    height, width = 36, 64
    linear = torch.linspace(
        0.45,
        0.95,
        width,
        dtype=torch.float32,
    ).view(1, 1, 1, width)
    linear_rgb = linear.expand(1, 3, height, width)
    encoded = (
        linear_rec709_to_slog3(linear_rgb)[0]
        .permute(1, 2, 0)
        .clamp(0, 1)
        .mul(255)
        .round()
        .byte()
        .numpy()
    )
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV MJPEG writer is unavailable")
    try:
        for _ in range(10):
            writer.write(cv2.cvtColor(encoded, cv2.COLOR_RGB2BGR))
    finally:
        writer.release()


def test_log_snow_preview_is_display_transformed_while_physical_signal_stays_separate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "snow-log.avi"
    _write_slog_snow_video(source)
    graph = build_initial_graph(
        project_id="log-snow-evidence",
        project_name="Log Snow Evidence",
        media=MediaInfo(
            path=str(source),
            duration_seconds=1,
            width=64,
            height=36,
            fps=10,
            frame_count=10,
            codec="mjpeg",
            input_color_space=ColorSpace.LOG,
            source_log_profile=SONY_SLOG3_SGAMUT3CINE,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1)],
        representative_frames=[Path("snow.jpg")],
    )

    result = build_project_evidence_pack(
        source=source,
        graph=graph,
        output_root=tmp_path / "log-evidence",
        backend=TorchComputeBackend("cpu"),
        budget=_budget(maximum_images=2),
        created_at=FIXED_TIME,
    )

    assert (
        result.technical_baseline.payload.color_pipeline.input_color_space
        == "log"
    )
    assert all(
        artifact.source_color_space == "log"
        and artifact.display_color_space == "srgb"
        and artifact.display_transform_applied
        for artifact in result.evidence_bundle.artifacts
    )
    assert any(
        abs(item.encoded_mean_luma - item.display_mean_luma) > 0.05
        for item in result.evidence_bundle.frame_statistics
    )
    assert result.evidence_bundle.physical_statistics_separate is True
