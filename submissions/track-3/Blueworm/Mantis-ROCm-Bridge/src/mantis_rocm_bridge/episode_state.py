"""Ordered stage-state machine for scripted and learned three-bowl episodes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import ContractError, validate_task_contract


class EpisodeStageTracker:
    """Reject skipped stages and issue success only after strict terminal evidence."""

    def __init__(
        self,
        task_contract: dict[str, Any],
        *,
        seed: int,
        effective_policy_step_limit: int | None = None,
    ) -> None:
        validate_task_contract(task_contract)
        if not isinstance(seed, int) or seed < 0:
            raise ContractError("episode seed must be a non-negative integer")
        stages = task_contract.get("stages")
        if (
            not isinstance(stages, list)
            or not stages
            or not all(isinstance(stage, str) and stage for stage in stages)
            or len(stages) != len(set(stages))
        ):
            raise ContractError("task stages must be unique non-empty strings")
        task_max = task_contract["max_policy_steps"]
        if effective_policy_step_limit is None:
            # Online/replay default: the episode may never exceed the frozen task floor.
            effective_limit = task_max
        else:
            if (
                not isinstance(effective_policy_step_limit, int)
                or isinstance(effective_policy_step_limit, bool)
                or effective_policy_step_limit <= 0
            ):
                raise ContractError("effective_policy_step_limit must be a positive integer")
            # The effective horizon may only raise the diagnostic probe headroom; it
            # can never relax below the frozen task max_policy_steps, which keeps
            # online/replay evidence strictly bounded by the original task limit.
            if effective_policy_step_limit < task_max:
                raise ContractError(
                    "effective_policy_step_limit cannot be below the task max_policy_steps"
                )
            effective_limit = effective_policy_step_limit
        self._task = deepcopy(task_contract)
        self._seed = seed
        self._stages = list(stages)
        self._events: list[dict[str, Any]] = []
        self._next_stage_index = 0
        self._last_policy_step = -1
        self._failure_stage: str | None = None
        self._effective_policy_step_limit = effective_limit

    @property
    def next_stage(self) -> str | None:
        if self._failure_stage is not None or self._next_stage_index >= len(self._stages):
            return None
        return self._stages[self._next_stage_index]

    def _validate_event(self, stage: str, policy_step: int) -> None:
        if self.next_stage is None:
            raise ContractError("episode is already terminal")
        if stage != self.next_stage:
            raise ContractError(f"expected stage {self.next_stage}, got {stage}")
        if not isinstance(policy_step, int) or policy_step < 0:
            raise ContractError("policy_step must be a non-negative integer")
        if policy_step < self._last_policy_step:
            raise ContractError("policy_step must be monotonic")
        if policy_step > self._effective_policy_step_limit:
            raise ContractError("policy_step exceeds the task limit")

    def complete_stage(
        self,
        stage: str,
        *,
        policy_step: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._validate_event(stage, policy_step)
        details = {} if details is None else deepcopy(details)
        if not isinstance(details, dict):
            raise ContractError("stage details must be an object")
        if stage == self._stages[-1]:
            required = self._task["success_stable_frames"]
            terminal_checks = {
                "strict_frame_success": details.get("strict_frame_success") is True,
                "stable_frames": (
                    isinstance(details.get("stable_frames"), int)
                    and details["stable_frames"] >= required
                ),
                "no_safety_failure": details.get("no_safety_failure") is True,
                "no_physics_divergence": details.get("no_physics_divergence") is True,
            }
            if not all(terminal_checks.values()):
                failed = [name for name, passed in terminal_checks.items() if not passed]
                raise ContractError(
                    "terminal stage lacks strict success evidence: " + ", ".join(failed)
                )
        self._events.append(
            {
                "stage": stage,
                "status": "completed",
                "policy_step": policy_step,
                "details": details,
            }
        )
        self._last_policy_step = policy_step
        self._next_stage_index += 1

    def fail_stage(
        self,
        stage: str,
        *,
        failure_stage: str,
        policy_step: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._validate_event(stage, policy_step)
        taxonomy = self._task["evaluation"]["failure_taxonomy"]
        if failure_stage not in taxonomy:
            raise ContractError("failure_stage is not in the frozen taxonomy")
        details = {} if details is None else deepcopy(details)
        if not isinstance(details, dict):
            raise ContractError("stage details must be an object")
        self._events.append(
            {
                "stage": stage,
                "status": "failed",
                "failure_stage": failure_stage,
                "policy_step": policy_step,
                "details": details,
            }
        )
        self._last_policy_step = policy_step
        self._failure_stage = failure_stage

    def receipt(self, *, g1_claim: bool = False, generation_mode: str = "online", effective_policy_step_limit: int | None = None) -> dict[str, Any]:
        # Validate generation_mode
        if generation_mode not in ("online", "probe", "replay"):
            raise ContractError(f"generation_mode must be 'online', 'probe', or 'replay', got {generation_mode}")

        # Validate effective_policy_step_limit if provided
        if effective_policy_step_limit is not None:
            if not isinstance(effective_policy_step_limit, int) or effective_policy_step_limit <= 0:
                raise ContractError(f"effective_policy_step_limit must be positive integer, got {effective_policy_step_limit}")
            # The reported horizon must match the horizon the tracker actually enforced.
            # A mismatch would let a receipt advertise a wider step budget than the events
            # were validated against (or vice versa).
            if effective_policy_step_limit != self._effective_policy_step_limit:
                raise ContractError(
                    f"effective_policy_step_limit ({effective_policy_step_limit}) must match "
                    f"the enforced horizon ({self._effective_policy_step_limit})"
                )

        # Online/replay must never exceed the frozen task step floor, even if the tracker
        # was constructed with a wider probe horizon.  This keeps online/replay evidence
        # strictly bounded by the original task max_policy_steps; only probe may raise it.
        if (
            generation_mode in ("online", "replay")
            and self._effective_policy_step_limit > self._task["max_policy_steps"]
        ):
            raise ContractError(
                f"{generation_mode} mode must enforce the task max_policy_steps "
                f"({self._task['max_policy_steps']}), not {self._effective_policy_step_limit}"
            )

        success = self._next_stage_index == len(self._stages) and self._failure_stage is None

        # G1 claim only allowed for online mode with success
        if g1_claim and generation_mode != "online":
            raise ContractError("G1 may only be claimed in online mode")
        if g1_claim and not success:
            raise ContractError("G1 may only be claimed by a complete strict episode")

        # episode_success_claim only for online mode
        episode_success_claim = generation_mode == "online" and success

        # g1_claim only for online mode (already validated above)
        g1_claim_final = bool(g1_claim and generation_mode == "online")

        completed = [
            event["stage"] for event in self._events if event["status"] == "completed"
        ]

        # Mode-specific claim boundaries
        if generation_mode == "online":
            claim_boundary = (
                "A successful receipt proves ordered scripted-stage completion under the "
                "strict evaluator for this seed only; it does not prove learned-policy or "
                "multi-seed performance."
            )
        elif generation_mode == "probe":
            claim_boundary = (
                "Diagnostic calibration stage completion only (probe mode). "
                "This does NOT prove episode success, G1, learned-policy, multi-seed, or ROCm claims."
            )
        elif generation_mode == "replay":
            claim_boundary = (
                "Frozen-plan stage completion only (replay mode). "
                "This does NOT prove episode success, G1, learned-policy, multi-seed, or ROCm claims."
            )
        else:
            # Should never reach here due to validation above
            raise ContractError(f"Unhandled generation_mode: {generation_mode}")

        receipt_dict = {
            "schema_version": 1,
            "task_id": self._task["task_id"],
            "protocol": self._task["protocol_version"],
            "seed": self._seed,
            "generation_mode": generation_mode,
            "success": success,
            "episode_success_claim": episode_success_claim,
            "g1_claim": g1_claim_final,
            "safety_failures": int(
                self._failure_stage
                in {"collision_safety", "joint_limit_safety", "workspace_safety"}
            ),
            "physics_divergence": self._failure_stage == "physics_divergence",
            "failure_stage": self._failure_stage,
            "policy_steps": max(self._last_policy_step, 0),
            "completed_stages": completed,
            "next_stage": self.next_stage,
            "events": deepcopy(self._events),
            "stage_trace_complete": success,
            "claim_boundary": claim_boundary,
        }
        if effective_policy_step_limit is not None:
            receipt_dict["effective_policy_step_limit"] = effective_policy_step_limit
        return receipt_dict


def replay_stage_trace(
    task_contract: dict[str, Any],
    trace: dict[str, Any],
    *,
    g1_claim: bool = False,
    generation_mode: str = "online",
    effective_policy_step_limit: int | None = None,
) -> dict[str, Any]:
    """Replay a serialized trace through the same ordered runtime state machine."""

    if not isinstance(trace, dict):
        raise ContractError("stage trace must be an object")
    events = trace.get("events")
    if not isinstance(events, list):
        raise ContractError("stage trace events must be a list")
    tracker = EpisodeStageTracker(
        task_contract,
        seed=trace.get("seed"),
        effective_policy_step_limit=effective_policy_step_limit,
    )
    for event in events:
        if not isinstance(event, dict):
            raise ContractError("every stage trace event must be an object")
        common = {
            "policy_step": event.get("policy_step"),
            "details": event.get("details"),
        }
        if event.get("status") == "completed":
            tracker.complete_stage(event.get("stage"), **common)
        elif event.get("status") == "failed":
            tracker.fail_stage(
                event.get("stage"),
                failure_stage=event.get("failure_stage"),
                **common,
            )
        else:
            raise ContractError("stage trace status must be completed or failed")
    return tracker.receipt(g1_claim=g1_claim, generation_mode=generation_mode, effective_policy_step_limit=effective_policy_step_limit)
