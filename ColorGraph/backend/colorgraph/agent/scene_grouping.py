from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from pydantic import BaseModel, ConfigDict, Field, model_validator

from colorgraph.agent.scene_understanding import ShotSceneAnalysis
from colorgraph.media.color_analysis import ShotColorAnalysis

SCENE_GROUPING_VERSION = "colorgraph.scene-grouping/v2"
_DEFAULT_CALIBRATION_PATH = (
    Path(__file__).resolve().parent / "calibration" / "scene_grouping_bootstrap_v1.json"
)


class SceneGroupingWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual: float = Field(ge=0)
    color: float = Field(ge=0)
    semantic: float = Field(ge=0)
    audio: float = Field(ge=0)

    @model_validator(mode="after")
    def require_nonzero_weight(self) -> SceneGroupingWeights:
        if self.visual + self.color + self.semantic + self.audio <= 0:
            raise ValueError("at least one scene-boundary feature weight must be positive")
        return self


class SceneGroupingCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["colorgraph.scene-grouping-calibration/v1"] = Field(
        default="colorgraph.scene-grouping-calibration/v1",
        alias="schema",
    )
    id: str
    dataset_version: str
    source_split: Literal["calibration", "bootstrap"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["bootstrap_not_gold", "calibration_only", "gold_calibrated"]
    weights: SceneGroupingWeights
    boundary_threshold: float = Field(ge=0, le=1)
    release_threshold: float = Field(ge=0, le=1)
    minimum_scene_shots: int = Field(default=1, ge=1)
    color_feature_scales: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> SceneGroupingCalibration:
        if self.release_threshold > self.boundary_threshold:
            raise ValueError("release threshold cannot exceed boundary threshold")
        if any(scale <= 0 for scale in self.color_feature_scales):
            raise ValueError("color feature scales must be positive")
        return self


class SceneBoundaryFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_index: int = Field(ge=1)
    visual_change: float = Field(ge=0, le=1)
    color_change: float = Field(ge=0, le=1)
    semantic_change: float = Field(ge=0, le=1)
    audio_change: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1)


class SceneGroupingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm_version: str = SCENE_GROUPING_VERSION
    selection_mode: Literal["baseline", "calibrated", "shadow"]
    shot_groups: list[list[int]]
    selected_boundaries: list[int] = Field(default_factory=list)
    candidate_shot_groups: list[list[int]] = Field(default_factory=list)
    candidate_boundaries: list[int] = Field(default_factory=list)
    baseline_shot_groups: list[list[int]] = Field(default_factory=list)
    baseline_boundaries: list[int] = Field(default_factory=list)
    adjacent_similarities: list[float] = Field(default_factory=list)
    boundary_scores: list[float] = Field(default_factory=list)
    boundary_features: list[SceneBoundaryFeatures] = Field(default_factory=list)
    calibration: SceneGroupingCalibration
    # Retained solely to make the old greedy comparator fully reproducible.
    visual_threshold: float
    semantic_threshold: float


@dataclass(frozen=True, slots=True)
class SceneCalibrationExample:
    embeddings: torch.Tensor
    reference_boundaries: list[int]
    color_features: torch.Tensor | None = None
    audio_features: torch.Tensor | None = None
    analyses: list[ShotSceneAnalysis] | None = None
    split: str = "calibration"


def load_scene_grouping_calibration(
    path: str | Path = _DEFAULT_CALIBRATION_PATH,
) -> SceneGroupingCalibration:
    resolved = Path(path).resolve()
    calibration = SceneGroupingCalibration.model_validate_json(
        resolved.read_text(encoding="utf-8")
    )
    if resolved == _DEFAULT_CALIBRATION_PATH.resolve():
        source = resolved.with_name("scene_grouping_bootstrap_examples_v1.json")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != calibration.source_sha256:
            raise ValueError("default scene grouping calibration source hash does not match")
    return calibration


def color_features_from_analyses(
    analyses: list[ShotColorAnalysis],
) -> torch.Tensor:
    return torch.asarray(
        [
            [
                analysis.exposure,
                analysis.temperature,
                analysis.tint,
                analysis.highlights,
            ]
            for analysis in analyses
        ],
        dtype=torch.float32,
    ).reshape(-1, 4)


