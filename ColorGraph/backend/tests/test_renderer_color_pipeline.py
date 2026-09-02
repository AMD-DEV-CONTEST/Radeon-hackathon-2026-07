from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image
from pydantic import ValidationError

from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    CURRENT_GRADE_GRAPH_SCHEMA_VERSION,
    CURRENT_RENDERER_VERSION,
    LEGACY_GRADE_GRAPH_SCHEMA_VERSION,
    LEGACY_RENDERER_VERSION,
    LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION,
    LINEAR_REC709_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    MediaInfo,
    NodeType,
    TimeRange,
)
from colorgraph.grading.color import convert_color_space
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.ocio_pipeline import (
    acescg_to_output,
    input_to_acescg,
    resolve_display_target,
)
from colorgraph.grading.precision import (
    MASTER_PRECISION_BUDGET,
    PREVIEW_PRECISION_BUDGET,
)
from colorgraph.services.graph_builder import build_initial_graph


def _explicit_graph(
    *,
    input_space: ColorSpace = ColorSpace.BT709_OETF,
    output_space: ColorSpace = ColorSpace.SRGB,
    source_log_profile: str | None = None,
) -> GradeGraph:
    graph = build_initial_graph(
        project_id="color-pipeline",
        project_name="Color Pipeline",
        media=MediaInfo(
            path="source.mov",
            duration_seconds=1,
            width=4,
            height=1,
            fps=24,
            frame_count=24,
            codec="prores",
            input_color_space=input_space,
            source_log_profile=source_log_profile,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1)],
        representative_frames=[Path("frame.jpg")],
        renderer_version=LINEAR_REC709_RENDERER_VERSION,
    )
    for node in graph.nodes:
        if node.type not in {NodeType.INPUT_TRANSFORM, NodeType.OUTPUT_TRANSFORM}:
            node.enabled = False
    graph.output_color_space = output_space
    output_node = next(node for node in graph.nodes if node.type == NodeType.OUTPUT_TRANSFORM)
    output_node.parameters["output_space"] = output_space.value
    return graph


def _engine() -> GradeRenderEngine:
    return GradeRenderEngine(TorchComputeBackend("cpu"))


def test_render_image_can_preserve_video_output_signal(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    default_still = tmp_path / "default-still.png"
    video_signal_still = tmp_path / "video-signal-still.png"
    values = np.asarray(
        [[[32, 32, 32], [96, 96, 96], [160, 160, 160], [224, 224, 224]]],
        dtype=np.uint8,
    )
    Image.fromarray(values, mode="RGB").save(source)
    graph = _aces_graph(output_space=ColorSpace.REC1886)
    engine = _engine()

    engine.render_image(source, default_still, graph)
    engine.render_image(
        source,
        video_signal_still,
        graph,
        display_color_space=None,
    )

    tensor = torch.from_numpy(values.astype(np.float32) / 255).permute(2, 0, 1).unsqueeze(0)
    expected, _ = engine.render_output_batch(tensor, graph, timestamps=[0])
    expected_values = expected[0].permute(1, 2, 0).clamp(0, 1).mul(255).round().byte().numpy()
    actual_signal = np.asarray(Image.open(video_signal_still).convert("RGB"))
    actual_default = np.asarray(Image.open(default_still).convert("RGB"))

    assert np.array_equal(actual_signal, expected_values)
    assert not np.array_equal(actual_default, actual_signal)


def _aces_graph(
    *,
    input_space: ColorSpace = ColorSpace.BT709_OETF,
    output_space: ColorSpace = ColorSpace.SRGB,
) -> GradeGraph:
    graph = build_initial_graph(
        project_id="aces-pipeline",
        project_name="ACES Pipeline",
        media=MediaInfo(
            path="source.mov",
            duration_seconds=1,
            width=4,
            height=1,
            fps=24,
            frame_count=24,
            codec="prores",
            input_color_space=input_space,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1)],
        representative_frames=[Path("frame.jpg")],
    )
    for node in graph.nodes:
        if node.type not in {NodeType.INPUT_TRANSFORM, NodeType.OUTPUT_TRANSFORM}:
            node.enabled = False
    graph.output_color_space = output_space
    target = resolve_display_target(output_space)
    output_node = next(node for node in graph.nodes if node.type == NodeType.OUTPUT_TRANSFORM)
    output_node.parameters.update(
        {
            "output_space": output_space.value,
            "display": target.display,
            "view": target.view,
        }
    )
    return graph


def test_renderer_v2_executes_declared_input_and_output_nodes() -> None:
    graph = _explicit_graph()
    linear = torch.tensor([0.0, 0.018, 0.18, 0.5], dtype=torch.float32).view(1, 1, 1, 4)
    linear = linear.expand(1, 3, 1, 4)
    encoded_input = convert_color_space(
        linear,
        ColorSpace.LINEAR_REC709,
        ColorSpace.BT709_OETF,
    )

    output, _ = _engine().render_output_batch(
        encoded_input,
        graph,
        timestamps=[0.0],
        mixed_precision=False,
    )
    expected = convert_color_space(
        linear,
        ColorSpace.LINEAR_REC709,
        ColorSpace.SRGB,
    )

    assert torch.allclose(output, expected, atol=2e-6)


