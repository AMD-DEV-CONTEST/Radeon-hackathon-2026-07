from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.act_closedloop_g3 import (
    AGGREGATE_ARTIFACTS,
    EXPECTED_GENESIS_VERSION,
    EXPECTED_LEROBOT_VERSION,
    FORBIDDEN_ASSISTANCE,
    G3_SEEDS,
    PER_EPISODE_ARTIFACTS,
    SMOKE_SEED,
    SafetySignals,
    EvaluatorFrame,
    _is_clamp_robot_bowl_pair,
    _contact_pairs,
    _is_allowed_proximal_pair,
    _is_same_side_clamp_pair,
    admit_policy_action,
    aggregate_receipt_claim_boundary,
    build_failure_taxonomy,
    build_sha256sums,
    classify_failure_reason,
    consume_cached_arrays,
    evaluate_g3_promotion,
    first_policy_physics_steps,
    hwc_to_chw_summary,
    is_frozen_g3_seed,
    is_smoke_seed,
    is_safety_failure_reason,
    policy_tick_to_physics_step,
    render_observation_arrays,
    run_closed_loop_episode,
    select_g3_seeds,
    smoke_seed_admission,
    taxonomy_label,
    tick_schedule,
    validate_config,
    validate_policy_config,
)
from mantis_rocm_bridge.act_openloop_inference import Observation, TensorSummary


ROOT = Path(__file__).resolve().parents[1]
GATE = load_json(ROOT / "configs" / "act-closedloop-g3-v1.json")
TASK = load_json(ROOT / "configs" / "task-pack-v1.json")
PORT = load_json(ROOT / "configs" / "mantis-port-config.json")
FIXED_PLAN = load_json(ROOT / "configs" / "fixed-base-plan.json")
INTERFACE = load_json(ROOT / "configs" / "mantis-lerobot-interface-v1.json")

ENV_SHAPE = (3, 240, 320)
WRIST_SHAPE = (3, 240, 424)

# A frozen "stacked" evaluator frame: three bowls axis-aligned at the target
# heights, zero velocity, grippers fully open -> frame_success True under the
# strict evaluator with no safety failure.
STACKED_POSITIONS = (
    (0.0, -0.1, 0.74),
    (0.0, -0.1, 0.77),
    (0.0, -0.1, 0.81),
)
# An unstacked frame: bowls on the table far apart -> frame_success False.
UNSTACKED_POSITIONS = (
    (-0.2, -0.1, 0.741),
    (0.0, 0.0, 0.741),
    (0.2, 0.1, 0.741),
)
ZERO_VELOCITY = ((0.0, 0.0, 0.0),) * 3


def _valid_policy_config() -> dict:
    """A complete ACT checkpoint config matching the frozen G3 loop."""

    return {
        "chunk_size": 30,
        "n_action_steps": 30,
        "n_obs_steps": 1,
        "input_features": {
            "observation.state": {"shape": [16], "type": "STATE"},
            "observation.images.env_cam": {"shape": [3, 240, 320], "type": "VISUAL"},
            "observation.images.left_wrist_cam": {"shape": [3, 240, 424], "type": "VISUAL"},
            "observation.images.right_wrist_cam": {"shape": [3, 240, 424], "type": "VISUAL"},
        },
        "output_features": {
            "action": {"shape": [16], "type": "ACTION"},
        },
    }


def _safe_action() -> list[float]:
    """Arm joints at 0 sit inside every fixed-base limit; grippers at 0.5."""

    action = [0.0] * 16
    action[7] = 0.5
    action[15] = 0.5
    return action


def _good_observation(policy_step: int) -> Observation:
    return Observation(
        global_index=policy_step,
        episode_index=0,
        offset=policy_step,
        state=[0.0] * 16,
        images={
            "observation.images.env_cam": TensorSummary(shape=ENV_SHAPE, finite=True),
            "observation.images.left_wrist_cam": TensorSummary(shape=WRIST_SHAPE, finite=True),
            "observation.images.right_wrist_cam": TensorSummary(shape=WRIST_SHAPE, finite=True),
        },
    )


class FakeClosedLoopRuntime:
    """Dependency-free ClosedLoopRuntime double driving a full episode.

    ``success_from_step`` switches the evaluator from an unstacked to the frozen
    stacked frame, so the strict tracker accumulates consecutive successes only
    after that step.  ``safety_from_step`` flips the privileged safety signals
    to a robot-table collision, and ``non_finite_from_step`` makes the policy
    emit a NaN action.  Each toggles a different terminal outcome.
    """

    def __init__(
        self,
        *,
        success_from_step: int | None = None,
        safety_from_step: int | None = None,
        non_finite_from_step: int | None = None,
        runtime_error_from_step: int | None = None,
        bad_observation_from_step: int | None = None,
        lerobot_version: str = EXPECTED_LEROBOT_VERSION,
        genesis_version: str = EXPECTED_GENESIS_VERSION,
        hip_device_count: int = 1,
    ) -> None:
        self.success_from_step = success_from_step
        self.safety_from_step = safety_from_step
        self.non_finite_from_step = non_finite_from_step
        self.runtime_error_from_step = runtime_error_from_step
        self.bad_observation_from_step = bad_observation_from_step
        self.lerobot_version = lerobot_version
        self.genesis_version = genesis_version
        self.policy_device = "cuda"
        self.policy_device_index = "cuda:0"
        self.hip_device_count = hip_device_count
        self.policy_config = _valid_policy_config()
        self.processor_artifact_hashes = {"pretrained_model/config.json": "a" * 64}
        self.environment_identity = {"torch_version": "2.9.1+rocm7.2.1"}
        self.input_hashes = {
            "port_config_sha256": "c" * 64,
            "interface_contract_sha256": "d" * 64,
            "fixed_base_plan_sha256": "e" * 64,
        }
        self.resets = 0
        self.infers = 0
        self.applies = 0

    def reset_policy_state(self) -> None:
        self.resets += 1

    def observe(self, policy_step: int) -> Observation:
        if (
            self.bad_observation_from_step is not None
            and policy_step >= self.bad_observation_from_step
        ):
            return Observation(
                global_index=policy_step,
                episode_index=0,
                offset=policy_step,
                state=[float("nan")] + [0.0] * 15,
                images={
                    "observation.images.env_cam": TensorSummary(shape=ENV_SHAPE, finite=True),
                    "observation.images.left_wrist_cam": TensorSummary(shape=WRIST_SHAPE, finite=True),
                    "observation.images.right_wrist_cam": TensorSummary(shape=WRIST_SHAPE, finite=True),
                },
            )
        return _good_observation(policy_step)

    def infer(self, observation: Observation, policy_step: int):
        self.infers += 1
        if (
            self.non_finite_from_step is not None
            and policy_step >= self.non_finite_from_step
        ):
            action = _safe_action()
            action[3] = float("nan")
            return action, 1.0
        return _safe_action(), 1.25

    def apply_target(self, physical_target_18d, *, policy_step, physics_step, physics_steps_to_hold):
        # No-op physics; the evaluator state is driven by sample_evaluator.
        self.applies += 1
        return None

    def sample_safety(self, policy_step: int) -> SafetySignals:
        collision = (
            self.safety_from_step is not None
            and policy_step >= self.safety_from_step
        )
        return SafetySignals(
            physics_step=policy_step,
            finite=True,
            robot_table_contact=collision,
            robot_self_contact=False,
            forbidden_collision_pairs=("mantis:left_clamp_left_link:geom <> table:plane") if collision else (),
            workspace_violations=(),
        )

    def sample_evaluator(self, policy_step: int) -> EvaluatorFrame:
        stacked = (
            self.success_from_step is not None
            and policy_step >= self.success_from_step
        )
        positions = STACKED_POSITIONS if stacked else UNSTACKED_POSITIONS
        if (
            self.runtime_error_from_step is not None
            and policy_step >= self.runtime_error_from_step
        ):
            raise RuntimeError("injected runtime error")
        return EvaluatorFrame(
            positions_xyz_m=positions,
            linear_velocities_m_s=ZERO_VELOCITY,
            angular_velocities_rad_s=ZERO_VELOCITY,
            left_gripper_open_fraction=1.0,
            right_gripper_open_fraction=1.0,
        )


