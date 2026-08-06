from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import numpy as np
import torch
import torch.nn.functional as functional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictVLMModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

VLM_SHADOW_VERSION = "colorgraph.siglip2-scene-shadow/v1"
VLM_CALIBRATION_VERSION = "colorgraph.vlm-shadow-calibration/v1"

VLMCategory = Literal["terrain", "lighting", "intent"]
CalibrationStatus = Literal[
    "bootstrap_not_gold",
    "calibration_only",
    "gold_calibrated",
]
CheckpointHashKind = Literal["colorgraph.torch-state-dict/v1"]


class VLMLabelSpec(_StrictVLMModel):
    label_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    category: VLMCategory
    prompt: str = Field(min_length=1)


DEFAULT_VLM_LABELS: tuple[VLMLabelSpec, ...] = (
    VLMLabelSpec(
        label_id="terrain.mountain",
        category="terrain",
        prompt="This is a photo of a mountain landscape.",
    ),
    VLMLabelSpec(
        label_id="terrain.forest",
        category="terrain",
        prompt="This is a photo of a forest or dense vegetation landscape.",
    ),
    VLMLabelSpec(
        label_id="terrain.coast",
        category="terrain",
        prompt="This is a photo of a coast or ocean landscape.",
    ),
    VLMLabelSpec(
        label_id="terrain.inland_water",
        category="terrain",
        prompt="This is a photo of a lake, river, or waterfall landscape.",
    ),
    VLMLabelSpec(
        label_id="terrain.snow",
        category="terrain",
        prompt="This is a photo of a snowy or icy landscape.",
    ),
    VLMLabelSpec(
        label_id="terrain.urban",
        category="terrain",
        prompt="This is a photo of an urban or architectural landscape.",
    ),
    VLMLabelSpec(
        label_id="lighting.sunny",
        category="lighting",
        prompt="This image has bright sunny daylight.",
    ),
    VLMLabelSpec(
        label_id="lighting.overcast",
        category="lighting",
        prompt="This image has soft overcast daylight.",
    ),
    VLMLabelSpec(
        label_id="lighting.golden_hour",
        category="lighting",
        prompt="This image has golden hour or sunset light.",
    ),
    VLMLabelSpec(
        label_id="lighting.blue_hour",
        category="lighting",
        prompt="This image has blue hour or twilight light.",
    ),
    VLMLabelSpec(
        label_id="lighting.misty",
        category="lighting",
        prompt="This image has misty or fog-diffused light.",
    ),
    VLMLabelSpec(
        label_id="lighting.mixed",
        category="lighting",
        prompt="This image has visibly mixed lighting conditions.",
    ),
    VLMLabelSpec(
        label_id="intent.natural",
        category="intent",
        prompt="A natural and restrained photographic treatment supports this image.",
    ),
    VLMLabelSpec(
        label_id="intent.documentary",
        category="intent",
        prompt="A cool restrained documentary treatment supports this image.",
    ),
    VLMLabelSpec(
        label_id="intent.cinematic_contrast",
        category="intent",
        prompt="A cinematic contrast-led treatment supports this image.",
    ),
    VLMLabelSpec(
        label_id="intent.atmospheric_softness",
        category="intent",
        prompt="A soft atmospheric low-contrast treatment supports this image.",
    ),
)


class VLMCalibrationExample(_StrictVLMModel):
    sample_id: str = Field(min_length=1)
    split: Literal["calibration"]
    raw_logits: dict[str, float]
    max_cosine: float = Field(ge=-1, le=1)
    positive_label_ids: list[str] = Field(default_factory=list)
    is_ood: bool = False


