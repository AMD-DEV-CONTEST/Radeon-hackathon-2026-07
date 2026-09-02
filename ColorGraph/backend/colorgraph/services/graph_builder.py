from __future__ import annotations

from pathlib import Path

from colorgraph.agent.scene_understanding import SceneTag, ShotSceneAnalysis
from colorgraph.domain.grade_graph import (
    CURRENT_GRADE_GRAPH_SCHEMA_VERSION,
    CURRENT_RENDERER_VERSION,
    LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION,
    LINEAR_REC709_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    GradeNode,
    Interpolation,
    MediaInfo,
    NodeType,
    ParameterTrack,
    Scene,
    ScopeLevel,
    Shot,
    SpatialKind,
    SpatialScope,
    TemporalScope,
    TimeRange,
)
from colorgraph.grading.looks import LOOK_RECIPES, look_parameters, sync_look_instances
from colorgraph.grading.ocio_pipeline import (
    OCIO_CONFIG_NAME,
    ocio_pipeline_metadata,
    resolve_display_target,
)
from colorgraph.media.color_analysis import COLOR_ANALYSIS_VERSION, ShotColorAnalysis


def _recipe_from_label(label: str) -> str:
    normalized = label.lower()
    if "cool" in normalized or "documentary" in normalized or "blue" in normalized:
        return "cool"
    if "warm" in normalized or "sunset" in normalized or "golden" in normalized:
        return "warm"
    if "fog" in normalized or "desaturated" in normalized or "mist" in normalized:
        return "foggy"
    return "natural"


def _select_recipe(
    shot_indices: list[int],
    scene_analyses: list[ShotSceneAnalysis],
    reference_style: SceneTag | None,
) -> str:
    if reference_style is not None:
        return _recipe_from_label(reference_style.label)
    scores = {recipe_id: 0.0 for recipe_id in LOOK_RECIPES}
    for index in shot_indices:
        if index >= len(scene_analyses):
            continue
        suggestion = scene_analyses[index].suggested_look
        scores[_recipe_from_label(suggestion.label)] += suggestion.confidence
    return max(scores, key=scores.get) if any(scores.values()) else "natural"


def _validated_scene_groups(
    shot_count: int,
    scene_groups: list[list[int]] | None,
) -> list[list[int]]:
    groups = scene_groups or [list(range(shot_count))]
    flattened = [index for group in groups for index in group]
    if flattened != list(range(shot_count)) or any(not group for group in groups):
        raise ValueError("scene groups must contain every shot index once in timeline order")
    return groups


def _scope(
    project_id: str,
    level: ScopeLevel,
    *,
    scene_id: str | None = None,
    shot_id: str | None = None,
    time_range: TimeRange | None = None,
) -> TemporalScope:
    return TemporalScope(
        level=level,
        project_id=project_id,
        scene_id=scene_id,
        shot_id=shot_id,
        time_range=time_range,
    )


