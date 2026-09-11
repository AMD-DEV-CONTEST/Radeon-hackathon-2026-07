import math
import unittest
from collections import deque

from parcel_sorter.mobile_harness import (
    MobileHarnessConfig,
    build_mobile_failure_replay_manifest,
    force_memory_scale_cap,
    select_mobile_harness_action,
    transport_deadline_requires_expert,
)
from parcel_sorter.mobile_pi05_contract import PI05ResidualContext
from parcel_sorter.mobile_vla_controller import (
    MobileVLAHarnessController,
    aggregate_pi05_absolute_action_chunk,
    aggregate_pi05_residual_action_chunk,
    prepare_pi05_absolute_open_loop_action_chunk,
    evaluate_vla_goal_judgement,
    prepare_pi05_open_loop_action_chunk,
    resolve_pi05_chunk_execution_steps,
    select_vla_policy_task,
    update_primitive_progress_peak,
)


def _state(*, force_n: float = 0.0) -> tuple[float, ...]:
    values = [0.0] * 43
    values[24:31] = [0.40, 0.10, 0.30, 1.0, 0.0, 0.0, 0.0]
    values[31:38] = [0.40, -0.10, 0.30, 1.0, 0.0, 0.0, 0.0]
    values[38:40] = [force_n, 0.0]
    return tuple(values)


def _action(*, left_tool: float = 1.0) -> tuple[float, ...]:
    return (
        0.03, 0.0, 0.0,
        0.42, 0.10, 0.30, 1.0, 0.0, 0.0, 0.0, left_tool,
        0.42, -0.10, 0.30, 1.0, 0.0, 0.0, 0.0, 1.0,
    )


