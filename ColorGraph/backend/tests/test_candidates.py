from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from colorgraph.api.routes import operations
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    ColorSpace,
    Keyframe,
    MediaInfo,
    NodeType,
    ParameterTrack,
    TimeRange,
)
from colorgraph.grading.looks import (
    LOOK_PARAMETER_KEYS,
    LOOK_RECIPE_SCHEMA,
    LOOK_RECIPE_VERSION,
    graph_digest,
    look_parameters,
    look_recipe_catalog,
    sync_look_instances,
)
from colorgraph.services.candidates import (
    CANDIDATE_RANKING_VERSION,
    CandidateSamplePoint,
    _candidate_sample_plan,
    _frame_quality_metrics,
    _hard_failures,
    generate_look_candidates,
    graph_with_look_recipe,
    pareto_fronts,
)
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.storage import ProjectStore


def _two_scene_graph(project_id: str = "candidate_test"):
    media = MediaInfo(
        path="source.mp4",
        duration_seconds=8,
        width=640,
        height=360,
        fps=25,
        frame_count=200,
        codec="h264",
        input_color_space=ColorSpace.BT709_OETF,
    )
    return build_initial_graph(
        project_id=project_id,
        project_name="Candidates",
        media=media,
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=4),
            TimeRange(start_seconds=4, end_seconds=8),
        ],
        representative_frames=[Path("one.jpg"), Path("two.jpg")],
        scene_groups=[[0], [1]],
    )


def test_candidate_recipe_only_changes_active_scene() -> None:
    graph = _two_scene_graph()

    updated = graph_with_look_recipe(graph, "warm", time_seconds=6)
    looks = [node for node in updated.nodes if node.type == NodeType.LOOK]
    assert looks[0].metadata["recipe_id"] == "natural"
    assert looks[1].metadata["recipe_id"] == "warm"
    assert looks[1].parameters["temperature"] == 0.18
    assert looks[1].metadata["look_instance"] == {
        "schema_version": "colorgraph.look-instance/v1",
        "recipe_version": LOOK_RECIPE_VERSION,
        "base_recipe_id": "warm",
        "user_overrides": {},
        "dirty": False,
    }


def test_multiframe_sample_plan_covers_shots_and_keyframes_reproducibly() -> None:
    graph = build_initial_graph(
        project_id="candidate-sampling",
        project_name="Candidate Sampling",
        media=MediaInfo(
            path="source.mp4",
            duration_seconds=8,
            width=640,
            height=360,
            fps=25,
            frame_count=200,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=4),
            TimeRange(start_seconds=4, end_seconds=8),
        ],
        representative_frames=[Path("one.jpg"), Path("two.jpg")],
    )
    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.tracks = [
        ParameterTrack(
            parameter="contrast",
            keyframes=[
                Keyframe(time_seconds=1, value=0),
                Keyframe(time_seconds=5.48, value=0.2),
            ],
        )
    ]

    first = _candidate_sample_plan(graph, 2.2)
    second = _candidate_sample_plan(graph, 2.2)

    assert first == second
    assert 2 <= len(first) <= 7
    assert any(sample.frame_index < 100 for sample in first)
    assert any(sample.frame_index >= 100 for sample in first)
    keyframe_sample = next(sample for sample in first if sample.frame_index == 137)
    assert any(reason.endswith(":keyframe") for reason in keyframe_sample.reasons)
    assert any("requested_time" in sample.reasons for sample in first)


def test_pareto_fronts_are_reproducible_without_a_weighted_sum() -> None:
    objectives = {
        "warm": {
            "intent": 0.9,
            "aesthetic": 0.5,
            "conservatism": 0.5,
        },
        "natural": {
            "intent": 0.7,
            "aesthetic": 0.7,
            "conservatism": 0.5,
        },
        "damaged": {
            "intent": 0.6,
            "aesthetic": 0.6,
            "conservatism": 0.4,
        },
    }

    expected = [["natural", "warm"], ["damaged"]]
    assert pareto_fronts(objectives) == expected
    assert pareto_fronts(dict(reversed(list(objectives.items())))) == expected


def test_hard_gate_evidence_identifies_the_exact_sample_and_metric() -> None:
    horizontal = np.linspace(0.1, 0.9, 64, dtype=np.float32)
    source = np.broadcast_to(horizontal, (32, 64)).copy()
    source_rgb = np.repeat(source[..., None], 3, axis=2)
    display = source_rgb.copy()
    raw = source_rgb.copy()
    raw[:, :16, 0] = 1.3
    metrics = _frame_quality_metrics(
        source_rgb,
        display,
        raw,
        mask_completeness=0,
    )
    sample = CandidateSamplePoint(
        frame_index=42,
        time_seconds=1.68,
        reasons=("shot_001:midpoint",),
    )

    failures = _hard_failures(metrics, sample, 3)

    assert {failure.check_id for failure in failures} >= {
        "output_gamut",
        "mask_completeness",
    }
    assert all(failure.frame_index == 42 for failure in failures)
    assert all(failure.sample_index == 3 for failure in failures)


