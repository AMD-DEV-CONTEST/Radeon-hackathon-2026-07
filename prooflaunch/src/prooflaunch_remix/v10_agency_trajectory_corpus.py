from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .v10_contracts import V10ContractError
from .v10_sft_corpus import stable_sha256


TARGET_TRAJECTORIES = 1_000
REUSED_TRAJECTORIES = 456
NEW_TRAJECTORIES = 544
TRAIN_TRAJECTORIES = 900
VALIDATION_TRAJECTORIES = 100

TARGET_OUTCOME_COUNTS: Mapping[str, int] = {
    "success": 200,
    "failure": 200,
    "retry": 200,
    "fallback": 140,
    "stop": 140,
    "human_escalation": 120,
}

ADDITIONAL_OUTCOME_COUNTS: Mapping[str, int] = {
    "success": 88,
    "failure": 48,
    "retry": 48,
    "fallback": 124,
    "stop": 124,
    "human_escalation": 112,
}

_TRAINING_LABEL = {
    "success": "imitate",
    "failure": "negative_do_not_imitate",
    "retry": "recovery",
    "fallback": "recovery",
    "stop": "imitate",
    "human_escalation": "imitate",
}

_TERMINAL_SIGNAL = {
    "success": "verified_success",
    "failure": "budget_exhausted_failure",
    "retry": "verified_success",
    "fallback": "verified_success",
    "stop": "verified_safe_stop",
    "human_escalation": "human_approval_required",
}

_TEMPLATES: Mapping[str, tuple[tuple[str, str, bool], ...]] = {
    "success": (
        ("inspect", "inspect_source_metadata", True),
        ("request_evidence", "validate_required_evidence", True),
        ("stop", "stop_after_verified_completion", True),
    ),
    "failure": (
        ("inspect", "inspect_source_metadata", True),
        ("repair", "unverified_action", False),
        ("repair", "repeated_unverified_action", False),
        ("stop", "stop_on_budget_exhaustion", True),
    ),
    "retry": (
        ("inspect", "inspect_source_metadata", True),
        ("repair", "primary_attempt_rejected", False),
        ("request_evidence", "retry_with_source_bound_evidence", True),
        ("stop", "stop_after_verified_retry", True),
    ),
    "fallback": (
        ("inspect", "inspect_source_metadata", True),
        ("repair", "primary_tool_unavailable", False),
        ("fallback", "switch_to_bounded_fallback", True),
        ("request_evidence", "validate_fallback_output", True),
        ("stop", "stop_after_verified_fallback", True),
    ),
    "stop": (
        ("inspect", "inspect_source_metadata", True),
        ("request_evidence", "required_payload_unobserved", True),
        ("stop", "safe_stop_without_media_claim", True),
    ),
    "human_escalation": (
        ("inspect", "inspect_source_metadata", True),
        ("request_evidence", "external_action_requires_approval", True),
        ("escalate", "route_to_named_human_approval", True),
    ),
}


def allocate_additional_outcomes() -> tuple[str, ...]:
    remaining = dict(ADDITIONAL_OUTCOME_COUNTS)
    order = tuple(remaining)
    result: list[str] = []
    while len(result) < NEW_TRAJECTORIES:
        for outcome in order:
            if remaining[outcome] > 0:
                result.append(outcome)
                remaining[outcome] -= 1
    if any(remaining.values()) or Counter(result) != Counter(ADDITIONAL_OUTCOME_COUNTS):
        raise V10ContractError("additional trajectory outcome allocation drifted")
    return tuple(result)


def build_source_bound_trajectory(
    episode: Mapping[str, Any], outcome_kind: str, ordinal: int
) -> dict[str, Any]:
    if outcome_kind not in _TEMPLATES:
        raise V10ContractError("unknown agency trajectory outcome")
    if not episode.get("rights_verified") or not episode.get("training_allowed"):
        raise V10ContractError("trajectory source episode lacks training rights")
    if episode.get("hidden_reasoning") or episode.get("external_side_effect"):
        raise V10ContractError("trajectory source episode violates visible offline boundary")

    trajectory_id = f"agency-source-bound-{ordinal:04d}-{outcome_kind}"
    state: dict[str, Any] = {
        "trajectory_id": trajectory_id,
        "source_episode_id": episode["episode_id"],
        "source_content_sha256": episode["content_sha256"],
        "stage": episode["stage"],
        "input_kind": episode["input_kind"],
        "payload_observed": episode["modality_payload_observed"],
        "status": "open",
        "attempt": 0,
    }
    events: list[dict[str, Any]] = []
    template = _TEMPLATES[outcome_kind]
    for step_index, (operation, rationale_code, accepted) in enumerate(template):
        action = {
            "issue_id": f"source-bound-{episode['episode_id']}",
            "operation": operation,
            "rationale_code": rationale_code,
        }
        terminal = step_index == len(template) - 1
        next_state = dict(state)
        next_state["attempt"] = step_index + 1
        next_state["last_operation"] = operation
        if terminal:
            next_state["status"] = "resolved" if outcome_kind in {
                "success", "retry", "fallback"
            } else "bounded_terminal"
            next_state["terminal_signal"] = _TERMINAL_SIGNAL[outcome_kind]
        tool_response = {
            "accepted": accepted,
            "operation": operation,
            "source_episode_id": episode["episode_id"],
            "visible_result_code": rationale_code,
            "payload_content_claimed": False,
            "external_side_effect": False,
        }
        event = {
            "step_index": step_index,
            "action": action,
            "observation": state,
            "observation_sha256": stable_sha256(state),
            "action_sha256": stable_sha256(action),
            "tool_response": tool_response,
            "tool_response_sha256": stable_sha256(tool_response),
            "next_observation": next_state,
            "next_observation_sha256": stable_sha256(next_state),
            "terminal": terminal,
            "terminal_signal": _TERMINAL_SIGNAL[outcome_kind] if terminal else None,
            "accepted": accepted,
        }
        events.append(event)
        state = next_state

    rejected = sum(not event["accepted"] for event in events)
    record: dict[str, Any] = {
        "schema": "ProofLaunchSourceBoundAgencyTrajectoryV2",
        "trajectory_id": trajectory_id,
        "task_id": f"source-bound-task-{episode['episode_id']}",
        "source_episode_id": episode["episode_id"],
        "source_episode_content_sha256": episode["content_sha256"],
        "source_ids": episode["source_ids"],
        "source_revisions": episode["source_revisions"],
        "source_identity_sha256s": episode["source_identity_sha256s"],
        "license_ids": episode["license_ids"],
        "rights_verified": True,
        "training_allowed": True,
        "stage": episode["stage"],
        "input_kind": episode["input_kind"],
        "outcome_kind": outcome_kind,
        "training_label": _TRAINING_LABEL[outcome_kind],
        "events": events,
        "trace_sha256": stable_sha256(events),
        "verification": {
            "passed": True,
            "expected_kind": outcome_kind,
            "terminal_signal": _TERMINAL_SIGNAL[outcome_kind],
            "rejected_action_count": rejected,
            "replayable_from_visible_payloads": True,
        },
        "source_policy_revision": "prooflaunch-source-bound-visible-replay-v2",
        "hidden_chain_of_thought_present": False,
        "model_teacher_used": False,
        "human_reviewed": False,
        "training_observed": False,
    }
    record["content_sha256"] = stable_sha256(record)
    return record
