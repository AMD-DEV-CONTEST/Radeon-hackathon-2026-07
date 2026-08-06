from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from colorgraph.agent.scene_grouping import group_consecutive_shots
from colorgraph.domain.grade_graph import MediaInfo, TimeRange
from colorgraph.media.representative_frames import (
    REPRESENTATIVE_FRAME_VERSION,
    FrameCandidate,
    FrameQualityMetrics,
    ShotFrameCandidates,
    candidate_timestamps,
    extract_representative_candidates,
    materialize_representatives,
    measure_frame_quality,
    quality_representative_sources,
    representative_metadata,
    select_cosine_medoids,
)
from colorgraph.services.graph_builder import build_initial_graph


def _quality(score: float = 5.0) -> FrameQualityMetrics:
    return FrameQualityMetrics(
        sharpness=100,
        entropy=6,
        mean_luma=0.5,
        black_ratio=0,
        clipping_ratio=0,
        quality_score=score,
    )


def _candidate(
    path: Path,
    timestamp: float,
    *,
    accepted: bool = True,
    score: float = 5.0,
) -> FrameCandidate:
    return FrameCandidate(
        path=path,
        time_seconds=timestamp,
        quality=_quality(score),
        accepted=accepted,
        rejection_reasons=() if accepted else ("blur",),
    )


def test_candidate_schedule_adapts_to_shot_duration_and_avoids_edges() -> None:
    ranges = [
        TimeRange(start_seconds=0, end_seconds=1),
        TimeRange(start_seconds=2, end_seconds=6),
        TimeRange(start_seconds=10, end_seconds=18),
    ]

    timestamps = [candidate_timestamps(time_range, fps=25) for time_range in ranges]

    assert [len(values) for values in timestamps] == [3, 5, 7]
    for time_range, values in zip(ranges, timestamps, strict=True):
        assert values[0] > time_range.start_seconds
        assert values[-1] < time_range.end_seconds
        assert values == sorted(values)


def test_quality_gate_rejects_black_low_entropy_blur_and_clipping(
    tmp_path: Path,
) -> None:
    black = tmp_path / "black.png"
    white = tmp_path / "white.png"
    textured = tmp_path / "textured.png"
    cv2.imwrite(str(black), np.zeros((96, 128, 3), dtype=np.uint8))
    cv2.imwrite(str(white), np.full((96, 128, 3), 255, dtype=np.uint8))
    rng = np.random.default_rng(7)
    cv2.imwrite(
        str(textured),
        rng.integers(20, 235, size=(96, 128, 3), dtype=np.uint8),
    )

    _, black_reasons = measure_frame_quality(black)
    _, white_reasons = measure_frame_quality(white)
    textured_quality, textured_reasons = measure_frame_quality(textured)

    assert {"black_frame", "low_entropy", "blur", "severe_clipping"} <= set(
        black_reasons
    )
    assert {"low_entropy", "blur", "severe_clipping"} <= set(white_reasons)
    assert textured_reasons == ()
    assert textured_quality.entropy > 6
    assert textured_quality.sharpness > 18


def test_candidate_extraction_uses_shared_multi_frame_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transformed: list[Path] = []

    def fake_extract(
        media_path: str | Path,
        time_seconds: float,
        output_path: str | Path,
        **_: object,
    ) -> Path:
        del media_path
        destination = Path(output_path)
        rng = np.random.default_rng(round(time_seconds * 1000) + 1)
        image = rng.integers(20, 235, size=(64, 96, 3), dtype=np.uint8)
        cv2.imwrite(str(destination), image)
        return destination

    monkeypatch.setattr(
        "colorgraph.media.representative_frames.extract_frame",
        fake_extract,
    )
    ranges = [
        TimeRange(start_seconds=0, end_seconds=1),
        TimeRange(start_seconds=1, end_seconds=5),
        TimeRange(start_seconds=5, end_seconds=12),
    ]

    result = extract_representative_candidates(
        tmp_path / "source.mov",
        ranges,
        tmp_path / "frames",
        fps=25,
        frame_transform=lambda path: transformed.append(path),
    )

    assert [shot.requested_count for shot in result] == [3, 5, 7]
    assert len(transformed) == 15
    assert all(candidate.accepted for shot in result for candidate in shot.candidates)
    assert result[2].candidates[-1].time_seconds < 12


