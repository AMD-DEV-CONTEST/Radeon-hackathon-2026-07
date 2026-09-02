import math

from radeon_home.mjcf_batch_evaluation import (
    aggregate_results,
    classify_trial,
    wilson_interval,
)


def test_wilson_interval_contains_observed_rate() -> None:
    lower, upper = wilson_interval(8, 10)
    assert lower < 0.8 < upper
    assert wilson_interval(0, 0) == [0.0, 0.0]


def test_classify_trial_reports_first_physical_failure() -> None:
    assert classify_trial({"transport_success": True}) == "success"
    assert classify_trial({"grasp_success": False}) == "grasp_failure"
    assert (
        classify_trial(
            {
                "grasp_success": True,
                "payload_lost_during_transport": True,
            }
        )
        == "payload_lost"
    )
    assert (
        classify_trial(
            {
                "grasp_success": True,
                "payload_lost_during_transport": False,
                "place_success": False,
            }
        )
        == "placement_failure"
    )


def test_aggregate_results_uses_nested_mjcf_metrics() -> None:
    results = [
        {
            "transport_success": True,
            "grasp_success": True,
            "payload_lost_during_transport": False,
            "place_success": True,
            "task": {"physical_object": "parcel_small"},
            "coordinate_transforms": {"transform_error_m": 0.001},
            "navigation": {
                "pickup_error_m": 0.002,
                "delivery_error_m": 0.003,
            },
            "manipulation": {
                "object_lift_m": 0.16,
                "placement_metrics": {"horizontal_error_m": 0.01},
            },
            "evaluation": {"runtime_s": 12.0},
        },
        {
            "transport_success": False,
            "grasp_success": True,
            "payload_lost_during_transport": True,
            "place_success": False,
            "task": {"physical_object": "parcel_heavy"},
            "coordinate_transforms": {"transform_error_m": 0.003},
            "navigation": {"pickup_error_m": 0.004},
            "manipulation": {"object_lift_m": 0.14},
            "evaluation": {"runtime_s": 18.0},
        },
    ]
    summary = aggregate_results(
        results, [{"seed": 3, "object_profile": "parcel_heavy"}]
    )
    assert summary["attempted_trials"] == 3
    assert summary["successful_trials"] == 1
    assert math.isclose(summary["transport_success_rate"], 1 / 3)
    assert summary["outcome_counts"] == {
        "execution_failure": 1,
        "payload_lost": 1,
        "success": 1,
    }
    assert summary["mean_transform_error_m"] == 0.002
    assert summary["mean_pickup_dock_error_m"] == 0.003
    assert summary["mean_delivery_dock_error_m"] == 0.003
    assert summary["mean_trial_runtime_s"] == 15.0
    assert summary["per_object"]["parcel_small"]["transport_success_rate"] == 1.0
    assert summary["per_object"]["parcel_heavy"]["outcome_counts"] == {
        "execution_failure": 1,
        "payload_lost": 1,
    }