class VLMCalibrationInput(_StrictVLMModel):
    schema_version: str = VLM_CALIBRATION_VERSION
    model_id: str = Field(min_length=1)
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: CheckpointHashKind | None = None
    status: CalibrationStatus = "calibration_only"
    labels: list[VLMLabelSpec] = Field(min_length=1)
    examples: list[VLMCalibrationExample] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_input(self) -> VLMCalibrationInput:
        if (self.checkpoint_sha256 is None) != (
            self.checkpoint_hash_kind is None
        ):
            raise ValueError(
                "VLM checkpoint SHA-256 and hash kind must be provided together"
            )
        label_ids = [label.label_id for label in self.labels]
        if len(set(label_ids)) != len(label_ids):
            raise ValueError("VLM label IDs must be unique")
        expected = set(label_ids)
        sample_ids = [example.sample_id for example in self.examples]
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("VLM calibration sample IDs must be unique")
        for example in self.examples:
            if set(example.raw_logits) != expected:
                raise ValueError(
                    f"{example.sample_id} logits do not match the frozen label set"
                )
            unknown = set(example.positive_label_ids) - expected
            if unknown:
                raise ValueError(
                    f"{example.sample_id} references unknown labels: {sorted(unknown)}"
                )
            if example.is_ood and example.positive_label_ids:
                raise ValueError("OOD examples cannot carry positive labels")
        if not any(example.is_ood for example in self.examples):
            raise ValueError("calibration input requires at least one OOD example")
        if not any(not example.is_ood for example in self.examples):
            raise ValueError("calibration input requires at least one in-domain example")
        for label_id in expected:
            positives = [
                label_id in example.positive_label_ids for example in self.examples
            ]
            if not any(positives) or all(positives):
                raise ValueError(
                    f"label {label_id} requires positive and negative calibration examples"
                )
        return self


class VLMShadowCalibration(_StrictVLMModel):
    schema_version: str = VLM_CALIBRATION_VERSION
    model_id: str
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: CheckpointHashKind | None = None
    source_split: Literal["calibration"] = "calibration"
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CalibrationStatus
    label_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_thresholds: dict[str, float]
    temperature: float = Field(gt=0)
    unknown_probability_threshold: float = Field(ge=0, le=1)
    minimum_max_cosine: float = Field(ge=-1, le=1)
    binary_log_loss: float = Field(ge=0)
    ood_balanced_accuracy: float = Field(ge=0, le=1)
    example_count: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_checkpoint_identity(self) -> VLMShadowCalibration:
        if (self.checkpoint_sha256 is None) != (
            self.checkpoint_hash_kind is None
        ):
            raise ValueError(
                "VLM checkpoint SHA-256 and hash kind must be provided together"
            )
        return self


class VLMLabelScore(_StrictVLMModel):
    label_id: str
    category: VLMCategory
    prompt: str
    raw_cosine: float = Field(ge=-1, le=1)
    raw_logit: float
    calibrated_probability: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    selected: bool


class VLMFrameShadow(_StrictVLMModel):
    frame_path: str
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scores: list[VLMLabelScore]
    selected_by_category: dict[VLMCategory, list[str]]
    unknown_categories: list[VLMCategory]
    ood: bool
    maximum_cosine: float = Field(ge=-1, le=1)
    maximum_probability: float = Field(ge=0, le=1)


class VLMShadowBatchReport(_StrictVLMModel):
    schema_version: str = VLM_SHADOW_VERSION
    model_id: str
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: CheckpointHashKind | None = None
    calibration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_status: CalibrationStatus
    label_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_count: int = Field(gt=0)
    text_prompt_count: int = Field(gt=0)
    logical_image_encoding_batches: int = Field(default=1, ge=1)
    logical_text_encoding_batches: int = Field(default=1, ge=1)
    probability_semantics: Literal["independent_sigmoid"] = "independent_sigmoid"
    technical_risk_source: Literal[
        "colorgraph.content-aware-color-analysis/v1"
    ] = "colorgraph.content-aware-color-analysis/v1"
    technical_risk_prompts_excluded: bool = True
    frames: list[VLMFrameShadow]

    @model_validator(mode="after")
    def validate_checkpoint_identity(self) -> VLMShadowBatchReport:
        if (self.checkpoint_sha256 is None) != (
            self.checkpoint_hash_kind is None
        ):
            raise ValueError(
                "VLM checkpoint SHA-256 and hash kind must be provided together"
            )
        return self


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def label_definition_sha256(labels: Sequence[VLMLabelSpec]) -> str:
    return _canonical_sha256(
        [label.model_dump(mode="json") for label in labels]
    )


def calibration_sha256(calibration: VLMShadowCalibration) -> str:
    return _canonical_sha256(calibration.model_dump(mode="json"))


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _binary_log_loss(probabilities: np.ndarray, targets: np.ndarray) -> float:
    clipped = np.clip(probabilities, 1e-9, 1 - 1e-9)
    return float(
        -np.mean(targets * np.log(clipped) + (1 - targets) * np.log(1 - clipped))
    )


