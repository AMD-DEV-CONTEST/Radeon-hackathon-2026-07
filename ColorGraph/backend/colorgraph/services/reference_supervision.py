from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image, ImageDraw

from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import (
    GradeGraph,
    GradeNode,
    NodeType,
    ScopeLevel,
    SpatialScope,
    TemporalScope,
)
from colorgraph.grading.color import (
    bt709_oetf_to_linear,
    linear_to_bt709_oetf,
    soft_clip_highlights,
)
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.media.frames import extract_frame
from colorgraph.media.probe import probe_media

REFERENCE_NODE_ID = "tone_partial_reference"
REFERENCE_SUPERVISION_VERSION = "colorgraph.partial-reference/v2"

ProgressCallback = Callable[[str, int, int], None]

_PARAMETER_NAMES = (
    "exposure",
    "contrast",
    "saturation",
    "temperature",
    "tint",
    "highlights",
    "shadows",
    "midtones",
    "curve_highlights",
)
_PARAMETER_SCALES = (2.0, 1.3, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    source_time_seconds: float
    reference_time_seconds: float
    matches: int
    inliers: int
    valid_pixels: int


@dataclass(frozen=True, slots=True)
class PartialReferenceResult:
    graph: GradeGraph
    parameters: dict[str, float]
    fit_metrics: dict[str, float]
    alignments: list[AlignmentResult]
    comparison_path: str
    work_dir: str

    def response_payload(self) -> dict:
        return {
            "parameters": self.parameters,
            "fit_metrics": self.fit_metrics,
            "alignments": [asdict(item) for item in self.alignments],
            "comparison_path": self.comparison_path,
            "work_dir": self.work_dir,
        }


def _parameter_values(raw: torch.Tensor) -> torch.Tensor:
    scales = raw.new_tensor(_PARAMETER_SCALES)
    return torch.tanh(raw) * scales


def _apply_tone(
    image: torch.Tensor,
    values: torch.Tensor,
) -> torch.Tensor:
    exposure, contrast, saturation, temperature, tint, highlights, shadows, midtones, high = (
        values.unbind()
    )

    adjusted = image * torch.pow(image.new_tensor(2.0), exposure)
    gains = torch.stack(
        (
            1.0 + temperature * 0.12 + tint * 0.025,
            1.0 - torch.abs(temperature) * 0.015 - tint * 0.05,
            1.0 - temperature * 0.12 + tint * 0.025,
        )
    ).view(1, 3, 1, 1)
    adjusted = adjusted * gains

    pivot = adjusted.new_tensor(0.18)
    logarithmic = torch.log2(adjusted.clamp_min(1e-6))
    adjusted = torch.pow(
        adjusted.new_tensor(2.0),
        (logarithmic - torch.log2(pivot)) * (1.0 + contrast) + torch.log2(pivot),
    )

    luma_weights = adjusted.new_tensor([0.2126, 0.7152, 0.0722]).view(1, 3, 1, 1)
    luma = (adjusted * luma_weights).sum(dim=1, keepdim=True)
    adjusted = luma + (adjusted - luma) * (1.0 + saturation)

    luma = (adjusted * luma_weights).sum(dim=1, keepdim=True)
    highlight_mask = ((luma - 0.42) / 0.42).clamp(0, 1)
    highlight_mask = highlight_mask.square() * (3 - 2 * highlight_mask)
    adjusted = adjusted * (1.0 + highlight_mask * highlights * 0.45)

    luma = (adjusted * luma_weights).sum(dim=1, keepdim=True).clamp(0, 1)
    shadow_weight = (1 - luma / 0.5).clamp(0, 1).square()
    highlight_weight = ((luma - 0.5) / 0.5).clamp(0, 1).square()
    midtone_weight = (1 - torch.abs(luma - 0.5) * 2).clamp(0, 1).square()
    gain = (
        1
        + shadow_weight * shadows * 0.35
        + midtone_weight * midtones * 0.25
        + highlight_weight * high * 0.35
    )
    return adjusted * gain


def _rgb_tensor(rgb: np.ndarray, device: torch.device) -> torch.Tensor:
    array = np.ascontiguousarray(rgb, dtype=np.float32)
    return torch.from_numpy(array).to(device).T.reshape(1, 3, 1, -1)


def _gamma_luma(image: torch.Tensor) -> torch.Tensor:
    weights = image.new_tensor([0.2126, 0.7152, 0.0722]).view(1, 3, 1, 1)
    return (image * weights).sum(dim=1, keepdim=True)


def _fit_tone_parameters_linear(
    source_linear_rgb: np.ndarray,
    target_signal_rgb: np.ndarray,
    *,
    device: torch.device,
    optimization_steps: int,
) -> tuple[dict[str, float], dict[str, float]]:
    if source_linear_rgb.shape != target_signal_rgb.shape or source_linear_rgb.ndim != 2:
        raise ValueError("source and target samples must be matching Nx3 arrays")
    if source_linear_rgb.shape[1] != 3 or source_linear_rgb.shape[0] < 128:
        raise ValueError("at least 128 paired RGB samples are required")
    if optimization_steps < 1:
        raise ValueError("optimization_steps must be positive")

    source_linear = _rgb_tensor(source_linear_rgb, device)
    target_signal = _rgb_tensor(np.clip(target_signal_rgb, 0, 1), device)
    baseline_signal = linear_to_bt709_oetf(soft_clip_highlights(source_linear)).clamp(0, 1)
    raw = torch.nn.Parameter(torch.zeros(len(_PARAMETER_NAMES), device=device))
    with torch.no_grad():
        source_median = torch.median(_gamma_luma(baseline_signal)).clamp_min(1e-4)
        target_median = torch.median(_gamma_luma(target_signal)).clamp_min(1e-4)
        initial_exposure = torch.log2(target_median / source_median).clamp(-1.8, 1.8)
        raw[0] = torch.atanh((initial_exposure / _PARAMETER_SCALES[0]).clamp(-0.95, 0.95))

    optimizer = torch.optim.Adam([raw], lr=0.045)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=optimization_steps,
        eta_min=0.004,
    )
    best_loss = float("inf")
    best_raw = raw.detach().clone()

    for _ in range(optimization_steps):
        optimizer.zero_grad(set_to_none=True)
        values = _parameter_values(raw)
        prediction = linear_to_bt709_oetf(
            soft_clip_highlights(_apply_tone(source_linear, values))
        ).clamp(0, 1)
        rgb_loss = functional.smooth_l1_loss(prediction, target_signal, beta=0.02)
        luma_loss = functional.smooth_l1_loss(
            _gamma_luma(prediction),
            _gamma_luma(target_signal),
            beta=0.015,
        )
        regularization = (values / values.new_tensor(_PARAMETER_SCALES)).square().mean()
        loss = rgb_loss + luma_loss * 0.35 + regularization * 0.00035
        loss.backward()
        optimizer.step()
        scheduler.step()
        loss_value = float(loss.detach())
        if loss_value < best_loss:
            best_loss = loss_value
            best_raw = raw.detach().clone()

    with torch.no_grad():
        values = _parameter_values(best_raw)
        prediction = linear_to_bt709_oetf(
            soft_clip_highlights(_apply_tone(source_linear, values))
        ).clamp(0, 1)
        before_rgb = torch.mean(torch.abs(baseline_signal - target_signal))
        after_rgb = torch.mean(torch.abs(prediction - target_signal))
        before_luma = torch.mean(
            torch.abs(_gamma_luma(baseline_signal) - _gamma_luma(target_signal))
        )
        after_luma = torch.mean(torch.abs(_gamma_luma(prediction) - _gamma_luma(target_signal)))

    parameters = {
        name: round(float(value), 6) for name, value in zip(_PARAMETER_NAMES, values, strict=True)
    }
    metrics = {
        "rgb_mae_before": round(float(before_rgb), 6),
        "rgb_mae_after": round(float(after_rgb), 6),
        "luma_mae_before": round(float(before_luma), 6),
        "luma_mae_after": round(float(after_luma), 6),
    }
    return parameters, metrics


