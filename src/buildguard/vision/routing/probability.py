"""Pluggable probability estimation for RoI/model pairs."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Protocol

from buildguard.config import VisionRoutingConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.vision.routing.schemas import RoiFeatures, RoutingModel


class ProbabilityEstimator(ABC):
    @abstractmethod
    def estimate(
        self,
        features: RoiFeatures,
        models: list[RoutingModel],
    ) -> dict[str, float]:
        """Return a probability for every supplied candidate model."""


def _logit(probability: float) -> float:
    return math.log(probability / (1.0 - probability))


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponential = math.exp(-value)
        return 1.0 / (1.0 + exponential)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


class HeuristicProbabilityEstimator(ProbabilityEstimator):
    """Apply the configured, inspectable probability equation."""

    def __init__(self, config: VisionRoutingConfig) -> None:
        self.config = config

    def estimate_one(self, features: RoiFeatures, model: RoutingModel) -> float:
        prior = self.config.model_priors.get(
            model.model_name,
            self.config.prior_probability,
        )
        scale_penalty = max(
            0.0,
            1.0
            - min(
                1.0,
                features.area_ratio / self.config.small_roi_area_ratio,
            ),
        )
        value = (
            _logit(prior)
            + self.config.probability_alpha * (features.roi_confidence - 0.5)
            + self.config.probability_beta * (features.texture_score - 0.5)
            + self.config.probability_gamma * (features.quality_score - 0.5)
            - self.config.probability_delta * scale_penalty
        )
        return max(0.0, min(1.0, _sigmoid(value)))

    def estimate(
        self,
        features: RoiFeatures,
        models: list[RoutingModel],
    ) -> dict[str, float]:
        return {
            model.model_name: self.estimate_one(features, model)
            for model in models
        }


class LearnedProbabilityRunner(Protocol):
    """Explicit contract for a user-supplied local learned probability model."""

    def predict_probabilities(
        self,
        features: RoiFeatures,
        models: list[RoutingModel],
    ) -> list[float]:
        """Return probabilities in exactly the same order as models."""


class LearnedProbabilityEstimator(ProbabilityEstimator):
    """Adapter only; model format and loading remain operator supplied."""

    def __init__(self, runner: LearnedProbabilityRunner | None = None) -> None:
        self.runner = runner

    def estimate(
        self,
        features: RoiFeatures,
        models: list[RoutingModel],
    ) -> dict[str, float]:
        if not models:
            return {}
        if self.runner is None:
            raise ModelUnavailableError(
                "Learned visual routing requires an explicit local probability runner"
            )
        probabilities = self.runner.predict_probabilities(features, models)
        if len(probabilities) != len(models):
            raise ValueError("Learned probability output count does not match candidates")
        if any(probability < 0 or probability > 1 for probability in probabilities):
            raise ValueError("Learned probabilities must be within 0..1")
        return {
            model.model_name: float(probability)
            for model, probability in zip(models, probabilities, strict=True)
        }
