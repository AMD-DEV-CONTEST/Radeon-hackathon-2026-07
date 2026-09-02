from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from colorgraph.agent import LocalSceneAnalyzer
from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import (
    LEGACY_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    NodeType,
)
from colorgraph.grading.color import convert_color_space
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.looks import (
    LOOK_PARAMETER_KEYS,
    LOOK_RECIPE_VERSION,
    LOOK_RECIPES,
    active_look_node,
    graph_digest,
    graph_with_look_recipe,
    look_parameters,
)
from colorgraph.grading.masks import GraphMaskResolver
from colorgraph.grading.precision import PREVIEW_PRECISION_BUDGET
from colorgraph.media.frames import extract_frame

CANDIDATE_RANKING_VERSION = "colorgraph.candidate-ranking/v2"
DEFAULT_CANDIDATE_SAMPLE_LIMIT = 7
PARETO_OBJECTIVE_ORDER = (
    "intent_alignment",
    "prompt_rule_match",
    "aesthetic_proxy",
    "conservatism",
    "technical_margin",
)


class HardFailureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    sample_index: int
    frame_index: int
    time_seconds: float
    observed: float
    threshold: float
    requirement: str
    detail: str


class CandidateSampleEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_index: int
    frame_index: int
    time_seconds: float
    reasons: list[str]
    filename: str
    intent_score: float = Field(ge=0, le=1)
    metrics: dict[str, float]
    hard_failure_ids: list[str]


class LookCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str
    recipe_version: str
    label: str
    parameters: dict[str, float]
    filename: str
    intent_score: float = Field(ge=0, le=1)
    semantic_prior: float = Field(ge=0, le=1)
    technical_score: float = Field(ge=0, le=100)
    # Retained for API compatibility. Ranking v2 never selects on this field;
    # it mirrors the technical score instead of combining independent goals.
    combined_score: float = Field(ge=0, le=100)
    aesthetic_score: float = Field(ge=0, le=1)
    conservatism_score: float = Field(ge=0, le=1)
    objective_values: dict[str, float]
    hard_checks_passed: bool
    hard_failures: list[HardFailureEvidence] = Field(default_factory=list)
    pareto_rank: int | None = Field(default=None, ge=0)
    pareto_front: bool = False
    dominated_by: list[str] = Field(default_factory=list)
    # Retained for API compatibility; in v2 this is the number of eligible
    # candidates Pareto-dominated by this candidate.
    pairwise_wins: int = Field(default=0, ge=0)
    metrics: dict[str, float]
    sample_evidence: list[CandidateSampleEvidence]


class CandidateSelectionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str
    selected: bool
    hard_checks_passed: bool
    pareto_rank: int | None = Field(default=None, ge=0)
    dominated_by: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)


class CandidateComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_seconds: float
    prompt: str
    canonical_intent: str
    graph_digest: str
    recipe_version: str
    ranking_version: str = CANDIDATE_RANKING_VERSION
    recommended_id: str
    recommendation_status: str
    candidates: list[LookCandidate]
    sample_frame_indices: list[int]
    sample_timestamps: list[float]
    pareto_recipe_ids: list[str]
    selection_evidence: list[CandidateSelectionEvidence]
    comparison_method: str = "multi-frame hard gates + Pareto objectives/v2"
    device_runtime: str


@dataclass(frozen=True, slots=True)
class CandidateSamplePoint:
    frame_index: int
    time_seconds: float
    reasons: tuple[str, ...]


@dataclass(slots=True)
class _RenderedCandidate:
    recipe_id: str
    output_paths: list[Path]
    frame_metrics: list[dict[str, float]]
    hard_failures: list[HardFailureEvidence]
    technical_score: float
    aesthetic_score: float
    conservatism_score: float
    semantic_prior: float


