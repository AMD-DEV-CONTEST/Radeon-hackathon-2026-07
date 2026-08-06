from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import numpy as np

from backend.config import Settings
from backend.schemas import CommandDecision
from command.labels import COMMAND_LABELS, EXECUTABLE_INTENTS, CommandIntent
from command.language import score_language_candidates, validate_recognition_language
from command.model import normalize_clip_length
from command.prototype import (
    extract_roi_embedding,
    load_profile_prototypes,
    match_prototypes,
    sanitize_profile_id,
)
from command.training import require_rocm

logger = logging.getLogger(__name__)


class CommandClassifierBackend(Protocol):
    def predict(
        self,
        mouth_frames: np.ndarray,
        language: str,
        metadata: dict[str, object],
    ) -> CommandDecision:
        raise NotImplementedError


@dataclass(frozen=True)
class ThresholdResolution:
    min_probability: float
    max_cosine_distance: dict[str, float]
    source: str


def resolve_thresholds(
    checkpoint_thresholds: dict[str, Any],
    probability_override: float | None,
    distance_override: float | None,
) -> ThresholdResolution:
    minimum_probability = float(checkpoint_thresholds["minProbability"])
    maximum_distances = {
        str(phrase_id): float(distance)
        for phrase_id, distance in checkpoint_thresholds["maxCosineDistance"].items()
    }
    override_names: list[str] = []
    if probability_override is not None:
        minimum_probability = _unit_interval_override(
            probability_override, "probability"
        )
        override_names.append("probability")
    if distance_override is not None:
        distance = _unit_interval_override(distance_override, "distance")
        maximum_distances = {phrase_id: distance for phrase_id in maximum_distances}
        override_names.append("distance")
    source = (
        "checkpoint" if not override_names else f"override:{','.join(override_names)}"
    )
    return ThresholdResolution(minimum_probability, maximum_distances, source)


def evaluate_phrase_rejection(
    probability: float,
    distance: float,
    predicted_phrase_id: str,
    thresholds: ThresholdResolution,
) -> tuple[bool, str | None]:
    if not math.isfinite(float(probability)) or not math.isfinite(float(distance)):
        return False, "non_finite_score"
    if probability < thresholds.min_probability:
        return False, "low_probability"
    if distance > thresholds.max_cosine_distance[predicted_phrase_id]:
        return False, "embedding_distance"
    return True, None


def _unit_interval_override(value: float, name: str) -> float:
    if not isinstance(value, Real) or isinstance(value, bool):
        raise TypeError(f"{name} override must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} override must be between 0 and 1")
    return normalized


def reject_by_thresholds(
    *,
    intent: CommandIntent,
    confidence: float,
    second_confidence: float,
    threshold: float,
    top1_margin: float,
    logits: list[float],
    top_k: list[dict[str, object]] | None = None,
    metadata: dict[str, object] | None = None,
) -> CommandDecision:
    margin = round(max(0.0, confidence - second_confidence), 6)
    executable = intent in EXECUTABLE_INTENTS
    if confidence < threshold:
        return CommandDecision(
            intent=CommandIntent.UNKNOWN,
            accepted=False,
            executable=False,
            confidence=confidence,
            margin=margin,
            topK=top_k or [],
            logits=logits,
            reason="below confidence threshold",
            metadata=metadata or {},
        )
    if margin < top1_margin:
        return CommandDecision(
            intent=CommandIntent.UNKNOWN,
            accepted=False,
            executable=False,
            confidence=confidence,
            margin=margin,
            topK=top_k or [],
            logits=logits,
            reason="top1/top2 margin too small",
            metadata=metadata or {},
        )
    if intent == CommandIntent.UNKNOWN:
        return CommandDecision(
            intent=CommandIntent.UNKNOWN,
            accepted=False,
            executable=False,
            confidence=confidence,
            margin=margin,
            topK=top_k or [],
            logits=logits,
            reason="classifier predicted UNKNOWN",
            metadata=metadata or {},
        )
    return CommandDecision(
        intent=intent,
        accepted=True,
        executable=executable,
        confidence=confidence,
        margin=margin,
        topK=top_k or [],
        logits=logits,
        reason="accepted executable intent"
        if executable
        else "accepted non-executable intent",
        metadata=metadata or {},
    )


class FakeCommandClassifierBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def predict(
        self,
        mouth_frames: np.ndarray,
        language: str,
        metadata: dict[str, object],
    ) -> CommandDecision:
        validate_recognition_language(language)
        motion = (
            float(np.abs(np.diff(mouth_frames.astype("float32"), axis=0)).mean())
            if len(mouth_frames) > 1
            else 0.0
        )
        if motion > 1.0:
            intent = CommandIntent.LIGHT_ON
            confidence = 0.91
            second = 0.42
        else:
            intent = CommandIntent.UNKNOWN
            confidence = 0.45
            second = 0.40
        logits = [0.0 for _ in COMMAND_LABELS]
        logits[COMMAND_LABELS.index(intent)] = confidence
        top_k = [{"intent": intent.value, "confidence": confidence}]
        return reject_by_thresholds(
            intent=intent,
            confidence=confidence,
            second_confidence=second,
            threshold=self.settings.command_confidence_threshold,
            top1_margin=self.settings.command_top1_margin,
            logits=logits,
            top_k=top_k,
            metadata=metadata,
        )


class TorchCommandClassifierBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.command_classifier_checkpoint is None:
            raise FileNotFoundError(
                "COMMAND_CLASSIFIER_CHECKPOINT is required when COMMAND_BACKEND=torch"
            )
        self.checkpoint = Path(settings.command_classifier_checkpoint)
        if not self.checkpoint.exists():
            raise FileNotFoundError(self.checkpoint)

        import torch

        from command.checkpoint import load_phrase_checkpoint

        self.torch = torch
        self.device = require_rocm(torch)
        self.loaded_checkpoint = load_phrase_checkpoint(self.checkpoint, self.device)
        self.thresholds = resolve_thresholds(
            self.loaded_checkpoint.decision_thresholds,
            probability_override=settings.command_phrase_probability_override,
            distance_override=settings.command_phrase_distance_override,
        )
        self.catalog_by_phrase_id = {
            entry.phrase_id: entry for entry in self.loaded_checkpoint.catalog.entries
        }
        self.phrase_languages = tuple(
            self.catalog_by_phrase_id[phrase_id].language
            for phrase_id in self.loaded_checkpoint.phrase_ids
        )
        self.centroids = torch.as_tensor(
            self.loaded_checkpoint.centroids,
            device=self.device,
            dtype=torch.float32,
        )

    def predict(
        self,
        mouth_frames: np.ndarray,
        language: str,
        metadata: dict[str, object],
    ) -> CommandDecision:
        selected_language = validate_recognition_language(language)
        started = perf_counter()
        frames = np.asarray(mouth_frames)
        tensor = normalize_clip_length(self.torch.from_numpy(frames)).unsqueeze(0)
        tensor = tensor.to(self.device)
        with self.torch.inference_mode():
            logits_tensor, embedding = self.loaded_checkpoint.model(tensor)
            logits_tensor = logits_tensor.squeeze(0)
        logits = [float(value) for value in logits_tensor.detach().cpu().tolist()]
        scores = score_language_candidates(
            logits, self.phrase_languages, selected_language
        )
        best_index = scores.ranked_indices[0]
        best_probability = scores.probabilities[best_index]
        second_probability = (
            scores.probabilities[scores.ranked_indices[1]]
            if len(scores.ranked_indices) > 1
            else 0.0
        )
        predicted_phrase_id = self.loaded_checkpoint.phrase_ids[best_index]
        predicted_entry = self.catalog_by_phrase_id[predicted_phrase_id]
        similarity_value = float(
            self.torch.nn.functional.cosine_similarity(
                embedding.squeeze(0), self.centroids[best_index], dim=0
            ).item()
        )
        raw_distance = (
            1.0 - min(1.0, max(-1.0, similarity_value))
            if math.isfinite(similarity_value)
            else math.nan
        )
        accepted, rejection_reason = evaluate_phrase_rejection(
            best_probability,
            raw_distance,
            predicted_phrase_id,
            self.thresholds,
        )
        distance = raw_distance if math.isfinite(raw_distance) else 2.0
        margin = round(max(0.0, best_probability - second_probability), 6)
        top_k = [
            self._top_k_item(index, scores.probabilities[index])
            for index in scores.ranked_indices[:3]
        ]
        result_metadata = dict(metadata)
        for reserved_key in (
            "phraseId",
            "matchedPhrase",
            "displayText",
            "language",
            "selectedLanguage",
            "eligiblePhraseIds",
        ):
            result_metadata.pop(reserved_key, None)
        result_metadata.update(
            {
                "backend": "torch",
                "latencyMs": int((perf_counter() - started) * 1000),
                "predictedPhraseId": predicted_phrase_id,
                "selectedLanguage": scores.selected_language,
                "eligiblePhraseIds": [
                    self.loaded_checkpoint.phrase_ids[index]
                    for index in scores.eligible_indices
                ],
                "probability": best_probability,
                "openSetDistance": distance,
                "openSetDistanceValid": math.isfinite(raw_distance),
                "thresholdSource": self.thresholds.source,
                "minProbabilityThreshold": self.thresholds.min_probability,
                "maxCosineDistanceThreshold": self.thresholds.max_cosine_distance[
                    predicted_phrase_id
                ],
            }
        )
        if not accepted:
            result_metadata["rejectionReason"] = rejection_reason
            return CommandDecision(
                intent=CommandIntent.UNKNOWN,
                accepted=False,
                executable=False,
                confidence=best_probability,
                margin=margin,
                topK=[
                    self._top_k_item(
                        index, scores.probabilities[index], include_text=False
                    )
                    for index in scores.ranked_indices[:3]
                ],
                logits=logits,
                reason=rejection_reason or "rejected",
                metadata=result_metadata,
            )

        result_metadata.update(
            {
                "phraseId": predicted_entry.phrase_id,
                "matchedPhrase": predicted_entry.text,
                "displayText": predicted_entry.text,
                "language": predicted_entry.language,
            }
        )
        executable = predicted_entry.intent in EXECUTABLE_INTENTS
        return CommandDecision(
            intent=predicted_entry.intent,
            accepted=True,
            executable=executable,
            confidence=best_probability,
            margin=margin,
            topK=top_k,
            logits=logits,
            reason="accepted executable intent"
            if executable
            else "accepted non-executable intent",
            metadata=result_metadata,
        )

    def _top_k_item(
        self, index: int, confidence: float, *, include_text: bool = True
    ) -> dict[str, object]:
        phrase_id = self.loaded_checkpoint.phrase_ids[index]
        entry = self.catalog_by_phrase_id[phrase_id]
        item: dict[str, object] = {
            "phraseId": entry.phrase_id,
            "language": entry.language,
            "intent": entry.intent.value,
            "confidence": confidence,
        }
        if include_text:
            item["text"] = entry.text
        return item


class PrototypeCommandClassifierBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.persistence_root

    def predict(
        self,
        mouth_frames: np.ndarray,
        language: str,
        metadata: dict[str, object],
    ) -> CommandDecision:
        selected_language = validate_recognition_language(language)
        started = perf_counter()
        embedding = extract_roi_embedding(
            mouth_frames, feature_dim=self.settings.prototype_feature_dim
        )
        profile_id = "global"
        scopes: list[tuple[str, str | None]] = [("global", "global")]

        last_match = None
        last_scope = "none"
        for scope, candidate_profile in scopes:
            if candidate_profile is None:
                continue
            try:
                sanitized_profile = sanitize_profile_id(candidate_profile)
            except ValueError:
                continue
            samples = load_profile_prototypes(self.root, sanitized_profile)
            samples = [
                sample
                for sample in samples
                if _clean_language(sample.metadata.get("language")) == selected_language
            ]
            if not samples:
                continue
            match = match_prototypes(
                embedding,
                samples,
                confidence_threshold=self.settings.prototype_confidence_threshold,
                margin_threshold=self.settings.prototype_top1_margin,
            )
            last_match = match
            last_scope = scope
            if match.accepted:
                break

        if last_match is None:
            match = match_prototypes(
                embedding,
                [],
                confidence_threshold=self.settings.prototype_confidence_threshold,
                margin_threshold=self.settings.prototype_top1_margin,
            )
            last_match = match
            last_scope = "none"

        intent = CommandIntent(last_match.intent)
        executable = last_match.accepted and intent in EXECUTABLE_INTENTS
        matched_metadata = dict(last_match.matched_metadata)
        matched_phrase = _clean_metadata_string(matched_metadata.get("phrase"))
        matched_language = _clean_language(matched_metadata.get("language"))
        result_metadata = {
            **metadata,
            "backend": "prototype",
            "profileId": profile_id,
            "profileScope": last_scope,
            "selectedLanguage": selected_language,
            "latencyMs": int((perf_counter() - started) * 1000),
        }
        if last_match.accepted:
            result_metadata["displayText"] = matched_phrase or intent.value
            if matched_phrase:
                result_metadata["matchedPhrase"] = matched_phrase
            if matched_language:
                result_metadata["matchedLanguage"] = matched_language
                result_metadata["language"] = matched_language
            if last_match.matched_sample_path:
                result_metadata["matchedSamplePath"] = last_match.matched_sample_path
        return CommandDecision(
            intent=intent,
            accepted=last_match.accepted,
            executable=executable,
            confidence=last_match.confidence,
            margin=last_match.margin,
            topK=last_match.top_k,
            logits=last_match.logits,
            reason=last_match.reason,
            metadata=result_metadata,
        )


def _clean_metadata_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_language(value: object) -> str | None:
    language = _clean_metadata_string(value)
    return language if language in {"zh", "en"} else None


def save_command_debug(
    settings: Settings, session_id: str, decision: CommandDecision
) -> Path:
    output_dir = (
        settings.debug_window_dir or settings.persistence_root / "logs" / "command-runs"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{session_id}-command-metadata.json"
    path.write_text(json.dumps(decision.model_dump(), ensure_ascii=False, indent=2))
    return path


def build_command_classifier(settings: Settings) -> CommandClassifierBackend:
    if settings.command_backend == "torch":
        return TorchCommandClassifierBackend(settings)
    if settings.command_backend == "prototype":
        return PrototypeCommandClassifierBackend(settings)
    return FakeCommandClassifierBackend(settings)