def test_cosine_medoid_ignores_embedding_outlier_and_uses_robust_mean(
    tmp_path: Path,
) -> None:
    candidates = (
        _candidate(tmp_path / "early.jpg", 0.5),
        _candidate(tmp_path / "middle.jpg", 1.0),
        _candidate(tmp_path / "outlier.jpg", 1.5),
    )
    shot = ShotFrameCandidates(
        shot_index=0,
        time_range=TimeRange(start_seconds=0, end_seconds=2),
        requested_count=3,
        candidates=candidates,
    )
    embeddings = torch.tensor(
        [
            [1.0, 0.0],
            [0.98, 0.20],
            [-1.0, 0.0],
        ]
    )

    selection = select_cosine_medoids([shot], embeddings)

    assert selection.source_paths == [tmp_path / "middle.jpg"]
    assert float(selection.shot_embeddings[0, 0]) > 0.98
    assert float(selection.shot_embeddings[0, 1]) > 0
    assert (
        selection.metadata[0]["selection_method"]
        == "cosine_medoid_with_robust_mean_embedding"
    )
    assert selection.metadata[0]["accepted_count"] == 3


def test_cosine_medoid_tie_prefers_temporal_center(tmp_path: Path) -> None:
    shot = ShotFrameCandidates(
        shot_index=0,
        time_range=TimeRange(start_seconds=0, end_seconds=2),
        requested_count=3,
        candidates=(
            _candidate(tmp_path / "early.jpg", 0.25),
            _candidate(tmp_path / "middle.jpg", 1.0),
            _candidate(tmp_path / "late.jpg", 1.75),
        ),
    )

    selection = select_cosine_medoids(
        [shot],
        torch.tensor([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]),
    )

    assert selection.source_paths == [tmp_path / "middle.jpg"]


def test_quality_filter_avoids_rejected_midpoint(tmp_path: Path) -> None:
    shot = ShotFrameCandidates(
        shot_index=0,
        time_range=TimeRange(start_seconds=0, end_seconds=4),
        requested_count=5,
        candidates=(
            _candidate(tmp_path / "early.jpg", 1.0, score=4),
            _candidate(tmp_path / "middle-black.jpg", 2.0, accepted=False, score=8),
            _candidate(tmp_path / "late.jpg", 3.0, score=5),
        ),
    )

    selected = quality_representative_sources([shot])

    assert selected == [tmp_path / "late.jpg"]


def test_robust_shot_embedding_prevents_midpoint_outlier_scene_split(
    tmp_path: Path,
) -> None:
    shots = [
        ShotFrameCandidates(
            shot_index=index,
            time_range=TimeRange(start_seconds=index * 3, end_seconds=(index + 1) * 3),
            requested_count=3,
            candidates=tuple(
                _candidate(
                    tmp_path / f"shot-{index}-candidate-{candidate_index}.jpg",
                    index * 3 + 0.75 * (candidate_index + 1),
                )
                for candidate_index in range(3)
            ),
        )
        for index in range(2)
    ]
    candidate_embeddings = torch.tensor(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.99, 0.05],
            [1.0, 0.0],
            [1.0, 0.02],
            [0.99, -0.05],
        ]
    )

    baseline = group_consecutive_shots(
        torch.stack((candidate_embeddings[1], candidate_embeddings[4]))
    )
    selection = select_cosine_medoids(shots, candidate_embeddings)
    robust = group_consecutive_shots(selection.shot_embeddings)

    assert baseline.shot_groups == [[0], [1]]
    assert robust.shot_groups == [[0, 1]]
    assert robust.adjacent_similarities[0] > 0.99


def test_materialized_medoid_keeps_canonical_ui_filename_and_graph_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "shot_001_candidate_02.jpg"
    source.write_bytes(b"selected-medoid")
    shot = ShotFrameCandidates(
        shot_index=0,
        time_range=TimeRange(start_seconds=0, end_seconds=2),
        requested_count=3,
        candidates=(_candidate(source, 1.0),),
    )
    metadata = representative_metadata(
        [shot],
        [source],
        method="cosine_medoid_with_robust_mean_embedding",
        medoid_similarities=[0.95],
    )

    representatives = materialize_representatives([shot], [source])
    graph = build_initial_graph(
        project_id="representative-evidence",
        project_name="Representative evidence",
        media=MediaInfo(
            path="source.mov",
            duration_seconds=2,
            width=1920,
            height=1080,
            fps=25,
            frame_count=50,
            codec="h264",
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=2)],
        representative_frames=representatives,
        representative_frame_metadata=metadata,
    )

    assert representatives[0].name == "shot_001.jpg"
    assert representatives[0].read_bytes() == b"selected-medoid"
    assert graph.shots[0].representative_frame == str(representatives[0])
    assert graph.metadata["representative_frames"][0]["version"] == (
        REPRESENTATIVE_FRAME_VERSION
    )
    assert graph.metadata["representative_frames"][0]["medoid_mean_similarity"] == 0.95