def test_candidate_generation_uses_multiframe_pareto_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = build_initial_graph(
        project_id="candidate-integration",
        project_name="Candidate Integration",
        media=MediaInfo(
            path="source.mp4",
            duration_seconds=2,
            width=32,
            height=18,
            fps=10,
            frame_count=20,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=1),
            TimeRange(start_seconds=1, end_seconds=2),
        ],
        representative_frames=[Path("one.jpg"), Path("two.jpg")],
    )

    def fake_extract(
        _source: Path,
        time_seconds: float,
        output_path: Path,
        *,
        maximum_width: int = 1280,
        high_quality: bool = False,
    ) -> Path:
        del maximum_width, high_quality
        x = np.linspace(32, 220, 32, dtype=np.uint8)
        image = np.broadcast_to(x, (18, 32)).copy()
        rgb = np.stack(
            (
                image,
                np.roll(image, round(time_seconds * 3), axis=1),
                np.flip(image, axis=1),
            ),
            axis=2,
        )
        Image.fromarray(rgb, mode="RGB").save(output_path)
        return output_path

    class FakeAnalyzer:
        observed_paths: list[Path]

        def score_images_against_text(
            self,
            paths: list[Path],
            text: str,
        ) -> list[float]:
            assert "landscape" in text
            self.observed_paths = paths
            return [
                0.9 if "candidate-warm-" in path.name else 0.65
                for path in paths
            ]

    monkeypatch.setattr(
        "colorgraph.services.candidates.extract_frame",
        fake_extract,
    )
    analyzer = FakeAnalyzer()

    comparison = generate_look_candidates(
        source=tmp_path / "source.mp4",
        graph=graph,
        previews_dir=tmp_path / "previews",
        time_seconds=0.4,
        prompt="warm landscape",
        backend=TorchComputeBackend("cpu"),
        analyzer=analyzer,  # type: ignore[arg-type]
        limit=4,
    )

    assert comparison.ranking_version == CANDIDATE_RANKING_VERSION
    assert len(comparison.sample_frame_indices) > 1
    assert any(frame >= 10 for frame in comparison.sample_frame_indices)
    assert len(analyzer.observed_paths) == (
        len(comparison.sample_frame_indices) * 4
    )
    assert len(comparison.selection_evidence) == 4
    assert all(
        len(candidate.sample_evidence)
        == len(comparison.sample_frame_indices)
        for candidate in comparison.candidates
    )
    assert all(
        candidate.combined_score == candidate.technical_score
        for candidate in comparison.candidates
    )


def test_recipe_catalog_is_versioned_and_contains_exact_parameters() -> None:
    catalog = look_recipe_catalog()

    assert catalog["schema_version"] == LOOK_RECIPE_SCHEMA
    assert catalog["recipe_version"] == LOOK_RECIPE_VERSION
    assert {recipe["id"] for recipe in catalog["recipes"]} == {
        "natural",
        "cool",
        "warm",
        "foggy",
    }
    assert all(
        tuple(recipe["parameters"]) == LOOK_PARAMETER_KEYS
        for recipe in catalog["recipes"]
    )
    natural = next(recipe for recipe in catalog["recipes"] if recipe["id"] == "natural")
    assert natural["parameters"] == look_parameters("natural")


def test_legacy_look_is_normalized_without_changing_content_digest() -> None:
    graph = _two_scene_graph()
    payload = graph.model_dump(mode="python")
    look = next(node for node in payload["nodes"] if node["type"] == NodeType.LOOK)
    look["metadata"].pop("look_instance")
    look["parameters"]["saturation"] = 0.123456
    legacy = type(graph).model_validate(payload)
    before_digest = graph_digest(legacy)

    normalized = sync_look_instances(legacy)
    normalized_look = next(node for node in normalized.nodes if node.id == look["id"])

    assert graph_digest(normalized) == before_digest
    assert normalized_look.metadata["look_instance"] == {
        "schema_version": "colorgraph.look-instance/v1",
        "recipe_version": LOOK_RECIPE_VERSION,
        "base_recipe_id": "natural",
        "user_overrides": {"saturation": 0.123456},
        "dirty": True,
    }


def test_graph_digest_is_stable_across_browser_integral_number_round_trip() -> None:
    graph = _two_scene_graph()
    integer_payload = graph.model_dump(mode="python")
    integer_payload["nodes"][1]["parameters"]["contrast"] = 0
    integer_graph = type(graph).model_validate(integer_payload)
    float_payload = graph.model_dump(mode="python")
    float_payload["nodes"][1]["parameters"]["contrast"] = 0.0
    float_graph = type(graph).model_validate(float_payload)

    assert graph_digest(integer_graph) == graph_digest(float_graph)


