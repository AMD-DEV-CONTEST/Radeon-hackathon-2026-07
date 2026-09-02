from radeon_home.evaluation_report import (
    classify_trial,
    compare_modes,
    render_markdown,
)


def test_classify_trial_identifies_safety_gate_stage() -> None:
    result = classify_trial(
        {
            "seed": 7,
            "grasp_success": True,
            "place_success": False,
            "transport_success": False,
            "terminated_reason": "payload_lost_during_transport",
        }
    )
    assert result["failure_stage"] == "transport"


def test_classify_trial_handles_early_grasp_failure() -> None:
    result = classify_trial(
        {
            "grasp_success": False,
            "transport_success": False,
            "terminated_reason": "grasp_not_verified",
        }
    )
    assert result["failure_stage"] == "grasp"


def test_compare_modes_reports_percentage_point_gain() -> None:
    physical = {
        "attempted_trials": 3,
        "transport_success_rate": 1 / 3,
        "trials": [{"transport_success": True}],
    }
    latch = {
        "attempted_trials": 3,
        "transport_success_rate": 1.0,
        "mean_place_xy_error_m": 0.137,
        "trials": [{"transport_success": True}],
    }
    comparison = compare_modes(physical, latch)
    assert round(comparison["success_rate_gain_percentage_points"], 1) == 66.7
    assert "task-level simulation constraint" in comparison["disclosure"]


def test_bilingual_report_contains_required_disclosure() -> None:
    comparison = compare_modes(
        {"attempted_trials": 3, "transport_success_rate": 1 / 3},
        {
            "attempted_trials": 3,
            "transport_success_rate": 1.0,
            "mean_place_xy_error_m": 0.137,
        },
    )
    report = render_markdown(comparison)
    assert "中文" in report
    assert "English" in report
    assert "不代表纯物理抓取成功率" in report
