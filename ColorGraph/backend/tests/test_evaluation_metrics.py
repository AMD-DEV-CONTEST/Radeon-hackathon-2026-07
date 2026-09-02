import numpy as np
import pytest

from colorgraph.evaluation.metrics import (
    banding_metrics,
    boundary_f1,
    boundary_f_score,
    classification_metrics,
    color_balance_acceptance_metrics,
    delta_e_2000,
    delta_e_itp,
    depth_temporal_scale_consistency,
    fleiss_kappa,
    interval_iou,
    mask_overlap_metrics,
    motion_compensated_temporal_stability,
    paired_cluster_bootstrap_difference,
    pairwise_ranking_metrics,
    percentile_latency,
    repair_acceptance_metrics,
    signal_range_metrics,
)


def test_shot_scene_and_transition_metrics_have_explicit_tolerance() -> None:
    boundaries = boundary_f1(
        [10, 20, 40],
        [11, 21, 30],
        tolerance_frames=1,
    )
    assert boundaries["precision"] == pytest.approx(2 / 3)
    assert boundaries["recall"] == pytest.approx(2 / 3)
    assert boundaries["f1"] == pytest.approx(2 / 3)

    transitions = interval_iou(
        [(10, 14), (30, 35)],
        [(10, 15)],
    )
    assert transitions["matched_mean_iou"] == pytest.approx(5 / 6)
    assert transitions["mean_iou"] == pytest.approx(5 / 12)

    labels = classification_metrics(
        ["forest", "unknown", "water", "forest"],
        ["forest", "mountain", "water", "mountain"],
    )
    assert labels["accuracy"] == 0.5
    assert labels["unknown_rate"] == 0.25
    assert 0 < labels["macro_f1"] < 1


def test_mask_overlap_boundary_and_motion_compensated_stability() -> None:
    reference = np.asarray(
        [[0, 0, 0], [0, 1, 1], [0, 1, 1]],
        dtype=np.float32,
    )
    identical = mask_overlap_metrics(reference, reference)
    assert identical == {"iou": 1.0, "dice": 1.0}
    assert boundary_f_score(reference, reference, tolerance_pixels=1) == 1.0

    masks = np.stack((reference, reference, reference))
    flows = np.zeros((2, 3, 3, 2), dtype=np.float32)
    temporal = motion_compensated_temporal_stability(masks, flows)
    assert temporal["mean_absolute_error"] == 0
    assert temporal["stability"] == 1


def test_depth_consistency_is_invariant_to_per_frame_scale_and_shift() -> None:
    base = np.asarray(
        [[0.0, 0.2, 0.5], [0.7, 0.8, 1.0]],
        dtype=np.float64,
    )
    metrics = depth_temporal_scale_consistency(
        np.stack((base, base * 2 + 5, base * 0.5 - 3))
    )
    assert metrics["temporal_median_absolute_error"] == pytest.approx(0, abs=1e-12)
    assert metrics["scale_coefficient_of_variation"] > 0


def test_delta_e_2000_matches_published_sharma_reference_pair() -> None:
    # First supplemental test pair from Sharma, Wu and Dalal (2005).
    first = np.asarray([[50.0, 2.6772, -79.7751]])
    second = np.asarray([[50.0, 0.0, -82.7485]])
    assert delta_e_2000(first, second)[0] == pytest.approx(2.0425, abs=5e-5)

    ictcp_a = np.asarray([[0.0, 0.0, 0.0]])
    ictcp_b = np.asarray([[1 / 720, 0.0, 0.0]])
    assert delta_e_itp(ictcp_a, ictcp_b)[0] == pytest.approx(1.0)


