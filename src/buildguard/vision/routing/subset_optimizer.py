"""Exact and deterministic greedy visual model subset optimization."""

from __future__ import annotations

import math
from itertools import combinations

from buildguard.config import VisionRoutingConfig
from buildguard.vision.routing.schemas import ScoredRoutingModel, SubsetScore

UTILITY_EPSILON = 1e-12
EXACT_ENUMERATION_LIMIT = 12


class SubsetOptimizer:
    def __init__(self, config: VisionRoutingConfig) -> None:
        self.config = config

    @staticmethod
    def _names(selected: list[ScoredRoutingModel]) -> list[str]:
        return sorted(item.model.model_name for item in selected)

    def score(
        self,
        selected: list[ScoredRoutingModel],
        candidates: list[ScoredRoutingModel],
    ) -> SubsetScore:
        benefit = 1.0 - math.prod(
            1.0 - item.probability * item.model.reliability
            for item in selected
        )
        available_classes = {
            label
            for candidate in candidates
            for label in candidate.model.defect_classes
        }
        selected_classes = {
            label
            for candidate in selected
            for label in candidate.model.defect_classes
        }
        coverage = (
            len(selected_classes) / len(available_classes)
            if available_classes
            else 0.0
        )
        total_cost = sum(item.cost for item in selected)
        call_fraction = len(selected) / len(candidates) if candidates else 0.0
        utility = (
            self.config.benefit_weight * benefit
            + self.config.coverage_weight * coverage
            - self.config.cost_weight * total_cost
            - self.config.call_count_weight * call_fraction
        )
        return SubsetScore(
            selected_model_names=self._names(selected),
            benefit=benefit,
            coverage=coverage,
            total_cost=total_cost,
            utility=utility,
        )

    @staticmethod
    def _better(candidate: SubsetScore, current: SubsetScore | None) -> bool:
        if current is None:
            return True
        if candidate.utility > current.utility + UTILITY_EPSILON:
            return True
        if current.utility > candidate.utility + UTILITY_EPSILON:
            return False
        if candidate.total_cost < current.total_cost - UTILITY_EPSILON:
            return True
        if current.total_cost < candidate.total_cost - UTILITY_EPSILON:
            return False
        if len(candidate.selected_model_names) < len(current.selected_model_names):
            return True
        if len(candidate.selected_model_names) > len(current.selected_model_names):
            return False
        return tuple(candidate.selected_model_names) < tuple(current.selected_model_names)

    def _feasible(self, selected: list[ScoredRoutingModel]) -> bool:
        return (
            len(selected) <= self.config.max_models_per_roi
            and sum(item.cost for item in selected)
            <= self.config.roi_budget + UTILITY_EPSILON
        )

    def _exact(self, candidates: list[ScoredRoutingModel]) -> SubsetScore:
        ordered = sorted(candidates, key=lambda item: item.model.model_name)
        best: SubsetScore | None = None
        maximum = min(self.config.max_models_per_roi, len(ordered))
        for count in range(maximum + 1):
            for subset in combinations(ordered, count):
                selected = list(subset)
                if not self._feasible(selected):
                    continue
                score = self.score(selected, ordered)
                if self._better(score, best):
                    best = score
        if best is None:
            return self.score([], ordered)
        return best

    def _greedy(self, candidates: list[ScoredRoutingModel]) -> SubsetScore:
        ordered = sorted(candidates, key=lambda item: item.model.model_name)
        selected: list[ScoredRoutingModel] = []
        current = self.score(selected, ordered)
        while len(selected) < self.config.max_models_per_roi:
            feasible_scores: list[tuple[SubsetScore, ScoredRoutingModel]] = []
            for candidate in ordered:
                if candidate in selected:
                    continue
                proposed = [*selected, candidate]
                if self._feasible(proposed):
                    feasible_scores.append((self.score(proposed, ordered), candidate))
            if not feasible_scores:
                break
            feasible_scores.sort(
                key=lambda item: (
                    -item[0].utility,
                    item[0].total_cost,
                    len(item[0].selected_model_names),
                    tuple(item[0].selected_model_names),
                )
            )
            proposed_score, proposed_candidate = feasible_scores[0]
            if proposed_score.utility <= current.utility + UTILITY_EPSILON:
                break
            selected.append(proposed_candidate)
            current = proposed_score
        return current

    def optimize(
        self,
        candidates: list[ScoredRoutingModel],
    ) -> tuple[SubsetScore, bool]:
        if len(candidates) <= EXACT_ENUMERATION_LIMIT:
            return self._exact(candidates), False
        return self._greedy(candidates), True
