from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import torch

from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import (
    GradeGraph,
    GradeNode,
    NodeType,
    ScopeLevel,
    SpatialKind,
)
from colorgraph.grading.engine import GradeRenderEngine

LUT_INTERPOLATION = "tetrahedral"
POST_LOOK_BAKE_POLICY = "baked_into_each_lut"


@dataclass(frozen=True, slots=True)
class LutExportArtifact:
    path: str
    filename: str
    kind: str
    scene_id: str | None
    look_node_id: str | None
    time_range: dict[str, float] | None
    input_space: str
    grading_space: str
    output_space: str
    size: int
    interpolation: str
    post_look_policy: str
    post_look_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExportPackage:
    archive_path: str
    graph_path: str
    manifest_path: str
    # Kept as the first LUT for API compatibility with v1 export responses.
    lut_path: str
    lut_paths: tuple[str, ...]
    lut_count: int
    quality_report_path: str | None
    mask_count: int


@dataclass(frozen=True, slots=True)
class _LutPlan:
    filename: str
    kind: str
    scene_id: str | None
    look_node_id: str | None
    time_range: dict[str, float] | None
    processor_graph: GradeGraph
    post_look_node_ids: tuple[str, ...]


def _safe_filename_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "unnamed"


def _time_range_payload(node: GradeNode | None) -> dict[str, float] | None:
    if node is None or node.temporal_scope.time_range is None:
        return None
    return node.temporal_scope.time_range.model_dump(mode="json")


def _scene_time_range(
    graph: GradeGraph,
    scene_id: str,
    look_node: GradeNode | None,
) -> dict[str, float] | None:
    explicit = _time_range_payload(look_node)
    if explicit is not None:
        return explicit
    ranges = [
        shot.time_range
        for shot in graph.shots
        if shot.scene_id == scene_id
    ]
    if not ranges:
        return None
    return {
        "start_seconds": min(item.start_seconds for item in ranges),
        "end_seconds": max(item.end_seconds for item in ranges),
    }


def _validate_lut_compatible_node(node: GradeNode) -> None:
    if node.spatial_scope.kind != SpatialKind.GLOBAL:
        raise ValueError(
            f"cannot bake spatial node {node.id!r} into a scene 3D LUT"
        )
    if node.spatial_scope.mask_asset_id is not None:
        raise ValueError(
            f"cannot bake masked node {node.id!r} into a scene 3D LUT"
        )
    if node.type == NodeType.POST_LOOK and (
        node.temporal_scope.level != ScopeLevel.PROJECT
        or node.temporal_scope.time_range is not None
    ):
        raise ValueError(
            f"post-look node {node.id!r} must have project-wide temporal scope "
            "to be baked into every scene LUT"
        )


def _lut_processor_graph(
    graph: GradeGraph,
    look_node: GradeNode | None,
    post_look_nodes: tuple[GradeNode, ...],
) -> GradeGraph:
    selected_nodes = [
        node
        for node in graph.ordered_nodes()
        if node.type in {NodeType.INPUT_TRANSFORM, NodeType.OUTPUT_TRANSFORM}
    ]
    if look_node is not None and look_node.enabled:
        selected_nodes.append(look_node)
    selected_nodes.extend(post_look_nodes)
    selected_nodes.sort(key=lambda node: node.order)

    for node in selected_nodes:
        _validate_lut_compatible_node(node)

    payload = graph.model_dump(mode="python")
    payload["nodes"] = []
    for index, source in enumerate(selected_nodes):
        node = source.model_copy(deep=True)
        node.order = index
        node.temporal_scope.level = ScopeLevel.PROJECT
        node.temporal_scope.scene_id = None
        node.temporal_scope.shot_id = None
        node.temporal_scope.sub_shot_id = None
        node.temporal_scope.time_range = None
        payload["nodes"].append(node.model_dump(mode="python"))
    payload["scenes"] = []
    payload["shots"] = []
    payload["masks"] = []
    return GradeGraph.model_validate(payload)


def _enabled_look_nodes(graph: GradeGraph) -> dict[str, GradeNode]:
    return {
        node.id: node
        for node in graph.nodes
        if node.enabled and node.type == NodeType.LOOK
    }


def _post_look_nodes(graph: GradeGraph) -> tuple[GradeNode, ...]:
    nodes = tuple(
        node
        for node in graph.ordered_nodes()
        if node.type == NodeType.POST_LOOK
    )
    for node in nodes:
        _validate_lut_compatible_node(node)
    return nodes


