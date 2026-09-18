"""Unified full-all, rule, cost-aware, and guarded visual router."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from buildguard.config import VisionModelConfig, VisionRoutingConfig
from buildguard.vision.routing.cost_model import CostModel
from buildguard.vision.routing.probability import (
    HeuristicProbabilityEstimator,
    ProbabilityEstimator,
)
from buildguard.vision.routing.recall_guard import RecallGuard
from buildguard.vision.routing.schemas import (
    RoiFeatures,
    RoutingDecision,
    RoutingModel,
    RoutingStrategy,
    ScoredRoutingModel,
)
from buildguard.vision.routing.subset_optimizer import SubsetOptimizer
from buildguard.vision.routing.temporal_smoothing import (
    TemporalProbabilitySmoother,
)
from buildguard.vision.semantic.schemas import SemanticRoutingResult


class VisualRouter:
    """Select only enabled and applicable configured local visual models."""

    def __init__(
        self,
        config: VisionRoutingConfig,
        *,
        probability_estimator: ProbabilityEstimator | None = None,
        smoother: TemporalProbabilitySmoother | None = None,
    ) -> None:
        self.config = config
        self.probability_estimator = (
            probability_estimator or HeuristicProbabilityEstimator(config)
        )
        self.cost_model = CostModel(config)
        self.optimizer = SubsetOptimizer(config)
        self.guard = RecallGuard(config)
        self.smoother = smoother or TemporalProbabilitySmoother(
            config.temporal_alpha
        )

    @staticmethod
    def _models(
        models: Sequence[VisionModelConfig | RoutingModel],
    ) -> list[RoutingModel]:
        converted = [
            model
            if isinstance(model, RoutingModel)
            else RoutingModel.from_config(model)
            for model in models
        ]
        names = [model.model_name for model in converted]
        if len(names) != len(set(names)):
            raise ValueError("Routing model names must be unique")
        return sorted(converted, key=lambda model: model.model_name)

    def candidates(
        self,
        features: RoiFeatures,
        models: Sequence[VisionModelConfig | RoutingModel],
    ) -> list[RoutingModel]:
        return [
            model
            for model in self._models(models)
            if model.enabled and model.applies_to(features.roi_label)
        ]

    def _scored_candidates(
        self,
        features: RoiFeatures,
        models: Sequence[VisionModelConfig | RoutingModel],
        temporal_key: str | None,
        semantic_probabilities: Mapping[str, float] | None,
        semantic_weight: float,
    ) -> list[ScoredRoutingModel]:
        candidates = self.candidates(features, models)
        probabilities = self.probability_estimator.estimate(features, candidates)
        if set(probabilities) != {model.model_name for model in candidates}:
            raise ValueError("Probability estimator must return every candidate exactly once")
        if semantic_weight < 0 or semantic_weight > 1:
            raise ValueError("semantic_weight must be within 0..1")
        semantic = dict(semantic_probabilities or {})
        candidate_names = {model.model_name for model in candidates}
        unknown = set(semantic) - candidate_names
        if unknown:
            raise ValueError(
                f"Semantic probabilities contain non-candidate models: {sorted(unknown)}"
            )
        if any(value < 0 or value > 1 for value in semantic.values()):
            raise ValueError("Semantic probabilities must be within 0..1")
        if semantic:
            probabilities = {
                name: (
                    semantic_weight * semantic[name]
                    + (1.0 - semantic_weight) * heuristic
                    if name in semantic
                    else heuristic
                )
                for name, heuristic in probabilities.items()
            }
        if temporal_key is not None:
            probabilities = self.smoother.smooth(
                temporal_key,
                probabilities,
                initial_previous=(
                    features.previous_probability
                    if features.track_age > 0
                    else None
                ),
            )
        return [
            ScoredRoutingModel(
                model=model,
                probability=probabilities[model.model_name],
                cost=self.cost_model.cost(model),
            )
            for model in candidates
        ]

    def _rule_select(
        self,
        features: RoiFeatures,
        candidates: list[ScoredRoutingModel],
    ) -> list[str]:
        if not candidates:
            return []
        ordered = sorted(
            candidates,
            key=lambda item: (
                -item.model.high_risk_relevance,
                -item.probability,
                -item.model.reliability,
                item.cost,
                item.model.model_name,
            ),
        )
        high_risk = (
            features.high_risk
            or features.roi_label in self.config.high_risk_roi_types
        )
        desired = self.config.min_models_high_risk if high_risk else 1
        if features.roi_confidence < self.config.low_confidence_threshold:
            desired = max(desired, 2)
        selected: list[ScoredRoutingModel] = []
        for candidate in ordered:
            if high_risk and (
                candidate.model.high_risk_relevance
                < self.config.rule_high_risk_relevance_threshold
                and len(selected) >= 1
            ):
                continue
            if len(selected) >= min(desired, self.config.max_models_per_roi):
                break
            if sum(item.cost for item in selected) + candidate.cost <= self.config.roi_budget:
                selected.append(candidate)
        if not selected:
            selected.append(
                min(
                    candidates,
                    key=lambda item: (
                        item.cost,
                        -item.probability,
                        item.model.model_name,
                    ),
                )
            )
        return sorted(item.model.model_name for item in selected)

    def route(
        self,
        features: RoiFeatures,
        models: Sequence[VisionModelConfig | RoutingModel],
        *,
        strategy: RoutingStrategy = "cost-aware-guard",
        temporal_key: str | None = None,
        semantic_probabilities: Mapping[str, float] | None = None,
        semantic_weight: float = 0.0,
        semantic_routing: SemanticRoutingResult | None = None,
    ) -> RoutingDecision:
        if strategy not in {
            "full-all",
            "rule",
            "cost-aware",
            "cost-aware-guard",
        }:
            raise ValueError(f"Unknown routing strategy: {strategy}")
        if not self.config.enabled:
            strategy = "full-all"
        scored = self._scored_candidates(
            features,
            models,
            temporal_key,
            semantic_probabilities,
            semantic_weight,
        )
        used_greedy = False
        guard_triggered = False
        guard_reasons: list[str] = []
        if strategy == "full-all":
            selected_names = [item.model.model_name for item in scored]
        elif strategy == "rule":
            selected_names = self._rule_select(features, scored)
        else:
            optimized, used_greedy = self.optimizer.optimize(scored)
            selected_names = optimized.selected_model_names
            if strategy == "cost-aware-guard":
                guarded = self.guard.apply(selected_names, scored, features)
                selected_names = guarded.selected_model_names
                guard_triggered = guarded.triggered
                guard_reasons = guarded.reasons
        selected_set = set(selected_names)
        selected = [
            item for item in scored if item.model.model_name in selected_set
        ]
        score = self.optimizer.score(selected, scored)
        return RoutingDecision(
            strategy=strategy,
            roi_label=features.roi_label,
            candidate_model_names=[
                item.model.model_name for item in scored
            ],
            selected_model_names=score.selected_model_names,
            model_scores=scored,
            benefit=score.benefit,
            coverage=score.coverage,
            total_cost=score.total_cost,
            utility=score.utility,
            guard_triggered=guard_triggered,
            guard_reasons=guard_reasons,
            used_greedy_optimizer=used_greedy,
            probability_source=(
                "mobileclip2_blend" if semantic_probabilities else "heuristic"
            ),
            semantic_routing=semantic_routing,
        )