_HARD_LIMITS = (
    (
        "highlight_clipping",
        "highlight_ratio",
        "maximum",
        0.06,
        "display pixels at or above 98.8% code value",
    ),
    (
        "shadow_clipping",
        "shadow_ratio",
        "maximum",
        0.20,
        "display pixels at or below 2% code value",
    ),
    (
        "oversaturation",
        "oversaturation_ratio",
        "maximum",
        0.12,
        "display pixels at or above HSV saturation 245/255",
    ),
    (
        "output_gamut",
        "gamut_outside_ratio",
        "maximum",
        0.01,
        "unclamped output channels outside the declared 0..1 signal range",
    ),
    (
        "structure_preservation",
        "structure_loss",
        "maximum",
        0.35,
        "Sobel edge-energy loss relative to the source frame",
    ),
    (
        "mask_completeness",
        "mask_completeness",
        "minimum",
        1.0,
        "all referenced masks decode at the sampled frame",
    ),
    (
        "finite_output",
        "nonfinite_ratio",
        "maximum",
        0.0,
        "rendered output must not contain NaN or infinity",
    ),
)


def _canonical_intent(prompt: str) -> str:
    normalized = prompt.lower()
    if any(
        word in normalized
        for word in ("清冷", "冷系", "纪录片", "cool", "documentary")
    ):
        return "a cool restrained documentary landscape with natural vegetation"
    if any(
        word in normalized
        for word in ("日落", "暖色", "温暖", "sunset", "warm")
    ):
        return "a warm cinematic sunset landscape with protected highlights"
    if any(
        word in normalized
        for word in ("雾", "柔和", "fog", "mist", "soft")
    ):
        return "a soft desaturated foggy cinematic landscape with depth"
    return "a natural clean travel landscape with detailed sky and vegetation"


def _preferred_recipe(prompt: str) -> str | None:
    normalized = prompt.lower()
    if any(
        word in normalized
        for word in ("清冷", "冷系", "纪录片", "cool", "documentary")
    ):
        return "cool"
    if any(
        word in normalized
        for word in ("日落", "暖色", "温暖", "sunset", "warm")
    ):
        return "warm"
    if any(
        word in normalized
        for word in ("雾", "柔和", "fog", "mist", "soft")
    ):
        return "foggy"
    if any(
        word in normalized
        for word in ("自然", "旅行", "通透", "natural", "travel")
    ):
        return "natural"
    return None


def _frame_index(graph: GradeGraph, timestamp: float) -> int:
    declared_last = max(0, graph.media.frame_count - 1)
    return min(
        max(0, round(max(0.0, timestamp) * graph.media.fps)),
        declared_last,
    )


