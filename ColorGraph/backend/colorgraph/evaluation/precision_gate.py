from __future__ import annotations

import hashlib
import json
import platform
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import torch

from colorgraph.devices import TorchComputeBackend
from colorgraph.devices.base import DeviceInfo
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    GradeNode,
    MediaInfo,
    NodeType,
    ScopeLevel,
    SpatialScope,
    TemporalScope,
    TimeRange,
)
from colorgraph.evaluation.metrics import delta_e_2000
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.ocio_pipeline import (
    ocio_pipeline_metadata,
    resolve_display_target,
)
from colorgraph.grading.precision import (
    MASTER_PRECISION_BUDGET,
    PREVIEW_PRECISION_BUDGET,
    RenderPrecisionBudget,
)
from colorgraph.services.graph_builder import build_initial_graph

AcceleratorRuntime = Literal["cuda", "rocm"]


class PrecisionComparison(StrictEvaluationModel):
    reference: str
    candidate: str
    reference_dtype: str
    candidate_dtype: str
    reference_output_sha256: str
    candidate_output_sha256: str
    maximum_normalized_channel_error: float
    p95_normalized_channel_error: float
    mean_normalized_channel_error: float
    maximum_delta_e_2000: float
    p95_delta_e_2000: float
    mean_delta_e_2000: float
    channel_error_budget: float
    delta_e_2000_budget: float
    passed: bool


class DeterminismComparison(StrictEvaluationModel):
    repeats: int
    output_sha256: list[str]
    maximum_normalized_channel_drift: float
    drift_budget: float
    passed: bool


class PrecisionGateReport(StrictEvaluationModel):
    schema_version: str = "colorgraph.precision-gate-report/v1"
    created_at: datetime
    status: Literal["passed", "failed"]
    expected_runtime: AcceleratorRuntime
    hardware: DeviceInfo
    operating_system: str
    python_version: str
    torch_version: str
    hip_version: str | None
    cuda_version: str | None
    input_sha256: str
    graph_sha256: str
    lut_sha256: str
    sample_shape: list[int]
    timestamps: list[float]
    cpu_elapsed_ms: float
    accelerator_elapsed_ms: list[float]
    peak_accelerator_memory_mb: int
    master: PrecisionComparison
    preview: PrecisionComparison
    determinism: DeterminismComparison


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tensor_sha256(value: torch.Tensor) -> str:
    array = value.detach().to(device="cpu", dtype=torch.float32).contiguous().numpy()
    return _sha256_bytes(array.tobytes())


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _write_stress_lut(path: Path, *, size: int = 5) -> str:
    lines = [
        'TITLE "ColorGraph deterministic precision stress LUT"',
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    denominator = size - 1
    for blue_index in range(size):
        blue = blue_index / denominator
        for green_index in range(size):
            green = green_index / denominator
            for red_index in range(size):
                red = red_index / denominator
                output_red = np.clip(red**0.94 * 1.015 + green * 0.012, 0, 1)
                output_green = np.clip(green**1.03 * 0.995 + blue * 0.008, 0, 1)
                output_blue = np.clip(blue**0.97 * 1.01 + red * 0.006, 0, 1)
                lines.append(
                    f"{output_red:.10f} {output_green:.10f} {output_blue:.10f}"
                )
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
    return _sha256_bytes(content.encode("utf-8"))


def _build_stress_graph(lut_path: Path) -> GradeGraph:
    project_id = "precision-gate"
    graph = build_initial_graph(
        project_id=project_id,
        project_name="Precision gate",
        media=MediaInfo(
            path="precision-gate.mov",
            duration_seconds=1,
            width=64,
            height=32,
            fps=24,
            frame_count=24,
            codec="raw",
            pixel_format="gbrpf32le",
            bit_depth=32,
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1)],
        representative_frames=[Path("precision-gate.png")],
    )
    balance = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    balance.parameters.update(
        {
            "slope_r": 1.03,
            "slope_g": 0.985,
            "slope_b": 1.015,
            "offset_r": -0.004,
            "offset_g": 0.006,
            "offset_b": -0.002,
            "power_r": 0.96,
            "power_g": 1.035,
            "power_b": 0.985,
            "exposure": 0.35,
            "temperature": -0.12,
            "tint": 0.08,
            "contrast": 0.14,
            "saturation": 0.09,
            "highlights": -0.18,
            "shadows": 0.11,
            "midtones": -0.07,
            "curve_highlights": 0.13,
        }
    )
    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.parameters.update(
        {
            "strength": 0.73,
            "temperature": 0.06,
            "tint": -0.035,
            "contrast": 0.08,
            "saturation": -0.04,
            "highlights": -0.09,
            "lut_path": str(lut_path),
        }
    )
    look.metadata["lut_input_space"] = "acescct"
    graph.nodes.append(
        GradeNode(
            id="tone_precision_gate",
            type=NodeType.TONE,
            label="Precision stress tone",
            order=50,
            temporal_scope=TemporalScope(
                level=ScopeLevel.PROJECT,
                project_id=project_id,
            ),
            spatial_scope=SpatialScope(),
            parameters={
                "slope_r": 0.99,
                "slope_g": 1.01,
                "slope_b": 1.02,
                "offset_r": 0.003,
                "offset_g": -0.002,
                "offset_b": 0.001,
                "power_r": 1.04,
                "power_g": 0.98,
                "power_b": 1.015,
                "contrast": -0.06,
                "saturation": 0.035,
                "shadows": -0.08,
                "midtones": 0.05,
                "curve_highlights": -0.04,
            },
        )
    )
    graph.output_color_space = ColorSpace.SRGB
    target = resolve_display_target(ColorSpace.SRGB)
    output = next(
        node for node in graph.nodes if node.type == NodeType.OUTPUT_TRANSFORM
    )
    output.parameters.update(
        {
            "output_space": ColorSpace.SRGB.value,
            "display": target.display,
            "view": target.view,
        }
    )
    graph.metadata["color_pipeline"] = ocio_pipeline_metadata(
        graph.media.input_color_space,
        source_log_profile=graph.media.source_log_profile,
        output_space=ColorSpace.SRGB,
    )
    return graph


