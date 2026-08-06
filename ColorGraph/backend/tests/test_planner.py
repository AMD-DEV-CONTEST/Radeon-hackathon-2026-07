from pathlib import Path

import pytest

from colorgraph.agent import CommandContext, GradeCommandPlanner
from colorgraph.domain.grade_graph import (
    ColorSpace,
    Keyframe,
    MediaInfo,
    NodeType,
    ParameterTrack,
    ScopeLevel,
    SpatialKind,
    TimeRange,
)
from colorgraph.services.graph_builder import build_initial_graph


def _graph(*, multiple_scenes: bool = False):
    shot_ranges = (
        [
            TimeRange(start_seconds=0, end_seconds=3),
            TimeRange(start_seconds=3, end_seconds=6),
            TimeRange(start_seconds=6, end_seconds=9),
            TimeRange(start_seconds=9, end_seconds=12),
        ]
        if multiple_scenes
        else [TimeRange(start_seconds=0, end_seconds=10)]
    )
    media = MediaInfo(
        path="source.mp4",
        duration_seconds=shot_ranges[-1].end_seconds,
        width=1280,
        height=720,
        fps=25,
        frame_count=int(shot_ranges[-1].end_seconds * 25),
        codec="h264",
        input_color_space=ColorSpace.BT709_OETF,
    )
    graph = build_initial_graph(
        project_id="project_test",
        project_name="Test",
        media=media,
        shot_ranges=shot_ranges,
        representative_frames=[
            Path(f"shot-{index + 1}.jpg")
            for index in range(len(shot_ranges))
        ],
        scene_groups=(
            [[0, 1], [2, 3]]
            if multiple_scenes
            else [[0]]
        ),
    )
    first_balance = next(
        node
        for node in graph.nodes
        if node.type == NodeType.BALANCE
    )
    first_balance.tracks = [
        ParameterTrack(
            parameter="exposure",
            keyframes=[
                Keyframe(time_seconds=0, value=-0.1),
                Keyframe(time_seconds=2, value=0.1),
            ],
        )
    ]
    return graph


def _balances(graph):
    return [
        node
        for node in graph.nodes
        if node.type == NodeType.BALANCE
    ]


def test_planner_creates_scoped_sky_node_and_locks_mountain() -> None:
    plan = GradeCommandPlanner().plan(
        _graph(),
        "后半段天空再压一点，保留云层，但不要改变山体。",
        CommandContext(current_time=2),
    )
    masked = [
        node
        for node in plan.graph.nodes
        if node.type == NodeType.MASKED_GRADE
    ]
    assert [node.spatial_scope.target for node in masked] == ["sky"]
    assert masked[0].temporal_scope.time_range == TimeRange(
        start_seconds=5,
        end_seconds=10,
    )
    assert masked[0].temporal_scope.level == ScopeLevel.SUB_SHOT
    assert plan.invalidated_ranges == [
        TimeRange(start_seconds=5, end_seconds=10)
    ]
    assert plan.required_mask_targets == ["mountain", "sky"]
    assert masked[0].metadata["protected_targets"] == ["mountain"]
    assert masked[0].spatial_scope.kind == SpatialKind.COMPOSITE
    assert masked[0].spatial_scope.mask_asset_id is None
    assert masked[0].spatial_scope.expression == "sky AND NOT mountain"


def test_planner_updates_every_scene_look_for_project_style() -> None:
    plan = GradeCommandPlanner().plan(
        _graph(multiple_scenes=True),
        "全片使用清冷风格的纪录片风格",
    )
    looks = [
        node
        for node in plan.graph.nodes
        if node.type == NodeType.LOOK
    ]
    assert len(looks) == 2
    assert all(look.label == "Cool Documentary" for look in looks)
    assert all(look.parameters["temperature"] == -0.18 for look in looks)
    assert all(
        look.metadata["look_instance"]["base_recipe_id"] == "cool"
        and look.metadata["look_instance"]["dirty"] is False
        and look.metadata["look_instance"]["user_overrides"] == {}
        for look in looks
    )
    assert {edit.node_id for edit in plan.edits} == {
        "look_scene_001",
        "look_scene_002",
    }