def _f1(
    probabilities: np.ndarray,
    targets: np.ndarray,
    threshold: float,
) -> tuple[float, float]:
    predictions = probabilities >= threshold
    truth = targets.astype(bool)
    true_positive = int(np.logical_and(predictions, truth).sum())
    false_positive = int(np.logical_and(predictions, ~truth).sum())
    false_negative = int(np.logical_and(~predictions, truth).sum())
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    value = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return value, precision


def _balanced_accuracy(
    values: np.ndarray,
    is_known: np.ndarray,
    threshold: float,
) -> float:
    predictions = values >= threshold
    known_mask = is_known.astype(bool)
    unknown_mask = ~known_mask
    true_positive_rate = (
        float(predictions[known_mask].mean()) if known_mask.any() else 0.0
    )
    true_negative_rate = (
        float((~predictions[unknown_mask]).mean()) if unknown_mask.any() else 0.0
    )
    return (true_positive_rate + true_negative_rate) / 2


def calibrate_vlm_shadow(
    calibration_input: VLMCalibrationInput,
) -> VLMShadowCalibration:
    labels = calibration_input.labels
    label_ids = [label.label_id for label in labels]
    logits = np.asarray(
        [
            [example.raw_logits[label_id] for label_id in label_ids]
            for example in calibration_input.examples
        ],
        dtype=np.float64,
    )
    targets = np.asarray(
        [
            [
                float(label_id in example.positive_label_ids)
                for label_id in label_ids
            ]
            for example in calibration_input.examples
        ],
        dtype=np.float64,
    )
    temperatures = np.geomspace(0.1, 10.0, 161)
    temperature, loss = min(
        (
            (
                float(value),
                _binary_log_loss(_sigmoid(logits / value), targets),
            )
            for value in temperatures
        ),
        key=lambda item: (item[1], abs(item[0] - 1.0)),
    )
    probabilities = _sigmoid(logits / temperature)
    threshold_grid = np.linspace(0.05, 0.95, 181)
    label_thresholds: dict[str, float] = {}
    for index, label_id in enumerate(label_ids):
        threshold = max(
            threshold_grid,
            key=lambda value: (
                *_f1(probabilities[:, index], targets[:, index], float(value)),
                -abs(float(value) - 0.5),
            ),
        )
        label_thresholds[label_id] = float(threshold)

    is_known = np.asarray(
        [not example.is_ood for example in calibration_input.examples],
        dtype=bool,
    )
    max_probability = probabilities.max(axis=1)
    unknown_probability_threshold, probability_accuracy = max(
        (
            (
                float(threshold),
                _balanced_accuracy(max_probability, is_known, float(threshold)),
            )
            for threshold in threshold_grid
        ),
        key=lambda item: (item[1], -abs(item[0] - 0.5)),
    )
    cosines = np.asarray(
        [example.max_cosine for example in calibration_input.examples],
        dtype=np.float64,
    )
    cosine_grid = np.linspace(-1.0, 1.0, 401)
    minimum_max_cosine, cosine_accuracy = max(
        (
            (
                float(threshold),
                _balanced_accuracy(cosines, is_known, float(threshold)),
            )
            for threshold in cosine_grid
        ),
        key=lambda item: (item[1], -abs(item[0])),
    )
    source_sha256 = _canonical_sha256(
        [example.model_dump(mode="json") for example in calibration_input.examples]
    )
    return VLMShadowCalibration(
        model_id=calibration_input.model_id,
        model_revision=calibration_input.model_revision,
        checkpoint_sha256=calibration_input.checkpoint_sha256,
        checkpoint_hash_kind=calibration_input.checkpoint_hash_kind,
        source_sha256=source_sha256,
        status=calibration_input.status,
        label_definition_sha256=label_definition_sha256(labels),
        label_thresholds=label_thresholds,
        temperature=temperature,
        unknown_probability_threshold=unknown_probability_threshold,
        minimum_max_cosine=minimum_max_cosine,
        binary_log_loss=loss,
        ood_balanced_accuracy=min(probability_accuracy, cosine_accuracy),
        example_count=len(calibration_input.examples),
    )