def _run_episode(runtime, **overrides):
    return run_closed_loop_episode(
        runtime,
        gate=GATE,
        gate_sha256="g" * 64,
        task=TASK,
        port=PORT,
        fixed_plan=FIXED_PLAN,
        seed=overrides.pop("seed", 101),
        source_hashes={"port_config": "c" * 64},
        checkpoint_hashes={"pretrained_model/config.json": "a" * 64},
        **overrides,
    )


def _load_cli_module():
    path = ROOT / "tools" / "run_genesis_act_closedloop_g3.py"
    spec = importlib.util.spec_from_file_location("run_genesis_act_closedloop_g3_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# Dependency isolation + static contract.
# ---------------------------------------------------------------------------


class DependencyIsolationTests(unittest.TestCase):
    def test_module_import_does_not_pull_heavy_dependencies(self):
        for heavy in ("torch", "lerobot", "PIL", "torchvision", "genesis"):
            sys.modules.pop(heavy, None)
        importlib.import_module("mantis_rocm_bridge.act_closedloop_g3")
        for heavy in ("torch", "lerobot", "PIL", "torchvision", "genesis"):
            self.assertNotIn(heavy, sys.modules, heavy)

    def test_core_module_imports_no_genesis_pytorch_or_lerobot_names(self):
        # Only *module-level* import statements must avoid the heavy deps;
        # lazy imports nested inside functions/methods are the intended pattern.
        source = (ROOT / "src" / "mantis_rocm_bridge" / "act_closedloop_g3.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        heavy = {"torch", "lerobot", "genesis", "PIL", "torchvision"}
        for node in tree.body:  # top-level statements only
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        alias.name.split(".")[0] in heavy,
                        f"top-level import of {alias.name} breaks dependency isolation",
                    )
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                self.assertFalse(
                    root in heavy,
                    f"top-level from-import of {node.module} breaks dependency isolation",
                )

    def test_runtime_class_is_lazy_constructible(self):
        from mantis_rocm_bridge.act_closedloop_g3 import GenesisClosedLoopRuntime

        self.assertTrue(callable(GenesisClosedLoopRuntime))
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("genesis", sys.modules)


class ConfigContractTests(unittest.TestCase):
    def test_checked_in_gate_config_is_valid(self):
        validate_config(GATE)  # does not raise

    def test_mutated_g3_seeds_are_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["episode_protocol"]["g3_seeds"] = [101, 102, 103, 104, 105, 106, 107, 108, 109, 111]
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_mutated_smoke_seed_is_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["episode_protocol"]["smoke_seed"] = 1
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_mutated_thresholds_are_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["promotion"]["minimum_g3_successes"] = 5
        with self.assertRaises(ContractError):
            validate_config(bad)
        bad = json.loads(json.dumps(GATE))
        bad["actuator_admission"][
            "gripper_readback_range_tolerance_normalized"
        ] = 0.004
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_mutated_clock_rule_is_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["control_schedule"]["policy_tick_to_physics_step"] = "floor(k / 30 / 0.004)"
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_mutated_first_physics_steps_is_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["control_schedule"]["first_policy_physics_steps"] = [0, 9, 17, 25, 33]
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_mutated_forbidden_assistance_is_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["forbidden_assistance"] = list(FORBIDDEN_ASSISTANCE) + ["extra_oracle"]
        with self.assertRaises(ContractError):
            validate_config(bad)
        bad = json.loads(json.dumps(GATE))
        bad["forbidden_assistance"] = list(FORBIDDEN_ASSISTANCE)[1:]
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_mutated_required_artifacts_are_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["required_per_episode_artifacts"] = list(PER_EPISODE_ARTIFACTS) + ["extra.txt"]
        with self.assertRaises(ContractError):
            validate_config(bad)
        bad = json.loads(json.dumps(GATE))
        bad["required_aggregate_artifacts"] = list(AGGREGATE_ARTIFACTS)[:-1]
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_mutated_claim_boundary_is_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["claim_boundary"]["seed_101_smoke_proves_g3"] = True
        with self.assertRaises(ContractError):
            validate_config(bad)
        bad = json.loads(json.dumps(GATE))
        bad["claim_boundary"]["passing_g3_proves_exact_distribution_closed_loop_only"] = False
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_frozen_artifact_sets_match_contract(self):
        self.assertEqual(tuple(GATE["required_per_episode_artifacts"]), PER_EPISODE_ARTIFACTS)
        self.assertEqual(tuple(GATE["required_aggregate_artifacts"]), AGGREGATE_ARTIFACTS)


# ---------------------------------------------------------------------------
# Seed selection and smoke / batch admission.
# ---------------------------------------------------------------------------


class SeedAdmissionTests(unittest.TestCase):
    def test_select_g3_seeds_is_exact_frozen_set(self):
        self.assertEqual(select_g3_seeds(GATE), list(G3_SEEDS))
        self.assertEqual(select_g3_seeds(GATE), [101, 102, 103, 104, 105, 106, 107, 108, 109, 110])

    def test_smoke_seed_is_101_and_part_of_g3_set(self):
        self.assertEqual(SMOKE_SEED, 101)
        self.assertTrue(is_smoke_seed(101, GATE))
        self.assertFalse(is_smoke_seed(102, GATE))
        self.assertTrue(is_frozen_g3_seed(101, GATE))
        self.assertFalse(is_frozen_g3_seed(100, GATE))

    def test_smoke_task_failure_without_safety_does_not_block_batch(self):
        receipt = {
            "seed": 101,
            "terminal": True,
            "task_success": False,
            "has_safety_failure": False,
            "safety_failure_count": 0,
            "terminal_reason": "timeout",
        }
        admission = smoke_seed_admission(receipt, GATE)
        self.assertTrue(admission["terminal_receipt"])
        self.assertFalse(admission["has_safety_failure"])
        self.assertTrue(admission["task_failure_without_safety_failure"])
        self.assertFalse(admission["blocks_batch"])
        self.assertFalse(admission["seed_replaced"])

    def test_smoke_safety_failure_blocks_batch(self):
        receipt = {
            "seed": 101,
            "terminal": True,
            "task_success": True,
            "has_safety_failure": True,
            "safety_failure_count": 1,
        }
        admission = smoke_seed_admission(receipt, GATE)
        self.assertTrue(admission["blocks_batch"])

    def test_smoke_missing_receipt_blocks_batch(self):
        receipt = {"seed": 101, "terminal": False, "has_safety_failure": False, "safety_failure_count": 0}
        admission = smoke_seed_admission(receipt, GATE)
        self.assertTrue(admission["blocks_batch"])


# ---------------------------------------------------------------------------
# Tick schedule mapping and skew.
# ---------------------------------------------------------------------------


class TickScheduleTests(unittest.TestCase):
    def test_initial_physics_steps_match_frozen_contract(self):
        self.assertEqual(first_policy_physics_steps(5), [0, 9, 17, 25, 34])
        self.assertEqual(
            first_policy_physics_steps(5),
            GATE["control_schedule"]["first_policy_physics_steps"],
        )

    def test_individual_tick_mapping_matches_ceiling_rule(self):
        for k, expected in enumerate([0, 9, 17, 25, 34, 42]):
            self.assertEqual(policy_tick_to_physics_step(k), expected)

    def test_schedule_skew_stays_below_one_physics_step(self):
        schedule = tick_schedule(count=1200)
        self.assertEqual(len(schedule), 1200)
        for row in schedule:
            self.assertLess(row["sampling_skew_s"], 0.004 + 1e-12)
            self.assertGreaterEqual(row["sampling_skew_s"], 0.0)
        # The held interval between ticks 0 and 1 is 9 physics steps.
        self.assertEqual(schedule[1]["physics_steps_held"], 9)

    def test_invalid_policy_step_is_rejected(self):
        with self.assertRaises(ContractError):
            policy_tick_to_physics_step(-1)
        with self.assertRaises(ContractError):
            policy_tick_to_physics_step(1.5)  # type: ignore[arg-type]

    def test_invalid_rates_are_rejected(self):
        with self.assertRaises(ContractError):
            tick_schedule(count=5, policy_hz=0.0)
        with self.assertRaises(ContractError):
            tick_schedule(count=5, physics_dt_s=-0.004)
        with self.assertRaises(ContractError):
            tick_schedule(count=0)


# ---------------------------------------------------------------------------
# Observation schema and actuator admission telemetry.
# ---------------------------------------------------------------------------


class ObservationAdmissionTests(unittest.TestCase):
    def test_safe_action_admits_with_full_telemetry(self):
        (
            projected_16d,
            raw_physical,
            physical,
            sat_indices,
            sat_names,
            sat_delta,
            physical_sat_delta,
            preproj,
            postproj,
        ) = admit_policy_action(_safe_action(), port=PORT, fixed_plan=FIXED_PLAN)
        self.assertEqual(len(projected_16d), 16)
        self.assertEqual(len(raw_physical), 18)
        self.assertEqual(len(physical), 18)
        self.assertEqual(sat_indices, [])
        self.assertEqual(sat_names, [])
        self.assertEqual(sat_delta, 0.0)
        self.assertEqual(preproj, [])
        self.assertEqual(postproj, [])

    def test_non_finite_action_is_rejected(self):
        action = _safe_action()
        action[3] = float("inf")
        result = admit_policy_action(action, port=PORT, fixed_plan=FIXED_PLAN)
        # Empty projection + a non_finite postprojection issue.
        self.assertEqual(result[0], [])
        self.assertEqual(result[2], [])
        self.assertEqual(result[8], ["non_finite_policy_action"])

    def test_v3_physical_projection_records_saturation(self):
        action = _safe_action()
        action[3] = 2.0  # left elbow beyond its fixed limit
        result = admit_policy_action(action, port=PORT, fixed_plan=FIXED_PLAN)
        projected_16d, raw_physical, physical, sat_indices, sat_names, _, _, preproj, postproj = result
        self.assertEqual(sat_names, ["left_elbow_joint"])
        self.assertTrue(preproj)  # preprojection diagnostic recorded
        self.assertEqual(postproj, [])  # projected back inside limits
        # Raw 18D kept the over-limit value; projected 18D saturated.
        elbow = PORT["target"]["physical_joint_order"].index("left_elbow_joint")
        self.assertGreater(raw_physical[elbow], physical[elbow])


# ---------------------------------------------------------------------------
# Full closed-loop episode via the dependency-injected fake runtime.
# ---------------------------------------------------------------------------


class ClosedLoopEpisodeTests(unittest.TestCase):
    def test_successful_episode_after_consecutive_frames(self):
        runtime = FakeClosedLoopRuntime(success_from_step=5)
        receipt = _run_episode(runtime)
        self.assertTrue(receipt["task_success"], receipt)
        self.assertEqual(receipt["terminal_reason"], "task_success")
        self.assertEqual(receipt["consecutive_success_frames"], 12)
        self.assertFalse(receipt["has_safety_failure"])
        self.assertTrue(receipt["terminal"])

    def test_one_policy_reset_per_episode(self):
        runtime = FakeClosedLoopRuntime(success_from_step=5)
        receipt = _run_episode(runtime)
        policy_state = receipt["policy_state"]
        self.assertEqual(policy_state["reset_calls_observed"], 1)
        self.assertEqual(policy_state["reset_count_target"], 1)
        self.assertTrue(policy_state["one_reset_per_episode"])
        self.assertEqual(policy_state["policy_reset_frequency"], "once_at_episode_start_only")
        self.assertTrue(policy_state["chunk_queue_preserved_across_ticks"])

    def test_timeout_when_stack_never_stabilizes(self):
        runtime = FakeClosedLoopRuntime(success_from_step=None)
        receipt = _run_episode(runtime)
        self.assertFalse(receipt["task_success"])
        self.assertEqual(receipt["terminal_reason"], "timeout")
        self.assertEqual(receipt["terminal_policy_step"], receipt["maximum_policy_steps"] - 1)
        self.assertFalse(receipt["has_safety_failure"])

    def test_safety_failure_overrides_potential_success(self):
        # Stacking starts at step 5 but a collision appears at step 8, before
        # the twelve consecutive frames can accumulate.
        runtime = FakeClosedLoopRuntime(success_from_step=5, safety_from_step=8)
        receipt = _run_episode(runtime)
        self.assertFalse(receipt["task_success"])
        self.assertEqual(receipt["terminal_reason"], "collision_safety")
        self.assertTrue(receipt["has_safety_failure"])
        self.assertEqual(receipt["failure_taxonomy_label"], "collision_safety")

    def test_non_finite_action_is_a_safety_failure(self):
        runtime = FakeClosedLoopRuntime(success_from_step=5, non_finite_from_step=7)
        receipt = _run_episode(runtime)
        self.assertFalse(receipt["task_success"])
        self.assertEqual(receipt["terminal_reason"], "non_finite_action")
        self.assertTrue(receipt["has_safety_failure"])
        self.assertTrue(is_safety_failure_reason("non_finite_action"))

    def test_runtime_error_is_terminal_with_receipt(self):
        runtime = FakeClosedLoopRuntime(runtime_error_from_step=4)
        receipt = _run_episode(runtime)
        self.assertFalse(receipt["task_success"])
        self.assertEqual(receipt["terminal_reason"], "runtime_error")
        self.assertTrue(receipt["terminal"])
        self.assertIsNotNone(receipt["runtime_error"])
        self.assertEqual(receipt["failure_taxonomy_label"], "runtime_error")

    def test_invalid_observation_terminates(self):
        runtime = FakeClosedLoopRuntime(bad_observation_from_step=3)
        receipt = _run_episode(runtime)
        self.assertFalse(receipt["task_success"])
        self.assertEqual(receipt["terminal_reason"], "runtime_error")

    def test_telemetry_records_raw_and_projected_actions(self):
        runtime = FakeClosedLoopRuntime(success_from_step=5)
        receipt = _run_episode(runtime)
        steps = receipt["policy_steps"]
        self.assertTrue(steps)
        first = steps[0]
        self.assertEqual(len(first["raw_action_16d"]), 16)
        self.assertEqual(len(first["projected_action_16d"]), 16)
        self.assertEqual(len(first["raw_physical_target_18d"]), 18)
        self.assertEqual(len(first["projected_physical_target_18d"]), 18)
        self.assertTrue(first["action_finite"])
        self.assertTrue(first["observation_valid"])
        self.assertEqual(first["physics_step"], 0)
        self.assertEqual(first["policy_step"], 0)
        self.assertIn("latency_ms", first)
        # Strict evaluator rows align one-to-one with applied policy steps.
        self.assertEqual(len(receipt["strict_evaluator_rows"]), len(steps))

    def test_runtime_identity_mismatch_fails_closed(self):
        runtime = FakeClosedLoopRuntime(
            success_from_step=5, lerobot_version="0.4.2", hip_device_count=2
        )
        receipt = _run_episode(runtime)
        identity_issues = receipt["runtime_identity"]["identity_issues"]
        self.assertTrue(any("lerobot_version_mismatch" in i for i in identity_issues))
        self.assertTrue(any("hip_device_count_mismatch" in i for i in identity_issues))
        # A runtime-identity drift must fail closed as a runtime error before a
        # single action is observed, inferred, or applied.
        self.assertFalse(receipt["task_success"])
        self.assertEqual(receipt["terminal_reason"], "runtime_error")
        self.assertTrue(receipt["terminal"])
        self.assertEqual(receipt["policy_steps"], [])
        self.assertEqual(runtime.applies, 0)
        self.assertEqual(runtime.infers, 0)
        # The seed-101 smoke admission must block the batch on this defect.
        admission = smoke_seed_admission(receipt, GATE)
        self.assertTrue(admission["blocks_batch"])
        self.assertFalse(admission["admitted_to_batch"])

    def test_policy_config_mismatch_fails_closed(self):
        runtime = FakeClosedLoopRuntime(success_from_step=5)
        runtime.policy_config = _valid_policy_config()
        runtime.policy_config["chunk_size"] = 20  # drift from the frozen 30
        receipt = _run_episode(runtime)
        self.assertFalse(receipt["task_success"])
        self.assertEqual(receipt["terminal_reason"], "runtime_error")
        self.assertEqual(receipt["policy_steps"], [])
        self.assertEqual(runtime.applies, 0)
        issues = receipt["runtime_identity"]["identity_issues"]
        self.assertTrue(any("policy_config_invalid" in i for i in issues))
        self.assertTrue(smoke_seed_admission(receipt, GATE)["blocks_batch"])

    def test_consecutive_frame_counter_resets_after_a_failed_frame(self):
        # Stacked at 0-2, unstacked at 3 (counter resets), then stacked from 4.
        runtime = FakeClosedLoopRuntime(success_from_step=4)
        # Inject a one-frame hole by overriding success window manually:
        runtime.success_from_step = 0

        class _HoleRuntime(FakeClosedLoopRuntime):
            def sample_evaluator(self, policy_step):
                # Stacked except at step 3, where the stack is broken.
                if policy_step == 3:
                    return EvaluatorFrame(
                        positions_xyz_m=UNSTACKED_POSITIONS,
                        linear_velocities_m_s=ZERO_VELOCITY,
                        angular_velocities_rad_s=ZERO_VELOCITY,
                        left_gripper_open_fraction=1.0,
                        right_gripper_open_fraction=1.0,
                    )
                return super().sample_evaluator(policy_step)

        hole = _HoleRuntime(success_from_step=0)
        receipt = _run_episode(hole)
        self.assertTrue(receipt["task_success"])
        self.assertEqual(receipt["consecutive_success_frames"], 12)
        # The hole at step 3 must force the episode to run past step 3+12.
        self.assertGreater(receipt["terminal_policy_step"], 3 + 11)

    def test_receipt_is_deterministic(self):
        first = _run_episode(FakeClosedLoopRuntime(success_from_step=5))
        second = _run_episode(FakeClosedLoopRuntime(success_from_step=5))
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )

    def test_claim_boundary_carried_into_receipt(self):
        receipt = _run_episode(FakeClosedLoopRuntime(success_from_step=5))
        boundary = receipt["claim_boundary"]
        self.assertTrue(boundary["passing_g3_proves_exact_distribution_closed_loop_only"])
        self.assertFalse(boundary["seed_101_smoke_proves_g3"])
        self.assertFalse(boundary["proves_training_convergence"])
        self.assertFalse(boundary["proves_amd_performance_advantage"])