def _stable_graph_payload(graph: GradeGraph) -> dict[str, object]:
    payload = graph.model_dump(mode="json")
    for node in payload["nodes"]:
        parameters = node["parameters"]
        if "lut_path" in parameters:
            parameters["lut_path"] = "<generated-precision-stress-lut>"
    return payload


def _stress_input() -> torch.Tensor:
    generator = torch.Generator(device="cpu")
    generator.manual_seed(20260728)
    image = torch.rand((4, 3, 32, 64), generator=generator, dtype=torch.float32)
    ramp = torch.linspace(-0.05, 1.15, 64, dtype=torch.float32)
    image[:, 0, 0, :] = ramp
    image[:, 1, 1, :] = torch.flip(ramp, dims=(0,))
    image[:, 2, 2, :] = torch.linspace(1.25, -0.1, 64)
    image[:, :, 3, :8] = torch.tensor(
        [
            [-0.05, -0.01, 0.0, 0.018, 0.18, 0.5, 1.0, 1.2],
            [1.2, 1.0, 0.5, 0.18, 0.018, 0.0, -0.01, -0.05],
            [0.0, 0.1, 0.2, 0.4, 0.8, 1.0, 1.1, 1.25],
        ],
        dtype=torch.float32,
    )
    return image


def _srgb_to_lab(value: torch.Tensor) -> np.ndarray:
    rgb = (
        value.detach()
        .to(device="cpu", dtype=torch.float64)
        .permute(0, 2, 3, 1)
        .numpy()
    )
    encoded = np.clip(rgb, 0, 1)
    linear = np.where(
        encoded <= 0.04045,
        encoded / 12.92,
        ((encoded + 0.055) / 1.055) ** 2.4,
    )
    matrix = np.asarray(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float64,
    )
    xyz = linear @ matrix.T
    xyz /= np.asarray([0.95047, 1.0, 1.08883], dtype=np.float64)
    epsilon = 216 / 24389
    kappa = 24389 / 27
    transformed = np.where(
        xyz > epsilon,
        np.cbrt(xyz),
        (kappa * xyz + 16) / 116,
    )
    return np.stack(
        (
            116 * transformed[..., 1] - 16,
            500 * (transformed[..., 0] - transformed[..., 1]),
            200 * (transformed[..., 1] - transformed[..., 2]),
        ),
        axis=-1,
    )


def _comparison(
    reference: torch.Tensor,
    candidate: torch.Tensor,
    *,
    reference_label: str,
    candidate_label: str,
    budget: RenderPrecisionBudget,
) -> PrecisionComparison:
    reference_cpu = reference.detach().to(device="cpu", dtype=torch.float32)
    candidate_cpu = candidate.detach().to(device="cpu", dtype=torch.float32)
    channel_error = (
        torch.abs(candidate_cpu - reference_cpu).reshape(-1).numpy()
    )
    perceptual_error = delta_e_2000(
        _srgb_to_lab(reference_cpu),
        _srgb_to_lab(candidate_cpu),
    ).reshape(-1)
    maximum_channel_error = float(np.max(channel_error))
    maximum_delta_e = float(np.max(perceptual_error))
    passed = (
        maximum_channel_error <= budget.maximum_normalized_channel_error
        and maximum_delta_e <= budget.maximum_delta_e_2000
    )
    return PrecisionComparison(
        reference=reference_label,
        candidate=candidate_label,
        reference_dtype=str(reference.dtype).removeprefix("torch."),
        candidate_dtype=str(candidate.dtype).removeprefix("torch."),
        reference_output_sha256=_tensor_sha256(reference_cpu),
        candidate_output_sha256=_tensor_sha256(candidate_cpu),
        maximum_normalized_channel_error=maximum_channel_error,
        p95_normalized_channel_error=float(np.percentile(channel_error, 95)),
        mean_normalized_channel_error=float(np.mean(channel_error)),
        maximum_delta_e_2000=maximum_delta_e,
        p95_delta_e_2000=float(np.percentile(perceptual_error, 95)),
        mean_delta_e_2000=float(np.mean(perceptual_error)),
        channel_error_budget=budget.maximum_normalized_channel_error,
        delta_e_2000_budget=budget.maximum_delta_e_2000,
        passed=passed,
    )