def test_signal_banding_ranking_consistency_and_engineering_metrics() -> None:
    signal = signal_range_metrics(np.asarray([-0.1, 0.0, 0.5, 1.0, 1.1]))
    assert signal["gamut_outside_ratio"] == pytest.approx(0.4)
    assert signal["clipping_ratio"] == pytest.approx(0.8)

    ramp = banding_metrics(np.linspace(0, 1, 1024), code_values=1024)
    assert ramp["occupied_code_ratio"] == 1
    assert ramp["banding_risk"] == 0

    ranking = pairwise_ranking_metrics(
        [2.0, -1.0, 0.5],
        [0.0, 1.0, -0.5],
        [1, -1, 1],
    )
    assert ranking["pairwise_accuracy"] == 1
    assert ranking["bradley_terry_log_loss"] < 0.25

    assert fleiss_kappa(np.asarray([[3, 0], [0, 3], [2, 1]])) > 0
    latency = percentile_latency([1, 2, 3, 4, 100])
    assert latency["latency_mean_ms"] == 22
    assert latency["latency_p95_ms"] > 80


def test_content_aware_balance_metrics_compare_expert_truth_and_baseline() -> None:
    metrics = color_balance_acceptance_metrics(
        candidate_exposure_ev=[0.05, 0.2, -0.15, 0.02],
        baseline_exposure_ev=[0.5, 0.6, 0.4, 0.5],
        reference_exposure_ev=[0.0, 0.2, -0.2, 0.0],
        candidate_temperature_kelvin=[6500, 5200, 4300, 6500],
        baseline_temperature_kelvin=[8000, 7000, 6500, 8000],
        reference_temperature_kelvin=[6400, 5100, 4200, 6400],
        candidate_tint=[0.01, -0.01, 0.02, 0],
        baseline_tint=[0.3, 0.2, 0.25, 0.3],
        reference_tint=[0, 0, 0, 0],
        candidate_clipping_ratio=[0.01, 0.02, 0.01, 0],
        baseline_clipping_ratio=[0.1, 0.2, 0.15, 0.1],
        cut_after_samples=[1],
    )

    assert metrics["candidate_exposure_mae_ev"] < 0.04
    assert metrics["exposure_mae_improvement_ev"] > 0.4
    assert metrics["white_balance_mae_improvement_mired"] > 30
    assert metrics["tint_mae_improvement"] > 0.2
    assert metrics["clipping_risk_improvement"] > 0.1
    assert (
        metrics["candidate_exposure_flicker_p95_ev"]
        < metrics["baseline_exposure_flicker_p95_ev"]
    )


def test_paired_source_cluster_bootstrap_is_deterministic() -> None:
    first = paired_cluster_bootstrap_difference(
        [1, 1, 0, 0],
        [0, 0, 0, 0],
        ["source-a", "source-a", "source-b", "source-b"],
        bootstrap_samples=100,
        bootstrap_seed=17,
    )
    second = paired_cluster_bootstrap_difference(
        [1, 1, 0, 0],
        [0, 0, 0, 0],
        ["source-a", "source-a", "source-b", "source-b"],
        bootstrap_samples=100,
        bootstrap_seed=17,
    )

    assert first == second
    assert first["mean_difference"] == 0.5
    assert first["source_groups"] == 2
    assert first["difference_ci95_low"] <= 0.5
    assert first["difference_ci95_high"] >= 0.5


def test_repair_acceptance_metrics_quantify_success_and_safe_rollbacks() -> None:
    metrics = repair_acceptance_metrics(
        should_accept=[True, True, False, False],
        accepted=[True, True, False, False],
        objectives_passed=[True, True, False, False],
        hard_safe=[True, True, True, True],
        side_effect_safe=[True, True, True, True],
        intent_drift_within_limit=[True, True, True, True],
        objective_improvement=[0.4, 0.2, 0, 0],
        intent_drift=[0.1, 0.2, 0, 0],
        source_group_ids=[
            "source-a",
            "source-b",
            "source-c",
            "source-d",
        ],
        bootstrap_samples=100,
        bootstrap_seed=23,
    )

    assert metrics["repair_success_rate"] == 1
    assert metrics["rollback_accuracy"] == 1
    assert metrics["unexpected_acceptance_rate"] == 0
    assert metrics["unsafe_acceptance_rate"] == 0
    assert metrics["accepted_objective_improvement_mean"] == pytest.approx(0.3)
