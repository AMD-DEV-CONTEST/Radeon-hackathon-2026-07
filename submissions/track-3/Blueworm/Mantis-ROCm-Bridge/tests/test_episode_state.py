from __future__ import annotations

import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.episode_state import EpisodeStageTracker, replay_stage_trace


ROOT = Path(__file__).resolve().parents[1]
TASK = load_json(ROOT / "configs/task-pack-v1.json")


class EpisodeStageTrackerTests(unittest.TestCase):
    def test_complete_ordered_trace_can_claim_g1(self) -> None:
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            tracker.complete_stage(stage, policy_step=index * 10, details=details)
        receipt = tracker.receipt(g1_claim=True)
        self.assertTrue(receipt["success"])
        self.assertTrue(receipt["g1_claim"])
        self.assertTrue(receipt["stage_trace_complete"])

    def test_skipped_stage_is_rejected(self) -> None:
        tracker = EpisodeStageTracker(TASK, seed=1)
        with self.assertRaises(ContractError):
            tracker.complete_stage(TASK["stages"][1], policy_step=0)

    def test_failure_is_terminal_and_preserves_taxonomy(self) -> None:
        tracker = EpisodeStageTracker(TASK, seed=1)
        tracker.complete_stage(TASK["stages"][0], policy_step=0)
        tracker.fail_stage(
            TASK["stages"][1],
            failure_stage="runtime_error",
            policy_step=3,
        )
        receipt = tracker.receipt()
        self.assertFalse(receipt["success"])
        self.assertEqual(receipt["failure_stage"], "runtime_error")
        with self.assertRaises(ContractError):
            tracker.complete_stage(TASK["stages"][2], policy_step=4)

    def test_terminal_stage_requires_strict_evidence(self) -> None:
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"][:-1]):
            tracker.complete_stage(stage, policy_step=index)
        with self.assertRaises(ContractError):
            tracker.complete_stage(
                TASK["stages"][-1],
                policy_step=20,
                details={"strict_frame_success": True, "stable_frames": 11},
            )

    def test_serialized_trace_replays_through_same_state_machine(self) -> None:
        events = []
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            events.append(
                {
                    "stage": stage,
                    "status": "completed",
                    "policy_step": index,
                    "details": details,
                }
            )
        receipt = replay_stage_trace(TASK, {"seed": 1, "events": events})
        self.assertTrue(receipt["success"])

    def test_invalid_generation_mode_rejected(self) -> None:
        """Invalid generation_mode is rejected."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        with self.assertRaises(ContractError) as cm:
            tracker.receipt(generation_mode="invalid")
        self.assertIn("generation_mode must be", str(cm.exception))

    def test_effective_limit_must_be_positive_int(self) -> None:
        """effective_policy_step_limit must be positive integer if provided."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        with self.assertRaises(ContractError) as cm:
            tracker.receipt(effective_policy_step_limit=0)
        self.assertIn("must be positive integer", str(cm.exception))

        with self.assertRaises(ContractError) as cm:
            tracker.receipt(effective_policy_step_limit=-5)
        self.assertIn("must be positive integer", str(cm.exception))

        with self.assertRaises(ContractError) as cm:
            tracker.receipt(effective_policy_step_limit="100")
        self.assertIn("must be positive integer", str(cm.exception))

    def test_effective_limit_accepted_when_valid(self) -> None:
        """Valid effective_policy_step_limit is included in receipt."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            tracker.complete_stage(stage, policy_step=index * 10, details=details)
        receipt = tracker.receipt(effective_policy_step_limit=1200)
        self.assertEqual(receipt["effective_policy_step_limit"], 1200)

    def test_g1_claim_only_allowed_in_online_mode(self) -> None:
        """G1 claim is rejected in probe and replay modes."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            tracker.complete_stage(stage, policy_step=index * 10, details=details)

        with self.assertRaises(ContractError) as cm:
            tracker.receipt(g1_claim=True, generation_mode="probe")
        self.assertIn("G1 may only be claimed in online mode", str(cm.exception))

        with self.assertRaises(ContractError) as cm:
            tracker.receipt(g1_claim=True, generation_mode="replay")
        self.assertIn("G1 may only be claimed in online mode", str(cm.exception))

    def test_probe_complete_trace_no_episode_success_claim(self) -> None:
        """Probe mode complete trace has success=true but episode_success_claim=false and g1=false."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            tracker.complete_stage(stage, policy_step=index * 10, details=details)
        receipt = tracker.receipt(generation_mode="probe")
        self.assertTrue(receipt["success"])
        self.assertFalse(receipt["episode_success_claim"])
        self.assertFalse(receipt["g1_claim"])
        self.assertIn("Diagnostic calibration stage completion only", receipt["claim_boundary"])
        self.assertIn("does NOT prove episode success", receipt["claim_boundary"])

    def test_replay_complete_trace_no_episode_success_claim(self) -> None:
        """Replay mode complete trace has success=true but episode_success_claim=false and g1=false."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            tracker.complete_stage(stage, policy_step=index * 10, details=details)
        receipt = tracker.receipt(generation_mode="replay")
        self.assertTrue(receipt["success"])
        self.assertFalse(receipt["episode_success_claim"])
        self.assertFalse(receipt["g1_claim"])
        self.assertIn("Frozen-plan stage completion only", receipt["claim_boundary"])
        self.assertIn("does NOT prove episode success", receipt["claim_boundary"])

    def test_online_complete_trace_has_episode_success_claim(self) -> None:
        """Online mode complete trace has episode_success_claim=true."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            tracker.complete_stage(stage, policy_step=index * 10, details=details)
        receipt = tracker.receipt(generation_mode="online")
        self.assertTrue(receipt["success"])
        self.assertTrue(receipt["episode_success_claim"])
        self.assertIn("A successful receipt proves ordered scripted-stage completion", receipt["claim_boundary"])

    def test_online_mode_g1_claim_works(self) -> None:
        """Online mode allows G1 claim with success."""
        tracker = EpisodeStageTracker(TASK, seed=1)
        for index, stage in enumerate(TASK["stages"]):
            details = {}
            if stage == TASK["stages"][-1]:
                details = {
                    "strict_frame_success": True,
                    "stable_frames": 12,
                    "no_safety_failure": True,
                    "no_physics_divergence": True,
                }
            tracker.complete_stage(stage, policy_step=index * 10, details=details)
        receipt = tracker.receipt(g1_claim=True, generation_mode="online")
        self.assertTrue(receipt["g1_claim"])
        self.assertTrue(receipt["episode_success_claim"])


def _complete_full_trace(tracker: EpisodeStageTracker, terminal_policy_step: int) -> None:
    """Complete every stage on a monotonic sequence ending at terminal_policy_step."""
    stage_count = len(TASK["stages"])
    for index, stage in enumerate(TASK["stages"]):
        policy_step = terminal_policy_step - (stage_count - 1 - index)
        details: dict[str, object] = {}
        if stage == TASK["stages"][-1]:
            details = {
                "strict_frame_success": True,
                "stable_frames": 12,
                "no_safety_failure": True,
                "no_physics_divergence": True,
            }
        tracker.complete_stage(stage, policy_step=policy_step, details=details)


def _trace_events_ending_at(terminal_policy_step: int) -> list[dict[str, object]]:
    """Build a serialized ordered trace whose steps end at terminal_policy_step."""
    stage_count = len(TASK["stages"])
    events: list[dict[str, object]] = []
    for index, stage in enumerate(TASK["stages"]):
        policy_step = terminal_policy_step - (stage_count - 1 - index)
        details: dict[str, object] = {}
        if stage == TASK["stages"][-1]:
            details = {
                "strict_frame_success": True,
                "stable_frames": 12,
                "no_safety_failure": True,
                "no_physics_divergence": True,
            }
        events.append(
            {
                "stage": stage,
                "status": "completed",
                "policy_step": policy_step,
                "details": details,
            }
        )
    return events


class ProbeEffectiveHorizonTests(unittest.TestCase):
    """Probe diagnostic mode may record events and emit a replay plan within an
    effective probe horizon that exceeds the frozen task step floor, while
    online/replay evidence stays strictly bounded by the task max_policy_steps."""

    def test_probe_horizon_accepts_steps_above_task_max(self) -> None:
        """A probe tracker with a raised horizon records stages past 1200 steps.

        This is the seed-1001 failure: the scripted trajectory legitimately runs
        past the task max_policy_steps during diagnostic calibration, and the
        tracker must not abort the run before the replay plan is written.
        """
        tracker = EpisodeStageTracker(
            TASK, seed=1001, effective_policy_step_limit=2400
        )
        _complete_full_trace(tracker, terminal_policy_step=1300)
        receipt = tracker.receipt(
            generation_mode="probe", effective_policy_step_limit=2400
        )
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["effective_policy_step_limit"], 2400)
        self.assertFalse(receipt["episode_success_claim"])
        self.assertFalse(receipt["g1_claim"])

    def test_probe_horizon_boundary_at_limit_is_accepted(self) -> None:
        """policy_step exactly equal to the effective horizon is allowed."""
        tracker = EpisodeStageTracker(
            TASK, seed=1001, effective_policy_step_limit=2400
        )
        tracker.complete_stage(TASK["stages"][0], policy_step=2400)

    def test_probe_horizon_rejects_steps_above_effective_limit(self) -> None:
        """Steps beyond the effective horizon are still rejected."""
        tracker = EpisodeStageTracker(
            TASK, seed=1001, effective_policy_step_limit=2400
        )
        with self.assertRaises(ContractError) as cm:
            tracker.complete_stage(TASK["stages"][0], policy_step=2401)
        self.assertIn("policy_step exceeds the task limit", str(cm.exception))

    def test_default_horizon_rejects_steps_above_task_max(self) -> None:
        """Without a raised horizon, steps above the task max are rejected.

        This preserves the strict online/replay floor.
        """
        tracker = EpisodeStageTracker(TASK, seed=1001)
        with self.assertRaises(ContractError) as cm:
            tracker.complete_stage(TASK["stages"][0], policy_step=1201)
        self.assertIn("policy_step exceeds the task limit", str(cm.exception))

    def test_default_horizon_boundary_at_task_max_is_accepted(self) -> None:
        """policy_step exactly equal to the task max is allowed by default."""
        tracker = EpisodeStageTracker(TASK, seed=1001)
        tracker.complete_stage(TASK["stages"][0], policy_step=1200)

    def test_effective_limit_below_task_max_is_rejected(self) -> None:
        """The effective horizon can never relax below the frozen task floor."""
        with self.assertRaises(ContractError) as cm:
            EpisodeStageTracker(TASK, seed=1001, effective_policy_step_limit=1000)
        self.assertIn(
            "cannot be below the task max_policy_steps", str(cm.exception)
        )

    def test_effective_limit_must_be_positive_int_at_construction(self) -> None:
        """Invalid effective horizons are rejected at construction time."""
        for invalid in (0, -5, "2400", 1200.0, True):
            with self.assertRaises(ContractError):
                EpisodeStageTracker(
                    TASK, seed=1001, effective_policy_step_limit=invalid  # type: ignore[arg-type]
                )

    def test_receipt_rejects_horizon_mismatching_enforced_limit(self) -> None:
        """The reported horizon must equal the horizon the tracker enforced."""
        tracker = EpisodeStageTracker(
            TASK, seed=1001, effective_policy_step_limit=2400
        )
        with self.assertRaises(ContractError) as cm:
            tracker.receipt(effective_policy_step_limit=1200)
        self.assertIn("must match the enforced horizon", str(cm.exception))

        reverse = EpisodeStageTracker(TASK, seed=1001)
        with self.assertRaises(ContractError):
            reverse.receipt(effective_policy_step_limit=2400)

    def test_online_and_replay_refuse_raised_horizon_in_receipt(self) -> None:
        """A raised horizon can never back an online or replay receipt."""
        tracker = EpisodeStageTracker(
            TASK, seed=1001, effective_policy_step_limit=2400
        )
        with self.assertRaises(ContractError) as cm:
            tracker.receipt(generation_mode="online")
        self.assertIn("must enforce the task max_policy_steps", str(cm.exception))
        with self.assertRaises(ContractError):
            tracker.receipt(generation_mode="replay")
        # Probe may use the raised horizon.
        probe = tracker.receipt(generation_mode="probe")
        self.assertFalse(probe["episode_success_claim"])

    def test_replay_stage_trace_threads_effective_horizon(self) -> None:
        """replay_stage_trace enforces the supplied horizon at validation time."""
        events = _trace_events_ending_at(terminal_policy_step=1300)
        # Default horizon (task max) rejects a trace that exceeds 1200 steps.
        with self.assertRaises(ContractError):
            replay_stage_trace(TASK, {"seed": 1001, "events": events})
        # A probe-sized horizon accepts the same trace.
        receipt = replay_stage_trace(
            TASK,
            {"seed": 1001, "events": events},
            generation_mode="probe",
            effective_policy_step_limit=2400,
        )
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["effective_policy_step_limit"], 2400)


if __name__ == "__main__":
    unittest.main()
