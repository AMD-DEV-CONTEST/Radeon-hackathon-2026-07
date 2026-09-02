import json
from pathlib import Path

import pytest
import torch
from fastapi import HTTPException

from colorgraph.api.routes import projects
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    CURRENT_GRADE_GRAPH_SCHEMA_VERSION,
    CURRENT_RENDERER_VERSION,
    LINEAR_REC709_RENDERER_VERSION,
    ColorSpace,
    MediaInfo,
    NodeType,
    TimeRange,
)
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.ocio_pipeline import OCIO_CONFIG_NAME
from colorgraph.services.color_pipeline_migration import (
    migrate_graph_to_aces2,
    preview_aces2_migration,
)
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.storage import ProjectStore


def _v2_graph():
    return build_initial_graph(
        project_id="migration",
        project_name="Migration",
        media=MediaInfo(
            path="source.mov",
            duration_seconds=1,
            width=4,
            height=2,
            fps=24,
            frame_count=24,
            codec="prores",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1)],
        representative_frames=[Path("frame.jpg")],
        renderer_version=LINEAR_REC709_RENDERER_VERSION,
    )


def test_v2_migration_preview_is_versioned_and_does_not_mutate_source() -> None:
    source = _v2_graph()
    preview = preview_aces2_migration(source)

    assert preview.status == "ready"
    assert source.renderer_version == LINEAR_REC709_RENDERER_VERSION
    assert source.working_color_space == ColorSpace.LINEAR_REC709
    assert preview.migrated_graph is not None

    migrated = preview.migrated_graph
    assert migrated.schema_version == CURRENT_GRADE_GRAPH_SCHEMA_VERSION
    assert migrated.renderer_version == CURRENT_RENDERER_VERSION
    assert migrated.working_color_space == ColorSpace.ACESCG
    assert migrated.output_color_space == ColorSpace.REC1886
    assert migrated.metadata["color_pipeline"]["config"] == OCIO_CONFIG_NAME
    assert migrated.metadata["color_pipeline_migrations"][-1]["from_renderer"] == (
        LINEAR_REC709_RENDERER_VERSION
    )

    input_node = next(node for node in migrated.nodes if node.type == NodeType.INPUT_TRANSFORM)
    output_node = next(node for node in migrated.nodes if node.type == NodeType.OUTPUT_TRANSFORM)
    assert input_node.parameters["interchange_space"] == ColorSpace.ACES2065_1.value
    assert output_node.parameters["display"] == "Rec.1886 Rec.709 - Display"


def test_migration_preview_preserves_v2_replay_and_exposes_v3_appearance_change() -> None:
    source = _v2_graph()
    for node in source.nodes:
        node.enabled = node.type in {
            NodeType.INPUT_TRANSFORM,
            NodeType.BALANCE,
            NodeType.OUTPUT_TRANSFORM,
        }
    balance = next(node for node in source.nodes if node.type == NodeType.BALANCE)
    balance.parameters.update(
        {
            "exposure": 0.35,
            "temperature": 0.3,
            "tint": -0.15,
            "contrast": 0.4,
            "saturation": 0.25,
            "highlights": -0.3,
            "shadows": 0.2,
            "midtones": -0.1,
            "curve_highlights": -0.2,
        }
    )
    image = torch.tensor(
        [[[[0.08, 0.4, 0.85]], [[0.15, 0.5, 0.7]], [[0.3, 0.6, 0.45]]]],
        dtype=torch.float32,
    )
    engine = GradeRenderEngine(TorchComputeBackend("cpu"))

    original, _ = engine.render_output_batch(
        image,
        source,
        timestamps=[0.5],
        mixed_precision=False,
    )
    preview = preview_aces2_migration(source)
    assert preview.migrated_graph is not None
    replayed, _ = engine.render_output_batch(
        image,
        source,
        timestamps=[0.5],
        mixed_precision=False,
    )
    migrated, _ = engine.render_output_batch(
        image,
        preview.migrated_graph,
        timestamps=[0.5],
        mixed_precision=False,
    )

    assert torch.equal(replayed, original)
    assert not torch.allclose(migrated, original, rtol=0, atol=1e-3)
    assert any("changes the response" in warning for warning in preview.warnings)


def test_migration_blocks_unqualified_legacy_luts() -> None:
    source = _v2_graph()
    look = next(node for node in source.nodes if node.type == NodeType.LOOK)
    look.parameters["lut_path"] = "legacy.cube"

    preview = preview_aces2_migration(source)
    assert preview.status == "blocked"
    assert preview.migrated_graph is None
    assert "without an explicit ACEScct input declaration" in preview.blocked_reasons[0]

    with pytest.raises(ValueError, match="migration is blocked"):
        migrate_graph_to_aces2(source)


def test_migration_pins_qualified_legacy_lut_to_trilinear_compatibility() -> None:
    source = _v2_graph()
    look = next(node for node in source.nodes if node.type == NodeType.LOOK)
    look.parameters["lut_path"] = "qualified.cube"
    look.metadata["lut_input_space"] = "acescct"

    preview = preview_aces2_migration(source)

    assert preview.migrated_graph is not None
    migrated_look = next(node for node in preview.migrated_graph.nodes if node.id == look.id)
    assert migrated_look.parameters["lut_interpolation"] == "trilinear"


def test_current_graph_migration_is_idempotent() -> None:
    current = build_initial_graph(
        project_id="current",
        project_name="Current",
        media=_v2_graph().media,
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1)],
        representative_frames=[Path("frame.jpg")],
    )
    preview = preview_aces2_migration(current)
    assert preview.status == "already_current"
    assert preview.migrated_graph == current


@pytest.mark.asyncio
async def test_migration_api_previews_before_saving_and_keeps_v2_revision(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Migration API")
    source = _v2_graph()
    store.save_graph(project, source)
    monkeypatch.setattr(projects, "project_store", lambda: store)

    preview = await projects.get_color_pipeline_migration_preview(project.id)
    assert preview.status == "ready"
    assert store.load_graph(project.id).renderer_version == LINEAR_REC709_RENDERER_VERSION

    with pytest.raises(HTTPException) as error:
        await projects.migrate_color_pipeline(
            project.id,
            projects.ColorPipelineMigrationRequest(confirm=False),
        )
    assert error.value.status_code == 422

    migrated = await projects.migrate_color_pipeline(
        project.id,
        projects.ColorPipelineMigrationRequest(confirm=True),
    )
    assert migrated.renderer_version == CURRENT_RENDERER_VERSION
    assert store.load_graph(project.id).renderer_version == CURRENT_RENDERER_VERSION

    revision_path = project.root / "grade_graph.pre-aces-v3.json"
    revision = json.loads(revision_path.read_text(encoding="utf-8"))
    assert revision["renderer_version"] == LINEAR_REC709_RENDERER_VERSION
