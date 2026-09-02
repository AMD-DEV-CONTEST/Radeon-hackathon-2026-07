from radeon_home.recovery_evaluation import (
    BASELINE_ACTION,
    select_recovery_action,
)


def test_baseline_action_has_no_hidden_adjustment() -> None:
    assert select_recovery_action("initial", 0) == BASELINE_ACTION
    assert BASELINE_ACTION.grasp_z_offset_m == 0.0
    assert BASELINE_ACTION.grip_preload_m == 0.0


def test_payload_loss_triggers_position_and_motion_adjustment() -> None:
    first = select_recovery_action("payload_lost", 1)
    second = select_recovery_action("payload_lost", 2)
    assert first.grasp_z_offset_m == -0.005
    assert first.grip_preload_m == 0.0003
    assert first.transport_steps == 400
    assert second.grasp_z_offset_m == 0.005
    assert second.transport_steps == 450


def test_grasp_failure_searches_both_sides_of_nominal_height() -> None:
    assert (
        select_recovery_action("grasp_failure", 1).grasp_z_offset_m == -0.005
    )
    assert (
        select_recovery_action("grasp_failure", 2).grasp_z_offset_m == 0.005
    )