def _candidate_sample_plan(
    graph: GradeGraph,
    time_seconds: float,
    *,
    maximum_samples: int = DEFAULT_CANDIDATE_SAMPLE_LIMIT,
) -> list[CandidateSamplePoint]:
    if maximum_samples < 1:
        raise ValueError("maximum_samples must be positive")
    timestamp = min(max(0.0, time_seconds), graph.media.duration_seconds)
    target_frame = _frame_index(graph, timestamp)
    active_shot = next(
        (
            shot
            for shot in graph.shots
            if (
                shot.time_range.start_seconds
                <= timestamp
                < shot.time_range.end_seconds
            )
        ),
        graph.shots[-1] if graph.shots else None,
    )
    active_scene_id = active_shot.scene_id if active_shot is not None else None
    scene_shots = [
        shot
        for shot in graph.shots
        if active_scene_id is None or shot.scene_id == active_scene_id
    ]
    reasons_by_frame: dict[int, set[str]] = {}

    def add(candidate_time: float, reason: str) -> None:
        frame_index = _frame_index(graph, candidate_time)
        reasons_by_frame.setdefault(frame_index, set()).add(reason)

    add(timestamp, "requested_time")
    for shot in scene_shots:
        start = shot.time_range.start_seconds
        duration = shot.time_range.end_seconds - start
        add(start + duration * 0.25, f"{shot.id}:quarter")
        add(start + duration * 0.50, f"{shot.id}:midpoint")
        add(start + duration * 0.75, f"{shot.id}:three_quarter")
        for change_point in shot.lighting_change_points:
            if start <= change_point < shot.time_range.end_seconds:
                add(change_point, f"{shot.id}:lighting_change")

    for node in graph.nodes:
        if not node.enabled:
            continue
        node_scene_id = node.temporal_scope.scene_id
        if (
            active_scene_id is not None
            and node_scene_id is not None
            and node_scene_id != active_scene_id
        ):
            continue
        for track in node.tracks:
            for keyframe in track.keyframes:
                if not scene_shots or any(
                    shot.time_range.start_seconds
                    <= keyframe.time_seconds
                    < shot.time_range.end_seconds
                    for shot in scene_shots
                ):
                    add(
                        keyframe.time_seconds,
                        f"{node.id}:{track.parameter}:keyframe",
                    )

    if not reasons_by_frame:
        reasons_by_frame[target_frame] = {"requested_time"}
    ordered_frames = sorted(reasons_by_frame)
    if len(ordered_frames) > maximum_samples:
        if maximum_samples == 1:
            selected_positions = {
                min(
                    range(len(ordered_frames)),
                    key=lambda index: (
                        abs(ordered_frames[index] - target_frame),
                        ordered_frames[index],
                    ),
                )
            }
        else:
            selected_positions = {
                round(index * (len(ordered_frames) - 1) / (maximum_samples - 1))
                for index in range(maximum_samples)
            }
            target_position = ordered_frames.index(target_frame)
            if target_position not in selected_positions:
                replaceable = sorted(
                    selected_positions,
                    key=lambda position: (
                        abs(ordered_frames[position] - target_frame),
                        position in {0, len(ordered_frames) - 1},
                    ),
                )
                selected_positions.remove(replaceable[0])
                selected_positions.add(target_position)
        ordered_frames = [
            ordered_frames[position]
            for position in sorted(selected_positions)
        ]

    return [
        CandidateSamplePoint(
            frame_index=frame_index,
            time_seconds=round(frame_index / graph.media.fps, 6),
            reasons=tuple(sorted(reasons_by_frame[frame_index])),
        )
        for frame_index in ordered_frames
    ]


def _edge_energy(rgb: np.ndarray) -> float:
    luma = (
        rgb[..., 0] * 0.2126
        + rgb[..., 1] * 0.7152
        + rgb[..., 2] * 0.0722
    ).astype(np.float32)
    horizontal = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)
    vertical = cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(np.sqrt(horizontal * horizontal + vertical * vertical)))


