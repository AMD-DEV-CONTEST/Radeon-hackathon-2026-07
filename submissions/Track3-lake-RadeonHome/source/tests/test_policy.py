from radeon_home.models import FailureType, GraspCandidate
from radeon_home.policy import HeuristicGraspPolicy, generate_candidates
from radeon_home.recovery import decide_recovery


def test_candidate_batch_has_expected_size() -> None:
    assert len(generate_candidates(obstacle_clearance_m=0.12)) == 54


def test_policy_prefers_safe_centered_grasp_initially() -> None:
    ranked = HeuristicGraspPolicy().rank(
        generate_candidates(obstacle_clearance_m=0.14)
    )
    best = ranked[0].candidate
    assert best.offset_x_m == 0
    assert best.offset_y_m == 0
    assert best.yaw_deg == 0


def test_policy_avoids_repeating_center_after_failure() -> None:
    policy = HeuristicGraspPolicy()
    center = GraspCandidate(0, 0, 0, 0.1, 0.14, previous_failures=1)
    shifted = GraspCandidate(0.015, 0, 0, 0.1, 0.14, previous_failures=1)
    assert policy.score(shifted).score > policy.score(center).score


def test_recovery_refreshes_moved_target() -> None:
    decision = decide_recovery(FailureType.TARGET_MOVED, attempt=1)
    assert decision.action == "refresh_target_pose"
    assert decision.parameter_changes["refresh_perception"] is True

