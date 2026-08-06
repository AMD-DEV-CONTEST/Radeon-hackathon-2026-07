from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image

from colorgraph.devices.base import ComputeBackend
from colorgraph.devices.evidence import TorchStageEvidence, TorchStageEvidenceRecorder
from colorgraph.domain.grade_graph import (
    CURRENT_RENDERER_VERSION,
    LEGACY_RENDERER_VERSION,
    LINEAR_REC709_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    GradeNode,
    NodeType,
    SpatialKind,
)
from colorgraph.grading.color import (
    acescct_to_acescg,
    acescg_to_acescct,
    apply_acescct_contrast,
    apply_acescct_highlights,
    apply_acescct_saturation,
    apply_acescct_tone,
    apply_acescg_white_balance,
    apply_asc_cdl,
    apply_cdl,
    apply_contrast,
    apply_exposure,
    apply_highlights,
    apply_saturation,
    apply_tone_curve,
    apply_white_balance,
    convert_color_space,
    linear_to_srgb,
    log_to_linear_rec709,
    soft_clip_highlights,
    srgb_to_linear,
)
from colorgraph.grading.keyframes import evaluate_track, evaluate_track_batch
from colorgraph.grading.lut import apply_lut
from colorgraph.grading.masks import composite_mask_key
from colorgraph.grading.ocio_pipeline import (
    OCIO_CONFIG_NAME,
    acescg_to_output,
    input_to_acescg,
    resolve_display_target,
)
from colorgraph.grading.precision import PREVIEW_PRECISION_BUDGET, fp32_grading_context


@dataclass(frozen=True, slots=True)
class RenderMetrics:
    elapsed_seconds: float
    frames: int
    fps: float
    device_runtime: str
    device_name: str
    batch_strategy: str = "grouped_eager"
    node_groups: int = 0
    identity_elision: bool = True


def _parameter_values(node: GradeNode, time_seconds: float) -> dict[str, float | int | str | bool]:
    values = dict(node.parameters)
    for track in node.tracks:
        values[track.parameter] = evaluate_track(track, time_seconds)
    return values


def _node_is_active(node: GradeNode, time_seconds: float) -> bool:
    time_range = node.temporal_scope.time_range
    return node.enabled and (
        time_range is None or time_range.start_seconds <= time_seconds < time_range.end_seconds
    )


def _track_values(
    node: GradeNode,
    timestamps: list[float],
) -> dict[str, list[float]]:
    track_values: dict[str, list[float]] = {}
    for track in node.tracks:
        track_values[track.parameter] = evaluate_track_batch(
            track,
            timestamps,
        ).tolist()
    return track_values


def _frame_execution_plans(
    graph: GradeGraph,
    timestamps: list[float],
) -> list[
    list[
        tuple[
            GradeNode,
            dict[str, float | int | str | bool],
        ]
    ]
]:
    plans: list[
        list[
            tuple[
                GradeNode,
                dict[str, float | int | str | bool],
            ]
        ]
    ] = [[] for _ in timestamps]
    for node in graph.ordered_nodes():
        if node.type in {
            NodeType.INPUT_TRANSFORM,
            NodeType.OUTPUT_TRANSFORM,
        }:
            continue
        track_values = _track_values(node, timestamps)
        for frame_index, timestamp in enumerate(timestamps):
            if not _node_is_active(node, timestamp):
                continue
            values = dict(node.parameters)
            values.update(
                {
                    parameter: samples[frame_index]
                    for parameter, samples in track_values.items()
                }
            )
            plans[frame_index].append((node, values))
    return plans