@pytest.mark.parametrize(
    ("prompt", "parameter", "delta"),
    [
        ("全片提亮", "exposure", 0.12),
        ("全片变暖", "temperature", 0.10),
    ],
)
def test_project_adjustment_expands_to_every_shot_and_is_reversible(
    prompt: str,
    parameter: str,
    delta: float,
) -> None:
    graph = _graph(multiple_scenes=True)
    original = graph.model_dump(mode="json")

    plan = GradeCommandPlanner().plan(graph, prompt)

    balances = _balances(plan.graph)
    assert len(balances) == 4
    assert all(balance.parameters[parameter] == delta for balance in balances)
    assert [edit.operation for edit in plan.edits] == ["update_balance"] * 4
    assert plan.invalidated_ranges == [
        TimeRange(start_seconds=0, end_seconds=12)
    ]
    assert graph.model_dump(mode="json") == original
    assert plan.undo_graph.model_dump(mode="json") == original
    if parameter == "exposure":
        track_values = [
            keyframe.value
            for keyframe in balances[0].tracks[0].keyframes
        ]
        assert track_values == pytest.approx([0.02, 0.22])


def test_current_shot_only_updates_selected_balance() -> None:
    graph = _graph(multiple_scenes=True)
    plan = GradeCommandPlanner().plan(
        graph,
        "当前镜头变暖",
        CommandContext(current_time=7, selected_shot_id="shot_003"),
    )

    changed = [
        balance
        for balance in _balances(plan.graph)
        if balance.parameters["temperature"] != 0
    ]
    assert [node.id for node in changed] == ["balance_shot_003"]
    assert changed[0].parameters["temperature"] == 0.10
    assert plan.invalidated_ranges == [
        TimeRange(start_seconds=6, end_seconds=9)
    ]


@pytest.mark.parametrize(
    ("prompt", "expected_range"),
    [
        (
            "当前镜头前半段提亮",
            TimeRange(start_seconds=3, end_seconds=4.5),
        ),
        (
            "当前镜头后半段提亮",
            TimeRange(start_seconds=4.5, end_seconds=6),
        ),
    ],
)
def test_half_shot_creates_exactly_scoped_overlay(
    prompt: str,
    expected_range: TimeRange,
) -> None:
    graph = _graph(multiple_scenes=True)
    original_balance_count = len(_balances(graph))

    plan = GradeCommandPlanner().plan(
        graph,
        prompt,
        CommandContext(current_time=4, selected_shot_id="shot_002"),
    )

    balances = _balances(plan.graph)
    assert len(balances) == original_balance_count + 1
    overlay = balances[-1]
    assert overlay.temporal_scope.level == ScopeLevel.SUB_SHOT
    assert overlay.temporal_scope.shot_id == "shot_002"
    assert overlay.temporal_scope.time_range == expected_range
    assert overlay.parameters["exposure"] == 0.12
    assert plan.invalidated_ranges == [expected_range]
    assert plan.edits[0].operation == "create_scoped_balance"


def test_named_scene_updates_all_and_only_that_scenes_shots() -> None:
    graph = _graph(multiple_scenes=True)
    plan = GradeCommandPlanner().plan(graph, "scene 2 压暗")

    changed = [
        balance
        for balance in _balances(plan.graph)
        if balance.parameters["exposure"] != 0
    ]
    assert [node.id for node in changed] == [
        "balance_shot_003",
        "balance_shot_004",
    ]
    assert all(node.parameters["exposure"] == -0.12 for node in changed)
    assert plan.invalidated_ranges == [
        TimeRange(start_seconds=6, end_seconds=12)
    ]


def test_global_adjustment_with_protection_uses_inverse_mask() -> None:
    graph = _graph(multiple_scenes=True)
    original_balances = [
        node.model_dump(mode="json")
        for node in _balances(graph)
    ]

    plan = GradeCommandPlanner().plan(
        graph,
        "全片提亮，但不要改变天空",
    )

    assert [
        node.model_dump(mode="json")
        for node in _balances(plan.graph)
    ] == original_balances
    masked = [
        node
        for node in plan.graph.nodes
        if node.type == NodeType.MASKED_GRADE
    ]
    assert len(masked) == 1
    assert masked[0].spatial_scope.kind == SpatialKind.COMPOSITE
    assert masked[0].spatial_scope.target == "global"
    assert masked[0].spatial_scope.expression == "NOT sky"
    assert masked[0].parameters["exposure"] == 0.12
    assert masked[0].temporal_scope.level == ScopeLevel.PROJECT
    assert plan.required_mask_targets == ["sky"]
    assert plan.invalidated_ranges == [
        TimeRange(start_seconds=0, end_seconds=12)
    ]