def run_precision_gate(
    output_path: str | Path,
    *,
    expected_runtime: AcceleratorRuntime,
    repeats: int = 3,
) -> PrecisionGateReport:
    if repeats < 2:
        raise ValueError("precision gate requires at least two accelerator repeats")
    accelerator = TorchComputeBackend(expected_runtime)
    cpu = TorchComputeBackend("cpu")
    timestamps = [0.125, 0.375, 0.625, 0.875]
    source = _stress_input()

    with tempfile.TemporaryDirectory(prefix="colorgraph-precision-") as directory:
        lut_path = Path(directory) / "stress.cube"
        lut_sha256 = _write_stress_lut(lut_path)
        graph = _build_stress_graph(lut_path)
        graph_sha256 = _canonical_sha256(_stable_graph_payload(graph))

        cpu_started = time.perf_counter()
        cpu_output, _ = GradeRenderEngine(cpu).render_output_batch(
            source,
            graph,
            timestamps=timestamps,
            mixed_precision=False,
        )
        cpu_elapsed_ms = (time.perf_counter() - cpu_started) * 1000

        if accelerator.info.runtime in {"cuda", "rocm"}:
            torch.cuda.reset_peak_memory_stats(accelerator.torch_device)
        accelerator_outputs: list[torch.Tensor] = []
        accelerator_elapsed_ms: list[float] = []
        for _ in range(repeats):
            accelerator.synchronize()
            started = time.perf_counter()
            output, _ = GradeRenderEngine(accelerator).render_output_batch(
                source,
                graph,
                timestamps=timestamps,
                mixed_precision=False,
            )
            accelerator.synchronize()
            accelerator_elapsed_ms.append((time.perf_counter() - started) * 1000)
            accelerator_outputs.append(output.detach().cpu())

        preview_source = source.to(dtype=torch.float16)
        preview_baseline, _ = GradeRenderEngine(accelerator).render_output_batch(
            preview_source,
            graph,
            timestamps=timestamps,
            mixed_precision=False,
        )
        preview_mixed, _ = GradeRenderEngine(accelerator).render_output_batch(
            preview_source,
            graph,
            timestamps=timestamps,
            mixed_precision=True,
        )
        accelerator.synchronize()

        master = _comparison(
            cpu_output,
            accelerator_outputs[0],
            reference_label="cpu_fp32",
            candidate_label=f"{expected_runtime}_fp32",
            budget=MASTER_PRECISION_BUDGET,
        )
        preview = _comparison(
            preview_baseline,
            preview_mixed,
            reference_label=f"{expected_runtime}_fp32_preview_baseline",
            candidate_label=f"{expected_runtime}_mixed_preview_request",
            budget=PREVIEW_PRECISION_BUDGET,
        )
        baseline = accelerator_outputs[0]
        drifts = [
            float(torch.max(torch.abs(candidate - baseline)).item())
            for candidate in accelerator_outputs[1:]
        ]
        maximum_drift = max(drifts, default=0.0)
        determinism = DeterminismComparison(
            repeats=repeats,
            output_sha256=[
                _tensor_sha256(output) for output in accelerator_outputs
            ],
            maximum_normalized_channel_drift=maximum_drift,
            drift_budget=MASTER_PRECISION_BUDGET.maximum_normalized_channel_error,
            passed=maximum_drift
            <= MASTER_PRECISION_BUDGET.maximum_normalized_channel_error,
        )
        peak_memory_mb = (
            round(
                torch.cuda.max_memory_allocated(accelerator.torch_device)
                / 1024**2
            )
            if accelerator.info.runtime in {"cuda", "rocm"}
            else 0
        )

    passed = master.passed and preview.passed and determinism.passed
    report = PrecisionGateReport(
        created_at=datetime.now(UTC),
        status="passed" if passed else "failed",
        expected_runtime=expected_runtime,
        hardware=accelerator.info,
        operating_system=platform.platform(),
        python_version=sys.version.split()[0],
        torch_version=torch.__version__,
        hip_version=torch.version.hip,
        cuda_version=torch.version.cuda,
        input_sha256=_tensor_sha256(source),
        graph_sha256=graph_sha256,
        lut_sha256=lut_sha256,
        sample_shape=list(source.shape),
        timestamps=timestamps,
        cpu_elapsed_ms=cpu_elapsed_ms,
        accelerator_elapsed_ms=accelerator_elapsed_ms,
        peak_accelerator_memory_mb=peak_memory_mb,
        master=master,
        preview=preview,
        determinism=determinism,
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