def _frame_quality_metrics(
    source_rgb: np.ndarray,
    display_rgb: np.ndarray,
    unclamped_output: np.ndarray,
    *,
    mask_completeness: float,
) -> dict[str, float]:
    display = np.asarray(display_rgb, dtype=np.float32)
    raw = np.asarray(unclamped_output, dtype=np.float32)
    finite = np.isfinite(raw)
    nonfinite_ratio = float(1.0 - finite.mean())
    safe_raw = np.where(finite, raw, 0.0)
    maximum = display.max(axis=2)
    minimum = display.min(axis=2)
    encoded = np.round(display.clip(0, 1) * 255).astype(np.uint8)
    hsv = cv2.cvtColor(encoded, cv2.COLOR_RGB2HSV).astype(np.float32)
    highlight_ratio = float(np.mean(maximum >= 0.988))
    shadow_ratio = float(np.mean(maximum <= 0.02))
    oversaturation_ratio = float(np.mean(hsv[:, :, 1] >= 245))
    channel_clip_ratio = float(
        np.mean((maximum >= 254 / 255) | (minimum <= 1 / 255))
    )
    gamut_outside_ratio = float(
        np.mean((safe_raw < -1e-5) | (safe_raw > 1.00001))
    )
    source_edge = _edge_energy(np.asarray(source_rgb, dtype=np.float32))
    output_edge = _edge_energy(display)
    structure_ratio = output_edge / max(source_edge, 1e-6)
    structure_loss = max(0.0, 1.0 - structure_ratio)
    luma = (
        display[..., 0] * 0.2126
        + display[..., 1] * 0.7152
        + display[..., 2] * 0.0722
    ).clip(0, 1)
    histogram = np.histogram(luma, bins=64, range=(0, 1))[0].astype(np.float64)
    probabilities = histogram / max(float(histogram.sum()), 1.0)
    probabilities = probabilities[probabilities > 0]
    normalized_entropy = float(
        -np.sum(probabilities * np.log2(probabilities)) / np.log2(64)
    )
    mean_saturation = float(np.mean(hsv[:, :, 1] / 255.0))
    contrast_proxy = float(np.clip(np.std(luma) / 0.18, 0, 1))
    exposure_balance = float(
        1.0 - min(abs(float(np.mean(luma)) - 0.45) / 0.45, 1.0)
    )
    saturation_balance = float(
        1.0 - min(abs(mean_saturation - 0.28) / 0.5, 1.0)
    )
    aesthetic_proxy = float(
        np.mean(
            [
                normalized_entropy,
                contrast_proxy,
                exposure_balance,
                saturation_balance,
                max(0.0, 1.0 - structure_loss),
            ]
        )
    )
    penalty = (
        min(highlight_ratio / 0.06, 1.5) * 20
        + min(shadow_ratio / 0.20, 1.5) * 15
        + min(oversaturation_ratio / 0.12, 1.5) * 18
        + min(channel_clip_ratio / 0.18, 1.5) * 8
        + min(gamut_outside_ratio / 0.01, 1.5) * 18
        + min(structure_loss / 0.35, 1.5) * 14
        + (1.0 - mask_completeness) * 40
        + min(nonfinite_ratio * 1_000, 1.0) * 100
    )
    return {
        "highlight_ratio": highlight_ratio,
        "shadow_ratio": shadow_ratio,
        "oversaturation_ratio": oversaturation_ratio,
        "channel_clip_ratio": channel_clip_ratio,
        "gamut_outside_ratio": gamut_outside_ratio,
        "structure_ratio": float(structure_ratio),
        "structure_loss": float(structure_loss),
        "mask_completeness": float(mask_completeness),
        "nonfinite_ratio": nonfinite_ratio,
        "mean_luma": float(np.mean(luma)),
        "mean_saturation": mean_saturation,
        "normalized_entropy": normalized_entropy,
        "aesthetic_proxy": aesthetic_proxy,
        "technical_score": float(np.clip(100.0 - penalty, 0, 100)),
    }


def _hard_failures(
    metrics: Mapping[str, float],
    sample: CandidateSamplePoint,
    sample_index: int,
) -> list[HardFailureEvidence]:
    failures: list[HardFailureEvidence] = []
    for check_id, key, requirement, threshold, detail in _HARD_LIMITS:
        observed = float(metrics[key])
        failed = (
            observed > threshold + 1e-12
            if requirement == "maximum"
            else observed < threshold - 1e-12
        )
        if failed:
            failures.append(
                HardFailureEvidence(
                    check_id=check_id,
                    sample_index=sample_index,
                    frame_index=sample.frame_index,
                    time_seconds=sample.time_seconds,
                    observed=observed,
                    threshold=threshold,
                    requirement=requirement,
                    detail=detail,
                )
            )
    return failures


def _conservatism_score(
    graph: GradeGraph,
    recipe_id: str,
    timestamp: float,
) -> float:
    active = active_look_node(graph, timestamp)
    if active is None:
        return 0.0
    scales = {
        "strength": 1.0,
        "contrast": 0.5,
        "saturation": 0.5,
        "temperature": 0.5,
        "highlights": 0.5,
    }
    recipe = look_parameters(recipe_id)
    normalized_changes = [
        min(
            abs(float(active.parameters.get(key, recipe[key])) - recipe[key])
            / scales[key],
            1.0,
        )
        for key in LOOK_PARAMETER_KEYS
    ]
    return float(np.clip(1.0 - np.mean(normalized_changes), 0, 1))