def build_initial_graph(
    *,
    project_id: str,
    project_name: str,
    media: MediaInfo,
    shot_ranges: list[TimeRange],
    representative_frames: list[Path],
    representative_frame_metadata: list[dict[str, object]] | None = None,
    color_analyses: list[ShotColorAnalysis] | None = None,
    scene_analyses: list[ShotSceneAnalysis] | None = None,
    scene_groups: list[list[int]] | None = None,
    scene_grouping_metadata: dict[str, object] | None = None,
    reference_frame: Path | None = None,
    reference_style: SceneTag | None = None,
    reference_similarities: list[float] | None = None,
    renderer_version: str = CURRENT_RENDERER_VERSION,
) -> GradeGraph:
    if len(representative_frames) != len(shot_ranges):
        raise ValueError("representative frames length must match shot ranges")
    if (
        representative_frame_metadata is not None
        and len(representative_frame_metadata) != len(shot_ranges)
    ):
        raise ValueError("representative frame metadata length must match shot ranges")
    if renderer_version == CURRENT_RENDERER_VERSION:
        schema_version = CURRENT_GRADE_GRAPH_SCHEMA_VERSION
        working_space = ColorSpace.ACESCG
        output_space = ColorSpace.REC1886
        display_target = resolve_display_target(output_space)
        pipeline_metadata = ocio_pipeline_metadata(
            media.input_color_space,
            source_log_profile=media.source_log_profile,
            output_space=output_space,
        )
    elif renderer_version == LINEAR_REC709_RENDERER_VERSION:
        schema_version = LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION
        working_space = ColorSpace.LINEAR_REC709
        output_space = ColorSpace.BT709_OETF
        display_target = None
        pipeline_metadata = None
    else:
        raise ValueError(f"cannot build a new graph for renderer {renderer_version!r}")

    analyses = scene_analyses or []
    groups = _validated_scene_groups(len(shot_ranges), scene_groups)
    shot_scene_ids = {
        shot_index: f"scene_{scene_index + 1:03d}"
        for scene_index, group in enumerate(groups)
        for shot_index in group
    }
    shots = [
        Shot(
            id=f"shot_{index + 1:03d}",
            scene_id=shot_scene_ids[index],
            index=index,
            time_range=time_range,
            representative_frame=str(representative_frames[index]),
            lighting_change_points=(
                color_analyses[index].lighting_change_points if color_analyses else []
            ),
        )
        for index, time_range in enumerate(shot_ranges)
    ]
    nodes: list[GradeNode] = [
        GradeNode(
            id="input_transform",
            type=NodeType.INPUT_TRANSFORM,
            label="Input color transform",
            order=0,
            temporal_scope=_scope(project_id, ScopeLevel.PROJECT),
            parameters={
                "input_space": media.input_color_space.value,
                "working_space": working_space.value,
                **(
                    {"source_log_profile": media.source_log_profile}
                    if media.source_log_profile is not None
                    else {}
                ),
                **(
                    {
                        "interchange_space": ColorSpace.ACES2065_1.value,
                        "ocio_config": OCIO_CONFIG_NAME,
                    }
                    if renderer_version == CURRENT_RENDERER_VERSION
                    else {}
                ),
            },
            metadata={
                "transform_version": (
                    "colorgraph.input-transform/v3"
                    if renderer_version == CURRENT_RENDERER_VERSION
                    else "colorgraph.input-transform/v2"
                )
            },
        )
    ]

    for index, shot in enumerate(shots):
        analysis = color_analyses[index] if color_analyses else None
        tracks: list[ParameterTrack] = []
        if analysis and len(analysis.exposure_keyframes) > 1:
            tracks.append(
                ParameterTrack(
                    parameter="exposure",
                    keyframes=analysis.exposure_keyframes,
                    interpolation=Interpolation.PCHIP,
                    max_velocity=0.75,
                    max_acceleration=1.5,
                )
            )
        if analysis and len(analysis.temperature_keyframes) > 1:
            tracks.append(
                ParameterTrack(
                    parameter="temperature",
                    keyframes=analysis.temperature_keyframes,
                    interpolation=Interpolation.PCHIP,
                    max_velocity=0.35,
                    max_acceleration=0.7,
                )
            )
        nodes.append(
            GradeNode(
                id=f"balance_{shot.id}",
                type=NodeType.BALANCE,
                label=f"Base balance · {shot.id}",
                order=10 + index,
                temporal_scope=_scope(
                    project_id,
                    ScopeLevel.SHOT,
                    scene_id=shot.scene_id,
                    shot_id=shot.id,
                    time_range=shot.time_range,
                ),
                parameters={
                    "exposure": analysis.exposure if analysis else 0.0,
                    "temperature": analysis.temperature if analysis else 0.0,
                    "tint": analysis.tint if analysis else 0.0,
                    "contrast": 0.0,
                    "saturation": 0.0,
                    "highlights": analysis.highlights if analysis else 0.0,
                },
                tracks=tracks,
                metadata={
                    "source": "content_aware_color_analysis",
                    "sampled_frames": analysis.sampled_frames if analysis else 0,
                    "color_analysis": (
                        {
                            "version": analysis.analysis_version,
                            "exposure": {
                                "estimate_ev": analysis.exposure,
                                "valid_sample_ratio": (
                                    analysis.exposure_valid_sample_ratio
                                ),
                                "uncertainty_ev": analysis.exposure_uncertainty,
                            },
                            "white_balance": {
                                "temperature_estimate": analysis.temperature,
                                "tint_estimate": analysis.tint,
                                "valid_sample_ratio": (
                                    analysis.white_balance_valid_sample_ratio
                                ),
                                "uncertainty": analysis.white_balance_uncertainty,
                            },
                            "trajectory": {
                                "method": "uncertainty_weighted_robust_trend_filter",
                                "lighting_change_points": (
                                    analysis.lighting_change_points
                                ),
                            },
                        }
                        if analysis
                        else {
                            "version": COLOR_ANALYSIS_VERSION,
                            "status": "not_sampled",
                        }
                    ),
                },
            )
        )

    scenes: list[Scene] = []
    for scene_index, group in enumerate(groups):
        scene_id = f"scene_{scene_index + 1:03d}"
        recipe_id = _select_recipe(group, analyses, reference_style)
        recipe = LOOK_RECIPES[recipe_id]
        parameters = look_parameters(recipe_id)
        parameters["lut_interpolation"] = (
            "tetrahedral"
            if renderer_version == CURRENT_RENDERER_VERSION
            else "trilinear"
        )
        if reference_style and "warm" in reference_style.label.lower():
            parameters["temperature"] = 0.14
            parameters["saturation"] = 0.10
        look_node_id = f"look_{scene_id}"
        first_shot = shots[group[0]]
        last_shot = shots[group[-1]]
        nodes.append(
            GradeNode(
                id=look_node_id,
                type=NodeType.LOOK,
                label=str(recipe["label"]),
                order=100 + scene_index,
                temporal_scope=_scope(
                    project_id,
                    ScopeLevel.SCENE,
                    scene_id=scene_id,
                    time_range=TimeRange(
                        start_seconds=first_shot.time_range.start_seconds,
                        end_seconds=last_shot.time_range.end_seconds,
                    ),
                ),
                parameters=parameters,
                metadata={
                    "recipe_id": recipe_id,
                    "source": (
                        "reference_image_clip"
                        if reference_style is not None
                        else ("shot_clip_consensus" if analyses else "deterministic_default")
                    ),
                    "reference_style": (
                        reference_style.model_dump(mode="json")
                        if reference_style is not None
                        else None
                    ),
                    **(
                        {"lut_input_space": "acescct"}
                        if renderer_version == CURRENT_RENDERER_VERSION
                        else {}
                    ),
                },
            )
        )
        scenes.append(
            Scene(
                id=scene_id,
                index=scene_index,
                label=f"Scene {scene_index + 1:02d}",
                shot_ids=[shots[index].id for index in group],
                look_node_id=look_node_id,
            )
        )

    nodes.append(
        GradeNode(
            id="output_transform",
            type=NodeType.OUTPUT_TRANSFORM,
            label="Output color transform",
            order=200,
            temporal_scope=_scope(project_id, ScopeLevel.PROJECT),
            spatial_scope=SpatialScope(kind=SpatialKind.GLOBAL),
            parameters={
                "working_space": working_space.value,
                "output_space": output_space.value,
                **(
                    {
                        "interchange_space": ColorSpace.ACES2065_1.value,
                        "ocio_config": OCIO_CONFIG_NAME,
                        "display": display_target.display,
                        "view": display_target.view,
                    }
                    if display_target is not None
                    else {}
                ),
            },
            metadata={
                "transform_version": (
                    "colorgraph.output-transform/v3"
                    if renderer_version == CURRENT_RENDERER_VERSION
                    else "colorgraph.output-transform/v2"
                )
            },
        )
    )

    graph = GradeGraph(
        schema_version=schema_version,
        renderer_version=renderer_version,
        id=f"graph_{project_id}",
        project_id=project_id,
        project_name=project_name,
        working_color_space=working_space,
        output_color_space=output_space,
        media=media,
        scenes=scenes,
        shots=shots,
        nodes=nodes,
        metadata={
            "analysis_version": "media-v3",
            "color_analysis_version": COLOR_ANALYSIS_VERSION,
            "representative_frames": representative_frame_metadata or [],
            "scene_analyses": ([analysis.model_dump(mode="json") for analysis in analyses]),
            "scene_grouping": scene_grouping_metadata or {"shot_groups": groups},
            **(
                {"color_pipeline": pipeline_metadata}
                if pipeline_metadata is not None
                else {}
            ),
            "reference_image": (
                {
                    "path": str(reference_frame),
                    "suggested_look": (
                        reference_style.model_dump(mode="json")
                        if reference_style is not None
                        else None
                    ),
                    "shot_similarities": reference_similarities or [],
                }
                if reference_frame is not None
                else None
            ),
        },
    )
    return sync_look_instances(graph)