# ---------------------------------------------------------------------------
# Failure taxonomy.
# ---------------------------------------------------------------------------


class FailureTaxonomyTests(unittest.TestCase):
    def test_classify_collision_overrides_timeout(self):
        reason = classify_failure_reason(
            collision=True, joint_limit=False, workspace=False,
            physics_divergence=False, non_finite=False, runtime_error=False, timeout=True,
        )
        self.assertEqual(reason, "collision_safety")

    def test_runtime_error_takes_precedence(self):
        reason = classify_failure_reason(
            collision=True, joint_limit=True, workspace=True,
            physics_divergence=True, non_finite=True, runtime_error=True, timeout=True,
        )
        self.assertEqual(reason, "runtime_error")

    def test_taxonomy_labels_map_to_frozen_set(self):
        taxonomy = TASK["evaluation"]["failure_taxonomy"]
        for reason in (
            "collision_safety", "joint_limit_safety", "workspace_safety",
            "physics_divergence", "runtime_error", "timeout", "task_success",
        ):
            label = taxonomy_label(reason)
            if reason != "task_success":
                self.assertIn(label, taxonomy)
        self.assertEqual(taxonomy_label("non_finite_action"), "runtime_error")

    def test_build_failure_taxonomy_aggregates_labels(self):
        taxonomy = TASK["evaluation"]["failure_taxonomy"]
        receipts = [
            {"seed": 101, "failure_taxonomy_label": "task_success", "has_safety_failure": False},
            {"seed": 102, "failure_taxonomy_label": "timeout", "has_safety_failure": False},
            {"seed": 103, "failure_taxonomy_label": "collision_safety", "has_safety_failure": True},
        ]
        agg = build_failure_taxonomy(receipts, taxonomy=taxonomy)
        self.assertEqual(agg["counts"]["task_success"], 1)
        self.assertEqual(agg["counts"]["timeout"], 1)
        self.assertEqual(agg["counts"]["collision_safety"], 1)
        self.assertEqual(agg["safety_failure_episodes"], [103])
        self.assertEqual(agg["total_episodes"], 3)


