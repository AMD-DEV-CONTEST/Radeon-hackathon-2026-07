"""Failure-aware recovery decisions shared by simulation and future real robot."""

from __future__ import annotations

from .models import FailureType, RecoveryDecision


def decide_recovery(
    failure: FailureType,
    *,
    attempt: int,
) -> RecoveryDecision:
    if failure is FailureType.GRASP_MISS:
        return RecoveryDecision(
            failure,
            "reobserve_and_rescore",
            {"candidate_offset_m": 0.015, "force_multiplier": 1.10},
            "Reobserve the object and select a non-central grasp candidate.",
        )
    if failure is FailureType.OBJECT_SLIP:
        return RecoveryDecision(
            failure,
            "slow_transport_and_regrasp",
            {"speed_multiplier": 0.60, "force_multiplier": 1.25},
            "Increase grip force and reduce transport acceleration.",
        )
    if failure is FailureType.PATH_BLOCKED:
        return RecoveryDecision(
            failure,
            "replan_with_clearance",
            {"minimum_clearance_m": 0.12, "raise_waypoint_m": 0.08},
            "Reject the blocked path and raise the transit waypoint.",
        )
    if failure is FailureType.TARGET_MOVED:
        return RecoveryDecision(
            failure,
            "refresh_target_pose",
            {"refresh_perception": True},
            "Refresh perception instead of placing at a stale target pose.",
        )
    return RecoveryDecision(
        failure,
        "replace_and_verify",
        {"placement_offset_m": 0.03 * max(1, attempt)},
        "Choose another valid point in the target region and verify again.",
    )

