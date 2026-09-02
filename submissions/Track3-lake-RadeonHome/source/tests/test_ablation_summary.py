import json

from radeon_home.ablation_summary import CONDITIONS, create_comparison, markdown


def test_ablation_summary_uses_matched_conditions(tmp_path) -> None:
    for index, (directory, _label, _carry, _slip) in enumerate(CONDITIONS):
        condition = tmp_path / directory
        condition.mkdir()
        (condition / "batch_summary.json").write_text(
            json.dumps(
                {
                    "attempted_trials": 2,
                    "successful_trials": index,
                    "transport_success_rate": index / 2,
                    "transport_success_wilson_95": [0.0, 1.0],
                    "grasp_success_rate": 1.0,
                    "payload_retention_rate": index / 2,
                    "place_success_rate": index / 2,
                    "outcome_counts": {"success": index},
                    "mean_place_horizontal_error_m": 0.01,
                    "mean_trial_runtime_s": 50.0,
                }
            )
        )
    result = create_comparison(tmp_path)
    assert len(result["conditions"]) == 3
    assert result["seeds"] == [20260730, 20260731]
    assert result["conditions"][0]["source"] == "A_gripper_only/batch_summary.json"
    assert "Gripper-only" in markdown(result)