def _normalized_embeddings(values: torch.Tensor, *, label: str) -> torch.Tensor:
    if values.ndim != 2:
        raise ValueError(f"{label} must have shape [shots, dimensions]")
    return torch.nn.functional.normalize(values.float(), dim=-1)


def _adjacent_cosine_changes(values: torch.Tensor) -> tuple[list[float], list[float]]:
    normalized = _normalized_embeddings(values, label="embeddings")
    similarities = [
        float(torch.dot(normalized[index - 1], normalized[index]).item())
        for index in range(1, normalized.shape[0])
    ]
    changes = [float(np.clip(1.0 - similarity, 0.0, 1.0)) for similarity in similarities]
    return similarities, changes


def _color_changes(
    color_features: torch.Tensor | None,
    *,
    shot_count: int,
    scales: list[float],
) -> list[float]:
    if color_features is None:
        return [0.0] * max(shot_count - 1, 0)
    values = color_features.float()
    if values.ndim != 2 or values.shape[0] != shot_count:
        raise ValueError("color features must have shape [shots, dimensions]")
    if scales and len(scales) != values.shape[1]:
        raise ValueError("calibration color feature scales do not match input dimensions")
    scale_tensor = torch.asarray(
        scales or [1.0] * values.shape[1],
        dtype=torch.float32,
    )
    differences = torch.abs(values[1:] - values[:-1]) / scale_tensor
    magnitudes = torch.sqrt(torch.mean(torch.square(differences), dim=1))
    return (1.0 - torch.exp(-magnitudes)).clamp(0, 1).tolist()


def _semantic_changes(
    analyses: list[ShotSceneAnalysis] | None,
    *,
    shot_count: int,
) -> list[float]:
    if not analyses:
        return [0.0] * max(shot_count - 1, 0)
    if len(analyses) != shot_count:
        raise ValueError("analyses length must match embeddings")
    changes: list[float] = []
    for index in range(1, shot_count):
        previous = analyses[index - 1]
        current = analyses[index]
        terrain = (
            min(previous.terrain.confidence, current.terrain.confidence)
            if previous.terrain.label != current.terrain.label
            else 0.0
        )
        lighting = (
            min(previous.lighting.confidence, current.lighting.confidence)
            if previous.lighting.label != current.lighting.label
            else 0.0
        )
        changes.append(float(np.clip((terrain + lighting) * 0.5, 0.0, 1.0)))
    return changes


def _audio_changes(
    audio_features: torch.Tensor | None,
    *,
    shot_count: int,
) -> list[float]:
    if audio_features is None:
        return [0.0] * max(shot_count - 1, 0)
    if audio_features.ndim != 2 or audio_features.shape[0] != shot_count:
        raise ValueError("audio features must have shape [shots, dimensions]")
    _, changes = _adjacent_cosine_changes(audio_features)
    return changes


def _boundary_features(
    embeddings: torch.Tensor,
    analyses: list[ShotSceneAnalysis] | None,
    color_features: torch.Tensor | None,
    audio_features: torch.Tensor | None,
    calibration: SceneGroupingCalibration,
) -> tuple[list[float], list[SceneBoundaryFeatures]]:
    similarities, visual_changes = _adjacent_cosine_changes(embeddings)
    shot_count = embeddings.shape[0]
    color_changes = _color_changes(
        color_features,
        shot_count=shot_count,
        scales=calibration.color_feature_scales,
    )
    semantic_changes = _semantic_changes(analyses, shot_count=shot_count)
    audio_changes = _audio_changes(audio_features, shot_count=shot_count)
    weights = calibration.weights
    total_weight = weights.visual + weights.color + weights.semantic + weights.audio

    features: list[SceneBoundaryFeatures] = []
    for index, values in enumerate(
        zip(
            visual_changes,
            color_changes,
            semantic_changes,
            audio_changes,
            strict=True,
        ),
        start=1,
    ):
        visual, color, semantic, audio = values
        score = (
            visual * weights.visual
            + color * weights.color
            + semantic * weights.semantic
            + audio * weights.audio
        ) / total_weight
        features.append(
            SceneBoundaryFeatures(
                shot_index=index,
                visual_change=round(visual, 6),
                color_change=round(color, 6),
                semantic_change=round(semantic, 6),
                audio_change=round(audio, 6),
                score=round(float(np.clip(score, 0, 1)), 6),
            )
        )
    return similarities, features


