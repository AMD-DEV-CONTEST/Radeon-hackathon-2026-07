"""Safety repair for empty, uncertain, small, poor-quality, and high-risk routes."""

from __future__ import annotations

from buildguard.config import VisionRoutingConfig
from buildguard.vision.routing.schemas import (
    GuardResult,
    RoiFeatures,
    ScoredRoutingModel,
)


class RecallGuard:
    def __init__(self, config: VisionRoutingConfig) -> None:
        self.config = config

    @staticmethod
    def _probability_order(
        candidates: list[ScoredRoutingModel],
    ) -> list[ScoredRoutingModel]:
        return sorted(
            candidates,
            key=lambda item: (
                -item.probability,
                item.cost,
                item.model.model_name,
            ),
        )

    @staticmethod
    def _high_risk_order(
        candidates: list[ScoredRoutingModel],
    ) -> list[ScoredRoutingModel]:
        return sorted(
            candidates,
            key=lambda item: (
                -item.model.high_risk_relevance,
                -item.probability,
                item.cost,
                item.model.model_name,
            ),
        )

    def apply(
        self,
        selected_model_names: list[str],
        candidates: list[ScoredRoutingModel],
        features: RoiFeatures,
    ) -> GuardResult:
        candidate_by_name = {
            item.model.model_name: item for item in candidates
        }
        selected = [
            candidate_by_name[name]
            for name in selected_model_names
            if name in candidate_by_name
        ]
        probability_order = self._probability_order(candidates)
        reasons: list[str] = []
        budget_limit = self.config.roi_budget * (
            1.0 + self.config.guard_budget_overrun_ratio
        )

        def add(candidate: ScoredRoutingModel, *, force: bool = False) -> bool:
            if candidate in selected:
                return True
            if len(selected) >= self.config.max_models_per_roi:
                return False
            proposed_cost = sum(item.cost for item in selected) + candidate.cost
            if not force and proposed_cost > budget_limit:
                return False
            selected.append(candidate)
            return True

        if not selected and probability_order:
            add(probability_order[0], force=True)
            reasons.append("empty_route")

        high_risk = (
            features.high_risk
            or features.roi_label in self.config.high_risk_roi_types
        )
        if high_risk:
            reasons.append("high_risk")
            for candidate in self._high_risk_order(candidates):
                if len(selected) >= min(
                    self.config.min_models_high_risk,
                    len(candidates),
                ):
                    break
                add(candidate)
            required = min(
                self.config.min_models_high_risk,
                len(candidates),
                self.config.max_models_per_roi,
            )
            if len(selected) < required:
                reasons.append("high_risk_budget_override")
                for candidate in sorted(
                    candidates,
                    key=lambda item: (
                        item.cost,
                        -item.model.high_risk_relevance,
                        -item.probability,
                        item.model.model_name,
                    ),
                ):
                    if len(selected) >= required:
                        break
                    add(candidate, force=True)

        uncertainty_reasons: list[str] = []
        if features.roi_confidence < self.config.low_confidence_threshold:
            uncertainty_reasons.append("low_confidence")
        if features.area_ratio < self.config.small_roi_area_ratio:
            uncertainty_reasons.append("small_roi")
        if features.quality_score < self.config.poor_quality_threshold:
            uncertainty_reasons.append("poor_quality")
        if len(probability_order) >= 2 and (
            probability_order[0].probability - probability_order[1].probability
            <= self.config.top_probability_gap
        ):
            uncertainty_reasons.append("top_probability_close")
        if uncertainty_reasons:
            reasons.extend(uncertainty_reasons)
            for candidate in probability_order[:2]:
                add(candidate)

        selected.sort(key=lambda item: item.model.model_name)
        total_cost = sum(item.cost for item in selected)
        return GuardResult(
            selected_model_names=[
                item.model.model_name for item in selected
            ],
            triggered=bool(reasons),
            reasons=list(dict.fromkeys(reasons)),
            budget_overrun=max(0.0, total_cost - self.config.roi_budget),
        )
