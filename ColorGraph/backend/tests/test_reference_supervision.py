from pathlib import Path

import numpy as np
import torch

from colorgraph.domain.grade_graph import ColorSpace, MediaInfo, NodeType, TimeRange
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.services.reference_supervision import (
    REFERENCE_NODE_ID,
    apply_partial_reference_node,
    fit_tone_parameters,
)


def test_tone_fit_reduces_paired_rgb_error() -> None:
    rng = np.random.default_rng(7)
    source = rng.uniform(0.05, 0.95, size=(8_000, 3)).astype(np.float32)
    target = np.clip(source * np.asarray([0.72, 0.70, 0.68], dtype=np.float32), 0, 1)

    parameters, metrics = fit_tone_parameters(
        source,
        target,
        device=torch.device("cpu"),
        optimization_steps=120,
    )

    assert metrics["rgb_mae_after"] < metrics["rgb_mae_before"] * 0.12
    assert metrics["luma_mae_after"] < metrics["luma_mae_before"] * 0.12
    assert set(parameters) == {
        "exposure",
        "contrast",
        "saturation",
        "temperature",
        "tint",
        "highlights",
        "shadows",
        "midtones",
        "curve_highlights",
    }


def test_partial_reference_node_is_independent_and_idempotent() -> None:
    media = MediaInfo(
        path="source.mov",
        duration_seconds=8,
        width=640,
        height=360,
        fps=25,
        frame_count=200,
        codec="prores",
        input_color_space=ColorSpace.BT709_OETF,
    )
    graph = build_initial_graph(
        project_id="reference_test",
        project_name="Reference",
        media=media,
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=8)],
        representative_frames=[Path("one.jpg")],
        scene_groups=[[0]],
    )
    parameters = {
        "exposure": -0.4,
        "contrast": 0.3,
        "saturation": -0.1,
        "temperature": 0.1,
        "tint": 0.0,
        "highlights": 0.2,
        "shadows": -0.2,
        "midtones": -0.25,
        "curve_highlights": 0.1,
    }

    first = apply_partial_reference_node(
        graph,
        node_id=REFERENCE_NODE_ID,
        parameters=parameters,
        supervision_metadata={"version": "test/v1"},
    )
    second = apply_partial_reference_node(
        first,
        node_id=REFERENCE_NODE_ID,
        parameters={**parameters, "exposure": -0.5},
        supervision_metadata={"version": "test/v2"},
    )

    reference_nodes = [node for node in second.nodes if node.id == REFERENCE_NODE_ID]
    assert len(reference_nodes) == 1
    assert reference_nodes[0].enabled
    assert reference_nodes[0].type == NodeType.TONE
    assert reference_nodes[0].parameters["exposure"] == -0.5
    assert reference_nodes[0].order < next(
        node.order for node in second.nodes if node.type == NodeType.OUTPUT_TRANSFORM
    )
    assert second.metadata["partial_reference_supervision"]["version"] == "test/v2"
