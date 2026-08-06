import hashlib
from pathlib import Path

import pytest
import torch

from colorgraph.agent import (
    SceneCalibrationExample,
    SceneGroupingCalibration,
    SceneGroupingWeights,
    SceneTag,
    calibrate_scene_grouping,
    group_consecutive_shots,
    load_scene_grouping_calibration,
)
from colorgraph.domain.grade_graph import ColorSpace, MediaInfo, NodeType, TimeRange
from colorgraph.services.graph_builder import build_initial_graph


def _calibration(
    *,
    threshold: float,
    release_threshold: float | None = None,
    minimum_scene_shots: int = 1,
    weights: SceneGroupingWeights | None = None,
) -> SceneGroupingCalibration:
    return SceneGroupingCalibration(
        id="test-calibration",
        dataset_version="synthetic-test",
        source_split="bootstrap",
        source_sha256="0" * 64,
        status="bootstrap_not_gold",
        weights=weights
        or SceneGroupingWeights(visual=0.7, color=0.3, semantic=0, audio=0),
        boundary_threshold=threshold,
        release_threshold=(
            release_threshold if release_threshold is not None else threshold
        ),
        minimum_scene_shots=minimum_scene_shots,
        color_feature_scales=[0.35, 0.2, 0.15, 0.25],
    )


def test_group_consecutive_shots_splits_large_visual_change() -> None:
    embeddings = torch.tensor(
        [
            [1.0, 0.0],
            [0.98, 0.05],
            [-0.8, 0.2],
        ]
    )
    result = group_consecutive_shots(embeddings)
    assert result.shot_groups == [[0, 1], [2]]
    assert result.adjacent_similarities[0] > 0.9
    assert result.adjacent_similarities[1] < 0


def test_continuous_boundary_score_combines_visual_color_and_audio_change() -> None:
    embeddings = torch.tensor(
        [
            [1.0, 0.0],
            [0.99, 0.03],
            [0.94, 0.20],
        ]
    )
    colors = torch.tensor(
        [
            [0.0, 0.0, 0.0, 0.0],
            [0.02, 0.01, 0.0, 0.0],
            [0.80, 0.30, 0.10, 0.20],
        ]
    )
    audio = torch.tensor(
        [
            [1.0, 0.0],
            [0.99, 0.02],
            [0.0, 1.0],
        ]
    )
    calibration = _calibration(
        threshold=0.18,
        weights=SceneGroupingWeights(
            visual=0.40,
            color=0.35,
            semantic=0.0,
            audio=0.25,
        ),
    )

    result = group_consecutive_shots(
        embeddings,
        color_features=colors,
        audio_features=audio,
        calibration=calibration,
        selection_mode="calibrated",
    )

    assert result.shot_groups == [[0, 1], [2]]
    assert result.boundary_scores[1] > result.boundary_scores[0]
    assert result.boundary_features[1].color_change > 0.7
    assert result.boundary_features[1].audio_change > 0.9


def test_shadow_mode_persists_candidate_without_replacing_legacy_groups() -> None:
    embeddings = torch.tensor([[1.0, 0.0], [0.75, 0.6614]])
    result = group_consecutive_shots(
        embeddings,
        calibration=_calibration(threshold=0.40),
        selection_mode="shadow",
    )

    assert result.baseline_shot_groups == [[0], [1]]
    assert result.candidate_shot_groups == [[0, 1]]
    assert result.shot_groups == result.baseline_shot_groups
    assert result.selection_mode == "shadow"
    assert result.calibration.status == "bootstrap_not_gold"


def test_dynamic_program_respects_minimum_scene_length() -> None:
    embeddings = torch.tensor(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.02, 0.99],
            [-1.0, 0.0],
            [-0.99, 0.03],
        ]
    )
    result = group_consecutive_shots(
        embeddings,
        calibration=_calibration(
            threshold=0.25,
            minimum_scene_shots=2,
            weights=SceneGroupingWeights(
                visual=1.0,
                color=0.0,
                semantic=0.0,
                audio=0.0,
            ),
        ),
        selection_mode="calibrated",
    )

    assert 1 not in result.selected_boundaries
    assert result.shot_groups == [[0, 1, 2], [3, 4]]