def fit_tone_parameters(
    source_rgb: np.ndarray,
    target_rgb: np.ndarray,
    *,
    device: torch.device,
    optimization_steps: int = 500,
) -> tuple[dict[str, float], dict[str, float]]:
    """Fit global tone controls to paired BT.709 signal samples.

    This compatibility entry point accepts an already encoded baseline. The
    partial-video workflow uses pre-node working-linear samples directly.
    """
    source_signal = _rgb_tensor(np.clip(source_rgb, 0, 1), device)
    with torch.inference_mode():
        source_linear = (
            bt709_oetf_to_linear(source_signal).reshape(3, -1).T.contiguous().cpu().numpy()
        )
    return _fit_tone_parameters_linear(
        source_linear,
        target_rgb,
        device=device,
        optimization_steps=optimization_steps,
    )


def _load_rgb(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"could not read extracted frame: {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _load_source_tensor(path: Path) -> torch.Tensor:
    image = Image.open(path).convert("RGB")
    array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)


def _tensor_hwc(tensor: torch.Tensor) -> np.ndarray:
    return tensor[0].permute(1, 2, 0).detach().cpu().numpy()


def _save_signal_frame(signal_rgb: np.ndarray, destination: Path) -> None:
    output = np.clip(signal_rgb * 255.0, 0, 255).round().astype(np.uint8)
    Image.fromarray(output, mode="RGB").save(destination)