class GradeRenderEngine:
    def __init__(
        self,
        backend: ComputeBackend,
        *,
        enable_batch_grouping: bool | None = None,
        enable_identity_elision: bool = True,
        enable_execution_planning: bool = True,
        maximum_grouped_pixels: int = 4_194_304,
    ) -> None:
        if maximum_grouped_pixels <= 0:
            raise ValueError("maximum_grouped_pixels must be positive")
        self.backend = backend
        self.enable_batch_grouping = enable_batch_grouping
        self.enable_identity_elision = enable_identity_elision
        self.enable_execution_planning = enable_execution_planning
        self.maximum_grouped_pixels = maximum_grouped_pixels
        self.last_output_evidence: TorchStageEvidence | None = None

    def _resolve_mask(
        self,
        node: GradeNode,
        image: torch.Tensor,
        masks: Mapping[str, torch.Tensor] | None,
    ) -> torch.Tensor | None:
        asset_id = (
            composite_mask_key(node.id)
            if node.spatial_scope.kind == SpatialKind.COMPOSITE and node.spatial_scope.expression
            else node.spatial_scope.mask_asset_id
        )
        if not asset_id:
            return None
        if not masks or asset_id not in masks:
            return image.new_zeros((image.shape[0], 1, image.shape[2], image.shape[3]))
        mask = masks[asset_id].to(device=image.device, dtype=image.dtype)
        if mask.ndim == 2:
            mask = mask.unsqueeze(0).unsqueeze(0)
        elif mask.ndim == 3:
            mask = mask.unsqueeze(1)
        if mask.shape[-2:] != image.shape[-2:]:
            mask = functional.interpolate(mask, image.shape[-2:], mode="bilinear")
        if mask.shape[0] == 1 and image.shape[0] > 1:
            mask = mask.expand(image.shape[0], -1, -1, -1)
        return mask.clamp(0, 1)

    def _apply_node(
        self,
        image: torch.Tensor,
        node: GradeNode,
        time_seconds: float,
        masks: Mapping[str, torch.Tensor] | None,
        *,
        working_color_space: ColorSpace = ColorSpace.LINEAR_REC709,
        parameter_values: Mapping[str, float | int | str | bool] | None = None,
    ) -> torch.Tensor:
        values = (
            dict(parameter_values)
            if parameter_values is not None
            else _parameter_values(node, time_seconds)
        )
        adjusted = image

        if node.type == NodeType.INPUT_TRANSFORM:
            input_space = values.get("input_space")
            working_space = values.get("working_space")
            if not isinstance(input_space, str) or not isinstance(working_space, str):
                raise ValueError("input transform requires string input_space and working_space")
            source_log_profile = values.get("source_log_profile")
            if source_log_profile is not None and not isinstance(source_log_profile, str):
                raise ValueError("source_log_profile must be a string when provided")
            if working_space == ColorSpace.ACESCG.value:
                return input_to_acescg(
                    image,
                    input_space,
                    source_log_profile=source_log_profile,
                )
            return convert_color_space(
                image,
                input_space,
                working_space,
                source_log_profile=source_log_profile,
            )
        if node.type == NodeType.OUTPUT_TRANSFORM:
            working_space = values.get("working_space")
            output_space = values.get("output_space")
            if not isinstance(working_space, str) or not isinstance(output_space, str):
                raise ValueError("output transform requires string working_space and output_space")
            destination_log_profile = values.get("destination_log_profile")
            if destination_log_profile is not None and not isinstance(
                destination_log_profile,
                str,
            ):
                raise ValueError("destination_log_profile must be a string when provided")
            if working_space == ColorSpace.ACESCG.value:
                display = values.get("display")
                view = values.get("view")
                if not isinstance(display, str) or not isinstance(view, str):
                    raise ValueError("ACES output transform requires string display and view")
                return acescg_to_output(
                    image,
                    output_space,
                    display=display,
                    view=view,
                )
            return convert_color_space(
                soft_clip_highlights(image),
                working_space,
                output_space,
                destination_log_profile=destination_log_profile,
            )
        aces_pipeline = working_color_space == ColorSpace.ACESCG
        if node.type in {NodeType.BALANCE, NodeType.TONE, NodeType.MASKED_GRADE}:
            exposure = float(values.get("exposure", 0.0))
            temperature = float(values.get("temperature", 0.0))
            tint = float(values.get("tint", 0.0))
            slope = tuple(
                float(values.get(f"slope_{channel}", 1.0))
                for channel in ("r", "g", "b")
            )
            offset = tuple(
                float(values.get(f"offset_{channel}", 0.0))
                for channel in ("r", "g", "b")
            )
            power = tuple(
                float(values.get(f"power_{channel}", 1.0))
                for channel in ("r", "g", "b")
            )
            contrast = float(values.get("contrast", 0.0))
            saturation = float(values.get("saturation", 0.0))
            highlights = float(values.get("highlights", 0.0))
            shadows = float(values.get("shadows", 0.0))
            midtones = float(values.get("midtones", 0.0))
            curve_highlights = float(values.get("curve_highlights", 0.0))
            cdl_is_identity = (
                slope == (1.0, 1.0, 1.0)
                and offset == (0.0, 0.0, 0.0)
                and power == (1.0, 1.0, 1.0)
            )
            shaping_is_identity = (
                contrast == 0.0
                and saturation == 0.0
                and highlights == 0.0
                and shadows == 0.0
                and midtones == 0.0
                and curve_highlights == 0.0
            )
            if aces_pipeline and self.enable_identity_elision:
                if exposure != 0.0:
                    adjusted = apply_exposure(adjusted, exposure)
                if temperature != 0.0 or tint != 0.0:
                    adjusted = apply_acescg_white_balance(
                        adjusted,
                        temperature,
                        tint,
                    )
                if not cdl_is_identity or not shaping_is_identity:
                    adjusted = acescg_to_acescct(adjusted)
                    if not cdl_is_identity:
                        adjusted = apply_asc_cdl(
                            adjusted,
                            slope=slope,
                            offset=offset,
                            power=power,
                        )
                    if contrast != 0.0:
                        adjusted = apply_acescct_contrast(adjusted, contrast)
                    if saturation != 0.0:
                        adjusted = apply_acescct_saturation(adjusted, saturation)
                    if highlights != 0.0:
                        adjusted = apply_acescct_highlights(adjusted, highlights)
                    if (
                        shadows != 0.0
                        or midtones != 0.0
                        or curve_highlights != 0.0
                    ):
                        adjusted = apply_acescct_tone(
                            adjusted,
                            shadows=shadows,
                            midtones=midtones,
                            highlights=curve_highlights,
                        )
                    adjusted = acescct_to_acescg(adjusted)
            elif aces_pipeline:
                # Exposure and chromatic adaptation are scene-linear ACEScg
                # operations. Creative shaping is explicitly enclosed by
                # ACEScct encode/decode boundaries.
                adjusted = apply_exposure(adjusted, exposure)
                adjusted = apply_acescg_white_balance(
                    adjusted,
                    temperature,
                    tint,
                )
                adjusted = acescg_to_acescct(adjusted)
                adjusted = apply_asc_cdl(
                    adjusted,
                    slope=slope,
                    offset=offset,
                    power=power,
                )
                adjusted = apply_acescct_contrast(adjusted, contrast)
                adjusted = apply_acescct_saturation(adjusted, saturation)
                adjusted = apply_acescct_highlights(adjusted, highlights)
                adjusted = apply_acescct_tone(
                    adjusted,
                    shadows=shadows,
                    midtones=midtones,
                    highlights=curve_highlights,
                )
                adjusted = acescct_to_acescg(adjusted)
            else:
                adjusted = apply_cdl(
                    adjusted,
                    slope=slope,
                    offset=offset,
                    power=power,
                )
                adjusted = apply_exposure(adjusted, exposure)
                adjusted = apply_white_balance(
                    adjusted,
                    temperature,
                    tint,
                )
                adjusted = apply_contrast(adjusted, contrast)
                adjusted = apply_saturation(adjusted, saturation)
                adjusted = apply_highlights(adjusted, highlights)
                adjusted = apply_tone_curve(
                    adjusted,
                    shadows=shadows,
                    midtones=midtones,
                    highlights=curve_highlights,
                )
        elif node.type == NodeType.LOOK:
            strength = float(values.get("strength", 1.0))
            temperature = float(values.get("temperature", 0.0))
            tint = float(values.get("tint", 0.0))
            contrast = float(values.get("contrast", 0.0))
            saturation = float(values.get("saturation", 0.0))
            highlights = float(values.get("highlights", 0.0))
            lut_path = values.get("lut_path")
            has_lut = isinstance(lut_path, str) and bool(lut_path)
            encoded_aces = aces_pipeline
            if aces_pipeline:
                looked = adjusted
                if (
                    not self.enable_identity_elision
                    or temperature != 0.0
                    or tint != 0.0
                ):
                    looked = apply_acescg_white_balance(
                        looked,
                        temperature,
                        tint,
                    )
                encoded_aces = (
                    not self.enable_identity_elision
                    or contrast != 0.0
                    or saturation != 0.0
                    or highlights != 0.0
                    or has_lut
                )
                if encoded_aces:
                    looked = acescg_to_acescct(looked)
                    if not self.enable_identity_elision or contrast != 0.0:
                        looked = apply_acescct_contrast(looked, contrast)
                    if not self.enable_identity_elision or saturation != 0.0:
                        looked = apply_acescct_saturation(looked, saturation)
                    if not self.enable_identity_elision or highlights != 0.0:
                        looked = apply_acescct_highlights(looked, highlights)
            else:
                looked = apply_white_balance(
                    adjusted,
                    temperature,
                    tint,
                )
                looked = apply_contrast(looked, contrast)
                looked = apply_saturation(looked, saturation)
                looked = apply_highlights(looked, highlights)
            if has_lut:
                if aces_pipeline and node.metadata.get("lut_input_space") != "acescct":
                    raise ValueError(
                        "renderer v3 LUT nodes must declare metadata.lut_input_space='acescct'"
                    )
                interpolation = values.get(
                    "lut_interpolation",
                    "tetrahedral" if aces_pipeline else "trilinear",
                )
                if not isinstance(interpolation, str):
                    raise ValueError("lut_interpolation must be a string")
                looked = apply_lut(
                    looked,
                    lut_path,
                    interpolation=interpolation,
                )
            if aces_pipeline and encoded_aces:
                looked = acescct_to_acescg(looked)
            adjusted = image + (looked - image) * max(0.0, min(1.0, strength))
        elif node.type == NodeType.POST_LOOK:
            if aces_pipeline:
                contrast = float(values.get("contrast", 0.0))
                saturation = float(values.get("saturation", 0.0))
                if (
                    not self.enable_identity_elision
                    or contrast != 0.0
                    or saturation != 0.0
                ):
                    adjusted = acescg_to_acescct(adjusted)
                    if not self.enable_identity_elision or contrast != 0.0:
                        adjusted = apply_acescct_contrast(adjusted, contrast)
                    if not self.enable_identity_elision or saturation != 0.0:
                        adjusted = apply_acescct_saturation(adjusted, saturation)
                    adjusted = acescct_to_acescg(adjusted)
            else:
                adjusted = apply_contrast(adjusted, float(values.get("contrast", 0.0)))
                adjusted = apply_saturation(adjusted, float(values.get("saturation", 0.0)))
        else:
            raise ValueError(f"renderer does not implement node type: {node.type.value}")

        mask = self._resolve_mask(node, image, masks)
        if mask is not None:
            strength = float(values.get("mask_strength", 1.0))
            blend = (mask * max(0.0, min(1.0, strength))).clamp(0, 1)
            return image + (adjusted - image) * blend
        return adjusted

    def render_linear(
        self,
        image: torch.Tensor,
        graph: GradeGraph,
        *,
        time_seconds: float,
        masks: Mapping[str, torch.Tensor] | None = None,
    ) -> torch.Tensor:
        rendered = image
        for node in graph.ordered_nodes():
            if node.type in {NodeType.INPUT_TRANSFORM, NodeType.OUTPUT_TRANSFORM}:
                continue
            if _node_is_active(node, time_seconds):
                rendered = self._apply_node(rendered, node, time_seconds, masks)
        return soft_clip_highlights(rendered)

    @staticmethod
    def _transform_space(node: GradeNode, key: str) -> ColorSpace:
        value = node.parameters.get(key)
        if not isinstance(value, str):
            raise ValueError(f"{node.type.value} requires string parameter {key!r}")
        try:
            color_space = ColorSpace(value)
        except ValueError as exc:
            raise ValueError(f"{node.type.value} declares unknown color space {value!r}") from exc
        if color_space == ColorSpace.REC709:
            raise ValueError(
                f"{node.type.value} uses ambiguous legacy color space 'rec709'; "
                "use 'bt709_oetf', 'rec1886', or 'srgb'"
            )
        return color_space

    @staticmethod
    def _validate_transform_scope(node: GradeNode) -> None:
        if node.temporal_scope.level.value != "project":
            raise ValueError(f"{node.type.value} must use project temporal scope")
        if node.temporal_scope.time_range is not None:
            raise ValueError(f"{node.type.value} cannot have a time range")
        if node.spatial_scope.kind != SpatialKind.GLOBAL:
            raise ValueError(f"{node.type.value} must use global spatial scope")
        if node.spatial_scope.mask_asset_id is not None:
            raise ValueError(f"{node.type.value} cannot reference a mask")

    def _validate_versioned_pipeline(
        self,
        graph: GradeGraph,
    ) -> tuple[GradeNode, GradeNode]:
        if graph.renderer_version == LINEAR_REC709_RENDERER_VERSION:
            expected_working = ColorSpace.LINEAR_REC709
            renderer_label = "renderer v2"
        elif graph.renderer_version == CURRENT_RENDERER_VERSION:
            expected_working = ColorSpace.ACESCG
            renderer_label = "renderer v3"
        else:
            raise ValueError(
                f"versioned pipeline validation does not support {graph.renderer_version!r}"
            )
        if graph.working_color_space != expected_working:
            raise ValueError(
                f"{renderer_label} requires "
                f"working_color_space={expected_working.value!r}; "
                f"got {graph.working_color_space.value!r}"
            )
        ordered = graph.ordered_nodes()
        inputs = [node for node in ordered if node.type == NodeType.INPUT_TRANSFORM]
        outputs = [node for node in ordered if node.type == NodeType.OUTPUT_TRANSFORM]
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError(
                f"{renderer_label} requires exactly one enabled input and output transform"
            )
        input_node = inputs[0]
        output_node = outputs[0]
        if ordered[0] is not input_node or ordered[-1] is not output_node:
            raise ValueError("input transform must be first and output transform must be last")
        self._validate_transform_scope(input_node)
        self._validate_transform_scope(output_node)

        declared_input = self._transform_space(input_node, "input_space")
        input_working = self._transform_space(input_node, "working_space")
        output_working = self._transform_space(output_node, "working_space")
        declared_output = self._transform_space(output_node, "output_space")
        if declared_input != graph.media.input_color_space:
            raise ValueError(
                "input transform does not match media input_color_space: "
                f"{declared_input.value!r} != {graph.media.input_color_space.value!r}"
            )
        if (
            input_working != graph.working_color_space
            or output_working != graph.working_color_space
        ):
            raise ValueError(
                "transform node working_space does not match graph working_color_space"
            )
        if declared_output != graph.output_color_space:
            raise ValueError(
                "output transform does not match graph output_color_space: "
                f"{declared_output.value!r} != {graph.output_color_space.value!r}"
            )

        node_log_profile = input_node.parameters.get("source_log_profile")
        if graph.media.input_color_space == ColorSpace.LOG:
            if not isinstance(node_log_profile, str):
                raise ValueError("log input transform requires source_log_profile")
            if node_log_profile != graph.media.source_log_profile:
                raise ValueError(
                    "input transform source_log_profile does not match media source_log_profile"
                )
        elif node_log_profile is not None or graph.media.source_log_profile is not None:
            raise ValueError("source_log_profile is only valid for log input")

        if graph.renderer_version == CURRENT_RENDERER_VERSION:
            for node in (input_node, output_node):
                if node.parameters.get("interchange_space") != ColorSpace.ACES2065_1.value:
                    raise ValueError(
                        "renderer v3 transforms require interchange_space='aces2065_1'"
                    )
                if node.parameters.get("ocio_config") != OCIO_CONFIG_NAME:
                    raise ValueError(
                        f"renderer v3 transforms require ocio_config={OCIO_CONFIG_NAME!r}"
                    )
            display = output_node.parameters.get("display")
            view = output_node.parameters.get("view")
            if not isinstance(display, str) or not isinstance(view, str):
                raise ValueError("renderer v3 output transform requires string display and view")
            resolve_display_target(
                declared_output,
                display=display,
                view=view,
            )
        return input_node, output_node

    def render_graph(
        self,
        image: torch.Tensor,
        graph: GradeGraph,
        *,
        time_seconds: float,
        masks: Mapping[str, torch.Tensor] | None = None,
    ) -> torch.Tensor:
        rendered = image
        for node in graph.ordered_nodes():
            if _node_is_active(node, time_seconds):
                rendered = self._apply_node(
                    rendered,
                    node,
                    time_seconds,
                    masks,
                    working_color_space=graph.working_color_space,
                )
        return rendered

    @staticmethod
    def _select_masks(
        masks: Mapping[str, torch.Tensor] | None,
        frame_indices: list[int],
        *,
        batch_size: int,
    ) -> dict[str, torch.Tensor] | None:
        if masks is None:
            return None
        selected: dict[str, torch.Tensor] = {}
        for asset_id, mask in masks.items():
            if mask.ndim >= 3 and mask.shape[0] == batch_size:
                indices = torch.tensor(
                    frame_indices,
                    dtype=torch.long,
                    device=mask.device,
                )
                selected[asset_id] = mask.index_select(0, indices)
            else:
                selected[asset_id] = mask
        return selected

    def _render_creative_nodes_framewise(
        self,
        working_images: torch.Tensor,
        graph: GradeGraph,
        *,
        timestamps: list[float],
        masks: Mapping[str, torch.Tensor] | None,
    ) -> tuple[torch.Tensor, int, str]:
        outputs: list[torch.Tensor] = []
        node_groups = 0
        for index in range(working_images.shape[0]):
            frame_masks = self._select_masks(
                masks,
                [index],
                batch_size=working_images.shape[0],
            )
            rendered = working_images[index : index + 1]
            for node in graph.ordered_nodes():
                if node.type in {
                    NodeType.INPUT_TRANSFORM,
                    NodeType.OUTPUT_TRANSFORM,
                }:
                    continue
                if _node_is_active(node, timestamps[index]):
                    rendered = self._apply_node(
                        rendered,
                        node,
                        timestamps[index],
                        frame_masks,
                        working_color_space=graph.working_color_space,
                    )
                    node_groups += 1
            outputs.append(rendered)
        return torch.cat(outputs, dim=0), node_groups, "framewise_eager"

    def _render_creative_nodes_planned_streaming(
        self,
        working_images: torch.Tensor,
        graph: GradeGraph,
        *,
        timestamps: list[float],
        masks: Mapping[str, torch.Tensor] | None,
    ) -> tuple[torch.Tensor, int, str]:
        plans = _frame_execution_plans(graph, timestamps)
        outputs: list[torch.Tensor] = []
        node_groups = 0
        for frame_index, plan in enumerate(plans):
            frame_masks = self._select_masks(
                masks,
                [frame_index],
                batch_size=working_images.shape[0],
            )
            rendered = working_images[frame_index : frame_index + 1]
            for node, values in plan:
                rendered = self._apply_node(
                    rendered,
                    node,
                    timestamps[frame_index],
                    frame_masks,
                    working_color_space=graph.working_color_space,
                    parameter_values=values,
                )
                node_groups += 1
            outputs.append(rendered)
        return (
            torch.cat(outputs, dim=0),
            node_groups,
            "planned_streaming_eager",
        )

    def _render_creative_nodes_grouped(
        self,
        working_images: torch.Tensor,
        graph: GradeGraph,
        *,
        timestamps: list[float],
        masks: Mapping[str, torch.Tensor] | None,
    ) -> tuple[torch.Tensor, int, str]:
        rendered = working_images
        batch_size = working_images.shape[0]
        all_indices = list(range(batch_size))
        plans = _frame_execution_plans(graph, timestamps)
        grouped_indices: dict[
            tuple[
                tuple[
                    str,
                    tuple[tuple[str, float | int | str | bool], ...],
                ],
                ...,
            ],
            list[int],
        ] = {}
        for frame_index, plan in enumerate(plans):
            signature = tuple(
                (
                    node.id,
                    tuple(values.items()),
                )
                for node, values in plan
            )
            grouped_indices.setdefault(signature, []).append(frame_index)

        node_groups = 0
        for frame_indices in grouped_indices.values():
            whole_batch = frame_indices == all_indices
            if whole_batch:
                group_output = rendered
                group_masks = masks
            else:
                indices = torch.tensor(
                    frame_indices,
                    dtype=torch.long,
                    device=rendered.device,
                )
                group_output = rendered.index_select(0, indices)
                group_masks = self._select_masks(
                    masks,
                    frame_indices,
                    batch_size=batch_size,
                )
            for node, values in plans[frame_indices[0]]:
                group_output = self._apply_node(
                    group_output,
                    node,
                    timestamps[frame_indices[0]],
                    group_masks,
                    working_color_space=graph.working_color_space,
                    parameter_values=values,
                )
                node_groups += 1
            if whole_batch:
                rendered = group_output
            else:
                rendered = rendered.index_copy(0, indices, group_output)
        return rendered, node_groups, "grouped_eager"

    def _render_creative_nodes_batch(
        self,
        working_images: torch.Tensor,
        graph: GradeGraph,
        *,
        timestamps: list[float],
        masks: Mapping[str, torch.Tensor] | None,
    ) -> tuple[torch.Tensor, int, str]:
        if not self.enable_execution_planning:
            return self._render_creative_nodes_framewise(
                working_images,
                graph,
                timestamps=timestamps,
                masks=masks,
            )
        use_grouping = self.enable_batch_grouping
        if use_grouping is None:
            pixel_count = (
                working_images.shape[0]
                * working_images.shape[-2]
                * working_images.shape[-1]
            )
            use_grouping = (
                self.backend.info.runtime == "cpu"
                or pixel_count <= self.maximum_grouped_pixels
            )
        if use_grouping:
            return self._render_creative_nodes_grouped(
                working_images,
                graph,
                timestamps=timestamps,
                masks=masks,
            )
        return self._render_creative_nodes_planned_streaming(
            working_images,
            graph,
            timestamps=timestamps,
            masks=masks,
        )

    def render_working_batch(
        self,
        images: torch.Tensor,
        graph: GradeGraph,
        *,
        timestamps: list[float],
        masks: Mapping[str, torch.Tensor] | None = None,
        mixed_precision: bool = False,
    ) -> tuple[torch.Tensor, RenderMetrics]:
        """Render versioned input and creative nodes without the output transform.

        The returned tensor is scene-linear working RGB (Linear Rec.709 for v2,
        ACEScg for v3) and intentionally keeps values outside 0..1.
        """
        if images.ndim != 4 or images.shape[1] != 3:
            raise ValueError("images must use NCHW layout with three RGB channels")
        if len(timestamps) != images.shape[0]:
            raise ValueError("timestamps length must equal batch size")
        if graph.renderer_version not in {
            LINEAR_REC709_RENDERER_VERSION,
            CURRENT_RENDERER_VERSION,
        }:
            raise ValueError("working-space rendering requires renderer v2 or v3")

        started = time.perf_counter()
        device_images = images.to(
            self.backend.torch_device,
            dtype=torch.float32,
            non_blocking=True,
        )
        with (
            self.backend.inference_context(mixed_precision=mixed_precision),
            fp32_grading_context(device_images.device),
        ):
            input_node, _ = self._validate_versioned_pipeline(graph)
            working_images = self._apply_node(
                device_images,
                input_node,
                0.0,
                None,
                working_color_space=graph.working_color_space,
            )
            result, node_groups, batch_strategy = self._render_creative_nodes_batch(
                working_images,
                graph,
                timestamps=timestamps,
                masks=masks,
            )

        self.backend.synchronize()
        elapsed = max(time.perf_counter() - started, 1e-9)
        info = self.backend.info
        return result, RenderMetrics(
            elapsed_seconds=elapsed,
            frames=images.shape[0],
            fps=images.shape[0] / elapsed,
            device_runtime=info.runtime,
            device_name=info.name,
            batch_strategy=batch_strategy,
            node_groups=node_groups,
            identity_elision=self.enable_identity_elision,
        )

    def render_output_batch(
        self,
        images: torch.Tensor,
        graph: GradeGraph,
        *,
        timestamps: list[float],
        masks: Mapping[str, torch.Tensor] | None = None,
        mixed_precision: bool = False,
        clamp_output: bool = True,
    ) -> tuple[torch.Tensor, RenderMetrics]:
        if images.ndim != 4 or images.shape[1] != 3:
            raise ValueError("images must use NCHW layout with three RGB channels")
        if len(timestamps) != images.shape[0]:
            raise ValueError("timestamps length must equal batch size")

        started = time.perf_counter()
        device_images = images.to(
            self.backend.torch_device,
            dtype=torch.float32,
            non_blocking=True,
        )
        evidence = TorchStageEvidenceRecorder(
            self.backend,
            stage="grade_graph_render",
            model_id=f"grade-renderer/{graph.renderer_version}",
            model=self,
            inputs={"images": device_images},
            model_devices_required=False,
        )
        # All currently implemented grading nodes contain transfer functions,
        # pow/log, LUT sampling or output transforms. They remain FP32 even
        # when a preview caller enables outer autocast for future safe ops.
        with (
            self.backend.inference_context(mixed_precision=mixed_precision),
            fp32_grading_context(device_images.device),
        ):
            legacy = graph.renderer_version == LEGACY_RENDERER_VERSION
            output_node: GradeNode | None = None
            if legacy:
                if graph.media.input_color_space == ColorSpace.LOG:
                    working_images = log_to_linear_rec709(
                        device_images,
                        graph.media.source_log_profile,
                    )
                else:
                    working_images = srgb_to_linear(device_images)
            elif graph.renderer_version in {
                LINEAR_REC709_RENDERER_VERSION,
                CURRENT_RENDERER_VERSION,
            }:
                input_node, output_node = self._validate_versioned_pipeline(graph)
                working_images = self._apply_node(
                    device_images,
                    input_node,
                    0.0,
                    None,
                    working_color_space=graph.working_color_space,
                )
            else:
                # Guard callers that bypassed GradeGraph validation.
                raise ValueError(f"unsupported renderer version: {graph.renderer_version!r}")

            rendered, node_groups, batch_strategy = self._render_creative_nodes_batch(
                working_images,
                graph,
                timestamps=timestamps,
                masks=masks,
            )
            if legacy:
                result = linear_to_srgb(soft_clip_highlights(rendered))
            else:
                if output_node is None:  # pragma: no cover - defensive invariant
                    raise RuntimeError("versioned renderer has no output transform")
                result = self._apply_node(
                    rendered,
                    output_node,
                    0.0,
                    None,
                    working_color_space=graph.working_color_space,
                )
            if clamp_output:
                result = result.clamp(0, 1)
        self.last_output_evidence = evidence.finish(result)
        self.backend.synchronize()
        elapsed = max(time.perf_counter() - started, 1e-9)
        info = self.backend.info
        return result, RenderMetrics(
            elapsed_seconds=elapsed,
            frames=images.shape[0],
            fps=images.shape[0] / elapsed,
            device_runtime=info.runtime,
            device_name=info.name,
            batch_strategy=batch_strategy,
            node_groups=node_groups,
            identity_elision=self.enable_identity_elision,
        )

    def render_srgb_batch(
        self,
        images: torch.Tensor,
        graph: GradeGraph,
        *,
        timestamps: list[float],
        masks: Mapping[str, torch.Tensor] | None = None,
        mixed_precision: bool = False,
    ) -> tuple[torch.Tensor, RenderMetrics]:
        """Compatibility wrapper; output follows the graph's versioned display encoding."""
        return self.render_output_batch(
            images,
            graph,
            timestamps=timestamps,
            masks=masks,
            mixed_precision=mixed_precision,
        )

    def render_image(
        self,
        source: str | Path,
        destination: str | Path,
        graph: GradeGraph,
        *,
        time_seconds: float = 0.0,
        masks: Mapping[str, torch.Tensor] | None = None,
        display_color_space: ColorSpace | None = ColorSpace.SRGB,
    ) -> RenderMetrics:
        """Render one image, optionally converting its output for still display.

        Passing ``display_color_space=None`` preserves the graph's encoded
        output signal. Interactive exact-frame previews use that mode so their
        pixels follow the same signal path as the graded playback video.
        """
        image = Image.open(source).convert("RGB")
        array = np.asarray(image, dtype=np.float32) / 255.0
        tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)
        output, metrics = self.render_output_batch(
            tensor,
            graph,
            timestamps=[time_seconds],
            masks=masks,
            mixed_precision=PREVIEW_PRECISION_BUDGET.mixed_precision_allowed,
        )
        if graph.renderer_version == LEGACY_RENDERER_VERSION or display_color_space is None:
            display_output = output
        else:
            output_node = next(
                node for node in graph.ordered_nodes() if node.type == NodeType.OUTPUT_TRANSFORM
            )
            destination_log_profile = output_node.parameters.get("destination_log_profile")
            display_output = convert_color_space(
                output,
                graph.output_color_space,
                display_color_space,
                source_log_profile=(
                    destination_log_profile if isinstance(destination_log_profile, str) else None
                ),
            ).clamp(0, 1)
        output_array = display_output[0].permute(1, 2, 0).mul(255).round().byte().cpu().numpy()
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        output_image = Image.fromarray(output_array, mode="RGB")
        if target.suffix.lower() in {".jpg", ".jpeg"}:
            output_image.save(target, quality=95, subsampling=0, optimize=True)
        else:
            output_image.save(target)
        return metrics