def test_calibration_selects_threshold_from_calibration_split() -> None:
    examples = [
        SceneCalibrationExample(
            embeddings=torch.tensor(
                [[1.0, 0.0], [0.82, 0.57], [0.80, 0.60], [0.78, 0.62]]
            ),
            color_features=torch.tensor(
                [
                    [0.0, 0.0, 0.0, 0.0],
                    [0.70, 0.30, 0.10, 0.20],
                    [0.71, 0.31, 0.10, 0.20],
                    [0.72, 0.31, 0.10, 0.20],
                ]
            ),
            reference_boundaries=[1],
        ),
        SceneCalibrationExample(
            embeddings=torch.tensor(
                [[1.0, 0.0], [0.99, 0.02], [0.98, 0.04], [0.97, 0.06]]
            ),
            color_features=torch.tensor(
                [
                    [0.0, 0.0, 0.0, 0.0],
                    [0.01, 0.0, 0.0, 0.0],
                    [0.02, 0.0, 0.0, 0.0],
                    [0.03, 0.0, 0.0, 0.0],
                ]
            ),
            reference_boundaries=[],
        ),
    ]
    calibration = calibrate_scene_grouping(
        examples,
        calibration_id="unit-calibration",
        dataset_version="unit-v1",
        weights=SceneGroupingWeights(
            visual=0.45,
            color=0.55,
            semantic=0.0,
            audio=0.0,
        ),
        color_feature_scales=[0.35, 0.2, 0.15, 0.25],
    )

    first = group_consecutive_shots(
        examples[0].embeddings,
        color_features=examples[0].color_features,
        calibration=calibration,
        selection_mode="calibrated",
    )
    second = group_consecutive_shots(
        examples[1].embeddings,
        color_features=examples[1].color_features,
        calibration=calibration,
        selection_mode="calibrated",
    )

    assert calibration.source_split == "calibration"
    assert calibration.status == "calibration_only"
    assert first.selected_boundaries == [1]
    assert second.selected_boundaries == []


def test_calibration_rejects_train_or_test_split() -> None:
    example = SceneCalibrationExample(
        embeddings=torch.tensor([[1.0, 0.0], [0.0, 1.0]]),
        reference_boundaries=[1],
        split="test",
    )

    with pytest.raises(ValueError, match="only use calibration split"):
        calibrate_scene_grouping(
            [example],
            calibration_id="invalid",
            dataset_version="test",
            weights=SceneGroupingWeights(
                visual=1,
                color=0,
                semantic=0,
                audio=0,
            ),
        )


def test_bootstrap_calibration_records_exact_source_hash() -> None:
    calibration = load_scene_grouping_calibration()
    source = (
        Path(__file__).parents[1]
        / "colorgraph"
        / "agent"
        / "calibration"
        / "scene_grouping_bootstrap_examples_v1.json"
    )

    assert hashlib.sha256(source.read_bytes()).hexdigest() == calibration.source_sha256
    assert calibration.status == "bootstrap_not_gold"


def test_graph_builder_assigns_scene_scopes_and_reference_look() -> None:
    media = MediaInfo(
        path="source.mp4",
        duration_seconds=9,
        width=1280,
        height=720,
        fps=25,
        frame_count=225,
        codec="h264",
        input_color_space=ColorSpace.BT709_OETF,
    )
    graph = build_initial_graph(
        project_id="project_scenes",
        project_name="Scenes",
        media=media,
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=3),
            TimeRange(start_seconds=3, end_seconds=6),
            TimeRange(start_seconds=6, end_seconds=9),
        ],
        representative_frames=[
            Path("shot_001.jpg"),
            Path("shot_002.jpg"),
            Path("shot_003.jpg"),
        ],
        scene_groups=[[0, 1], [2]],
        reference_frame=Path("reference.jpg"),
        reference_style=SceneTag(
            label="cool restrained documentary",
            confidence=0.91,
        ),
    )

    assert [scene.shot_ids for scene in graph.scenes] == [
        ["shot_001", "shot_002"],
        ["shot_003"],
    ]
    assert [shot.scene_id for shot in graph.shots] == [
        "scene_001",
        "scene_001",
        "scene_002",
    ]
    looks = [node for node in graph.nodes if node.type == NodeType.LOOK]
    assert [node.metadata["recipe_id"] for node in looks] == ["cool", "cool"]
    assert looks[0].temporal_scope.time_range == TimeRange(
        start_seconds=0,
        end_seconds=6,
    )
    assert looks[1].temporal_scope.time_range == TimeRange(
        start_seconds=6,
        end_seconds=9,
    )