# ---------------------------------------------------------------------------
# G3 promotion + claim boundaries.
# ---------------------------------------------------------------------------


class G3PromotionTests(unittest.TestCase):
    def _receipt(self, seed, *, success, safety=False, reason="timeout"):
        return {
            "seed": seed,
            "task_success": success,
            "has_safety_failure": safety,
            "safety_failure_count": 1 if safety else 0,
            "terminal": True,
            "terminal_reason": "task_success" if success else reason,
            "failure_taxonomy_label": "task_success" if success else reason,
        }

    def test_six_successes_zero_safety_passes_g3(self):
        receipts = [self._receipt(s, success=(s <= 106)) for s in G3_SEEDS]
        promotion = evaluate_g3_promotion(receipts, GATE)
        self.assertTrue(promotion["g3_pass"])
        self.assertEqual(promotion["strict_successes"], 6)
        self.assertEqual(promotion["safety_failures"], 0)
        self.assertTrue(promotion["no_seed_replacement"])

    def test_five_successes_fails_g3(self):
        receipts = [self._receipt(s, success=(s <= 105)) for s in G3_SEEDS]
        promotion = evaluate_g3_promotion(receipts, GATE)
        self.assertFalse(promotion["g3_pass"])
        self.assertEqual(promotion["strict_successes"], 5)

    def test_any_safety_failure_fails_g3_even_with_six_successes(self):
        receipts = [self._receipt(s, success=(s <= 106)) for s in G3_SEEDS]
        receipts[9] = self._receipt(110, success=True, safety=True, reason="collision_safety")
        promotion = evaluate_g3_promotion(receipts, GATE)
        self.assertFalse(promotion["g3_pass"])
        self.assertEqual(promotion["safety_failures"], 1)

    def test_incomplete_batch_is_blocked_without_seed_replacement(self):
        receipts = [self._receipt(s, success=True) for s in G3_SEEDS[:9]]
        promotion = evaluate_g3_promotion(receipts, GATE)
        self.assertFalse(promotion["g3_pass"])
        self.assertTrue(promotion["blocked"])
        self.assertFalse(promotion["batch_complete"])
        self.assertEqual(promotion["observed_episodes"], 9)

    def test_duplicate_seed_is_treated_as_replacement(self):
        receipts = [self._receipt(s, success=True) for s in G3_SEEDS]
        receipts[9] = self._receipt(101, success=True)  # duplicate 101, missing 110
        promotion = evaluate_g3_promotion(receipts, GATE)
        self.assertFalse(promotion["g3_pass"])
        self.assertFalse(promotion["seeds_unique"])
        self.assertFalse(promotion["no_seed_replacement"])

    def test_claim_boundary_for_smoke_and_incomplete_batch_is_no_claim(self):
        incomplete = [self._receipt(s, success=True) for s in G3_SEEDS[:9]]
        promotion = evaluate_g3_promotion(incomplete, GATE)
        self.assertIn("does not prove G3 promotion", aggregate_receipt_claim_boundary(GATE, promotion["g3_pass"]))

    def test_claim_boundary_for_passing_g3_uses_frozen_statement(self):
        receipts = [self._receipt(s, success=(s <= 106)) for s in G3_SEEDS]
        promotion = evaluate_g3_promotion(receipts, GATE)
        self.assertTrue(promotion["g3_pass"])
        statement = aggregate_receipt_claim_boundary(GATE, True)
        self.assertEqual(statement, GATE["claim_boundary"]["statement"])
        self.assertIn("official single AMD Radeon ROCm runtime", statement)

    def test_claim_boundary_for_failing_g3_is_no_claim(self):
        receipts = [self._receipt(s, success=(s <= 105)) for s in G3_SEEDS]
        promotion = evaluate_g3_promotion(receipts, GATE)
        self.assertFalse(promotion["g3_pass"])
        self.assertIn("does not prove G3 promotion", aggregate_receipt_claim_boundary(GATE, False))