class MobileHarnessTests(unittest.TestCase):
    def test_absolute_chunk_aggregation_keeps_final_progress(self) -> None:
        first = tuple(float(index) for index in range(23))
        second = tuple(float(index + 2) for index in range(23))
        result = aggregate_pi05_absolute_action_chunk(
            (first, second), execution_steps=2
        )
        self.assertEqual(len(result), 23)
        self.assertEqual(result[0], 1.0)
        self.assertEqual(result[-1], second[-1])

    def test_absolute_ordered_chunk_uses_fused_mode_logits(self) -> None:
        row = tuple(float(index) for index in range(23))
        result = prepare_pi05_absolute_open_loop_action_chunk(
            (row, row), execution_steps=2, mode_logits=(9.0, 8.0, 7.0)
        )
        self.assertEqual(result[0][19:22], (9.0, 8.0, 7.0))
        self.assertEqual(result[0][22], row[22])

    def test_ordered_queue_is_visible_to_the_control_rate_scheduler(self) -> None:
        controller = object.__new__(MobileVLAHarnessController)
        controller._chunk_execution_protocol = "pi05-open-loop-queue-v1"
        controller._action_chunk_queue = deque(((0.0,),))
        controller._queued_chunk_stage = "transport"
        self.assertTrue(controller.has_queued_action("transport"))
        self.assertFalse(controller.has_queued_action("lift"))

    def test_runtime_reset_clears_episode_progress_state(self) -> None:
        controller = object.__new__(MobileVLAHarnessController)
        controller._calls = 5
        controller._inference_calls = 3
        controller._force_history_n = deque((1.0, 2.0), maxlen=4)
        controller._external_force_observation_pending = True
        controller._primitive_progress_peak = 0.95
        controller._progress_stage = "transport"
        controller._action_chunk_queue = deque(((0.0,),))
        controller._queued_chunk_stage = "transport"
        controller._queued_chunk_seed = 1
        controller._queued_mode_head_output = None
        controller._queued_chunk_total = 1
        controller._last_policy_output = (0.0,)
        controller.reset_runtime_state()
        self.assertEqual(controller._primitive_progress_peak, 0.0)
        self.assertIsNone(controller._progress_stage)
        self.assertFalse(controller._action_chunk_queue)

    def test_stage_aware_chunk_horizon_is_explicit_and_bounded(self) -> None:
        stage_steps = {
            "pregrasp": 1,
            "grasp_approach": 2,
            "lift": 3,
            "transport": 10,
        }
        self.assertEqual(
            resolve_pi05_chunk_execution_steps(
                "grasp_approach", 1, stage_steps, chunk_size=30
            ),
            2,
        )
        self.assertEqual(
            resolve_pi05_chunk_execution_steps(
                "release", 1, stage_steps, chunk_size=30
            ),
            1,
        )
        with self.assertRaisesRegex(ValueError, "within the policy chunk"):
            resolve_pi05_chunk_execution_steps(
                "transport", 1, {"transport": 31}, chunk_size=30
            )

    def test_stage_aware_chunk_horizon_rejects_unknown_stage(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported stages"):
            resolve_pi05_chunk_execution_steps(
                "transport", 1, {"dock": 2}, chunk_size=30
            )

    def test_controller_resolves_runtime_chunk_horizon_from_its_config(self) -> None:
        controller = object.__new__(MobileVLAHarnessController)
        controller._config = type("Config", (), {"chunk_size": 30})()
        controller._chunk_execution_steps = 1
        controller._stage_chunk_execution_steps = {"pregrasp": 2}

        self.assertEqual(
            controller._effective_chunk_execution_steps("pregrasp"),
            2,
        )

    def test_pi05_chunk_aggregation_matches_a_slow_execution_window(self) -> None:
        rows = []
        for step in range(4):
            action = [float(step)] * 14
            action[12] = -1.0 if step < 3 else 1.0
            action[13] = step / 3.0
            rows.append(action)
        reduced = aggregate_pi05_residual_action_chunk(rows, execution_steps=3)
        self.assertEqual(reduced[:12], (1.0,) * 12)
        self.assertEqual(reduced[12], -1.0)
        self.assertAlmostEqual(reduced[13], 2.0 / 3.0)

    def test_pi05_chunk_aggregation_rejects_wrong_action_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "14-D"):
            aggregate_pi05_residual_action_chunk([[0.0] * 13], execution_steps=1)

    def test_pi05_open_loop_chunk_preserves_temporal_order(self) -> None:
        rows = []
        for step in range(4):
            action = [float(step)] * 14
            action[12] = -1.0 if step < 2 else 1.0
            action[13] = step / 3.0
            rows.append(action)

        window = prepare_pi05_open_loop_action_chunk(
            rows,
            execution_steps=3,
            mode_logits=(0.5, -0.25, 0.75),
        )

        self.assertEqual([row[0] for row in window], [0.0, 1.0, 2.0])
        self.assertTrue(all(row[9:12] == (0.5, -0.25, 0.75) for row in window))
        self.assertEqual([row[12] for row in window], [-1.0, -1.0, 1.0])
        self.assertEqual([row[13] for row in window], [0.0, 1.0 / 3.0, 2.0 / 3.0])

    def test_force_memory_observation_is_decoupled_from_inference(self) -> None:
        controller = object.__new__(MobileVLAHarnessController)
        controller._force_history_n = deque(maxlen=3)
        controller._external_force_observation_pending = False

        controller.observe_contact_forces(-2.0, 3.5)
        controller.observe_contact_forces(4.0, 1.0)

        self.assertEqual(tuple(controller._force_history_n), (3.5, 4.0))
        self.assertTrue(controller._external_force_observation_pending)
        with self.assertRaisesRegex(ValueError, "finite"):
            controller.observe_contact_forces(math.nan, 0.0)

    def test_runtime_reset_restarts_common_random_number_panel(self) -> None:
        controller = object.__new__(MobileVLAHarnessController)
        controller._calls = 7
        controller._inference_calls = 18
        controller._force_history_n = deque((2.0, 3.0), maxlen=3)
        controller._external_force_observation_pending = True
        controller._action_chunk_queue = deque(((0.0,) * 14,))
        controller._queued_chunk_stage = "pregrasp"
        controller._queued_chunk_seed = 20260744
        controller._queued_mode_head_output = (1.0, 0.0, 0.0)
        controller._queued_chunk_total = 1
        controller._last_policy_output = (0.0,) * 14

        controller.reset_runtime_state()

        self.assertEqual(controller._calls, 0)
        self.assertEqual(controller._inference_calls, 0)
        self.assertEqual(tuple(controller._force_history_n), ())
        self.assertFalse(controller._external_force_observation_pending)
        self.assertEqual(tuple(controller._action_chunk_queue), ())
        self.assertIsNone(controller._queued_chunk_seed)
        self.assertIsNone(controller._last_policy_output)

    def test_pi05_residual_inference_adds_mode_blind_observable_context(self) -> None:
        task = "Recover contact and transport the parcel to the marked destination."
        context = PI05ResidualContext(
            sealed_cup_mask=(False, False, False),
            parcel_shape="box",
            parcel_size_m=(0.064, 0.0375, 0.0285),
            parcel_mass_kg=0.08,
            grasp_mode="top_suction",
            retry_index=0,
            stage="pregrasp",
            left_force_history_n=(),
            right_force_history_n=(),
            left_contact_anchor_m=(0.0, 0.0, 0.0),
            right_contact_anchor_m=(0.0, 0.0, 0.0),
            grasp_mode_conditioned=False,
        )
        selected = select_vla_policy_task(
            task,
            "pregrasp",
            uses_progress_channel=True,
            uses_residual_contract=True,
            residual_context=context,
        )
        self.assertIn("shape box", selected)
        self.assertIn("current phase pregrasp", selected)
        self.assertNotIn("top_suction", selected)

    def test_legacy_progress_checkpoint_keeps_primitive_prompt(self) -> None:
        task = "Sort the parcel safely."
        selected = select_vla_policy_task(
            task,
            "lift",
            uses_progress_channel=True,
            uses_residual_contract=False,
        )
        self.assertIn("Lift the attached parcel", selected)
        self.assertIn(task, selected)

    def test_progress_peak_is_latched_within_stage_and_reset_between_stages(self) -> None:
        peak = update_primitive_progress_peak(0.0, 0.92, stage_changed=True)
        self.assertEqual(peak, 0.92)
        self.assertEqual(
            update_primitive_progress_peak(peak, 0.78, stage_changed=False),
            0.92,
        )
        self.assertEqual(
            update_primitive_progress_peak(peak, 0.10, stage_changed=True),
            0.10,
        )

    def test_goal_judgement_blocks_a_transport_proposal_away_from_target(self) -> None:
        state = list(_state())
        state[0:2] = [0.0, 0.0]
        state[40:42] = [0.30, 0.0]
        judgement = evaluate_vla_goal_judgement(
            state,
            (-0.04, 0.0),
            stage="transport",
            primitive_complete=False,
            goal_xy=(0.30, 0.0),
        )
        self.assertFalse(judgement.direction_consistent)
        self.assertEqual(judgement.scale_cap, 0.0)

    def test_goal_judgement_accepts_arrival_only_inside_tolerance(self) -> None:
        state = list(_state())
        state[0:2] = [0.29, 0.0]
        state[40:42] = [0.30, 0.0]
        judgement = evaluate_vla_goal_judgement(
            state,
            (0.01, 0.0),
            stage="transport",
            primitive_complete=True,
            goal_xy=(0.30, 0.0),
        )
        self.assertTrue(judgement.arrival_claimed)
        self.assertTrue(judgement.arrival_verified)

    def test_force_memory_preserves_full_scale_for_stable_low_contact(self) -> None:
        decision = force_memory_scale_cap((4.0, 4.5, 4.2, 4.6))
        self.assertEqual(decision.scale_cap, 1.0)
        self.assertEqual(decision.reasons, ("stable_force_history",))

    def test_force_memory_caps_vla_for_rising_contact(self) -> None:
        memory = force_memory_scale_cap((4.0, 5.0, 8.0, 12.0))
        self.assertEqual(memory.scale_cap, 0.0)
        decision = select_mobile_harness_action(
            state=_state(),
            expert_action=_action(),
            vla_action=_action(),
            stage="transport",
            maximum_vla_scale=memory.scale_cap,
        )
        self.assertEqual(decision.selected.scale, 0.0)
        self.assertTrue(decision.fallback_to_expert)
        self.assertTrue(
            any(
                "force_memory_scale_gate" in candidate.reasons
                for candidate in decision.candidates
                if candidate.scale > 0.0
            )
        )

    def test_transport_deadline_handoff_preserves_completion_capacity(self) -> None:
        self.assertFalse(
            transport_deadline_requires_expert(
                distance_m=0.30,
                remaining_time_s=10.0,
                expert_forward_speed_m_s=0.05,
            )
        )
        self.assertTrue(
            transport_deadline_requires_expert(
                distance_m=0.045,
                remaining_time_s=1.0,
                expert_forward_speed_m_s=0.05,
            )
        )
        self.assertFalse(
            transport_deadline_requires_expert(
                distance_m=0.004,
                remaining_time_s=0.1,
                expert_forward_speed_m_s=0.0,
            )
        )

    def test_payload_aware_progress_floor_bounds_transport_slowdown(self) -> None:
        expert = list(_action())
        expert[:3] = [0.05, 0.0, 0.0]
        vla = list(expert)
        vla[:3] = [0.0, 0.0, 0.0]
        decision = select_mobile_harness_action(
            state=_state(),
            expert_action=expert,
            vla_action=vla,
            stage="transport",
            config=MobileHarnessConfig(min_progress_ratio=0.75),
        )
        self.assertGreater(decision.selected.scale, 0.0)
        self.assertAlmostEqual(decision.selected.min_progress_ratio, 0.75)
        self.assertAlmostEqual(decision.selected.action[0], 0.0375)

    def test_selects_largest_safe_bounded_residual(self) -> None:
        expert = _action()
        vla = list(expert)
        vla[0] = 0.20
        vla[3] = 0.50
        decision = select_mobile_harness_action(
            state=_state(), expert_action=expert, vla_action=vla, stage="transport"
        )
        self.assertFalse(decision.emergency_stop)
        self.assertGreater(decision.selected.scale, 0.0)
        self.assertLessEqual(math.hypot(*decision.selected.action[:2]), 0.05)
        self.assertLessEqual(math.dist(decision.selected.action[3:6], _state()[24:27]), 0.04)

    def test_stage_interlock_corrects_release_tool_command(self) -> None:
        expert = _action(left_tool=-1.0)
        vla = _action(left_tool=1.0)
        decision = select_mobile_harness_action(
            state=_state(), expert_action=expert, vla_action=vla, stage="release"
        )
        self.assertEqual(decision.selected.action[10], -1.0)
        self.assertEqual(decision.selected.tool_command_corrections, 1)
        self.assertIn("stage_tool_interlock", decision.selected.reasons)

    def test_near_contact_base_residual_preserves_nominal_progress(self) -> None:
        expert = list(_action())
        expert[:3] = [0.002, 0.010, 0.0]
        vla = list(expert)
        vla[:3] = [0.002, -0.010, 0.0]
        decision = select_mobile_harness_action(
            state=_state(), expert_action=expert, vla_action=vla, stage="grasp_approach"
        )
        selected = decision.selected.action
        progress = (selected[0] * expert[0] + selected[1] * expert[1]) / (
            expert[0] ** 2 + expert[1] ** 2
        )
        self.assertGreaterEqual(progress, 0.5)
        self.assertGreaterEqual(selected[1], 0.0)
        self.assertTrue(decision.fallback_to_expert)
        self.assertIn("contact_precision_handoff", decision.selected.reasons)

    def test_grasp_approach_accepts_nominal_top_suction_speed(self) -> None:
        expert = list(_action())
        expert[:3] = [0.0, 0.12, 0.0]
        decision = select_mobile_harness_action(
            state=_state(),
            expert_action=expert,
            vla_action=expert,
            stage="grasp_approach",
        )
        self.assertFalse(decision.emergency_stop)
        self.assertAlmostEqual(math.hypot(*decision.selected.action[:2]), 0.12)

    def test_residual_contract_preserves_nominal_arm_target(self) -> None:
        expert = list(_action())
        expert[3:6] = [0.70, 0.40, 0.60]
        vla = list(expert)
        vla[3] += 0.01
        decision = select_mobile_harness_action(
            state=_state(),
            expert_action=expert,
            vla_action=vla,
            stage="pregrasp",
            arm_reference_is_expert_target=True,
        )
        self.assertFalse(decision.emergency_stop)
        self.assertAlmostEqual(decision.selected.action[3], 0.71)
        self.assertAlmostEqual(decision.selected.action[4], 0.40)
        self.assertAlmostEqual(decision.selected.action[5], 0.60)

    def test_absolute_vla_does_not_blend_expert_motion(self) -> None:
        expert = list(_action())
        expert[:3] = [-0.03, 0.0, 0.0]
        expert[3:6] = [0.38, 0.10, 0.30]
        vla = list(_action())
        vla[:3] = [0.03, 0.01, 0.0]
        vla[3:6] = [0.42, 0.11, 0.30]
        decision = select_mobile_harness_action(
            state=_state(),
            expert_action=expert,
            vla_action=vla,
            stage="transport",
            absolute_vla_action=True,
        )
        self.assertEqual(decision.selected.scale, 1.0)
        self.assertFalse(decision.fallback_to_expert)
        self.assertAlmostEqual(decision.selected.action[0], 0.03)
        self.assertAlmostEqual(decision.selected.action[1], 0.01)
        self.assertAlmostEqual(decision.selected.action[3], 0.42)
        self.assertAlmostEqual(decision.selected.action[4], 0.11)

    def test_absolute_vla_safety_scale_moves_from_observed_state(self) -> None:
        expert = list(_action())
        expert[3] = 0.38
        vla = list(_action())
        vla[3] = 0.42
        decision = select_mobile_harness_action(
            state=_state(),
            expert_action=expert,
            vla_action=vla,
            stage="transport",
            maximum_vla_scale=0.5,
            absolute_vla_action=True,
        )
        self.assertEqual(decision.selected.scale, 0.5)
        self.assertFalse(decision.fallback_to_expert)
        self.assertAlmostEqual(decision.selected.action[3], 0.41)

    def test_absolute_release_uses_deterministic_tool_interlock_only(self) -> None:
        decision = select_mobile_harness_action(
            state=_state(),
            expert_action=_action(left_tool=1.0),
            vla_action=_action(left_tool=1.0),
            stage="release",
            absolute_vla_action=True,
        )
        self.assertEqual(decision.selected.action[10], -1.0)
        self.assertFalse(decision.fallback_to_expert)
        self.assertIn("deterministic_release_interlock", decision.selected.reasons)

    def test_force_gate_stops_base_holds_arms_and_releases_suction(self) -> None:
        decision = select_mobile_harness_action(
            state=_state(force_n=35.0),
            expert_action=_action(),
            vla_action=_action(),
            stage="lift",
        )
        self.assertTrue(decision.emergency_stop)
        self.assertEqual(decision.selected.action[:3], (0.0, 0.0, 0.0))
        self.assertEqual(decision.selected.action[10], -1.0)
        self.assertEqual(decision.selected.action[3:10], _state()[24:31])

    def test_invalid_vla_falls_back_to_expert(self) -> None:
        decision = select_mobile_harness_action(
            state=_state(), expert_action=_action(), vla_action=(math.nan,) * 19, stage="lift"
        )
        self.assertTrue(decision.rejected_vla)
        self.assertTrue(decision.fallback_to_expert)
        self.assertEqual(decision.selected.scale, 0.0)

    def test_mobile_failure_manifest_prioritizes_heavy_lift_boundaries(self) -> None:
        summary = {
            "results": [
                {"episode_id": "ok", "success": True},
                {
                    "episode_id": "heavy",
                    "profile": "medium_carton",
                    "success": False,
                    "failure_stage": "lift_success",
                    "max_contact_force_n": 13.4,
                    "parameters": {"mass_kg": 0.65, "friction": 0.8},
                },
                {
                    "episode_id": "light",
                    "profile": "small_carton",
                    "success": False,
                    "failure_stage": "lift_success",
                    "max_contact_force_n": 9.0,
                    "parameters": {"mass_kg": 0.55, "friction": 0.9},
                },
            ]
        }
        manifest = build_mobile_failure_replay_manifest(summary)
        self.assertEqual([item["episode_id"] for item in manifest["items"]], ["heavy", "light"])
        self.assertAlmostEqual(manifest["items"][0]["curriculum_bridge"]["mass_kg"], 0.585)
        self.assertEqual(manifest["counts_by_failure_stage"], {"lift_success": 2})


if __name__ == "__main__":
    unittest.main()