@pytest.mark.asyncio
async def test_look_apply_conflict_repeat_restore_and_stale_digest(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Look Transactions")
    graph = _two_scene_graph(project.id)
    store.save_graph(project, graph)
    monkeypatch.setattr(operations, "project_store", lambda: store)

    active_look = next(
        node
        for node in graph.nodes
        if node.type == NodeType.LOOK and node.temporal_scope.scene_id == "scene_002"
    )
    first_look_before = next(
        node
        for node in graph.nodes
        if node.type == NodeType.LOOK and node.temporal_scope.scene_id == "scene_001"
    ).model_dump(mode="json")
    balance_nodes_before = [
        node.model_dump(mode="json")
        for node in graph.nodes
        if node.type == NodeType.BALANCE
    ]

    dirty = graph.model_copy(deep=True)
    dirty_active = next(node for node in dirty.nodes if node.id == active_look.id)
    dirty_active.parameters["saturation"] = 0.314159
    dirty = await operations.replace_grade_graph(project.id, dirty)
    instance = dirty_active = next(node for node in dirty.nodes if node.id == active_look.id)
    assert instance.metadata["look_instance"]["dirty"] is True
    assert instance.metadata["look_instance"]["user_overrides"] == {
        "saturation": 0.314159
    }

    request = operations.LookApplyRequest(
        recipe_id="warm",
        recipe_version=LOOK_RECIPE_VERSION,
        graph_digest=graph_digest(dirty),
        time_seconds=6,
    )
    with pytest.raises(HTTPException) as conflict:
        await operations.apply_candidate_look(project.id, request)
    assert conflict.value.status_code == 409
    assert conflict.value.detail["code"] == "dirty_look_requires_confirmation"

    applied = await operations.apply_candidate_look(
        project.id,
        request.model_copy(update={"discard_overrides": True}),
    )
    assert applied.action == "applied"
    applied_active = next(node for node in applied.graph.nodes if node.id == active_look.id)
    assert {
        key: applied_active.parameters[key]
        for key in LOOK_PARAMETER_KEYS
    } == look_parameters("warm")
    assert applied_active.metadata["look_instance"]["dirty"] is False
    assert next(
        node
        for node in applied.graph.nodes
        if node.type == NodeType.LOOK and node.temporal_scope.scene_id == "scene_001"
    ).model_dump(mode="json") == first_look_before
    assert [
        node.model_dump(mode="json")
        for node in applied.graph.nodes
        if node.type == NodeType.BALANCE
    ] == balance_nodes_before

    edited = applied.graph.model_copy(deep=True)
    edited_active = next(node for node in edited.nodes if node.id == active_look.id)
    edited_active.parameters["highlights"] = -0.111111
    edited = await operations.replace_grade_graph(project.id, edited)
    repeated = await operations.apply_candidate_look(
        project.id,
        operations.LookApplyRequest(
            recipe_id="warm",
            recipe_version=LOOK_RECIPE_VERSION,
            graph_digest=graph_digest(edited),
            time_seconds=6,
        ),
    )
    repeated_active = next(node for node in repeated.graph.nodes if node.id == active_look.id)
    assert repeated.action == "unchanged"
    assert repeated_active.parameters["highlights"] == -0.111111
    assert repeated_active.metadata["look_instance"]["dirty"] is True

    restored = await operations.restore_original_look(
        project.id,
        operations.LookRestoreRequest(time_seconds=6),
    )
    restored_active = next(node for node in restored.graph.nodes if node.id == active_look.id)
    assert restored.action == "restored"
    assert {
        key: restored_active.parameters[key]
        for key in LOOK_PARAMETER_KEYS
    } == look_parameters("warm")
    assert restored_active.metadata["look_instance"]["dirty"] is False
    assert store.load_graph(project.id) == restored.graph

    stale_digest = restored.graph_digest
    changed = restored.graph.model_copy(deep=True)
    balance = next(node for node in changed.nodes if node.type == NodeType.BALANCE)
    balance.parameters["exposure"] = 0.7654321
    await operations.replace_grade_graph(project.id, changed)
    with pytest.raises(HTTPException) as stale:
        await operations.apply_candidate_look(
            project.id,
            operations.LookApplyRequest(
                recipe_id="cool",
                recipe_version=LOOK_RECIPE_VERSION,
                graph_digest=stale_digest,
                time_seconds=6,
            ),
        )
    assert stale.value.status_code == 409
    assert stale.value.detail["code"] == "stale_candidate"