def test_renderer_v3_executes_aces_input_working_and_output_stages() -> None:
    graph = _aces_graph()
    linear = torch.tensor([0.018, 0.18, 1.0, 4.0], dtype=torch.float32).view(
        1, 1, 1, 4
    )
    linear = linear.expand(1, 3, 1, 4)
    encoded_input = convert_color_space(
        linear,
        ColorSpace.LINEAR_REC709,
        ColorSpace.BT709_OETF,
    )

    working, _ = _engine().render_working_batch(
        encoded_input,
        graph,
        timestamps=[0.0],
    )
    output, _ = _engine().render_output_batch(
        encoded_input,
        graph,
        timestamps=[0.0],
    )
    expected_working = input_to_acescg(
        encoded_input,
        ColorSpace.BT709_OETF,
    )
    expected_output = acescg_to_output(
        expected_working,
        ColorSpace.SRGB,
    ).clamp(0, 1)

    assert graph.working_color_space == ColorSpace.ACESCG
    assert torch.allclose(working, expected_working, rtol=0, atol=2e-6)
    assert torch.allclose(output, expected_output, rtol=0, atol=2e-6)


def test_renderer_v3_keeps_scene_linear_exposure_in_acescg() -> None:
    graph = _aces_graph(input_space=ColorSpace.ACESCG)
    balance = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    balance.enabled = True
    balance.parameters["exposure"] = 1.0
    source = torch.tensor([0.01, 0.18, 1.0], dtype=torch.float32).view(1, 3, 1, 1)

    working, _ = _engine().render_working_batch(
        source,
        graph,
        timestamps=[0.25],
    )

    assert torch.allclose(working, source * 2.0, rtol=0, atol=3e-5)


def test_working_render_stops_before_output_soft_clip_and_encoding() -> None:
    graph = _explicit_graph()
    linear = torch.tensor([0.18, 0.5, 0.9], dtype=torch.float32).view(1, 1, 1, 3)
    linear = linear.expand(1, 3, 1, 3)
    encoded_input = convert_color_space(
        linear,
        ColorSpace.LINEAR_REC709,
        ColorSpace.BT709_OETF,
    )

    working, _ = _engine().render_working_batch(
        encoded_input,
        graph,
        timestamps=[0.0],
        mixed_precision=False,
    )
    output, _ = _engine().render_output_batch(
        encoded_input,
        graph,
        timestamps=[0.0],
        mixed_precision=False,
    )

    assert torch.allclose(working, linear, atol=2e-6)
    assert (
        output[0, 0, 0, -1]
        < convert_color_space(
            linear,
            ColorSpace.LINEAR_REC709,
            ColorSpace.SRGB,
        )[0, 0, 0, -1]
    )


def test_renderer_rejects_transform_declaration_mismatch() -> None:
    graph = _explicit_graph()
    input_node = next(node for node in graph.nodes if node.type == NodeType.INPUT_TRANSFORM)
    input_node.parameters["input_space"] = ColorSpace.SRGB.value

    with pytest.raises(ValueError, match="does not match media input_color_space"):
        _engine().render_output_batch(
            torch.zeros((1, 3, 1, 1)),
            graph,
            timestamps=[0.0],
            mixed_precision=False,
        )


def test_renderer_rejects_unknown_or_missing_transform() -> None:
    graph = _explicit_graph()
    input_node = next(node for node in graph.nodes if node.type == NodeType.INPUT_TRANSFORM)
    input_node.parameters["input_space"] = "camera_magic"
    with pytest.raises(ValueError, match="unknown color space"):
        _engine().render_output_batch(
            torch.zeros((1, 3, 1, 1)),
            graph,
            timestamps=[0.0],
            mixed_precision=False,
        )

    input_node.parameters["input_space"] = ColorSpace.BT709_OETF.value
    input_node.enabled = False
    with pytest.raises(ValueError, match="exactly one enabled input and output transform"):
        _engine().render_output_batch(
            torch.zeros((1, 3, 1, 1)),
            graph,
            timestamps=[0.0],
            mixed_precision=False,
        )


def test_renderer_rejects_unimplemented_working_space() -> None:
    graph = _explicit_graph()
    graph.working_color_space = ColorSpace.ACESCCT
    for node in graph.nodes:
        if node.type in {NodeType.INPUT_TRANSFORM, NodeType.OUTPUT_TRANSFORM}:
            node.parameters["working_space"] = ColorSpace.ACESCCT.value

    with pytest.raises(ValueError, match="requires working_color_space='linear_rec709'"):
        _engine().render_output_batch(
            torch.zeros((1, 3, 1, 1)),
            graph,
            timestamps=[0.0],
            mixed_precision=False,
        )