# ---------------------------------------------------------------------------
# Fresh-directory + exclusive-artifact publishing.
# ---------------------------------------------------------------------------


class ArtifactPublishTests(unittest.TestCase):
    def setUp(self):
        self.cli = _load_cli_module()

    def _receipt(self, success: bool) -> dict:
        return {
            "schema_version": 1,
            "gate_id": "mantis_act_closedloop_g3_v1",
            "task_id": "stack_bowls_three",
            "phase": "closed_loop_learned_policy_evaluation",
            "seed": 101,
            "task_success": success,
            "terminal": True,
            "terminal_reason": "task_success" if success else "timeout",
            "has_safety_failure": False,
            "safety_failure_count": 0,
            "safety_failure_reasons": [],
            "failure_taxonomy_label": "task_success" if success else "timeout",
            "policy_steps": [{"policy_step": 0, "raw_action_16d": [0.0] * 16}],
            "strict_evaluator_rows": [{"policy_step": 0, "frame_success": success}],
            "claim_boundary": GATE["claim_boundary"],
        }

    def test_publish_writes_all_per_episode_artifacts_exclusively(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ep"
            out.mkdir()
            self.cli.publish_episode_artifacts(
                output_dir=out,
                started={"gate_id": "g", "seed": 101},
                command="run ...",
                environment={"python_version": "3.10"},
                policy_steps=[{"policy_step": 0}],
                evaluator_rows=[{"policy_step": 0}],
                receipt=self._receipt(True),
                stdout_text="ok\n",
                stderr_text="",
                exit_code=0,
                gpu_before="before\n",
                gpu_during="during\n",
                gpu_after="after\n",
            )
            for name in PER_EPISODE_ARTIFACTS:
                self.assertTrue((out / name).is_file(), name)
            self.assertEqual((out / "status").read_text(encoding="utf-8"), "PASS\n")
            with self.assertRaises(FileExistsError):
                (out / "status").open("x", encoding="utf-8")

    def test_failed_episode_writes_fail_status_and_immutable_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ep"
            out.mkdir()
            self.cli.publish_episode_artifacts(
                output_dir=out,
                started={"gate_id": "g", "seed": 101},
                command="run ...",
                environment={},
                policy_steps=[],
                evaluator_rows=[],
                receipt=self._receipt(False),
                stdout_text="",
                stderr_text="boom\n",
                exit_code=2,
                gpu_before="", gpu_during="", gpu_after="",
            )
            self.assertEqual((out / "status").read_text(encoding="utf-8"), "FAIL\n")
            receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["task_success"])

    def test_manifest_is_deterministic_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            for out in (out_a, out_b):
                out.mkdir()
                self.cli.publish_episode_artifacts(
                    output_dir=out, started={"gate_id": "g"}, command="c",
                    environment={}, policy_steps=[], evaluator_rows=[],
                    receipt=self._receipt(True), stdout_text="", stderr_text="",
                    exit_code=0, gpu_before="", gpu_during="", gpu_after="",
                )
            manifest_a = (out_a / "SHA256SUMS").read_text(encoding="utf-8")
            manifest_b = (out_b / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertEqual(manifest_a, manifest_b)
            names = [line.split("  ", 1)[1] for line in manifest_a.splitlines()]
            self.assertEqual(names, sorted(names))
            self.assertNotIn("SHA256SUMS", names)

    def test_existing_output_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "out"
            existing.mkdir()
            with self.assertRaises(SystemExit) as ctx:
                self.cli.main([
                    str(Path(tmp) / "ckpt"), "--seed", "101",
                    "--output-dir", str(existing),
                    "--bowl-asset-root", str(Path(tmp) / "bowl"),
                    "--mantis-urdf", str(Path(tmp) / "mantis.urdf"),
                ])
            self.assertEqual(ctx.exception.code, 2)

    def test_build_sha256sums_is_sorted_and_excludes_self(self):
        manifest = build_sha256sums([("b" * 64, "zeta.txt"), ("a" * 64, "alpha.txt")])
        names = [line.split("  ", 1)[1] for line in manifest.splitlines()]
        self.assertEqual(names, ["alpha.txt", "zeta.txt"])


# ---------------------------------------------------------------------------
# CLI argument handling (absolute paths, frozen seed enforcement).
# ---------------------------------------------------------------------------


class CLIArgumentTests(unittest.TestCase):
    def setUp(self):
        self.cli = _load_cli_module()
        self._stdout = io.StringIO()
        self._patcher_stdout = __import__("contextlib").redirect_stdout(self._stdout)
        self._patcher_stdout.__enter__()
        self._orig_runtime = self.cli.GenesisClosedLoopRuntime
        self._orig_run = self.cli.run_closed_loop_episode

    def tearDown(self):
        self._patcher_stdout.__exit__(None, None, None)
        self.cli.GenesisClosedLoopRuntime = self._orig_runtime
        self.cli.run_closed_loop_episode = self._orig_run

    def _stub(self, *, receipt):
        class _StubRuntime:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.processor_artifact_hashes = {"pretrained_model/config.json": "a" * 64}

        def _stub_run(runtime, **kwargs):
            return receipt

        self.cli.GenesisClosedLoopRuntime = _StubRuntime
        self.cli.run_closed_loop_episode = _stub_run

    def test_non_frozen_seed_is_rejected(self):
        self._stub(receipt={"task_success": True, "policy_steps": [], "strict_evaluator_rows": []})
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt"
            (ckpt / "pretrained_model").mkdir(parents=True)
            bowl = Path(tmp) / "bowl"
            (bowl / "urdf").mkdir(parents=True)
            (bowl / "urdf" / "robotwin_002_bowl_model3.urdf").write_text("x")
            (bowl / "manifest.json").write_text(json.dumps({"distribution_allowed": True}), encoding="utf-8")
            urdf = Path(tmp) / "mantis.urdf"
            urdf.write_text("x")
            out = Path(tmp) / "out"
            with self.assertRaises(SystemExit) as ctx:
                self.cli.main([
                    str(ckpt), "--seed", "999",
                    "--output-dir", str(out),
                    "--bowl-asset-root", str(bowl),
                    "--mantis-urdf", str(urdf),
                ])
            self.assertEqual(ctx.exception.code, 2)

    def test_relative_checkpoint_root_is_rejected(self):
        self._stub(receipt={"task_success": True, "policy_steps": [], "strict_evaluator_rows": []})
        with self.assertRaises(SystemExit) as ctx:
            self.cli.main([
                "relative/ckpt", "--seed", "101",
                "--output-dir", "/abs/out",
                "--bowl-asset-root", "/abs/bowl",
                "--mantis-urdf", "/abs/mantis.urdf",
            ])
        self.assertEqual(ctx.exception.code, 2)

    def test_frozen_seed_with_stub_passes_and_publishes(self):
        self._stub(receipt={
            "task_success": True, "terminal": True, "terminal_reason": "task_success",
            "has_safety_failure": False, "safety_failure_count": 0,
            "safety_failure_reasons": [], "failure_taxonomy_label": "task_success",
            "policy_steps": [], "strict_evaluator_rows": [],
            "claim_boundary": GATE["claim_boundary"],
        })
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt"
            (ckpt / "pretrained_model").mkdir(parents=True)
            bowl = Path(tmp) / "bowl"
            (bowl / "urdf").mkdir(parents=True)
            (bowl / "urdf" / "robotwin_002_bowl_model3.urdf").write_text("x")
            (bowl / "manifest.json").write_text(json.dumps({"distribution_allowed": True}), encoding="utf-8")
            urdf = Path(tmp) / "mantis.urdf"
            urdf.write_text("x")
            out = Path(tmp) / "out"
            rc = self.cli.main([
                str(ckpt), "--seed", "101",
                "--output-dir", str(out),
                "--bowl-asset-root", str(bowl),
                "--mantis-urdf", str(urdf),
            ])
            self.assertEqual(rc, 0)
            for name in PER_EPISODE_ARTIFACTS:
                self.assertTrue((out / name).is_file(), name)
            self.assertEqual((out / "status").read_text(encoding="utf-8"), "PASS\n")

    def test_cli_fail_closed_on_runtime_exception(self):
        class _BoomRuntime:
            def __init__(self, **kwargs):
                raise RuntimeError("boom")
            processor_artifact_hashes = {}

        self.cli.GenesisClosedLoopRuntime = _BoomRuntime

        def _stub_run(runtime, **kwargs):  # pragma: no cover - never reached
            raise AssertionError("runtime construction must fail first")

        self.cli.run_closed_loop_episode = _stub_run
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt"
            (ckpt / "pretrained_model").mkdir(parents=True)
            bowl = Path(tmp) / "bowl"
            (bowl / "urdf").mkdir(parents=True)
            (bowl / "urdf" / "robotwin_002_bowl_model3.urdf").write_text("x")
            (bowl / "manifest.json").write_text(json.dumps({"distribution_allowed": True}), encoding="utf-8")
            urdf = Path(tmp) / "mantis.urdf"
            urdf.write_text("x")
            out = Path(tmp) / "out"
            rc = self.cli.main([
                str(ckpt), "--seed", "101",
                "--output-dir", str(out),
                "--bowl-asset-root", str(bowl),
                "--mantis-urdf", str(urdf),
            ])
            self.assertEqual(rc, 2)
            receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["task_success"])
            # A CLI exception is an immutable *terminal* infrastructure receipt,
            # not a relabelled task failure; smoke admission must block on it.
            self.assertTrue(receipt["terminal"])
            self.assertEqual(receipt["terminal_reason"], "runtime_error")
            self.assertTrue(receipt["infrastructure_failure"])
            self.assertTrue(smoke_seed_admission(receipt, GATE)["blocks_batch"])
            self.assertEqual((out / "status").read_text(encoding="utf-8"), "FAIL\n")
            self.assertIn("closed_loop_runtime_failed", (out / "stderr.log").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# WP-P3-CL-001 repair regressions.
# ---------------------------------------------------------------------------


class CheckpointAdmissionContractTests(unittest.TestCase):
    """The CLI/runtime must load the admitted v3 gate for checkpoint admission."""

    def setUp(self):
        self.v3_gate = load_json(ROOT / "configs" / "act-openloop-inference-v3.json")

    def test_g3_gate_has_no_saved_processor_requirements(self):
        # The defect: the G3 gate carries no saved_processor_requirements, so it
        # can never be the object passed to validate_required_checkpoint_files.
        self.assertNotIn("saved_processor_requirements", GATE)

    def test_g3_gate_cannot_provide_required_checkpoint_files(self):
        from mantis_rocm_bridge.act_openloop_inference import (
            required_pretrained_files,
            validate_required_checkpoint_files,
        )

        with self.assertRaises(ContractError):
            required_pretrained_files(GATE)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ContractError):
                validate_required_checkpoint_files(Path(tmp), GATE)

    def test_v3_gate_admits_required_processor_files(self):
        from mantis_rocm_bridge.act_openloop_inference import (
            validate_required_checkpoint_files,
        )

        required = self.v3_gate["saved_processor_requirements"]["required_files"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in required:
                (base / name).parent.mkdir(parents=True, exist_ok=True)
                (base / name).write_text("artifact")
            admitted = validate_required_checkpoint_files(base, self.v3_gate)
            self.assertEqual(set(admitted), set(required))

    def test_runtime_rejects_non_v3_openloop_admission_gate(self):
        from mantis_rocm_bridge.act_closedloop_g3 import GenesisClosedLoopRuntime

        kwargs = dict(
            checkpoint_root="/tmp/ckpt",
            pretrained_model="/tmp/ckpt/pretrained_model",
            mantis_urdf="/tmp/mantis.urdf",
            bowl_urdf="/tmp/bowl.urdf",
            gate=GATE,
            task=TASK,
            port=PORT,
            fixed_plan=FIXED_PLAN,
            scene_contract={},
            camera_contract={},
            source_task={},
            interface=INTERFACE,
            seed=101,
            backend="cpu",
            port_sha256="p",
            interface_sha256="i",
            fixed_plan_sha256="f",
            openloop_admission_gate_sha256="v",
        )
        # A non-v3 admission gate (e.g. the G3 gate itself) must be rejected
        # before any heavy runtime dependency is imported.
        bad = json.loads(json.dumps(GATE))
        with self.assertRaises(ContractError):
            GenesisClosedLoopRuntime(openloop_admission_gate=bad, **kwargs)
        with self.assertRaises(ContractError):
            GenesisClosedLoopRuntime(openloop_admission_gate="not-a-dict", **kwargs)  # type: ignore[arg-type]


class PolicyConfigValidationTests(unittest.TestCase):
    def test_valid_policy_config_is_accepted(self):
        validate_policy_config(_valid_policy_config(), GATE)  # does not raise

    def test_chunk_size_drift_is_rejected(self):
        cfg = _valid_policy_config()
        cfg["chunk_size"] = 20
        with self.assertRaises(ContractError):
            validate_policy_config(cfg, GATE)

    def test_n_obs_steps_drift_is_rejected(self):
        cfg = _valid_policy_config()
        cfg["n_obs_steps"] = 2
        with self.assertRaises(ContractError):
            validate_policy_config(cfg, GATE)

    def test_state_dimension_drift_is_rejected(self):
        cfg = _valid_policy_config()
        cfg["input_features"]["observation.state"]["shape"] = [14]
        with self.assertRaises(ContractError):
            validate_policy_config(cfg, GATE)

    def test_image_shape_drift_is_rejected(self):
        cfg = _valid_policy_config()
        cfg["input_features"]["observation.images.env_cam"]["shape"] = [3, 240, 321]
        with self.assertRaises(ContractError):
            validate_policy_config(cfg, GATE)

    def test_missing_image_feature_is_rejected(self):
        cfg = _valid_policy_config()
        del cfg["input_features"]["observation.images.right_wrist_cam"]
        with self.assertRaises(ContractError):
            validate_policy_config(cfg, GATE)


class CameraObservationContractTests(unittest.TestCase):
    """One causal camera observation: render once, report CHW, consume cache."""

    def setUp(self):
        import numpy as np

        self.np = np

    def _fake_camera(self, h, w):
        np = self.np

        class _FakeCamera:
            def __init__(self):
                self.render_count = 0

            def render(self, rgb=True, force_render=True):
                self.render_count += 1
                # Genesis-style HWC uint8 frame.
                return (np.random.rand(h, w, 3) * 255).astype(np.uint8)

        return _FakeCamera()

    def test_hwc_to_chw_summary_reports_channel_first_shape(self):
        np = self.np
        array = np.zeros((240, 320, 3), dtype=np.uint8)
        summary = hwc_to_chw_summary(array)
        self.assertEqual(summary.shape, (3, 240, 320))  # CHW, not HWC
        self.assertTrue(summary.finite)
        self.assertGreaterEqual(summary.min_value, 0.0)
        self.assertLessEqual(summary.max_value, 1.0)

    def test_observe_renders_each_camera_once_and_caches(self):
        cameras = {
            "env_cam": self._fake_camera(240, 320),
            "left_wrist_cam": self._fake_camera(240, 424),
            "right_wrist_cam": self._fake_camera(240, 424),
        }
        cache: dict = {}
        arrays = render_observation_arrays(cameras, policy_step=7, cache=cache)
        # Each camera rendered exactly once for the policy step.
        self.assertEqual(cameras["env_cam"].render_count, 1)
        self.assertEqual(cameras["left_wrist_cam"].render_count, 1)
        self.assertEqual(cameras["right_wrist_cam"].render_count, 1)
        # Shapes are HWC and cached for that step.
        self.assertEqual(cache["policy_step"], 7)
        self.assertEqual(arrays["observation.images.env_cam"].shape, (240, 320, 3))
        self.assertEqual(
            arrays["observation.images.left_wrist_cam"].shape, (240, 424, 3)
        )

    def test_consume_uses_cache_without_re_rendering(self):
        cameras = {
            "env_cam": self._fake_camera(240, 320),
            "left_wrist_cam": self._fake_camera(240, 424),
            "right_wrist_cam": self._fake_camera(240, 424),
        }
        cache: dict = {}
        render_observation_arrays(cameras, policy_step=3, cache=cache)
        consumed = consume_cached_arrays(cache, policy_step=3)
        self.assertEqual(set(consumed), set(arrays_expected_features()))
        # No additional render happened during consumption.
        self.assertEqual(cameras["env_cam"].render_count, 1)

    def test_consume_rejects_stale_and_missing_cache(self):
        cameras = {
            "env_cam": self._fake_camera(240, 320),
            "left_wrist_cam": self._fake_camera(240, 424),
            "right_wrist_cam": self._fake_camera(240, 424),
        }
        cache: dict = {}
        # Missing cache (observe never ran).
        with self.assertRaises(ContractError):
            consume_cached_arrays(cache, policy_step=0)
        render_observation_arrays(cameras, policy_step=3, cache=cache)
        # Stale cache (different policy step).
        with self.assertRaises(ContractError):
            consume_cached_arrays(cache, policy_step=4)


def arrays_expected_features():
    return (
        "observation.images.env_cam",
        "observation.images.left_wrist_cam",
        "observation.images.right_wrist_cam",
    )


class GripperStateContractV2Tests(unittest.TestCase):
    """Gripper readback uses the bounded v2 projection (residual reported)."""

    def test_asymmetric_fingers_are_projected_not_rejected(self):
        from mantis_rocm_bridge.gripper import (
            physical_to_virtual,
            project_physical_to_virtual,
            virtual_to_physical,
        )

        # Build a physical vector with deliberately asymmetric left fingers,
        # nudging along each finger's coefficient so both estimates stay inside
        # the [0, 1] domain (one at 0.6, the other at 0.5 -> spread 0.1).
        virtual_home = [0.0] * 16
        virtual_home[7] = 0.5
        virtual_home[15] = 0.5
        physical = virtual_to_physical(virtual_home, PORT, allow_unverified=True)
        names = PORT["target"]["physical_joint_order"]
        coeffs = PORT["assets"]["virtual_gripper_mapping"]["coefficients"]["left_gripper_joint"]
        clamp_names = list(coeffs)
        idx0 = names.index(clamp_names[0])
        physical[idx0] += 0.1 * float(coeffs[clamp_names[0]])
        # The bounded projection returns a vector and reports the spread...
        projection = project_physical_to_virtual(physical, PORT, allow_unverified=True)
        self.assertEqual(len(projection.vector), 16)
        left = next(g for g in projection.grippers if g.virtual_name == "left_gripper_joint")
        self.assertGreater(left.spread, 0.0)
        # ...while the strict physical_to_virtual rejects the asymmetry.
        with self.assertRaises(ContractError):
            physical_to_virtual(physical, PORT, allow_unverified=True)

    def test_out_of_domain_finger_is_still_rejected(self):
        from mantis_rocm_bridge.gripper import (
            project_physical_to_virtual,
            virtual_to_physical,
        )

        virtual_home = [0.0] * 16
        virtual_home[7] = 0.5
        virtual_home[15] = 0.5
        physical = virtual_to_physical(virtual_home, PORT, allow_unverified=True)
        names = PORT["target"]["physical_joint_order"]
        coeffs = PORT["assets"]["virtual_gripper_mapping"]["coefficients"]["left_gripper_joint"]
        offsets = PORT["assets"]["virtual_gripper_mapping"]["offsets"][
            "left_gripper_joint"
        ]
        # Float32/physics readback can land a few ULP above the commanded
        # boundary. The G3-specific 0.003 tolerance reuses the full-capture
        # endpoint contract and admits a 0.0025 excursion before clamping.
        for clamp_name, coefficient in coeffs.items():
            idx = names.index(clamp_name)
            physical[idx] = (
                float(offsets[clamp_name])
                + (1.0 + 0.0025) * float(coefficient)
            )
        projection = project_physical_to_virtual(
            physical,
            PORT,
            allow_unverified=True,
            range_tolerance=0.003,
        )
        left = next(
            item
            for item in projection.grippers
            if item.virtual_name == "left_gripper_joint"
        )
        self.assertEqual(left.projected_mean, 1.0)
        # A materially out-of-domain finger remains fail-closed.
        clamp_name = next(iter(coeffs))
        idx = names.index(clamp_name)
        physical[idx] += 100.0 * float(coeffs[clamp_name])
        with self.assertRaises(ContractError):
            project_physical_to_virtual(
                physical,
                PORT,
                allow_unverified=True,
                range_tolerance=0.003,
            )

    def test_receipt_records_gripper_diagnostics_when_runtime_exposes_them(self):
        class _GripperRuntime(FakeClosedLoopRuntime):
            def __init__(self):
                super().__init__(success_from_step=5)
                self.gripper_state_diagnostics = [
                    {
                        "policy_step": 0,
                        "range_tolerance_normalized": 0.003,
                        "grippers": [
                            {
                                "virtual_name": "left_gripper_joint",
                                "physical_names": ["a", "b"],
                                "estimates": [0.4, 0.5],
                                "projected_mean": 0.45,
                                "spread": 0.1,
                            }
                        ],
                    }
                ]

        receipt = _run_episode(_GripperRuntime())
        diag = receipt["gripper_state_diagnostics"]
        self.assertTrue(diag["available"])
        self.assertTrue(diag["history"])
        self.assertEqual(
            diag["history"][0]["range_tolerance_normalized"],
            0.003,
        )

    def test_fake_runtime_receipt_records_absence(self):
        receipt = _run_episode(FakeClosedLoopRuntime(success_from_step=5))
        diag = receipt["gripper_state_diagnostics"]
        self.assertFalse(diag["available"])


class ContactSafetyClassificationTests(unittest.TestCase):
    """Pure contact-pair classification for every safety case."""

    def test_allowed_proximal_pair_is_order_independent(self):
        a = "mantis:pelvis_link:geom <> mantis:right_shoulder_yaw_link:geom"
        b = "mantis:right_shoulder_yaw_link:geom <> mantis:pelvis_link:geom"
        # The pair string is sorted elsewhere, but the predicate must not depend
        # on which side carries which link.
        self.assertTrue(_is_allowed_proximal_pair(a))
        self.assertTrue(_is_allowed_proximal_pair(b))

    def test_non_proximal_pairs_are_not_allowed(self):
        self.assertFalse(_is_allowed_proximal_pair(
            "mantis:pelvis_link:geom <> mantis:pelvis_link:geom"
        ))
        self.assertFalse(_is_allowed_proximal_pair(
            "mantis:right_shoulder_yaw_link:geom <> mantis:left_elbow_link:geom"
        ))
        self.assertFalse(_is_allowed_proximal_pair(
            "mantis:left_clamp_left_link:geom <> table:plane"
        ))

    def test_same_side_clamp_pairs_are_excluded_self_contacts(self):
        self.assertTrue(_is_same_side_clamp_pair(
            "mantis:left_clamp_left_link:geom <> mantis:left_clamp_right_link:geom"
        ))
        self.assertTrue(_is_same_side_clamp_pair(
            "mantis:right_clamp_left_link:geom <> mantis:right_clamp_right_link:geom"
        ))
        # Cross-side or arm self contacts are NOT the same-side clamp exclusion.
        self.assertFalse(_is_same_side_clamp_pair(
            "mantis:left_clamp_left_link:geom <> mantis:right_clamp_left_link:geom"
        ))

    def test_clamp_robot_bowl_contact_is_allowed(self):
        self.assertTrue(_is_clamp_robot_bowl_pair(
            "bowl_0:link <> mantis:left_clamp_left_link:geom"
        ))
        self.assertTrue(_is_clamp_robot_bowl_pair(
            "mantis:right_clamp_right_link:geom <> bowl_1:link"
        ))

    def test_non_clamp_robot_bowl_contact_is_forbidden(self):
        # An arm/wrist link touching a bowl is forbidden, regardless of pose.
        self.assertFalse(_is_clamp_robot_bowl_pair(
            "bowl_0:link <> mantis:left_wrist_roll_link:geom"
        ))
        self.assertFalse(_is_clamp_robot_bowl_pair(
            "bowl_0:link <> mantis:pelvis_link:geom"
        ))

    def test_robot_table_is_not_a_clamp_bowl_contact(self):
        self.assertFalse(_is_clamp_robot_bowl_pair(
            "mantis:left_clamp_left_link:geom <> table:plane"
        ))

    def test_contact_pairs_rejects_unexpected_structure(self):
        with self.assertRaises(ContractError):
            _contact_pairs([], {})  # not a dict
        with self.assertRaises(ContractError):
            _contact_pairs({"no_geom_a": []}, {})


class InfrastructureAdmissionTests(unittest.TestCase):
    def test_terminal_runtime_error_blocks_batch(self):
        receipt = {
            "seed": 101,
            "terminal": True,
            "terminal_reason": "runtime_error",
            "task_success": False,
            "has_safety_failure": False,
            "safety_failure_count": 0,
        }
        admission = smoke_seed_admission(receipt, GATE)
        self.assertTrue(admission["blocks_batch"])
        self.assertFalse(admission["admitted_to_batch"])

    def test_runtime_identity_issue_blocks_batch(self):
        receipt = {
            "seed": 101,
            "terminal": True,
            "terminal_reason": "runtime_error",
            "task_success": False,
            "has_safety_failure": False,
            "safety_failure_count": 0,
            "runtime_identity": {"identity_issues": ["lerobot_version_mismatch:0.4.2:0.4.4"]},
        }
        admission = smoke_seed_admission(receipt, GATE)
        self.assertTrue(admission["blocks_batch"])
        self.assertTrue(admission["has_runtime_identity_issue"])

    def test_terminal_timeout_with_zero_safety_is_admissible(self):
        receipt = {
            "seed": 101,
            "terminal": True,
            "terminal_reason": "timeout",
            "task_success": False,
            "has_safety_failure": False,
            "safety_failure_count": 0,
            "runtime_identity": {"identity_issues": []},
        }
        admission = smoke_seed_admission(receipt, GATE)
        self.assertFalse(admission["blocks_batch"])
        self.assertTrue(admission["admitted_to_batch"])
        self.assertTrue(admission["task_failure_without_safety_failure"])

    def test_nonterminal_receipt_blocks_batch(self):
        receipt = {
            "seed": 101,
            "terminal": False,
            "has_safety_failure": False,
            "safety_failure_count": 0,
        }
        self.assertTrue(smoke_seed_admission(receipt, GATE)["blocks_batch"])


class RocmProcessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.cli = _load_cli_module()

    def test_rocm_smi_evidence_returns_structured_dict_without_raising(self):
        evidence = self.cli._rocm_smi_evidence()
        for key in ("available", "command", "return_code", "stdout", "stderr"):
            self.assertIn(key, evidence)
        # The availability flag is always a boolean control; stdout/stderr are
        # always textual. These invariants hold on a no-ROCm macOS worker and on
        # an AMD Linux worker where rocm-smi is present.
        self.assertIsInstance(evidence["available"], bool)
        self.assertIsInstance(evidence["stdout"], str)
        self.assertIsInstance(evidence["stderr"], str)
        if evidence["available"]:
            # A real capture records the command, an integer return code, and
            # captured stdout from the official AMD single device.
            self.assertIsInstance(evidence["command"], str)
            self.assertTrue(evidence["command"])
            self.assertIsInstance(evidence["return_code"], int)
        else:
            # Missing telemetry is recorded as such: no return code was
            # produced and a human-readable stderr explains the miss, rather
            # than the absence masquerading as task-success evidence.
            self.assertIsNone(evidence["return_code"])
            self.assertTrue(evidence["stderr"])

    def test_gpu_evidence_records_torch_and_rocm_smi_sections(self):
        text = self.cli._gpu_evidence("before")
        # The labeled section header plus the torch and rocm-smi telemetry
        # sections are always emitted, regardless of device availability.
        self.assertIn("before:", text)
        self.assertIn("torch:", text)
        self.assertIn("rocm_smi:", text)
        # Branch on the *actual* parsed rocm-smi availability, which differs
        # between a no-ROCm macOS worker and an AMD Linux worker.
        rocm_line = next(
            line for line in text.splitlines() if line.strip().startswith("rocm_smi:")
        )
        parsed = json.loads(rocm_line.split("rocm_smi:", 1)[1].strip())
        self.assertIn("available", parsed)
        if not parsed.get("available"):
            # Missing telemetry is recorded as such, never as success evidence.
            self.assertIn("not treated as task-success evidence", text)
        else:
            # Available telemetry: the missing-telemetry note is deliberately
            # absent, and the captured command / integer return code are
            # recorded as normal telemetry fields.
            self.assertNotIn("not treated as task-success evidence", text)
            self.assertIsInstance(parsed["command"], str)
            self.assertTrue(parsed["command"])
            self.assertIsInstance(parsed["return_code"], int)


if __name__ == "__main__":
    unittest.main()