def _dominates(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> bool:
    keys = tuple(sorted(left))
    if tuple(sorted(right)) != keys:
        raise ValueError("Pareto candidates must expose the same objectives")
    not_worse = all(left[key] >= right[key] - 1e-12 for key in keys)
    strictly_better = any(left[key] > right[key] + 1e-12 for key in keys)
    return not_worse and strictly_better


def pareto_fronts(
    objectives: Mapping[str, Mapping[str, float]],
) -> list[list[str]]:
    """Return deterministic non-dominated fronts for maximize-only objectives."""

    if not objectives:
        return []
    objective_keys: tuple[str, ...] | None = None
    for candidate_id, values in objectives.items():
        keys = tuple(sorted(values))
        if not keys:
            raise ValueError(f"candidate {candidate_id!r} has no Pareto objectives")
        if objective_keys is None:
            objective_keys = keys
        elif keys != objective_keys:
            raise ValueError("Pareto candidates must expose the same objectives")
        if not all(np.isfinite(float(value)) for value in values.values()):
            raise ValueError(f"candidate {candidate_id!r} has non-finite objective values")

    remaining = set(objectives)
    fronts: list[list[str]] = []
    while remaining:
        front = sorted(
            candidate_id
            for candidate_id in remaining
            if not any(
                _dominates(objectives[other], objectives[candidate_id])
                for other in remaining
                if other != candidate_id
            )
        )
        if not front:  # pragma: no cover - finite partial order invariant
            raise RuntimeError("Pareto frontier construction made no progress")
        fronts.append(front)
        remaining.difference_update(front)
    return fronts


def _display_output(
    output: torch.Tensor,
    graph: GradeGraph,
) -> torch.Tensor:
    if graph.renderer_version == LEGACY_RENDERER_VERSION:
        return output.clamp(0, 1)
    output_node = next(
        node
        for node in graph.ordered_nodes()
        if node.type == NodeType.OUTPUT_TRANSFORM
    )
    destination_log_profile = output_node.parameters.get(
        "destination_log_profile"
    )
    return convert_color_space(
        output,
        graph.output_color_space,
        ColorSpace.SRGB,
        source_log_profile=(
            destination_log_profile
            if isinstance(destination_log_profile, str)
            else None
        ),
    ).clamp(0, 1)


def _load_source_batch(paths: list[Path]) -> tuple[torch.Tensor, list[np.ndarray]]:
    arrays: list[np.ndarray] = []
    for path in paths:
        with Image.open(path) as image:
            arrays.append(
                np.array(image.convert("RGB"), dtype=np.float32, copy=True)
                / 255.0
            )
    tensor = torch.stack(
        [
            torch.from_numpy(array).permute(2, 0, 1)
            for array in arrays
        ]
    )
    return tensor, arrays


def _save_candidate_frames(
    display: torch.Tensor,
    *,
    previews_dir: Path,
    recipe_id: str,
    samples: list[CandidateSamplePoint],
    cache_token: str,
) -> list[Path]:
    paths: list[Path] = []
    for sample_index, sample in enumerate(samples):
        path = (
            previews_dir
            / (
                f"candidate-{recipe_id}-{sample.frame_index:08d}-"
                f"{cache_token}.jpg"
            )
        )
        encoded = (
            display[sample_index]
            .permute(1, 2, 0)
            .mul(255)
            .round()
            .byte()
            .cpu()
            .numpy()
        )
        Image.fromarray(encoded, mode="RGB").save(
            path,
            quality=95,
            subsampling=0,
            optimize=True,
        )
        paths.append(path)
    return paths


def _aggregate_metrics(
    frame_metrics: list[dict[str, float]],
) -> dict[str, float]:
    result: dict[str, float] = {
        "sample_count": float(len(frame_metrics)),
    }
    for key in frame_metrics[0]:
        values = np.asarray(
            [metrics[key] for metrics in frame_metrics],
            dtype=np.float64,
        )
        result[f"{key}_median"] = float(np.median(values))
        result[f"{key}_p95"] = float(np.percentile(values, 95))
        result[f"{key}_max"] = float(np.max(values))
    return result


def _candidate_sort_key(candidate: LookCandidate) -> tuple[object, ...]:
    rank = candidate.pareto_rank if candidate.pareto_rank is not None else 10_000
    objective_values = candidate.objective_values
    minimum_objective = min(objective_values.values())
    return (
        rank,
        -minimum_objective,
        *(
            -objective_values[objective]
            for objective in PARETO_OBJECTIVE_ORDER
        ),
        candidate.recipe_id,
    )


def generate_look_candidates(
    *,
    source: Path,
    graph: GradeGraph,
    previews_dir: Path,
    time_seconds: float,
    prompt: str,
    backend: ComputeBackend,
    analyzer: LocalSceneAnalyzer,
    limit: int = 3,
) -> CandidateComparison:
    timestamp = min(
        max(0.0, time_seconds),
        graph.media.duration_seconds,
    )
    digest = graph_digest(graph)
    cache_token = digest[:16]
    previews_dir.mkdir(parents=True, exist_ok=True)
    samples = _candidate_sample_plan(graph, timestamp)
    source_paths: list[Path] = []
    for sample in samples:
        path = (
            previews_dir
            / (
                f"candidate-source-{sample.frame_index:08d}-"
                f"{cache_token}.jpg"
            )
        )
        extract_frame(
            source,
            sample.time_seconds,
            path,
            high_quality=True,
        )
        source_paths.append(path)
    source_batch, source_arrays = _load_source_batch(source_paths)

    masks: Mapping[str, torch.Tensor] | None = None
    mask_completeness = 1.0
    mask_error: str | None = None
    resolver: GraphMaskResolver | None = None
    try:
        resolver = GraphMaskResolver(graph, verify_storage=False)
        if resolver.assets:
            loaded = resolver.load_batch(
                [sample.frame_index for sample in samples],
                device=backend.torch_device,
            )
            valid = all(
                tensor.shape[0] == len(samples)
                and bool(torch.isfinite(tensor).all())
                and bool((tensor >= 0).all())
                and bool((tensor <= 1).all())
                for tensor in loaded.values()
            )
            if valid:
                masks = loaded
            else:
                mask_completeness = 0.0
                mask_error = "referenced mask batch has invalid shape or values"
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        mask_completeness = 0.0
        mask_error = f"{type(exc).__name__}: {exc}"
    finally:
        if resolver is not None:
            resolver.close()

    canonical_intent = _canonical_intent(prompt)
    preferred_recipe = _preferred_recipe(prompt)
    if preferred_recipe is None:
        active_look = active_look_node(graph, timestamp)
        current_recipe = (
            active_look.metadata.get("recipe_id")
            if active_look is not None
            else None
        )
        preferred_recipe = (
            str(current_recipe)
            if current_recipe in LOOK_RECIPES
            else None
        )

    engine = GradeRenderEngine(backend)
    rendered_candidates: list[_RenderedCandidate] = []
    all_output_paths: list[Path] = []
    for recipe_id in LOOK_RECIPES:
        candidate_graph = graph_with_look_recipe(
            graph,
            recipe_id,
            time_seconds=timestamp,
            source=CANDIDATE_RANKING_VERSION,
        )
        raw_output, _ = engine.render_output_batch(
            source_batch,
            candidate_graph,
            timestamps=[sample.time_seconds for sample in samples],
            masks=masks,
            mixed_precision=PREVIEW_PRECISION_BUDGET.mixed_precision_allowed,
            clamp_output=False,
        )
        display = _display_output(raw_output, candidate_graph)
        output_paths = _save_candidate_frames(
            display,
            previews_dir=previews_dir,
            recipe_id=recipe_id,
            samples=samples,
            cache_token=cache_token,
        )
        all_output_paths.extend(output_paths)
        raw_arrays = raw_output.permute(0, 2, 3, 1).float().cpu().numpy()
        display_arrays = display.permute(0, 2, 3, 1).float().cpu().numpy()
        frame_metrics = [
            _frame_quality_metrics(
                source_arrays[index],
                display_arrays[index],
                raw_arrays[index],
                mask_completeness=mask_completeness,
            )
            for index in range(len(samples))
        ]
        failures = [
            failure
            for sample_index, (sample, metrics) in enumerate(
                zip(samples, frame_metrics, strict=True)
            )
            for failure in _hard_failures(
                metrics,
                sample,
                sample_index,
            )
        ]
        rendered_candidates.append(
            _RenderedCandidate(
                recipe_id=recipe_id,
                output_paths=output_paths,
                frame_metrics=frame_metrics,
                hard_failures=failures,
                technical_score=float(
                    np.percentile(
                        [
                            metrics["technical_score"]
                            for metrics in frame_metrics
                        ],
                        25,
                    )
                ),
                aesthetic_score=float(
                    np.percentile(
                        [
                            metrics["aesthetic_proxy"]
                            for metrics in frame_metrics
                        ],
                        25,
                    )
                ),
                conservatism_score=_conservatism_score(
                    graph,
                    recipe_id,
                    timestamp,
                ),
                semantic_prior=(
                    1.0
                    if recipe_id == preferred_recipe
                    else 0.0
                ),
            )
        )

    raw_intent_scores = analyzer.score_images_against_text(
        all_output_paths,
        canonical_intent,
    )
    if len(raw_intent_scores) != len(all_output_paths):
        raise RuntimeError(
            "scene analyzer returned a different number of intent scores "
            "than candidate frames"
        )
    intent_scores = [
        float(np.clip(score, 0, 1))
        for score in raw_intent_scores
    ]
    intent_offset = 0
    candidates: list[LookCandidate] = []
    target_sample_index = min(
        range(len(samples)),
        key=lambda index: (
            abs(samples[index].frame_index - _frame_index(graph, timestamp)),
            samples[index].frame_index,
        ),
    )
    for rendered in rendered_candidates:
        per_frame_intent = intent_scores[
            intent_offset : intent_offset + len(samples)
        ]
        intent_offset += len(samples)
        intent_score = float(np.percentile(per_frame_intent, 25))
        objective_values = {
            "intent_alignment": intent_score,
            "prompt_rule_match": rendered.semantic_prior,
            "aesthetic_proxy": rendered.aesthetic_score,
            "conservatism": rendered.conservatism_score,
            "technical_margin": rendered.technical_score / 100.0,
        }
        aggregate_metrics = _aggregate_metrics(rendered.frame_metrics)
        aggregate_metrics["intent_score_p25"] = intent_score
        aggregate_metrics["mask_error_present"] = (
            1.0 if mask_error is not None else 0.0
        )
        sample_evidence: list[CandidateSampleEvidence] = []
        for sample_index, sample in enumerate(samples):
            sample_failures = [
                failure.check_id
                for failure in rendered.hard_failures
                if failure.sample_index == sample_index
            ]
            sample_evidence.append(
                CandidateSampleEvidence(
                    sample_index=sample_index,
                    frame_index=sample.frame_index,
                    time_seconds=sample.time_seconds,
                    reasons=list(sample.reasons),
                    filename=rendered.output_paths[sample_index].name,
                    intent_score=per_frame_intent[sample_index],
                    metrics=rendered.frame_metrics[sample_index],
                    hard_failure_ids=sorted(set(sample_failures)),
                )
            )
        candidates.append(
            LookCandidate(
                recipe_id=rendered.recipe_id,
                recipe_version=LOOK_RECIPE_VERSION,
                label=str(LOOK_RECIPES[rendered.recipe_id]["label"]),
                parameters=look_parameters(rendered.recipe_id),
                filename=rendered.output_paths[target_sample_index].name,
                intent_score=intent_score,
                semantic_prior=rendered.semantic_prior,
                technical_score=rendered.technical_score,
                combined_score=rendered.technical_score,
                aesthetic_score=rendered.aesthetic_score,
                conservatism_score=rendered.conservatism_score,
                objective_values=objective_values,
                hard_checks_passed=not rendered.hard_failures,
                hard_failures=rendered.hard_failures,
                metrics=aggregate_metrics,
                sample_evidence=sample_evidence,
            )
        )

    eligible_objectives = {
        candidate.recipe_id: candidate.objective_values
        for candidate in candidates
        if candidate.hard_checks_passed
    }
    fronts = pareto_fronts(eligible_objectives)
    ranks = {
        recipe_id: rank
        for rank, front in enumerate(fronts)
        for recipe_id in front
    }
    ranked_candidates: list[LookCandidate] = []
    for candidate in candidates:
        if not candidate.hard_checks_passed:
            ranked_candidates.append(candidate)
            continue
        dominated_by = sorted(
            other.recipe_id
            for other in candidates
            if other.hard_checks_passed
            and other.recipe_id != candidate.recipe_id
            and _dominates(
                other.objective_values,
                candidate.objective_values,
            )
        )
        dominates_count = sum(
            other.hard_checks_passed
            and other.recipe_id != candidate.recipe_id
            and _dominates(
                candidate.objective_values,
                other.objective_values,
            )
            for other in candidates
        )
        rank = ranks[candidate.recipe_id]
        ranked_candidates.append(
            candidate.model_copy(
                update={
                    "pareto_rank": rank,
                    "pareto_front": rank == 0,
                    "dominated_by": dominated_by,
                    "pairwise_wins": dominates_count,
                }
            )
        )

    response_limit = max(1, min(limit, len(ranked_candidates)))
    eligible = sorted(
        (
            candidate
            for candidate in ranked_candidates
            if candidate.hard_checks_passed
        ),
        key=_candidate_sort_key,
    )
    if eligible:
        selected = eligible[:response_limit]
        recommendation_status = "hard-pass-pareto"
    else:
        selected = sorted(
            ranked_candidates,
            key=lambda candidate: (
                len(candidate.hard_failures),
                -candidate.technical_score,
                candidate.recipe_id,
            ),
        )[:response_limit]
        recommendation_status = "unsafe-fallback-no-hard-pass"
    selected_ids = {candidate.recipe_id for candidate in selected}

    selection_evidence: list[CandidateSelectionEvidence] = []
    for candidate in sorted(
        ranked_candidates,
        key=lambda item: item.recipe_id,
    ):
        rejection_reasons: list[str] = []
        if not candidate.hard_checks_passed:
            rejection_reasons.extend(
                f"hard_gate:{failure.check_id}:frame={failure.frame_index}"
                for failure in candidate.hard_failures
            )
        elif candidate.pareto_rank not in {None, 0}:
            rejection_reasons.append(
                "pareto_dominated_by:"
                + ",".join(candidate.dominated_by)
            )
        if candidate.recipe_id not in selected_ids and not rejection_reasons:
            rejection_reasons.append("response_limit")
        selection_evidence.append(
            CandidateSelectionEvidence(
                recipe_id=candidate.recipe_id,
                selected=candidate.recipe_id in selected_ids,
                hard_checks_passed=candidate.hard_checks_passed,
                pareto_rank=candidate.pareto_rank,
                dominated_by=candidate.dominated_by,
                rejection_reasons=rejection_reasons,
            )
        )

    return CandidateComparison(
        time_seconds=timestamp,
        prompt=prompt,
        canonical_intent=canonical_intent,
        graph_digest=digest,
        recipe_version=LOOK_RECIPE_VERSION,
        recommended_id=selected[0].recipe_id,
        recommendation_status=recommendation_status,
        candidates=selected,
        sample_frame_indices=[
            sample.frame_index
            for sample in samples
        ],
        sample_timestamps=[
            sample.time_seconds
            for sample in samples
        ],
        pareto_recipe_ids=fronts[0] if fronts else [],
        selection_evidence=selection_evidence,
        device_runtime=backend.info.runtime,
    )