def _plan_scene_luts(graph: GradeGraph) -> tuple[_LutPlan, ...]:
    look_nodes = _enabled_look_nodes(graph)
    post_look_nodes = _post_look_nodes(graph)
    post_ids = tuple(node.id for node in post_look_nodes)
    referenced_look_ids: set[str] = set()
    plans: list[_LutPlan] = []

    for scene in sorted(graph.scenes, key=lambda item: item.index):
        look_node: GradeNode | None = None
        if scene.look_node_id is not None:
            matching_node = next(
                (node for node in graph.nodes if node.id == scene.look_node_id),
                None,
            )
            if matching_node is None:
                raise ValueError(
                    f"scene {scene.id!r} references missing Look node "
                    f"{scene.look_node_id!r}"
                )
            if matching_node.type != NodeType.LOOK:
                raise ValueError(
                    f"scene {scene.id!r} references non-Look node "
                    f"{scene.look_node_id!r}"
                )
            if matching_node.enabled:
                look_node = matching_node
                referenced_look_ids.add(matching_node.id)

        scene_slug = _safe_filename_component(scene.id)
        look_slug = (
            _safe_filename_component(look_node.id)
            if look_node is not None
            else "technical"
        )
        plans.append(
            _LutPlan(
                filename=f"{scene.index + 1:03d}-{scene_slug}-{look_slug}.cube",
                kind="scene_look" if look_node is not None else "scene_technical",
                scene_id=scene.id,
                look_node_id=look_node.id if look_node is not None else None,
                time_range=_scene_time_range(graph, scene.id, look_node),
                processor_graph=_lut_processor_graph(
                    graph,
                    look_node,
                    post_look_nodes,
                ),
                post_look_node_ids=post_ids,
            )
        )

    # Preserve valid legacy graphs that have Look nodes but no Scene records.
    orphan_looks = [
        node
        for node in look_nodes.values()
        if node.id not in referenced_look_ids
    ]
    for index, look_node in enumerate(sorted(orphan_looks, key=lambda node: node.order)):
        plans.append(
            _LutPlan(
                filename=(
                    f"look-{index + 1:03d}-"
                    f"{_safe_filename_component(look_node.id)}.cube"
                ),
                kind="unassigned_look",
                scene_id=look_node.temporal_scope.scene_id,
                look_node_id=look_node.id,
                time_range=_time_range_payload(look_node),
                processor_graph=_lut_processor_graph(
                    graph,
                    look_node,
                    post_look_nodes,
                ),
                post_look_node_ids=post_ids,
            )
        )

    if not plans:
        duration = graph.media.duration_seconds
        plans.append(
            _LutPlan(
                filename=(
                    "project-post-look.cube"
                    if post_look_nodes
                    else "technical-transform.cube"
                ),
                kind="project_post_look" if post_look_nodes else "technical_transform",
                scene_id=None,
                look_node_id=None,
                time_range=(
                    {"start_seconds": 0.0, "end_seconds": duration}
                    if duration > 0
                    else None
                ),
                processor_graph=_lut_processor_graph(
                    graph,
                    None,
                    post_look_nodes,
                ),
                post_look_node_ids=post_ids,
            )
        )

    return tuple(plans)


