from __future__ import annotations

from pathlib import Path

import torch

from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    GradeNode,
    Interpolation,
    Keyframe,
    MediaInfo,
    NodeType,
    ParameterTrack,
    ScopeLevel,
    SpatialKind,
    SpatialScope,
    TemporalScope,
    TimeRange,
)
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.precision import MASTER_PRECISION_BUDGET
from colorgraph.services.graph_builder import build_initial_graph


def _tracked_graph():
    media = MediaInfo(
        path="batch-source.mov",
        duration_seconds=2,
        width=32,
        height=18,
        fps=4,
        frame_count=8,
        codec="prores",
    )
    graph = build_initial_graph(
        project_id="batch-render",
        project_name="Batch Render",
        media=media,
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=1),
            TimeRange(start_seconds=1, end_seconds=2),
        ],
        representative_frames=[Path("shot-1.jpg"), Path("shot-2.jpg")],
    )
    first_balance = next(node for node in graph.nodes if node.id == "balance_shot_001")
    first_balance.parameters.update(
        {
            "contrast": 0.12,
            "saturation": 0.08,
            "highlights": -0.05,
        }
    )
    first_balance.tracks = [
        ParameterTrack(
            parameter="exposure",
            interpolation=Interpolation.PCHIP,
            max_velocity=0.8,
            max_acceleration=1.5,
            keyframes=[
                Keyframe(time_seconds=0, value=-0.1),
                Keyframe(time_seconds=0.45, value=0.2),
                Keyframe(time_seconds=1, value=0.05),
            ],
        )
    ]
    graph.nodes.append(
        GradeNode(
            id="masked_sky",
            type=NodeType.MASKED_GRADE,
            label="Masked sky",
            order=150,
            temporal_scope=TemporalScope(
                level=ScopeLevel.PROJECT,
                project_id=graph.project_id,
            ),
            spatial_scope=SpatialScope(
                kind=SpatialKind.SEMANTIC,
                target="sky",
                mask_asset_id="mask_sky",
            ),
            parameters={
                "exposure": -0.08,
                "saturation": 0.1,
                "mask_strength": 0.7,
            },
        )
    )
    return graph


def test_grouped_batch_renderer_matches_framewise_reference() -> None:
    graph = _tracked_graph()
    generator = torch.Generator().manual_seed(20260730)
    images = torch.rand((8, 3, 18, 32), generator=generator)
    sky_masks = torch.linspace(0, 1, 18).view(1, 18, 1).expand(8, 18, 32)
    timestamps = [index / 4 for index in range(8)]
    backend = TorchComputeBackend("cpu")

    grouped, grouped_metrics = GradeRenderEngine(
        backend,
        enable_batch_grouping=True,
    ).render_output_batch(
        images,
        graph,
        timestamps=timestamps,
        masks={"mask_sky": sky_masks},
    )
    reference, reference_metrics = GradeRenderEngine(
        backend,
        enable_batch_grouping=False,
        enable_identity_elision=False,
        enable_execution_planning=False,
    ).render_output_batch(
        images,
        graph,
        timestamps=timestamps,
        masks={"mask_sky": sky_masks},
    )
    planned, planned_metrics = GradeRenderEngine(
        backend,
        enable_batch_grouping=False,
    ).render_output_batch(
        images,
        graph,
        timestamps=timestamps,
        masks={"mask_sky": sky_masks},
    )

    assert torch.max(torch.abs(grouped - reference)).item() <= (
        MASTER_PRECISION_BUDGET.maximum_normalized_channel_error
    )
    assert torch.equal(grouped, planned)
    assert grouped_metrics.batch_strategy == "grouped_eager"
    assert reference_metrics.batch_strategy == "framewise_eager"
    assert planned_metrics.batch_strategy == "planned_streaming_eager"
    assert grouped_metrics.identity_elision is True
    assert reference_metrics.identity_elision is False
    assert grouped_metrics.node_groups == 15
    assert reference_metrics.node_groups == 24
    assert planned_metrics.node_groups == 24
