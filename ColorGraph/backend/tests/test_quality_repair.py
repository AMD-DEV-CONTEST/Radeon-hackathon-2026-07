from pathlib import Path

from colorgraph.domain.grade_graph import ColorSpace, MediaInfo, TimeRange
from colorgraph.quality.models import CheckStatus, QualityCheck, QualityReport
from colorgraph.quality.repair import propose_technical_repairs
from colorgraph.services.graph_builder import build_initial_graph


def test_repair_reduces_look_saturation() -> None:
    graph = build_initial_graph(
        project_id="repair-test",
        project_name="Repair",
        media=MediaInfo(
            path="source.mp4",
            duration_seconds=2,
            width=640,
            height=360,
            fps=25,
            frame_count=50,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=2)],
        representative_frames=[Path("shot.jpg")],
    )
    report = QualityReport(
        source_path="source.mp4",
        output_path="graded.mp4",
        sampled_frames=10,
        score=70,
        hard_checks_passed=False,
        summary="oversaturated",
        checks=[
            QualityCheck(
                id="oversaturation",
                label="oversaturation",
                status=CheckStatus.FAIL,
                value=0.1,
                threshold=0.08,
                unit="ratio",
                detail="test",
            )
        ],
    )
    original = next(node for node in graph.nodes if node.type.value == "look")
    repaired = propose_technical_repairs(graph, report)
    changed = next(node for node in repaired.graph.nodes if node.type.value == "look")
    assert changed.parameters["saturation"] < original.parameters["saturation"]
    assert repaired.actions
