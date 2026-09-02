from __future__ import annotations

from enum import Enum


class RootCausePacketStatus(str, Enum):
    ROOT_CAUSE_PACKET_READY = "ROOT_CAUSE_PACKET_READY"
    ROOT_CAUSE_PACKET_INCOMPLETE = "ROOT_CAUSE_PACKET_INCOMPLETE"
    ROOT_CAUSE_PACKET_CONFLICT = "ROOT_CAUSE_PACKET_CONFLICT"
    ROOT_CAUSE_PACKET_STALE = "ROOT_CAUSE_PACKET_STALE"
    ROOT_CAUSE_PACKET_REJECTED = "ROOT_CAUSE_PACKET_REJECTED"
    RERUN_AUTHORIZED = "RERUN_AUTHORIZED"
    RERUN_BLOCKED_NO_PACKET = "RERUN_BLOCKED_NO_PACKET"
    RERUN_BLOCKED_STALE_PACKET = "RERUN_BLOCKED_STALE_PACKET"


READY_STATUS = RootCausePacketStatus.ROOT_CAUSE_PACKET_READY.value


REQUIRED_PACKET_FIELDS = (
    "packet_id",
    "benchmark_name",
    "candidate_id",
    "baseline_score",
    "candidate_score",
    "score_delta",
    "baseline_artifact_reference",
    "candidate_artifact_reference",
    "failing_tests",
    "regression_diff_summary",
    "suspected_patch_location",
    "suspected_failure_class",
    "repair_hypothesis",
    "expected_score_recovery",
    "rerun_scope",
    "evidence_inputs",
    "created_at",
)


CRITICAL_PACKET_FIELDS = (
    "failing_tests",
    "baseline_artifact_reference",
    "candidate_artifact_reference",
    "suspected_patch_location",
    "repair_hypothesis",
)


ALLOWED_RERUN_SCOPE_FIELDS = (
    "tool",
    "candidate_id",
    "filter",
    "max_workers",
    "max_attempts",
    "timeout_seconds",
    "run_root",
    "baseline_eval",
    "min_baseline_passed",
)
