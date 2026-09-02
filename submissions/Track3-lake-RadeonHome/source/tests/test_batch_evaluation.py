from radeon_home.batch_evaluation import aggregate_results


def test_aggregate_results_tracks_success_retry_and_errors() -> None:
    results = [
        {
            "transport_success": True,
            "retry_count": 1,
            "dock_error_m": 0.01,
            "delivery_dock_error_m": 0.02,
            "place_xy_error_m": 0.03,
        },
        {
            "transport_success": False,
            "retry_count": 0,
            "dock_error_m": 0.03,
            "delivery_dock_error_m": 0.04,
            "place_xy_error_m": 0.05,
        },
    ]
    summary = aggregate_results(results, [{"seed": 3}])
    assert summary["attempted_trials"] == 3
    assert summary["transport_success_rate"] == 1 / 3
    assert summary["retry_rate"] == 0.5
    assert summary["mean_pickup_dock_error_m"] == 0.02
