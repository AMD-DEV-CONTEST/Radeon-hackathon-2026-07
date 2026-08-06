from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from colorgraph.domain.grade_graph import (
    CURRENT_GRADE_GRAPH_SCHEMA_VERSION,
    CURRENT_RENDERER_VERSION,
    LEGACY_RENDERER_VERSION,
    LINEAR_REC709_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    NodeType,
    StrictModel,
)
from colorgraph.grading.ocio_pipeline import (
    OCIO_CONFIG_NAME,
    ocio_pipeline_metadata,
    resolve_display_target,
)


class ColorPipelineMigrationPreview(StrictModel):
    schema_version: str = "colorgraph.color-pipeline-migration-preview/v1"
    status: Literal["ready", "blocked", "already_current"]
    source_renderer_version: str
    target_renderer_version: str = CURRENT_RENDERER_VERSION
    source_output_space: ColorSpace
    target_output_space: ColorSpace
    warnings: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    migrated_graph: GradeGraph | None = None


def _target_output_space(source: ColorSpace) -> ColorSpace:
    if source == ColorSpace.SRGB:
        return ColorSpace.SRGB
    if source in {
        ColorSpace.BT709_OETF,
        ColorSpace.REC1886,
        ColorSpace.LINEAR_REC709,
    }:
        return ColorSpace.REC1886
    raise ValueError(
        "automatic ACES migration only supports sRGB or Rec.709-family output projects"
    )


def preview_aces2_migration(graph: GradeGraph) -> ColorPipelineMigrationPreview:
    if graph.renderer_version == CURRENT_RENDERER_VERSION:
        return ColorPipelineMigrationPreview(
            status="already_current",
            source_renderer_version=graph.renderer_version,
            source_output_space=graph.output_color_space,
            target_output_space=graph.output_color_space,
            migrated_graph=graph.model_copy(deep=True),
        )

    blocked_reasons: list[str] = []
    warnings: list[str] = []
    try:
        target_output = _target_output_space(graph.output_color_space)
    except ValueError as exc:
        target_output = ColorSpace.REC1886
        blocked_reasons.append(str(exc))

    if graph.renderer_version == LEGACY_RENDERER_VERSION:
        blocked_reasons.append(
            "renderer v1 uses ambiguous Rec.709/sRGB semantics; migrate it to v2 explicitly first"
        )
    elif graph.renderer_version != LINEAR_REC709_RENDERER_VERSION:
        blocked_reasons.append(f"unsupported source renderer {graph.renderer_version!r}")

    for node in graph.nodes:
        lut_path = node.parameters.get("lut_path")
        if (
            node.enabled
            and isinstance(lut_path, str)
            and lut_path
            and node.metadata.get("lut_input_space") != "acescct"
        ):
            blocked_reasons.append(
                f"node {node.id!r} has a LUT without an explicit ACEScct input declaration"
            )

    warnings.append(
        "ACEScg/ACEScct changes the response of existing creative parameters; "
        "compare the migration preview before replacing the saved graph"
    )
    if graph.output_color_space == ColorSpace.BT709_OETF:
        warnings.append(
            "scene-referred BT.709 OETF output becomes the ACES 2 SDR Rec.1886 display target"
        )
    if graph.media.source_log_profile == "dji_mavic3_dlog_rec709_v1":
        warnings.append(
            "the DJI display-look LUT becomes the official D-Log/D-Gamut camera input transform"
        )

    if blocked_reasons:
        return ColorPipelineMigrationPreview(
            status="blocked",
            source_renderer_version=graph.renderer_version,
            source_output_space=graph.output_color_space,
            target_output_space=target_output,
            warnings=warnings,
            blocked_reasons=blocked_reasons,
        )

    payload = graph.model_dump(mode="python")
    payload["schema_version"] = CURRENT_GRADE_GRAPH_SCHEMA_VERSION
    payload["renderer_version"] = CURRENT_RENDERER_VERSION
    payload["working_color_space"] = ColorSpace.ACESCG
    payload["output_color_space"] = target_output

    input_nodes = [node for node in payload["nodes"] if node["type"] == NodeType.INPUT_TRANSFORM]
    output_nodes = [node for node in payload["nodes"] if node["type"] == NodeType.OUTPUT_TRANSFORM]
    if len(input_nodes) != 1 or len(output_nodes) != 1:
        return ColorPipelineMigrationPreview(
            status="blocked",
            source_renderer_version=graph.renderer_version,
            source_output_space=graph.output_color_space,
            target_output_space=target_output,
            warnings=warnings,
            blocked_reasons=[
                "migration requires exactly one input transform and one output transform"
            ],
        )

    input_node = input_nodes[0]
    input_node["parameters"]["working_space"] = ColorSpace.ACESCG.value
    input_node["parameters"]["interchange_space"] = ColorSpace.ACES2065_1.value
    input_node["parameters"]["ocio_config"] = OCIO_CONFIG_NAME
    input_node["metadata"]["transform_version"] = "colorgraph.input-transform/v3"

    target = resolve_display_target(target_output)
    output_node = output_nodes[0]
    output_node["parameters"] = {
        "working_space": ColorSpace.ACESCG.value,
        "output_space": target_output.value,
        "interchange_space": ColorSpace.ACES2065_1.value,
        "ocio_config": OCIO_CONFIG_NAME,
        "display": target.display,
        "view": target.view,
    }
    output_node["metadata"]["transform_version"] = "colorgraph.output-transform/v3"

    for node in payload["nodes"]:
        lut_path = node["parameters"].get("lut_path")
        if isinstance(lut_path, str) and lut_path:
            node["parameters"].setdefault("lut_interpolation", "trilinear")

    metadata = dict(payload["metadata"])
    metadata["color_pipeline"] = ocio_pipeline_metadata(
        graph.media.input_color_space,
        source_log_profile=graph.media.source_log_profile,
        output_space=target_output,
    )
    history = list(metadata.get("color_pipeline_migrations", []))
    history.append(
        {
            "from_schema": graph.schema_version,
            "from_renderer": graph.renderer_version,
            "to_schema": CURRENT_GRADE_GRAPH_SCHEMA_VERSION,
            "to_renderer": CURRENT_RENDERER_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    metadata["color_pipeline_migrations"] = history
    payload["metadata"] = metadata
    payload["updated_at"] = datetime.now(UTC)
    migrated = GradeGraph.model_validate(payload)
    return ColorPipelineMigrationPreview(
        status="ready",
        source_renderer_version=graph.renderer_version,
        source_output_space=graph.output_color_space,
        target_output_space=target_output,
        warnings=warnings,
        migrated_graph=migrated,
    )


def migrate_graph_to_aces2(graph: GradeGraph) -> GradeGraph:
    preview = preview_aces2_migration(graph)
    if preview.status == "blocked" or preview.migrated_graph is None:
        reasons = "; ".join(preview.blocked_reasons) or "migration preview is unavailable"
        raise ValueError(f"ACES 2 migration is blocked: {reasons}")
    return preview.migrated_graph