def _groups_from_boundaries(shot_count: int, boundaries: list[int]) -> list[list[int]]:
    if shot_count == 0:
        return []
    starts = [0, *sorted(set(boundaries))]
    ends = [*starts[1:], shot_count]
    return [list(range(start, end)) for start, end in zip(starts, ends, strict=True)]


def _decode_boundaries(
    scores: list[float],
    calibration: SceneGroupingCalibration,
) -> list[int]:
    shot_count = len(scores) + 1
    if shot_count <= 1:
        return []
    minimum = calibration.minimum_scene_shots
    negative_infinity = -1e12
    best = [negative_infinity] * (shot_count + 1)
    previous = [-1] * (shot_count + 1)
    best[0] = 0.0
    for end in range(1, shot_count + 1):
        for start in range(0, end):
            if start > 0 and end - start < minimum:
                continue
            if start == 0 and end < minimum and end != shot_count:
                continue
            if best[start] <= negative_infinity / 2:
                continue
            boundary_reward = (
                0.0
                if start == 0
                else scores[start - 1] - calibration.boundary_threshold
            )
            candidate = best[start] + boundary_reward
            if candidate > best[end]:
                best[end] = candidate
                previous[end] = start

    boundaries: list[int] = []
    cursor = shot_count
    while cursor > 0 and previous[cursor] >= 0:
        start = previous[cursor]
        if start > 0 and scores[start - 1] >= calibration.release_threshold:
            boundaries.append(start)
        cursor = start
    return sorted(boundaries)


def _greedy_baseline(
    embeddings: torch.Tensor,
    analyses: list[ShotSceneAnalysis] | None,
    *,
    visual_threshold: float,
    semantic_threshold: float,
) -> tuple[list[list[int]], list[int]]:
    normalized = _normalized_embeddings(embeddings, label="embeddings")
    shot_count = normalized.shape[0]
    if analyses is not None and len(analyses) not in {0, shot_count}:
        raise ValueError("analyses length must match embeddings")
    boundaries: list[int] = []
    for index in range(1, shot_count):
        similarity = float(torch.dot(normalized[index - 1], normalized[index]).item())
        terrain_changed = False
        lighting_changed = False
        if analyses:
            terrain_changed = analyses[index - 1].terrain.label != analyses[index].terrain.label
            lighting_changed = (
                analyses[index - 1].lighting.label != analyses[index].lighting.label
            )
        if similarity < visual_threshold or (
            similarity < semantic_threshold and terrain_changed and lighting_changed
        ):
            boundaries.append(index)
    return _groups_from_boundaries(shot_count, boundaries), boundaries


def group_consecutive_shots(
    embeddings: torch.Tensor,
    analyses: list[ShotSceneAnalysis] | None = None,
    *,
    color_features: torch.Tensor | None = None,
    audio_features: torch.Tensor | None = None,
    calibration: SceneGroupingCalibration | None = None,
    selection_mode: Literal["baseline", "calibrated", "shadow"] = "shadow",
    visual_threshold: float = 0.78,
    semantic_threshold: float = 0.88,
) -> SceneGroupingResult:
    """Score every adjacent boundary and globally decode contiguous scenes.

    Shadow mode is the production-safe default until a frozen Gold Set calibration
    is signed off: it returns the legacy groups while persisting the v2 candidate.
    """

    if embeddings.ndim != 2:
        raise ValueError("embeddings must have shape [shots, dimensions]")
    shot_count = embeddings.shape[0]
    resolved_calibration = calibration or load_scene_grouping_calibration()
    baseline_groups, baseline_boundaries = _greedy_baseline(
        embeddings,
        analyses,
        visual_threshold=visual_threshold,
        semantic_threshold=semantic_threshold,
    )
    if shot_count == 0:
        return SceneGroupingResult(
            selection_mode=selection_mode,
            shot_groups=[],
            candidate_shot_groups=[],
            baseline_shot_groups=[],
            calibration=resolved_calibration,
            visual_threshold=visual_threshold,
            semantic_threshold=semantic_threshold,
        )

    similarities, features = _boundary_features(
        embeddings,
        analyses,
        color_features,
        audio_features,
        resolved_calibration,
    )
    scores = [feature.score for feature in features]
    candidate_boundaries = _decode_boundaries(scores, resolved_calibration)
    candidate_groups = _groups_from_boundaries(shot_count, candidate_boundaries)

    if selection_mode == "calibrated":
        selected_groups = candidate_groups
        selected_boundaries = candidate_boundaries
    else:
        selected_groups = baseline_groups
        selected_boundaries = baseline_boundaries
    return SceneGroupingResult(
        selection_mode=selection_mode,
        shot_groups=selected_groups,
        selected_boundaries=selected_boundaries,
        candidate_shot_groups=candidate_groups,
        candidate_boundaries=candidate_boundaries,
        baseline_shot_groups=baseline_groups,
        baseline_boundaries=baseline_boundaries,
        adjacent_similarities=similarities,
        boundary_scores=scores,
        boundary_features=features,
        calibration=resolved_calibration,
        visual_threshold=visual_threshold,
        semantic_threshold=semantic_threshold,
    )


