from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pytest

from buildguard.config import VisionModelConfig, VisionRoutingConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.common import BoundingBox
from buildguard.vision.routing.evaluation import (
    RoutingEvaluationCase,
    RoutingEvaluator,
    RoutingPrediction,
)
from buildguard.vision.routing.feature_extractor import RoiFeatureExtractor
from buildguard.vision.routing.probability import LearnedProbabilityEstimator
from buildguard.vision.routing.router import VisualRouter
from buildguard.vision.routing.schemas import (
    RoiContext,
    RoiFeatures,
    RoutingModel,
    ScoredRoutingModel,
)
from buildguard.vision.routing.subset_optimizer import SubsetOptimizer
from buildguard.vision.routing.temporal_smoothing import TemporalProbabilitySmoother


def model(name: str, **updates: Any) -> VisionModelConfig:
    values: dict[str, Any] = {
        "model_name": name,
        "backend": "mock",
        "applicable_roi_types": ["person"],
        "defect_classes": [f"defect_{name}"],
        "input_size": (320, 320),
        "confidence_threshold": 0.3,
        "nms_iou": 0.5,
        "device": "cpu",
        "reliability": 0.9,
        "estimated_latency_ms": 10,
        "estimated_memory_mb": 64,
        "fixed_call_cost": 0.01,
        "high_risk_relevance": 0.5,
        "enabled": True,
    }
    values.update(updates)
    return VisionModelConfig.model_validate(values)


def features(**updates: Any) -> RoiFeatures:
    values: dict[str, Any] = {
        "roi_label": "person",
        "roi_confidence": 0.8,
        "area_ratio": 0.2,
        "aspect_ratio": 1.0,
        "center": (0.5, 0.5),
        "brightness": 0.5,
        "contrast": 0.7,
        "blur": 0.1,
        "edge_density": 0.4,
        "texture_score": 0.7,
        "motion_score": 0.1,
        "track_age": 3,
        "previous_probability": 0.4,
        "previous_detection_confidence": 0.6,
        "device_load": 0.2,
        "high_risk": False,
    }
    values.update(updates)
    return RoiFeatures.model_validate(values)


def routing_config(**updates: Any) -> VisionRoutingConfig:
    values: dict[str, Any] = {
        "prior_probability": 0.7,
        "latency_reference_ms": 100,
        "memory_reference_mb": 1024,
        "benefit_weight": 1.0,
        "coverage_weight": 0.4,
        "cost_weight": 0.4,
        "call_count_weight": 0.1,
        "max_models_per_roi": 3,
        "roi_budget": 3.0,
        "min_models_high_risk": 2,
    }
    values.update(updates)
    return VisionRoutingConfig.model_validate(values)


def test_roi_feature_extraction_is_normalized_and_deterministic() -> None:
    image = np.full((100, 200, 3), 100, dtype=np.uint8)
    image[20:80, 40:160:4] = 220
    previous = np.full_like(image, 80)
    extractor = RoiFeatureExtractor()
    request = RoiContext(
        roi_label="person",
        roi_confidence=0.8,
        track_age=4,
        previous_probability=0.6,
        previous_detection_confidence=0.7,
        device_load=0.25,
    )
    first = extractor.extract(
        image,
        BoundingBox(x1=40, y1=20, x2=160, y2=80),
        request,
        previous_image=previous,
    )
    second = extractor.extract(
        image,
        BoundingBox(x1=40, y1=20, x2=160, y2=80),
        request,
        previous_image=previous,
    )
    assert first == second
    assert first.area_ratio == pytest.approx(0.36)
    assert first.aspect_ratio == pytest.approx(2.0)
    assert first.center == pytest.approx((0.5, 0.5))
    assert 0 <= first.quality_score <= 1
    assert first.motion_score > 0