def _align_frame(
    source_rgb: np.ndarray,
    target_rgb: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int]:
    source_gray = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2GRAY)
    target_gray = cv2.cvtColor(target_rgb, cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.018)
    source_keypoints, source_descriptors = sift.detectAndCompute(source_gray, None)
    target_keypoints, target_descriptors = sift.detectAndCompute(target_gray, None)
    if source_descriptors is None or target_descriptors is None:
        raise RuntimeError("SIFT could not find features in one of the paired frames")

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    candidates = matcher.knnMatch(source_descriptors, target_descriptors, k=2)
    matches = [first for first, second in candidates if first.distance < second.distance * 0.73]
    if len(matches) < 16:
        raise RuntimeError(f"insufficient SIFT correspondences: {len(matches)}")

    source_points = np.float32([source_keypoints[match.queryIdx].pt for match in matches]).reshape(
        -1, 1, 2
    )
    target_points = np.float32([target_keypoints[match.trainIdx].pt for match in matches]).reshape(
        -1, 1, 2
    )
    homography, inlier_mask = cv2.findHomography(
        source_points,
        target_points,
        cv2.RANSAC,
        4.0,
    )
    if homography is None or inlier_mask is None:
        raise RuntimeError("SIFT correspondences did not produce a homography")
    inliers = int(inlier_mask.sum())
    if inliers < 12:
        raise RuntimeError(f"homography is unreliable: only {inliers} inliers")

    height, width = target_rgb.shape[:2]
    aligned = cv2.warpPerspective(
        source_rgb,
        homography,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    valid = cv2.warpPerspective(
        np.full(source_rgb.shape[:2], 255, dtype=np.uint8),
        homography,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
    )
    valid = cv2.erode(valid, np.ones((15, 15), dtype=np.uint8), iterations=1) > 250

    # The low-pass comparison intentionally cannot learn H.264 ringing, noise,
    # sharpening halos, or fine texture from a heavily compressed web reference.
    aligned_low = cv2.GaussianBlur(aligned, (0, 0), sigmaX=4.0, sigmaY=4.0)
    target_low = cv2.GaussianBlur(target_rgb, (0, 0), sigmaX=4.0, sigmaY=4.0)
    return aligned, aligned_low, target_low, valid, homography, len(matches), inliers


def _apply_parameters_to_working_image(
    working_linear_rgb: np.ndarray,
    parameters: dict[str, float],
) -> np.ndarray:
    tensor = torch.from_numpy(working_linear_rgb.astype(np.float32)).permute(2, 0, 1).unsqueeze(0)
    values = tensor.new_tensor([parameters[name] for name in _PARAMETER_NAMES])
    with torch.inference_mode():
        output = linear_to_bt709_oetf(soft_clip_highlights(_apply_tone(tensor, values))).clamp(0, 1)
    return (
        output.reshape(3, working_linear_rgb.shape[0], working_linear_rgb.shape[1])
        .permute(1, 2, 0)
        .mul(255)
        .round()
        .byte()
        .numpy()
    )


def _save_comparison(
    pairs: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    parameters: dict[str, float],
    destination: Path,
) -> None:
    rows: list[Image.Image] = []
    labels = ("BASELINE", "PARTIAL MATCH", "WEB REFERENCE")
    for baseline, working_linear, reference in pairs:
        matched = _apply_parameters_to_working_image(working_linear, parameters)
        panels: list[Image.Image] = []
        for label, array in zip(labels, (baseline, matched, reference), strict=True):
            panel = Image.fromarray(array, mode="RGB")
            panel.thumbnail((480, 270), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (480, 296), "black")
            canvas.paste(panel, ((480 - panel.width) // 2, 26))
            ImageDraw.Draw(canvas).text((10, 7), label, fill="white")
            panels.append(canvas)
        row = Image.new("RGB", (1440, 296), "black")
        for index, panel in enumerate(panels):
            row.paste(panel, (index * 480, 0))
        rows.append(row)
    sheet = Image.new("RGB", (1440, 296 * len(rows)), "black")
    for index, row in enumerate(rows):
        sheet.paste(row, (0, index * 296))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=92, subsampling=0)


def _without_reference_node(graph: GradeGraph, node_id: str) -> GradeGraph:
    payload = graph.model_dump(mode="python")
    reference_node_ids = {node_id, REFERENCE_NODE_ID, "tone_website_reference"}
    payload["nodes"] = [node for node in payload["nodes"] if node["id"] not in reference_node_ids]
    return GradeGraph.model_validate(payload)


def apply_partial_reference_node(
    graph: GradeGraph,
    *,
    node_id: str,
    parameters: dict[str, float],
    supervision_metadata: dict,
) -> GradeGraph:
    payload = _without_reference_node(graph, node_id).model_dump(mode="python")
    nodes = payload["nodes"]
    output_nodes = [node for node in nodes if node["type"] == NodeType.OUTPUT_TRANSFORM]
    if len(output_nodes) != 1:
        raise ValueError("partial reference supervision requires one output transform")
    output_node = output_nodes[0]
    output_order = int(output_node["order"])
    last_creative_order = max(
        (int(node["order"]) for node in nodes if node["type"] != NodeType.OUTPUT_TRANSFORM),
        default=0,
    )
    preferred_order = 150
    order = (
        preferred_order
        if last_creative_order < preferred_order < output_order
        else last_creative_order + 10
    )
    if order >= output_order:
        output_node["order"] = order + 10

    reference_node = GradeNode(
        id=node_id,
        type=NodeType.TONE,
        label="Partial video reference match",
        order=order,
        temporal_scope=TemporalScope(
            level=ScopeLevel.PROJECT,
            project_id=graph.project_id,
        ),
        spatial_scope=SpatialScope(),
        parameters=parameters,
        metadata=supervision_metadata,
    )
    nodes.append(reference_node.model_dump(mode="python"))
    payload["nodes"] = sorted(nodes, key=lambda node: int(node["order"]))
    metadata = dict(payload["metadata"])
    metadata["partial_reference_supervision"] = supervision_metadata
    payload["metadata"] = metadata
    payload["updated_at"] = datetime.now(UTC)
    return GradeGraph.model_validate(payload)


def fit_partial_video_reference(
    *,
    source: str | Path,
    reference: str | Path,
    graph: GradeGraph,
    work_dir: str | Path,
    source_start_seconds: float,
    source_end_seconds: float,
    reference_start_seconds: float,
    reference_end_seconds: float,
    backend: ComputeBackend,
    sample_count: int = 5,
    fit_samples: int = 300_000,
    optimization_steps: int = 500,
    maximum_width: int = 1280,
    node_id: str = REFERENCE_NODE_ID,
    progress: ProgressCallback | None = None,
) -> PartialReferenceResult:
    source_path = Path(source).resolve()
    reference_path = Path(reference).resolve()
    destination = Path(work_dir).resolve()
    if not source_path.is_file() or not reference_path.is_file():
        raise FileNotFoundError("source and reference videos must both exist")
    if source_end_seconds <= source_start_seconds:
        raise ValueError("source range end must be greater than its start")
    if reference_end_seconds <= reference_start_seconds:
        raise ValueError("reference range end must be greater than its start")
    if sample_count < 3:
        raise ValueError("at least three supervision frames are required")
    if fit_samples < 128:
        raise ValueError("fit_samples must be at least 128")

    reference_media = probe_media(reference_path)
    if source_end_seconds > graph.media.duration_seconds + 1e-3:
        raise ValueError("source supervision range exceeds source duration")
    if reference_end_seconds > reference_media.duration_seconds + 1e-3:
        raise ValueError("reference supervision range exceeds reference duration")

    destination.mkdir(parents=True, exist_ok=True)
    baseline_graph = _without_reference_node(graph, node_id)
    engine = GradeRenderEngine(backend)
    positions = np.linspace(0.1, 0.9, sample_count, dtype=np.float64)
    rng = np.random.default_rng(20260728)
    samples_per_frame = max(128, int(np.ceil(fit_samples / sample_count)))
    source_samples: list[np.ndarray] = []
    target_samples: list[np.ndarray] = []
    comparisons: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    alignments: list[AlignmentResult] = []

    for index, position in enumerate(positions, start=1):
        source_time = source_start_seconds + (source_end_seconds - source_start_seconds) * float(
            position
        )
        reference_time = reference_start_seconds + (
            reference_end_seconds - reference_start_seconds
        ) * float(position)
        source_frame = destination / f"source-{index:02d}.png"
        baseline_frame = destination / f"baseline-{index:02d}.png"
        reference_frame = destination / f"reference-{index:02d}.png"
        extract_frame(
            source_path,
            source_time,
            source_frame,
            maximum_width=maximum_width,
        )
        extract_frame(
            reference_path,
            reference_time,
            reference_frame,
            maximum_width=maximum_width,
        )
        source_tensor = _load_source_tensor(source_frame)
        baseline_output, _ = engine.render_output_batch(
            source_tensor,
            baseline_graph,
            timestamps=[source_time],
            mixed_precision=False,
        )
        working_output, _ = engine.render_working_batch(
            source_tensor,
            baseline_graph,
            timestamps=[source_time],
            mixed_precision=False,
        )
        baseline_signal = _tensor_hwc(baseline_output)
        working_linear = _tensor_hwc(working_output)
        _save_signal_frame(baseline_signal, baseline_frame)
        baseline_rgb = np.clip(baseline_signal * 255.0, 0, 255).round().astype(np.uint8)
        reference_rgb = _load_rgb(reference_frame)
        aligned, _, target_low, valid, homography, matches, inliers = _align_frame(
            baseline_rgb,
            reference_rgb,
        )
        height, width = reference_rgb.shape[:2]
        aligned_working = cv2.warpPerspective(
            working_linear,
            homography,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        aligned_working_low = cv2.GaussianBlur(
            aligned_working,
            (0, 0),
            sigmaX=4.0,
            sigmaY=4.0,
        )

        valid_indices = np.flatnonzero(valid)
        if len(valid_indices) < 128:
            raise RuntimeError("homography has too little overlapping image area")
        chosen = rng.choice(
            valid_indices,
            size=min(samples_per_frame, len(valid_indices)),
            replace=False,
        )
        source_samples.append(aligned_working_low.reshape(-1, 3)[chosen].astype(np.float32))
        target_samples.append(target_low.reshape(-1, 3)[chosen].astype(np.float32) / 255.0)
        comparisons.append((aligned, aligned_working, reference_rgb))
        alignments.append(
            AlignmentResult(
                source_time_seconds=round(source_time, 6),
                reference_time_seconds=round(reference_time, 6),
                matches=matches,
                inliers=inliers,
                valid_pixels=len(valid_indices),
            )
        )
        if progress is not None:
            progress("align", index, sample_count)

    paired_source = np.concatenate(source_samples, axis=0)
    paired_target = np.concatenate(target_samples, axis=0)
    if len(paired_source) > fit_samples:
        selected = rng.choice(len(paired_source), size=fit_samples, replace=False)
        paired_source = paired_source[selected]
        paired_target = paired_target[selected]
    if progress is not None:
        progress("optimize", 0, optimization_steps)
    parameters, fit_metrics = _fit_tone_parameters_linear(
        paired_source,
        paired_target,
        device=backend.torch_device,
        optimization_steps=optimization_steps,
    )
    if progress is not None:
        progress("optimize", optimization_steps, optimization_steps)

    comparison_path = destination / "partial-reference-comparison.jpg"
    _save_comparison(comparisons, parameters, comparison_path)
    speed = (source_end_seconds - source_start_seconds) / (
        reference_end_seconds - reference_start_seconds
    )
    supervision_metadata = {
        "version": REFERENCE_SUPERVISION_VERSION,
        "source": "compressed_video_partial_reference",
        "reference_file": str(reference_path),
        "reference_range_seconds": [
            round(reference_start_seconds, 6),
            round(reference_end_seconds, 6),
        ],
        "source_range_seconds": [
            round(source_start_seconds, 6),
            round(source_end_seconds, 6),
        ],
        "source_playback_speed": round(speed, 6),
        "sample_count": sample_count,
        "fit_samples": len(paired_source),
        "alignment_method": "SIFT homography per sampled frame",
        "fit_domain": (
            "pre-node linear_rec709 through the exact tone node and BT.709 output transform"
        ),
        "alignment_matches": [item.matches for item in alignments],
        "alignment_inliers": [item.inliers for item in alignments],
        "reference_encoding": (
            f"{reference_media.width}x{reference_media.height} "
            f"{reference_media.codec} {reference_media.pixel_format or 'unknown'}"
        ),
        "usage_policy": (
            "global low-frequency tone and color only; geometry is aligned per frame; "
            "compression texture, ringing, sharpening, noise, and banding are excluded"
        ),
        "fit_metrics": fit_metrics,
        "comparison_path": str(comparison_path),
    }
    updated_graph = apply_partial_reference_node(
        graph,
        node_id=node_id,
        parameters=parameters,
        supervision_metadata=supervision_metadata,
    )
    return PartialReferenceResult(
        graph=updated_graph,
        parameters=parameters,
        fit_metrics=fit_metrics,
        alignments=alignments,
        comparison_path=str(comparison_path),
        work_dir=str(destination),
    )