def _exact_boundary_counts(
    predicted: list[int],
    reference: list[int],
) -> tuple[int, int, int]:
    predicted_set = set(predicted)
    reference_set = set(reference)
    return (
        len(predicted_set & reference_set),
        len(predicted_set - reference_set),
        len(reference_set - predicted_set),
    )


def _calibration_digest(examples: list[SceneCalibrationExample]) -> str:
    payload = [
        {
            "embeddings": example.embeddings.float().tolist(),
            "color_features": (
                example.color_features.float().tolist()
                if example.color_features is not None
                else None
            ),
            "audio_features": (
                example.audio_features.float().tolist()
                if example.audio_features is not None
                else None
            ),
            "reference_boundaries": example.reference_boundaries,
            "split": example.split,
        }
        for example in examples
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def calibrate_scene_grouping(
    examples: list[SceneCalibrationExample],
    *,
    calibration_id: str,
    dataset_version: str,
    weights: SceneGroupingWeights,
    color_feature_scales: list[float] | None = None,
    minimum_scene_shots: int = 1,
    status: Literal["calibration_only", "gold_calibrated"] = "calibration_only",
) -> SceneGroupingCalibration:
    if not examples:
        raise ValueError("at least one calibration example is required")
    if any(example.split != "calibration" for example in examples):
        raise ValueError("scene grouping thresholds may only use calibration split examples")

    provisional = SceneGroupingCalibration(
        id=calibration_id,
        dataset_version=dataset_version,
        source_split="calibration",
        source_sha256=_calibration_digest(examples),
        status=status,
        weights=weights,
        boundary_threshold=0.5,
        release_threshold=0.5,
        minimum_scene_shots=minimum_scene_shots,
        color_feature_scales=color_feature_scales or [],
    )
    example_scores: list[list[float]] = []
    observed_scores: list[float] = []
    for example in examples:
        _, features = _boundary_features(
            example.embeddings,
            example.analyses,
            example.color_features,
            example.audio_features,
            provisional,
        )
        scores = [feature.score for feature in features]
        example_scores.append(scores)
        observed_scores.extend(scores)
    unique = sorted(set(observed_scores))
    candidates = sorted(
        {
            0.0,
            1.0,
            *unique,
            *[
                (left + right) * 0.5
                for left, right in zip(unique[:-1], unique[1:], strict=True)
            ],
        }
    )

    best_threshold = candidates[0]
    best_objective = (-1.0, -1.0, -1.0)
    for threshold in candidates:
        candidate_calibration = provisional.model_copy(
            update={
                "boundary_threshold": threshold,
                "release_threshold": threshold,
            }
        )
        true_positive = false_positive = false_negative = 0
        for example, scores in zip(examples, example_scores, strict=True):
            predicted = _decode_boundaries(scores, candidate_calibration)
            counts = _exact_boundary_counts(predicted, example.reference_boundaries)
            true_positive += counts[0]
            false_positive += counts[1]
            false_negative += counts[2]
        precision = true_positive / max(true_positive + false_positive, 1)
        recall = true_positive / max(true_positive + false_negative, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        objective = (f1, precision, threshold)
        if objective > best_objective:
            best_objective = objective
            best_threshold = threshold

    return provisional.model_copy(
        update={
            "boundary_threshold": round(best_threshold, 6),
            "release_threshold": round(best_threshold * 0.75, 6),
        }
    )