def test_cost_increase_does_not_increase_model_calls() -> None:
    config = routing_config(model_priors={"a": 0.8, "b": 0.8})
    router = VisualRouter(config)
    base_models = [model("a"), model("b")]
    base = router.route(features(), base_models, strategy="cost-aware")
    expensive_models = [
        model("a"),
        model(
            "b",
            estimated_latency_ms=1000,
            estimated_memory_mb=8192,
            fixed_call_cost=5,
        ),
    ]
    expensive = router.route(features(), expensive_models, strategy="cost-aware")
    assert len(expensive.selected_model_names) <= len(base.selected_model_names)


def test_recall_guard_repairs_empty_route() -> None:
    config = routing_config(
        model_priors={"a": 0.2, "b": 0.1},
        benefit_weight=0,
        coverage_weight=0,
        cost_weight=10,
        call_count_weight=1,
    )
    router = VisualRouter(config)
    unguarded = router.route(
        features(),
        [model("a"), model("b")],
        strategy="cost-aware",
    )
    guarded = router.route(
        features(),
        [model("a"), model("b")],
        strategy="cost-aware-guard",
    )
    assert unguarded.selected_model_names == []
    assert len(guarded.selected_model_names) == 1
    assert guarded.guard_triggered
    assert "empty_route" in guarded.guard_reasons


def test_guard_never_adds_disabled_or_inapplicable_model() -> None:
    models = [
        model("candidate"),
        model("disabled", enabled=False),
        model("vehicle-only", applicable_roi_types=["vehicle"]),
    ]
    decision = VisualRouter(
        routing_config(
            benefit_weight=0,
            coverage_weight=0,
            cost_weight=10,
        )
    ).route(features(), models, strategy="cost-aware-guard")
    assert decision.candidate_model_names == ["candidate"]
    assert decision.selected_model_names == ["candidate"]


def test_high_risk_guard_selects_configured_minimum() -> None:
    config = routing_config(
        model_priors={"a": 0.8, "b": 0.7, "c": 0.6},
        max_models_per_roi=3,
        min_models_high_risk=2,
        roi_budget=1,
    )
    decision = VisualRouter(config).route(
        features(high_risk=True),
        [
            model("a", high_risk_relevance=0.9),
            model("b", high_risk_relevance=0.8),
            model("c", high_risk_relevance=0.1),
        ],
        strategy="cost-aware-guard",
    )
    assert len(decision.selected_model_names) >= 2
    assert "high_risk" in decision.guard_reasons


def test_high_risk_minimum_survives_tight_budget_without_non_candidates() -> None:
    config = routing_config(
        model_priors={"a": 0.8, "b": 0.7},
        max_models_per_roi=2,
        min_models_high_risk=2,
        roi_budget=0.05,
        guard_budget_overrun_ratio=0,
    )
    decision = VisualRouter(config).route(
        features(high_risk=True),
        [
            model("a", fixed_call_cost=1),
            model("b", fixed_call_cost=1),
            model("disabled", enabled=False),
        ],
        strategy="cost-aware-guard",
    )
    assert decision.selected_model_names == ["a", "b"]
    assert "high_risk_budget_override" in decision.guard_reasons


def test_temporal_probability_smoothing_reduces_jitter() -> None:
    smoother = TemporalProbabilitySmoother(alpha=0.5)
    first = smoother.smooth("camera-1:track-1", {"model": 0.9})
    second = smoother.smooth("camera-1:track-1", {"model": 0.1})
    raw_change = abs(0.1 - 0.9)
    smoothed_change = abs(second["model"] - first["model"])
    assert first["model"] == pytest.approx(0.9)
    assert second["model"] == pytest.approx(0.5)
    assert smoothed_change < raw_change