def test_legacy_v1_graph_keeps_previous_srgb_compatibility() -> None:
    graph = GradeGraph.model_validate(
        {
            "schema_version": LEGACY_GRADE_GRAPH_SCHEMA_VERSION,
            "id": "legacy-graph",
            "project_id": "legacy-project",
            "project_name": "Legacy",
            "working_color_space": "linear_rec709",
            "output_color_space": "rec709",
            "media": {
                "path": "legacy.mp4",
                "duration_seconds": 1,
                "width": 3,
                "height": 1,
                "fps": 24,
                "frame_count": 24,
                "codec": "h264",
                "input_color_space": "rec709",
            },
        }
    )
    encoded = torch.tensor([0.02, 0.18, 0.6], dtype=torch.float32).view(1, 1, 1, 3)
    encoded = encoded.expand(1, 3, 1, 3)

    output, _ = _engine().render_output_batch(
        encoded,
        graph,
        timestamps=[0.0],
        mixed_precision=False,
    )

    assert graph.renderer_version == LEGACY_RENDERER_VERSION
    assert torch.allclose(output, encoded, atol=2e-6)


def test_graph_version_pairs_are_explicit_and_validated() -> None:
    graph = _explicit_graph()
    assert graph.schema_version == LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION
    assert graph.renderer_version == LINEAR_REC709_RENDERER_VERSION
    legacy_look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    assert legacy_look.parameters["lut_interpolation"] == "trilinear"

    payload = graph.model_dump(mode="python")
    payload["schema_version"] = LEGACY_GRADE_GRAPH_SCHEMA_VERSION
    payload["renderer_version"] = LINEAR_REC709_RENDERER_VERSION
    with pytest.raises(ValidationError, match="unsupported grade graph / renderer version pair"):
        GradeGraph.model_validate(payload)

    aces_graph = build_initial_graph(
        project_id="aces-version",
        project_name="ACES Version",
        media=graph.media,
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1)],
        representative_frames=[Path("frame.jpg")],
    )
    assert aces_graph.schema_version == CURRENT_GRADE_GRAPH_SCHEMA_VERSION
    assert aces_graph.renderer_version == CURRENT_RENDERER_VERSION
    aces_look = next(node for node in aces_graph.nodes if node.type == NodeType.LOOK)
    assert aces_look.parameters["lut_interpolation"] == "tetrahedral"
    assert aces_look.metadata["lut_input_space"] == "acescct"


@pytest.mark.skipif(not torch.cuda.is_available(), reason="accelerator is unavailable")
def test_master_fp32_cpu_and_accelerator_outputs_stay_within_precision_budget() -> None:
    graph = _explicit_graph()
    for node in graph.nodes:
        if node.type == NodeType.BALANCE:
            node.enabled = True
            node.parameters.update(
                {
                    "exposure": 0.35,
                    "temperature": -0.12,
                    "tint": 0.08,
                    "contrast": 0.14,
                    "saturation": 0.09,
                    "highlights": -0.18,
                }
            )
    image = torch.linspace(0.001, 0.999, 3 * 16 * 32, dtype=torch.float32).reshape(
        1,
        3,
        16,
        32,
    )

    cpu_output, _ = GradeRenderEngine(TorchComputeBackend("cpu")).render_output_batch(
        image,
        graph,
        timestamps=[0.25],
        mixed_precision=MASTER_PRECISION_BUDGET.mixed_precision_allowed,
    )
    accelerator_output, _ = GradeRenderEngine(TorchComputeBackend("auto")).render_output_batch(
        image,
        graph,
        timestamps=[0.25],
        mixed_precision=MASTER_PRECISION_BUDGET.mixed_precision_allowed,
    )

    assert torch.allclose(
        cpu_output,
        accelerator_output.cpu(),
        rtol=0,
        atol=MASTER_PRECISION_BUDGET.maximum_normalized_channel_error,
    )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="accelerator is unavailable")
def test_preview_autocast_request_keeps_sensitive_grading_fp32_within_budget() -> None:
    graph = _explicit_graph()
    image = torch.linspace(0.001, 0.999, 3 * 8 * 16, dtype=torch.float16).reshape(
        1,
        3,
        8,
        16,
    )
    engine = GradeRenderEngine(TorchComputeBackend("auto"))

    fp32_output, _ = engine.render_output_batch(
        image,
        graph,
        timestamps=[0.5],
        mixed_precision=False,
    )
    preview_output, _ = engine.render_output_batch(
        image,
        graph,
        timestamps=[0.5],
        mixed_precision=True,
    )

    assert fp32_output.dtype == torch.float32
    assert preview_output.dtype == torch.float32
    assert torch.max(torch.abs(preview_output - fp32_output)).item() <= (
        PREVIEW_PRECISION_BUDGET.maximum_normalized_channel_error
    )