def score_vlm_shadow_embeddings(
    image_features: torch.Tensor,
    text_features: torch.Tensor,
    *,
    frame_paths: Sequence[str],
    frame_sha256: Sequence[str],
    labels: Sequence[VLMLabelSpec],
    calibration: VLMShadowCalibration,
    model_id: str,
    model_revision: str,
    logit_scale: float,
    logit_bias: float,
    checkpoint_sha256: str | None = None,
    checkpoint_hash_kind: CheckpointHashKind | None = None,
) -> VLMShadowBatchReport:
    if model_id != calibration.model_id or model_revision != calibration.model_revision:
        raise ValueError("VLM runtime identity does not match the calibration artifact")
    if (
        calibration.checkpoint_sha256 is not None
        and (
            checkpoint_sha256 != calibration.checkpoint_sha256
            or checkpoint_hash_kind != calibration.checkpoint_hash_kind
        )
    ):
        raise ValueError(
            "VLM runtime checkpoint identity does not match the calibration artifact"
        )
    if calibration.label_definition_sha256 != label_definition_sha256(labels):
        raise ValueError("VLM label definitions do not match the calibration artifact")
    if set(calibration.label_thresholds) != {
        label.label_id for label in labels
    }:
        raise ValueError("VLM calibration thresholds do not match the label set")
    if image_features.ndim != 2 or text_features.ndim != 2:
        raise ValueError("VLM features must be rank-2 tensors")
    if image_features.shape[1] != text_features.shape[1]:
        raise ValueError("VLM image/text feature dimensions differ")
    if image_features.shape[0] != len(frame_paths) or len(frame_paths) != len(
        frame_sha256
    ):
        raise ValueError("VLM frame metadata does not match image features")
    if text_features.shape[0] != len(labels):
        raise ValueError("VLM text features do not match labels")
    if logit_scale <= 0:
        raise ValueError("VLM logit scale must be positive")

    images = functional.normalize(image_features.float(), dim=-1)
    texts = functional.normalize(text_features.float(), dim=-1)
    cosine = torch.clamp(images @ texts.transpose(0, 1), -1.0, 1.0)
    logits = cosine * float(logit_scale) + float(logit_bias)
    probabilities = torch.sigmoid(logits / calibration.temperature)
    categories: tuple[VLMCategory, ...] = ("terrain", "lighting", "intent")
    frames: list[VLMFrameShadow] = []
    for frame_index, frame_path in enumerate(frame_paths):
        maximum_cosine = float(cosine[frame_index].max().item())
        maximum_probability = float(probabilities[frame_index].max().item())
        ood = (
            maximum_cosine < calibration.minimum_max_cosine
            or maximum_probability < calibration.unknown_probability_threshold
        )
        scores: list[VLMLabelScore] = []
        selected_by_category: dict[VLMCategory, list[str]] = {
            category: [] for category in categories
        }
        for label_index, label in enumerate(labels):
            threshold = calibration.label_thresholds[label.label_id]
            selected = (
                not ood
                and float(probabilities[frame_index, label_index].item())
                >= threshold
            )
            if selected:
                selected_by_category[label.category].append(label.label_id)
            scores.append(
                VLMLabelScore(
                    label_id=label.label_id,
                    category=label.category,
                    prompt=label.prompt,
                    raw_cosine=float(cosine[frame_index, label_index].item()),
                    raw_logit=float(logits[frame_index, label_index].item()),
                    calibrated_probability=float(
                        probabilities[frame_index, label_index].item()
                    ),
                    threshold=threshold,
                    selected=selected,
                )
            )
        unknown_categories = [
            category
            for category in categories
            if not selected_by_category[category]
        ]
        frames.append(
            VLMFrameShadow(
                frame_path=frame_path,
                frame_sha256=frame_sha256[frame_index],
                scores=scores,
                selected_by_category=selected_by_category,
                unknown_categories=unknown_categories,
                ood=ood,
                maximum_cosine=maximum_cosine,
                maximum_probability=maximum_probability,
            )
        )
    return VLMShadowBatchReport(
        model_id=model_id,
        model_revision=model_revision,
        checkpoint_sha256=checkpoint_sha256,
        checkpoint_hash_kind=checkpoint_hash_kind,
        calibration_sha256=calibration_sha256(calibration),
        calibration_status=calibration.status,
        label_definition_sha256=calibration.label_definition_sha256,
        image_count=len(frame_paths),
        text_prompt_count=len(labels),
        frames=frames,
    )


def calibrate_vlm_shadow_file(
    input_path: str | Path,
    output_path: str | Path,
) -> VLMShadowCalibration:
    source = Path(input_path).resolve()
    calibration_input = VLMCalibrationInput.model_validate_json(
        source.read_text(encoding="utf-8")
    )
    calibration = calibrate_vlm_shadow(calibration_input)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            calibration.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return calibration