def _write_cube_lut(
    plan: _LutPlan,
    backend: ComputeBackend,
    destination: Path,
    *,
    size: int,
) -> Path:
    levels = torch.linspace(0, 1, size)
    blue, green, red = torch.meshgrid(levels, levels, levels, indexing="ij")
    colors = torch.stack((red, green, blue), dim=-1).reshape(-1, 3)
    # A one-pixel-high image lets the deterministic renderer produce exactly
    # the same selected scene Look as preview/video rendering.
    image = colors.t().unsqueeze(0).unsqueeze(2)
    output, _ = GradeRenderEngine(backend).render_output_batch(
        image,
        plan.processor_graph,
        timestamps=[0.0],
    )
    transformed = output[0, :, 0, :].t().float().cpu().numpy()

    target = destination.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    title = (
        f"ColorGraph {plan.scene_id} / {plan.look_node_id}"
        if plan.scene_id is not None
        else "ColorGraph Project Transform"
    )
    lines = [
        f'TITLE "{title}"',
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    lines.extend(
        f"{red_value:.8f} {green_value:.8f} {blue_value:.8f}"
        for red_value, green_value, blue_value in transformed
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def export_scene_luts(
    graph: GradeGraph,
    backend: ComputeBackend,
    destination_directory: str | Path,
    *,
    size: int = 33,
) -> tuple[LutExportArtifact, ...]:
    if size < 2 or size > 65:
        raise ValueError("LUT size must be between 2 and 65")
    destination = Path(destination_directory).resolve()
    artifacts: list[LutExportArtifact] = []
    for plan in _plan_scene_luts(graph):
        path = _write_cube_lut(
            plan,
            backend,
            destination / plan.filename,
            size=size,
        )
        artifacts.append(
            LutExportArtifact(
                path=str(path),
                filename=path.name,
                kind=plan.kind,
                scene_id=plan.scene_id,
                look_node_id=plan.look_node_id,
                time_range=plan.time_range,
                input_space=graph.media.input_color_space.value,
                grading_space=graph.working_color_space.value,
                output_space=graph.output_color_space.value,
                size=size,
                interpolation=LUT_INTERPOLATION,
                post_look_policy=(
                    POST_LOOK_BAKE_POLICY
                    if plan.post_look_node_ids
                    else "none"
                ),
                post_look_node_ids=plan.post_look_node_ids,
            )
        )
    return tuple(artifacts)


def export_scene_lut(
    graph: GradeGraph,
    backend: ComputeBackend,
    destination: str | Path,
    *,
    size: int = 33,
) -> Path:
    """Export a single-scene graph while retaining the v1 helper API."""
    if size < 2 or size > 65:
        raise ValueError("LUT size must be between 2 and 65")
    plans = _plan_scene_luts(graph)
    if len(plans) != 1:
        raise ValueError(
            "graph produces multiple scene LUTs; use export_scene_luts() "
            "so mutually exclusive Looks remain isolated"
        )
    return _write_cube_lut(
        plans[0],
        backend,
        Path(destination),
        size=size,
    )


def _artifact_manifest(artifact: LutExportArtifact) -> dict[str, object]:
    return {
        "filename": artifact.filename,
        "kind": artifact.kind,
        "scene_id": artifact.scene_id,
        "look_node_id": artifact.look_node_id,
        "time_range": artifact.time_range,
        "input_space": artifact.input_space,
        "grading_space": artifact.grading_space,
        "output_space": artifact.output_space,
        "size": artifact.size,
        "interpolation": artifact.interpolation,
        "post_look_policy": artifact.post_look_policy,
        "post_look_node_ids": list(artifact.post_look_node_ids),
    }


def export_grade_package(
    graph: GradeGraph,
    backend: ComputeBackend,
    destination_directory: str | Path,
    *,
    video_path: str | Path | None = None,
    quality_report_path: str | Path | None = None,
    lut_size: int = 33,
) -> ExportPackage:
    destination = Path(destination_directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    graph_path = destination / "grade_graph.json"
    graph_path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
    lut_artifacts = export_scene_luts(
        graph,
        backend,
        destination / "luts",
        size=lut_size,
    )

    manifest = {
        "schema": "colorgraph.export-package/v2",
        "created_at": datetime.now(UTC).isoformat(),
        "project_id": graph.project_id,
        "project_name": graph.project_name,
        "source": graph.media.path,
        "device": backend.info.model_dump(mode="json"),
        "lut_policy": {
            "scene_look_isolation": "one_lut_per_scene_and_look",
            "post_look": (
                POST_LOOK_BAKE_POLICY
                if any(artifact.post_look_node_ids for artifact in lut_artifacts)
                else "none"
            ),
        },
        "assets": {
            "video": Path(video_path).name if video_path else None,
            "grade_graph": graph_path.name,
            "scene_luts": [
                _artifact_manifest(artifact)
                for artifact in lut_artifacts
            ],
            "quality_report": (
                Path(quality_report_path).name
                if quality_report_path
                else None
            ),
            "masks": [
                {
                    "id": asset.id,
                    "target": asset.target,
                    "path": f"masks/{asset.target}",
                    "confidence": asset.confidence,
                    "frame_count": asset.frame_count,
                    "integrity": {
                        "schema": asset.metadata.get("schema"),
                        "target_aliases": asset.metadata.get("target_aliases"),
                        "width": asset.metadata.get("width"),
                        "height": asset.metadata.get("height"),
                        "fps": asset.metadata.get("fps"),
                        "storage": asset.metadata.get("storage"),
                        "sequence_sha256": asset.metadata.get("sequence_sha256"),
                        "video_sha256": asset.metadata.get("video_sha256"),
                        "decode_verified": asset.metadata.get("decode_verified"),
                        "missing_frame_policy": asset.metadata.get(
                            "missing_frame_policy"
                        ),
                        "tracking": asset.metadata.get("tracking"),
                    },
                }
                for asset in graph.masks
            ],
        },
        "portability": {
            "compute_api": "PyTorch device abstraction",
            "current_runtime": backend.info.runtime,
            "rocm_ready": True,
            "video_encoder_fallbacks": ["h264_amf", "libx264"],
        },
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    archive_path = destination / f"{graph.project_id}-grade-package.zip"
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        archive.write(graph_path, graph_path.name)
        for artifact in lut_artifacts:
            archive.write(artifact.path, f"luts/{artifact.filename}")
        archive.write(manifest_path, manifest_path.name)
        if video_path and Path(video_path).is_file():
            archive.write(Path(video_path), f"video/{Path(video_path).name}")
        if quality_report_path and Path(quality_report_path).is_file():
            archive.write(
                Path(quality_report_path),
                Path(quality_report_path).name,
            )
        for asset in graph.masks:
            mask_root = Path(asset.path)
            if not mask_root.is_dir():
                continue
            mask_video_path = Path(str(asset.metadata.get("video_path", "")))
            if mask_video_path.is_file():
                archive.write(
                    mask_video_path,
                    f"masks/{asset.target}.mkv",
                )
            else:
                for mask_path in mask_root.glob("*.png"):
                    archive.write(
                        mask_path,
                        f"masks/{asset.target}/{mask_path.name}",
                    )
    lut_paths = tuple(artifact.path for artifact in lut_artifacts)
    return ExportPackage(
        archive_path=str(archive_path),
        graph_path=str(graph_path),
        manifest_path=str(manifest_path),
        lut_path=lut_paths[0],
        lut_paths=lut_paths,
        lut_count=len(lut_paths),
        quality_report_path=(
            str(Path(quality_report_path).resolve())
            if quality_report_path
            else None
        ),
        mask_count=len(graph.masks),
    )
