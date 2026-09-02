import json
import zipfile
from pathlib import Path

from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    GradeNode,
    MediaInfo,
    NodeType,
    ScopeLevel,
    TemporalScope,
    TimeRange,
)
from colorgraph.exports.package import (
    POST_LOOK_BAKE_POLICY,
    _plan_scene_luts,
    export_grade_package,
    export_scene_luts,
)
from colorgraph.services.graph_builder import build_initial_graph


def _graph(*, scene_count: int = 1) -> GradeGraph:
    duration = float(scene_count * 2)
    graph = build_initial_graph(
        project_id="lut-export",
        project_name="LUT Export",
        media=MediaInfo(
            path="source.mov",
            duration_seconds=duration,
            width=1920,
            height=1080,
            fps=24,
            frame_count=int(duration * 24),
            codec="prores",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(
                start_seconds=float(index * 2),
                end_seconds=float((index + 1) * 2),
            )
            for index in range(scene_count)
        ],
        representative_frames=[
            Path(f"scene-{index + 1}.jpg")
            for index in range(scene_count)
        ],
        scene_groups=[[index] for index in range(scene_count)],
    )
    looks = [node for node in graph.nodes if node.type == NodeType.LOOK]
    for index, look in enumerate(looks):
        look.parameters["temperature"] = 0.2 if index % 2 == 0 else -0.2
        look.parameters["saturation"] = 0.1 * (index + 1)
    return graph


def _add_post_look(graph: GradeGraph) -> None:
    graph.nodes.append(
        GradeNode(
            id="project_post_look",
            type=NodeType.POST_LOOK,
            label="Project Post Look",
            order=150,
            temporal_scope=TemporalScope(
                level=ScopeLevel.PROJECT,
                project_id=graph.project_id,
            ),
            parameters={"contrast": 0.08, "saturation": 0.05},
        )
    )


def test_single_scene_exports_exactly_one_selected_look(tmp_path: Path) -> None:
    graph = _graph()
    artifacts = export_scene_luts(
        graph,
        TorchComputeBackend("cpu"),
        tmp_path,
        size=3,
    )

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.scene_id == "scene_001"
    assert artifact.look_node_id == "look_scene_001"
    assert artifact.time_range == {
        "start_seconds": 0.0,
        "end_seconds": 2.0,
    }
    assert artifact.input_space == ColorSpace.BT709_OETF.value
    assert artifact.grading_space == ColorSpace.ACESCG.value
    assert artifact.output_space == ColorSpace.REC1886.value
    assert artifact.size == 3
    assert artifact.interpolation == "tetrahedral"
    assert Path(artifact.path).read_text(encoding="utf-8").count("\n") == 31


def test_multi_scene_processors_never_chain_mutually_exclusive_looks() -> None:
    graph = _graph(scene_count=3)
    plans = _plan_scene_luts(graph)

    assert len(plans) == 3
    assert len({plan.filename for plan in plans}) == 3
    for plan in plans:
        processor_looks = [
            node.id
            for node in plan.processor_graph.nodes
            if node.type == NodeType.LOOK
        ]
        assert processor_looks == [plan.look_node_id]
        assert all(
            node.temporal_scope.level == ScopeLevel.PROJECT
            for node in plan.processor_graph.nodes
        )


def test_no_look_exports_scene_technical_luts(tmp_path: Path) -> None:
    graph = _graph(scene_count=2)
    graph.nodes = [
        node
        for node in graph.nodes
        if node.type != NodeType.LOOK
    ]
    for scene in graph.scenes:
        scene.look_node_id = None

    artifacts = export_scene_luts(
        graph,
        TorchComputeBackend("cpu"),
        tmp_path,
        size=2,
    )

    assert len(artifacts) == 2
    assert {artifact.kind for artifact in artifacts} == {"scene_technical"}
    assert all(artifact.look_node_id is None for artifact in artifacts)
    assert all(Path(artifact.path).is_file() for artifact in artifacts)


def test_post_look_is_baked_and_manifest_declares_policy(tmp_path: Path) -> None:
    graph = _graph(scene_count=2)
    _add_post_look(graph)

    plans = _plan_scene_luts(graph)
    assert len(plans) == 2
    for plan in plans:
        assert [
            node.id
            for node in plan.processor_graph.nodes
            if node.type == NodeType.POST_LOOK
        ] == ["project_post_look"]
        assert len(
            [
                node
                for node in plan.processor_graph.nodes
                if node.type == NodeType.LOOK
            ]
        ) == 1

    package = export_grade_package(
        graph,
        TorchComputeBackend("cpu"),
        tmp_path / "package",
        lut_size=2,
    )
    manifest = json.loads(Path(package.manifest_path).read_text(encoding="utf-8"))
    lut_records = manifest["assets"]["scene_luts"]

    assert manifest["schema"] == "colorgraph.export-package/v2"
    assert manifest["lut_policy"] == {
        "scene_look_isolation": "one_lut_per_scene_and_look",
        "post_look": POST_LOOK_BAKE_POLICY,
    }
    assert len(lut_records) == package.lut_count == 2
    assert all(record["post_look_policy"] == POST_LOOK_BAKE_POLICY for record in lut_records)
    assert all(record["post_look_node_ids"] == ["project_post_look"] for record in lut_records)
    assert all(
        {
            "input_space",
            "grading_space",
            "output_space",
            "time_range",
            "size",
            "interpolation",
        }
        <= record.keys()
        for record in lut_records
    )

    with zipfile.ZipFile(package.archive_path) as archive:
        archived_names = set(archive.namelist())
    assert {f"luts/{record['filename']}" for record in lut_records} <= archived_names