def test_exact_optimizer_matches_independent_small_bruteforce() -> None:
    config = routing_config(max_models_per_roi=2, roi_budget=1.0)
    optimizer = SubsetOptimizer(config)
    candidates = [
        ScoredRoutingModel(
            model=RoutingModel.from_config(model("a", defect_classes=["x"])),
            probability=0.8,
            cost=0.2,
        ),
        ScoredRoutingModel(
            model=RoutingModel.from_config(model("b", defect_classes=["y"])),
            probability=0.7,
            cost=0.25,
        ),
        ScoredRoutingModel(
            model=RoutingModel.from_config(model("c", defect_classes=["x", "y"])),
            probability=0.5,
            cost=0.5,
        ),
    ]
    optimized, used_greedy = optimizer.optimize(candidates)
    feasible = [
        optimizer.score(list(subset), candidates)
        for count in range(3)
        for subset in combinations(candidates, count)
        if sum(item.cost for item in subset) <= config.roi_budget
    ]
    brute = min(
        feasible,
        key=lambda score: (
            -score.utility,
            score.total_cost,
            len(score.selected_model_names),
            tuple(score.selected_model_names),
        ),
    )
    assert not used_greedy
    assert optimized == brute


def test_routing_is_deterministic_and_large_sets_use_greedy() -> None:
    config = routing_config(
        max_models_per_roi=3,
        model_priors={f"m{index:02d}": 0.6 for index in range(13)},
    )
    models = [model(f"m{index:02d}") for index in range(13)]
    router = VisualRouter(config)
    first = router.route(features(), models, strategy="cost-aware")
    second = router.route(features(), list(reversed(models)), strategy="cost-aware")
    assert first == second
    assert first.used_greedy_optimizer


def test_full_all_baseline_selects_every_enabled_applicable_model() -> None:
    config = routing_config(
        max_models_per_roi=1,
        min_models_high_risk=1,
        roi_budget=0.01,
    )
    models = [
        model("a"),
        model("b"),
        model("disabled", enabled=False),
        model("other-roi", applicable_roi_types=["vehicle"]),
    ]
    decision = VisualRouter(config).route(
        features(),
        models,
        strategy="full-all",
    )
    assert decision.candidate_model_names == ["a", "b"]
    assert decision.selected_model_names == ["a", "b"]


def test_learned_probability_adapter_requires_explicit_runner() -> None:
    with pytest.raises(ModelUnavailableError, match="explicit local"):
        LearnedProbabilityEstimator().estimate(
            features(),
            [RoutingModel.from_config(model("a"))],
        )


def test_unified_evaluation_outputs_all_required_metrics() -> None:
    models = [
        model("a", defect_classes=["helmet"], estimated_latency_ms=10),
        model("b", defect_classes=["edge"], estimated_latency_ms=20),
    ]
    router = VisualRouter(
        routing_config(
            model_priors={"a": 0.8, "b": 0.8},
            roi_budget=3,
        )
    )
    case = RoutingEvaluationCase(
        case_id="case-1",
        features=features(),
        ground_truth_classes=["helmet", "edge"],
        high_risk_classes=["edge"],
        model_predictions={
            "a": [
                RoutingPrediction(
                    label="helmet",
                    confidence=0.9,
                    true_positive=True,
                )
            ],
            "b": [
                RoutingPrediction(
                    label="edge",
                    confidence=0.8,
                    true_positive=True,
                )
            ],
        },
    )
    comparison = RoutingEvaluator(router, models).compare([case])
    assert set(comparison) == {
        "full-all",
        "rule",
        "cost-aware",
        "cost-aware-guard",
    }
    full = comparison["full-all"].metrics
    assert full.recall == 1
    assert full.map == 1
    assert full.high_risk_recall == 1
    assert full.call_count == 2
    assert full.call_reduction == 0
    assert full.latency_ms == 30
    assert full.vram_mb == 128
    assert full.average_models_per_roi == 2
    assert full.guard_rate == 0
    assert full.resource_source == "estimated"

    measured_case = case.model_copy(
        update={
            "measured_model_latency_ms": {"a": 12.0, "b": 21.0},
            "measured_model_vram_mb": {"a": 70.0, "b": 65.0},
        }
    )
    measured = RoutingEvaluator(router, models).evaluate(
        [measured_case], "full-all"
    ).metrics
    assert measured.resource_source == "measured"
    assert measured.latency_ms == 33
    assert measured.vram_mb == 135
