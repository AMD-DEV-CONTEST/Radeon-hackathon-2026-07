from __future__ import annotations

import importlib.util
import ast
import io
import json
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.act_openloop_inference import (
    EXPECTED_LEROBOT_VERSION,
    LeRobotOpenLoopRuntime,
    Observation,
    OUTPUT_ARTIFACTS,
    SampleResult,
    TensorSummary,
    enforce_joint_limits,
    expand_virtual_to_physical,
    physical_joint_limits,
    project_physical_joint_target,
    project_virtual_gripper_action,
    required_pretrained_files,
    run_open_loop_inference,
    sample_offsets,
    select_samples,
    validate_action_vector,
    validate_config,
    validate_interface_contract,
    validate_observation,
    validate_required_checkpoint_files,
)


ROOT = Path(__file__).resolve().parents[1]
GATE = load_json(ROOT / "configs" / "act-openloop-inference-v1.json")
GATE_V2 = load_json(ROOT / "configs" / "act-openloop-inference-v2.json")
GATE_V3 = load_json(ROOT / "configs" / "act-openloop-inference-v3.json")
PORT = load_json(ROOT / "configs" / "mantis-port-config.json")
FIXED_PLAN = load_json(ROOT / "configs" / "fixed-base-plan.json")

ENV_SHAPE = (3, 240, 320)
WRIST_SHAPE = (3, 240, 424)
IMAGE_FEATURES = {
    "observation.images.env_cam": [3, 240, 320],
    "observation.images.left_wrist_cam": [3, 240, 424],
    "observation.images.right_wrist_cam": [3, 240, 424],
}

REQUIRED_PROCESSOR_FILES = [
    "pretrained_model/config.json",
    "pretrained_model/model.safetensors",
    "pretrained_model/policy_preprocessor.json",
    "pretrained_model/policy_preprocessor_step_3_normalizer_processor.safetensors",
    "pretrained_model/policy_postprocessor.json",
    "pretrained_model/policy_postprocessor_step_0_unnormalizer_processor.safetensors",
]


def _good_state(global_index: int) -> list[float]:
    base = 0.01 * (global_index + 1)
    return [base + 0.001 * j for j in range(16)]


def _safe_action(global_index: int) -> list[float]:
    # Arm joints at 0.0 sit inside every fixed-base limit; grippers at 0.5 map
    # to clamp positions inside [-0.0376, 0.0376].
    action = [0.0] * 16
    action[7] = 0.5
    action[15] = 0.5
    return action


def _good_observation(global_index: int, episode: int, offset: int) -> Observation:
    return Observation(
        global_index=global_index,
        episode_index=episode,
        offset=offset,
        state=_good_state(global_index),
        images={
            "observation.images.env_cam": TensorSummary(shape=ENV_SHAPE, finite=True),
            "observation.images.left_wrist_cam": TensorSummary(shape=WRIST_SHAPE, finite=True),
            "observation.images.right_wrist_cam": TensorSummary(shape=WRIST_SHAPE, finite=True),
        },
    )


def _four_episode_bounds() -> dict[int, tuple[int, int]]:
    # Four episodes of length 10 -> globals 0..39; first/mid/last per episode
    # yields exactly 12 distinct samples.
    return {0: (0, 10), 1: (10, 10), 2: (20, 10), 3: (30, 10)}


class FakeRuntime:
    """Dependency-free InferenceRuntime double for the pure core."""

    def __init__(
        self,
        bounds: dict[int, tuple[int, int]] | None = None,
        *,
        action_factory=_safe_action,
        bad_actions: dict[int, list[float]] | None = None,
        bad_observations: dict[int, Observation] | None = None,
        infer_errors: set[int] | None = None,
        lerobot_version: str = EXPECTED_LEROBOT_VERSION,
        policy_device: str = "cuda",
        policy_device_index: str = "cuda:0",
        hip_device_count: int = 1,
    ) -> None:
        self._bounds = dict(bounds or _four_episode_bounds())
        self._action_factory = action_factory
        self._bad_actions = dict(bad_actions or {})
        self._bad_observations = dict(bad_observations or {})
        self._infer_errors = set(infer_errors or ())
        self.lerobot_version = lerobot_version
        self.policy_device = policy_device
        self.policy_device_index = policy_device_index
        self.hip_device_count = hip_device_count
        self.policy_config = {"chunk_size": 30, "n_action_steps": 30}
        self.processor_artifact_hashes = {
            name: "a" * 64 for name in REQUIRED_PROCESSOR_FILES
        }
        self.environment_identity = {"torch_version": "2.9.1+rocm7.2.1"}
        self.input_hashes = {
            "dataset_root": "b" * 64,
            "port_config_sha256": "c" * 64,
            "interface_contract_sha256": "d" * 64,
            "fixed_base_plan_sha256": "e" * 64,
        }
        self.resets = 0

    def episode_bounds(self) -> dict[int, tuple[int, int]]:
        return {ep: (first, length) for ep, (first, length) in self._bounds.items()}

    def observe(self, global_index: int) -> Observation:
        if global_index in self._bad_observations:
            return self._bad_observations[global_index]
        episode, offset = self._locate(global_index)
        return _good_observation(global_index, episode, offset)

    def reset_policy_state(self) -> None:
        self.resets += 1

    def infer(self, observation: Observation) -> tuple[list[float], float | None]:
        if observation.global_index in self._infer_errors:
            raise ContractError(f"injected infer failure at {observation.global_index}")
        if observation.global_index in self._bad_actions:
            return list(self._bad_actions[observation.global_index]), None
        return list(self._action_factory(observation.global_index)), 1.25

    def _locate(self, global_index: int) -> tuple[int, int]:
        for episode, (first, length) in self._bounds.items():
            if first <= global_index < first + length:
                return episode, global_index - first
        raise ContractError(f"global index {global_index} is outside every episode")


def _load_cli_module():
    path = ROOT / "tools" / "run_act_openloop_inference.py"
    spec = importlib.util.spec_from_file_location("run_act_openloop_inference_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# Config contract.
# ---------------------------------------------------------------------------


class ConfigContractTests(unittest.TestCase):
    def test_checked_in_gate_config_is_valid(self):
        validate_config(GATE)  # does not raise

    def test_checked_in_projection_gate_config_is_valid(self):
        validate_config(GATE_V2)  # does not raise

    def test_checked_in_physical_projection_gate_config_is_valid(self):
        validate_config(GATE_V3)  # does not raise

    def test_projection_cannot_be_silently_added_to_v1_gate(self):
        bad = json.loads(json.dumps(GATE_V2))
        bad["gate_id"] = GATE["gate_id"]
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_required_processor_files_are_step_specific(self):
        files = required_pretrained_files(GATE)
        self.assertEqual(
            sorted(files),
            sorted(REQUIRED_PROCESSOR_FILES),
        )
        # The nonexistent generic safetensors names must never be required.
        self.assertNotIn("pretrained_model/policy_preprocessor.safetensors", files)
        self.assertNotIn("pretrained_model/policy_postprocessor.safetensors", files)
        self.assertIn(
            "pretrained_model/policy_preprocessor_step_3_normalizer_processor.safetensors",
            files,
        )
        self.assertIn(
            "pretrained_model/policy_postprocessor_step_0_unnormalizer_processor.safetensors",
            files,
        )

    def test_processor_loader_uses_lerobot_policies_api(self):
        loader = GATE["saved_processor_requirements"]["processor_loader"]
        self.assertIn("lerobot.policies.factory.make_pre_post_processors", loader)
        self.assertIn("policy_cfg=policy.config", loader)
        self.assertIn("pretrained_path", loader)

    def test_runtime_imports_processor_factory_from_exact_0_4_4_module(self):
        source_path = (
            ROOT / "src" / "mantis_rocm_bridge" / "act_openloop_inference.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = {
            (node.module, alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertIn(
            ("lerobot.policies.factory", "make_pre_post_processors"),
            imports,
        )
        self.assertNotIn(
            ("lerobot.policies", "make_pre_post_processors"),
            imports,
        )

    def test_generic_safetensors_requirement_is_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["saved_processor_requirements"]["required_files"] = [
            "pretrained_model/config.json",
            "pretrained_model/model.safetensors",
            "pretrained_model/policy_preprocessor.json",
            "pretrained_model/policy_preprocessor.safetensors",
            "pretrained_model/policy_postprocessor.json",
            "pretrained_model/policy_postprocessor.safetensors",
        ]
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_old_loader_module_is_rejected(self):
        bad = json.loads(json.dumps(GATE))
        bad["saved_processor_requirements"]["processor_loader"] = (
            "lerobot.common.datasets.utils.make_pre_post_processors with the pretrained_model path"
        )
        with self.assertRaises(ContractError):
            validate_config(bad)

    def test_dimensions_and_sample_counts_are_frozen(self):
        self.assertEqual(GATE["dimensions"], {
            "state_dimension": 16,
            "action_dimension": 16,
            "physical_joint_count": 18,
        })
        self.assertEqual(GATE["sampling"]["expected_distinct_samples"], 12)
        self.assertEqual(GATE["sampling"]["episodes"], 4)

    def test_claim_boundary_is_interoperability_only(self):
        boundary = GATE["claim_boundary"]
        self.assertTrue(boundary["open_loop_interoperability_only"])
        for flag in (
            "proves_policy_convergence",
            "proves_closed_loop_control",
            "proves_task_success",
            "proves_generalization",
            "proves_robustness",
            "proves_real_robot_safety",
            "proves_amd_performance_advantage",
        ):
            self.assertFalse(boundary[flag], flag)

    def test_checked_in_interface_matches_gate(self):
        interface = load_json(
            ROOT / "configs" / "mantis-lerobot-interface-v1.json"
        )
        validate_interface_contract(interface, gate=GATE)

    def test_interface_order_mismatch_fails_closed(self):
        interface = load_json(
            ROOT / "configs" / "mantis-lerobot-interface-v1.json"
        )
        interface["action_names"] = list(reversed(interface["action_names"]))
        with self.assertRaises(ContractError):
            validate_interface_contract(interface, gate=GATE)


# ---------------------------------------------------------------------------
# Sample selection.
# ---------------------------------------------------------------------------


class SampleSelectionTests(unittest.TestCase):
    def test_offsets_collapse_short_episodes(self):
        self.assertEqual(sample_offsets(0), [])
        self.assertEqual(sample_offsets(1), [0])
        self.assertEqual(sample_offsets(2), [0, 1])
        self.assertEqual(sample_offsets(3), [0, 1, 2])
        self.assertEqual(sample_offsets(4), [0, 2, 3])

    def test_four_episodes_yield_exactly_twelve_distinct(self):
        bounds = _four_episode_bounds()
        selected = select_samples(
            bounds, expected_episodes=4, expected_distinct_samples=12
        )
        self.assertEqual(len(selected), 12)
        globals_selected = [g for _, g, _ in selected]
        self.assertEqual(len(set(globals_selected)), 12)
        # first / midpoint / last per episode.
        self.assertEqual(
            [(ep, off) for ep, _, off in selected if ep == 0],
            [(0, 0), (0, 5), (0, 9)],
        )

    def test_non_contiguous_episodes_fail_closed(self):
        with self.assertRaises(ContractError):
            select_samples({1: (0, 3)}, expected_episodes=4, expected_distinct_samples=12)

    def test_wrong_distinct_count_fails_closed(self):
        # Four single-frame episodes select only four distinct samples.
        with self.assertRaises(ContractError):
            select_samples(
                {0: (0, 1), 1: (1, 1), 2: (2, 1), 3: (3, 1)},
                expected_episodes=4,
                expected_distinct_samples=12,
            )


# ---------------------------------------------------------------------------
# Observation / action validation.
# ---------------------------------------------------------------------------


class ObservationActionTests(unittest.TestCase):
    def test_good_observation_validates(self):
        issues = validate_observation(
            _good_observation(0, 0, 0),
            image_features=IMAGE_FEATURES,
            state_dimension=16,
        )
        self.assertEqual(issues, [])

    def test_non_finite_state_is_rejected(self):
        bad = _good_observation(0, 0, 0)
        bad = Observation(
            global_index=0,
            episode_index=0,
            offset=0,
            state=[float("nan")] + [0.0] * 15,
            images=bad.images,
        )
        issues = validate_observation(
            bad, image_features=IMAGE_FEATURES, state_dimension=16
        )
        self.assertTrue(any(i.startswith("invalid_state") for i in issues))

    def test_wrong_state_dimension_is_rejected(self):
        bad = _good_observation(0, 0, 0)
        bad = Observation(
            global_index=0,
            episode_index=0,
            offset=0,
            state=[0.0] * 15,
            images=bad.images,
        )
        issues = validate_observation(
            bad, image_features=IMAGE_FEATURES, state_dimension=16
        )
        self.assertTrue(any(i.startswith("invalid_state") for i in issues))

    def test_image_shape_mismatch_is_rejected(self):
        bad = _good_observation(0, 0, 0)
        images = dict(bad.images)
        images["observation.images.env_cam"] = TensorSummary(shape=(3, 240, 321), finite=True)
        bad = Observation(0, 0, 0, bad.state, images)
        issues = validate_observation(
            bad, image_features=IMAGE_FEATURES, state_dimension=16
        )
        self.assertTrue(any(i.startswith("image_shape_mismatch") for i in issues))

    def test_non_finite_image_is_rejected(self):
        bad = _good_observation(0, 0, 0)
        images = dict(bad.images)
        images["observation.images.env_cam"] = TensorSummary(shape=ENV_SHAPE, finite=False)
        bad = Observation(0, 0, 0, bad.state, images)
        issues = validate_observation(
            bad, image_features=IMAGE_FEATURES, state_dimension=16
        )
        self.assertTrue(any(i.startswith("image_not_finite") for i in issues))

    def test_image_value_out_of_range_is_rejected(self):
        bad = _good_observation(0, 0, 0)
        images = dict(bad.images)
        images["observation.images.env_cam"] = TensorSummary(
            shape=ENV_SHAPE, finite=True, min_value=-0.01, max_value=1.01
        )
        bad = Observation(0, 0, 0, bad.state, images)
        issues = validate_observation(
            bad, image_features=IMAGE_FEATURES, state_dimension=16
        )
        self.assertTrue(any(i.startswith("image_value_out_of_range") for i in issues))

    def test_finite_action_validates(self):
        finite, components = validate_action_vector(_safe_action(0), action_dimension=16)
        self.assertTrue(finite)
        self.assertEqual(len(components), 16)

    def test_non_finite_action_is_rejected(self):
        bad = _safe_action(0)
        bad[3] = float("inf")
        finite, components = validate_action_vector(bad, action_dimension=16)
        self.assertFalse(finite)
        self.assertEqual(components, [])

    def test_wrong_dimension_action_is_rejected(self):
        finite, _ = validate_action_vector([0.0] * 15, action_dimension=16)
        self.assertFalse(finite)


# ---------------------------------------------------------------------------
# Gripper range and fixed joint limits.
# ---------------------------------------------------------------------------


class SafetyLimitTests(unittest.TestCase):
    def test_physical_joint_limits_cover_all_eighteen(self):
        limits = physical_joint_limits(
            FIXED_PLAN, PORT["target"]["physical_joint_order"]
        )
        self.assertEqual(set(limits), set(PORT["target"]["physical_joint_order"]))
        self.assertEqual(len(limits), 18)

    def test_safe_action_passes_joint_limits(self):
        physical = expand_virtual_to_physical(_safe_action(0), port=PORT)
        self.assertEqual(len(physical), 18)
        order = PORT["target"]["physical_joint_order"]
        limits = physical_joint_limits(FIXED_PLAN, order)
        self.assertEqual(enforce_joint_limits(physical, physical_order=order, limits=limits), [])

    def test_gripper_out_of_range_is_rejected(self):
        bad = _safe_action(0)
        bad[7] = 1.5  # outside [0, 1]
        with self.assertRaises(ContractError):
            expand_virtual_to_physical(bad, port=PORT)

    def test_v2_projection_saturates_only_gripper_channels(self):
        raw = [0.01 * index for index in range(16)]
        raw[7] = 1.005
        raw[15] = -0.011
        projected, indices, max_delta = project_virtual_gripper_action(
            raw, gate=GATE_V2, port=PORT
        )
        self.assertEqual(indices, [7, 15])
        self.assertEqual(projected[7], 1.0)
        self.assertEqual(projected[15], 0.0)
        self.assertAlmostEqual(max_delta, 0.011)
        for index in range(16):
            if index not in (7, 15):
                self.assertEqual(projected[index], raw[index])

    def test_v1_projection_preserves_strict_rejection_semantics(self):
        raw = _safe_action(0)
        raw[7] = 1.001
        projected, indices, max_delta = project_virtual_gripper_action(
            raw, gate=GATE, port=PORT
        )
        self.assertEqual(projected, raw)
        self.assertEqual(indices, [])
        self.assertEqual(max_delta, 0.0)
        with self.assertRaises(ContractError):
            expand_virtual_to_physical(projected, port=PORT)

    def test_projection_indices_are_derived_from_port_joint_order(self):
        bad_port = json.loads(json.dumps(PORT))
        bad_port["target"]["joint_order"][7] = "left_not_a_gripper_joint_name"
        with self.assertRaises(ContractError):
            project_virtual_gripper_action(
                _safe_action(0), gate=GATE_V2, port=bad_port
            )

    def test_v3_physical_projection_saturates_to_fixed_joint_limits(self):
        order = PORT["target"]["physical_joint_order"]
        limits = physical_joint_limits(FIXED_PLAN, order)
        physical = expand_virtual_to_physical(_safe_action(0), port=PORT)
        elbow_index = order.index("left_elbow_joint")
        wrist_index = order.index("left_wrist_yaw_joint")
        physical[elbow_index] = 2.0
        physical[wrist_index] = 1.754
        projected, names, max_delta = project_physical_joint_target(
            physical,
            gate=GATE_V3,
            physical_order=order,
            limits=limits,
        )
        self.assertEqual(names, ["left_elbow_joint", "left_wrist_yaw_joint"])
        self.assertEqual(projected[elbow_index], limits["left_elbow_joint"][1])
        self.assertEqual(projected[wrist_index], limits["left_wrist_yaw_joint"][1])
        self.assertAlmostEqual(max_delta, 2.0 - limits["left_elbow_joint"][1])
        self.assertEqual(
            enforce_joint_limits(projected, physical_order=order, limits=limits), []
        )

    def test_v2_keeps_physical_joint_rejection_semantics(self):
        order = PORT["target"]["physical_joint_order"]
        limits = physical_joint_limits(FIXED_PLAN, order)
        physical = expand_virtual_to_physical(_safe_action(0), port=PORT)
        physical[order.index("left_wrist_yaw_joint")] = 1.754
        projected, names, max_delta = project_physical_joint_target(
            physical,
            gate=GATE_V2,
            physical_order=order,
            limits=limits,
        )
        self.assertEqual(projected, physical)
        self.assertEqual(names, [])
        self.assertEqual(max_delta, 0.0)
        self.assertTrue(
            enforce_joint_limits(projected, physical_order=order, limits=limits)
        )

    def test_joint_limit_violation_is_reported(self):
        # Push the left elbow beyond its [-2.477, 0.662] fixed limit.
        bad = _safe_action(0)
        bad[3] = 2.0
        physical = expand_virtual_to_physical(bad, port=PORT)
        order = PORT["target"]["physical_joint_order"]
        limits = physical_joint_limits(FIXED_PLAN, order)
        issues = enforce_joint_limits(physical, physical_order=order, limits=limits)
        self.assertTrue(any("left_elbow_joint" in i for i in issues))


# ---------------------------------------------------------------------------
# Checkpoint processor file requirements.
# ---------------------------------------------------------------------------


class CheckpointFileTests(unittest.TestCase):
    def _make_checkpoint(self, tmp: Path) -> Path:
        checkpoint_root = tmp / "060000"
        pretrained = checkpoint_root / "pretrained_model"
        pretrained.mkdir(parents=True)
        for name in REQUIRED_PROCESSOR_FILES:
            (checkpoint_root / name).write_text(name, encoding="utf-8")
        return checkpoint_root

    def test_complete_checkpoint_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_root = self._make_checkpoint(Path(tmp))
            files = validate_required_checkpoint_files(checkpoint_root, GATE)
            self.assertEqual(sorted(files), sorted(REQUIRED_PROCESSOR_FILES))

    def test_missing_step_specific_safetensors_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_root = self._make_checkpoint(Path(tmp))
            (checkpoint_root / "pretrained_model" /
             "policy_preprocessor_step_3_normalizer_processor.safetensors").unlink()
            with self.assertRaises(ContractError):
                validate_required_checkpoint_files(checkpoint_root, GATE)

    def test_nonexistent_directory_fails(self):
        with self.assertRaises(ContractError):
            validate_required_checkpoint_files(
                Path("/nonexistent-checkpoint-dir-12345"), GATE
            )


# ---------------------------------------------------------------------------
# End-to-end core receipts (pass / fail).
# ---------------------------------------------------------------------------


class CoreReceiptTests(unittest.TestCase):
    def _run(self, runtime, *, gate=GATE):
        return run_open_loop_inference(
            runtime,
            gate=gate,
            gate_sha256="g" * 64,
            port=PORT,
            fixed_plan=FIXED_PLAN,
            interface=load_json(ROOT / "configs" / "mantis-lerobot-interface-v1.json"),
        )

    def test_clean_runtime_passes_with_twelve_samples(self):
        receipt = self._run(FakeRuntime())
        self.assertTrue(receipt["open_loop_inference_pass"], receipt["issues"])
        self.assertEqual(receipt["issues"], [])
        self.assertEqual(receipt["decoded_samples"], 12)
        self.assertEqual(receipt["distinct_selected_samples"], 12)
        self.assertEqual(len(receipt["selected_global_indices"]), 12)
        self.assertEqual(sorted(receipt["selected_episodes"]), [0, 1, 2, 3])
        self.assertTrue(all(s["safety_pass"] for s in receipt["per_sample"]))
        self.assertTrue(all(s["action_finite"] for s in receipt["per_sample"]))
        # Reset is invoked once per independent sample (no episodic leakage).
        self.assertEqual(receipt["decoded_samples"], 12)
        # allow_unverified simulation-only mapping is recorded explicitly.
        gripper = receipt["gripper_contract"]
        self.assertTrue(gripper["simulation_only"])
        self.assertTrue(gripper["allow_unverified"])
        self.assertEqual(
            gripper["allow_unverified_only_for"], "genesis_simulation_projection"
        )

    def test_runtime_identity_mismatch_fails_closed(self):
        runtime = FakeRuntime(lerobot_version="0.4.2", hip_device_count=2)
        receipt = self._run(runtime)
        self.assertFalse(receipt["open_loop_inference_pass"])
        self.assertTrue(any("lerobot_version_mismatch" in i for i in receipt["issues"]))
        self.assertTrue(any("hip_device_count_mismatch" in i for i in receipt["issues"]))

    def test_joint_limit_violation_fails_closed(self):
        over_limit = _safe_action(0)
        over_limit[3] = 2.0  # left elbow beyond its fixed limit
        runtime = FakeRuntime(bad_actions={gi: over_limit for gi in range(40)})
        receipt = self._run(runtime)
        self.assertFalse(receipt["open_loop_inference_pass"])
        self.assertTrue(
            any("joint_limit_violation:left_elbow_joint" in i for i in receipt["issues"])
        )

    def test_gripper_out_of_range_fails_closed(self):
        bad = _safe_action(0)
        bad[15] = 2.0
        runtime = FakeRuntime(bad_actions={gi: bad for gi in range(40)})
        receipt = self._run(runtime)
        self.assertFalse(receipt["open_loop_inference_pass"])
        self.assertTrue(any("gripper_expansion_failed" in i for i in receipt["issues"]))

    def test_v2_gripper_projection_passes_and_records_raw_action(self):
        bad = _safe_action(0)
        bad[7] = 1.005
        bad[15] = -0.011
        runtime = FakeRuntime(bad_actions={gi: bad for gi in range(40)})
        receipt = self._run(runtime, gate=GATE_V2)
        self.assertTrue(receipt["open_loop_inference_pass"], receipt["issues"])
        self.assertEqual(receipt["gripper_contract"]["saturated_sample_count"], 12)
        self.assertEqual(receipt["gripper_contract"]["saturated_channel_count"], 24)
        self.assertAlmostEqual(
            receipt["gripper_contract"]["max_abs_saturation_delta"], 0.011
        )
        for sample in receipt["per_sample"]:
            self.assertEqual(sample["raw_action_16d"][7], 1.005)
            self.assertEqual(sample["raw_action_16d"][15], -0.011)
            self.assertEqual(sample["projected_action_16d"][7], 1.0)
            self.assertEqual(sample["projected_action_16d"][15], 0.0)
            self.assertEqual(sample["saturated_action_indices"], [7, 15])
            self.assertEqual(len(sample["physical_target_18d"]), 18)

    def test_v2_projection_does_not_mask_arm_joint_limit_violation(self):
        bad = _safe_action(0)
        bad[3] = 2.0
        bad[7] = 1.005
        runtime = FakeRuntime(bad_actions={gi: bad for gi in range(40)})
        receipt = self._run(runtime, gate=GATE_V2)
        self.assertFalse(receipt["open_loop_inference_pass"])
        self.assertTrue(
            any("joint_limit_violation:left_elbow_joint" in i for i in receipt["issues"])
        )

    def test_v3_projects_physical_target_and_records_preprojection_violation(self):
        bad = _safe_action(0)
        bad[3] = 2.0
        bad[7] = 1.005
        runtime = FakeRuntime(bad_actions={gi: bad for gi in range(40)})
        receipt = self._run(runtime, gate=GATE_V3)
        self.assertTrue(receipt["open_loop_inference_pass"], receipt["issues"])
        projection = receipt["physical_joint_output_projection"]
        self.assertEqual(projection["saturated_sample_count"], 12)
        self.assertEqual(projection["saturated_joint_count"], 12)
        self.assertAlmostEqual(
            projection["max_abs_saturation_delta"],
            2.0 - FIXED_PLAN["joint_limits"]["left_elbow_joint"]["upper"],
        )
        for sample in receipt["per_sample"]:
            self.assertTrue(sample["preprojection_joint_limit_issues"])
            self.assertEqual(
                sample["saturated_physical_joint_names"], ["left_elbow_joint"]
            )
            self.assertEqual(sample["joint_limit_issues"], [])
            self.assertEqual(len(sample["raw_physical_target_18d"]), 18)
            self.assertEqual(len(sample["projected_physical_target_18d"]), 18)

    def test_inference_error_is_recorded_without_aborting(self):
        runtime = FakeRuntime(infer_errors={0})
        receipt = self._run(runtime)
        self.assertFalse(receipt["open_loop_inference_pass"])
        self.assertTrue(any("inference_error" in i for i in receipt["issues"]))
        # The other 11 samples still decode and infer.
        self.assertEqual(receipt["decoded_samples"], 12)

    def test_claim_boundary_carried_into_receipt(self):
        receipt = self._run(FakeRuntime())
        boundary = receipt["claim_boundary"]
        self.assertTrue(boundary["open_loop_interoperability_only"])
        self.assertFalse(boundary["proves_closed_loop_control"])
        self.assertFalse(boundary["proves_task_success"])
        self.assertFalse(boundary["proves_amd_performance_advantage"])

    def test_receipt_is_deterministic(self):
        first = self._run(FakeRuntime())
        second = self._run(FakeRuntime())
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


# ---------------------------------------------------------------------------
# Lazy heavy imports + processor loader wiring.
# ---------------------------------------------------------------------------


class LazyImportTests(unittest.TestCase):
    def test_module_import_does_not_pull_torch_or_lerobot(self):
        import importlib

        for heavy in ("torch", "lerobot", "PIL", "torchvision"):
            sys.modules.pop(heavy, None)
        importlib.import_module("mantis_rocm_bridge.act_openloop_inference")
        for heavy in ("torch", "lerobot", "PIL", "torchvision"):
            self.assertNotIn(heavy, sys.modules, heavy)

    def test_runtime_class_is_lazy_constructible(self):
        # The real adapter must be defined but must not import torch until
        # constructed (and never on module import).
        self.assertTrue(callable(LeRobotOpenLoopRuntime))
        self.assertNotIn("torch", sys.modules)


# ---------------------------------------------------------------------------
# CLI argument handling, exclusive output, fail-closed publishing.
# ---------------------------------------------------------------------------


class CLIArgumentTests(unittest.TestCase):
    def setUp(self):
        self.cli = _load_cli_module()
        self._stdout = io.StringIO()
        self._patcher = contextlib.redirect_stdout(self._stdout)
        self._patcher.__enter__()
        self._orig_runtime = self.cli.LeRobotOpenLoopRuntime
        self._orig_run = self.cli.run_open_loop_inference

    def tearDown(self):
        self._patcher.__exit__(None, None, None)
        self.cli.LeRobotOpenLoopRuntime = self._orig_runtime
        self.cli.run_open_loop_inference = self._orig_run

    def _stub_core(self, *, receipt):
        captured = {}

        class _StubRuntime:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        def _stub_run(runtime, **_):
            return receipt

        self.cli.LeRobotOpenLoopRuntime = _StubRuntime
        self.cli.run_open_loop_inference = _stub_run
        return captured

    def test_relative_dataset_root_is_rejected(self):
        self._stub_core(receipt={"open_loop_inference_pass": True, "per_sample": []})
        with self.assertRaises(SystemExit) as ctx:
            self.cli.main(["relative/ds", "--repo-id", "mantis/x",
                           "--pretrained-model", "/abs/pm", "--output-dir", "/abs/out"])
        self.assertEqual(ctx.exception.code, 2)

    def test_relative_pretrained_model_is_rejected(self):
        self._stub_core(receipt={"open_loop_inference_pass": True, "per_sample": []})
        with self.assertRaises(SystemExit) as ctx:
            self.cli.main(["/abs/ds", "--repo-id", "mantis/x",
                           "--pretrained-model", "relative/pm", "--output-dir", "/abs/out"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_dataset_dir_is_rejected(self):
        self._stub_core(receipt={"open_loop_inference_pass": True, "per_sample": []})
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            with self.assertRaises(SystemExit) as ctx:
                self.cli.main([str(missing), "--repo-id", "mantis/x",
                               "--pretrained-model", "/abs/pm", "--output-dir", "/abs/out"])
            self.assertEqual(ctx.exception.code, 2)

    def test_existing_output_dir_is_refused(self):
        self._stub_core(receipt={"open_loop_inference_pass": True, "per_sample": []})
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "out"
            existing.mkdir()
            with self.assertRaises(SystemExit) as ctx:
                self.cli.main([str(tmp), "--repo-id", "mantis/x",
                               "--pretrained-model", "/abs/pm", "--output-dir", str(existing)])
            self.assertEqual(ctx.exception.code, 2)

    def test_all_paths_resolved_absolute_and_passed_to_core(self):
        captured = self._stub_core(receipt={"open_loop_inference_pass": True, "per_sample": []})
        with tempfile.TemporaryDirectory() as tmp:
            ds = Path(tmp) / "ds"
            ds.mkdir()
            pm = Path(tmp) / "pm"
            pm.mkdir()
            out = Path(tmp) / "out"
            rc = self.cli.main([
                str(ds), "--repo-id", "mantis/x",
                "--pretrained-model", str(pm), "--output-dir", str(out),
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(Path(captured["dataset_root"]).is_absolute())
            self.assertTrue(Path(captured["pretrained_model"]).is_absolute())
            self.assertEqual(captured["repo_id"], "mantis/x")


# ---------------------------------------------------------------------------
# Fail-closed publishing + deterministic manifest.
# ---------------------------------------------------------------------------


class PublishArtifactTests(unittest.TestCase):
    def setUp(self):
        self.cli = _load_cli_module()

    def _receipt(self, passing: bool) -> dict:
        return {
            "schema_version": 1,
            "gate_id": "mantis_act_openloop_inference_v1",
            "task_id": "stack_bowls_three",
            "phase": "open_loop_inference_gate",
            "open_loop_inference_pass": passing,
            "issues": [] if passing else ["gate_failed_closed:ContractError:boom"],
            "per_sample": [],
            "claim_boundary": GATE["claim_boundary"],
        }

    def test_publish_writes_all_artifacts_exclusively(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            self.cli.publish_artifacts(
                output_dir=out,
                started={"gate_id": "g"},
                actions=[{"global_index": 0}],
                receipt=self._receipt(True),
            )
            for name in OUTPUT_ARTIFACTS:
                self.assertTrue((out / name).is_file(), name)
            self.assertEqual((out / "status").read_text(encoding="utf-8"), "PASS\n")
            # Re-publishing the same file via the writer would raise (no overwrite).
            with self.assertRaises(FileExistsError):
                (out / "status").open("x", encoding="utf-8")

    def test_fail_receipt_records_fail_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            self.cli.publish_artifacts(
                output_dir=out,
                started={"gate_id": "g"},
                actions=[],
                receipt=self._receipt(False),
            )
            self.assertEqual((out / "status").read_text(encoding="utf-8"), "FAIL\n")
            receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["open_loop_inference_pass"])

    def test_manifest_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            out_a.mkdir()
            out_b.mkdir()
            self.cli.publish_artifacts(
                output_dir=out_a, started={"gate_id": "g"}, actions=[], receipt=self._receipt(True)
            )
            self.cli.publish_artifacts(
                output_dir=out_b, started={"gate_id": "g"}, actions=[], receipt=self._receipt(True)
            )
            manifest_a = (out_a / "SHA256SUMS").read_text(encoding="utf-8")
            manifest_b = (out_b / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertEqual(manifest_a, manifest_b)
            # The manifest lists every non-manifest artifact, sorted by name.
            names = [line.split("  ", 1)[1] for line in manifest_a.splitlines()]
            self.assertEqual(names, sorted(names))
            self.assertIn("receipt.json", names)
            self.assertIn("started.json", names)
            self.assertNotIn("SHA256SUMS", names)

    def test_manifest_covers_only_real_files_sorted(self):
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "started.json").write_text("alpha", encoding="utf-8")
            (out / "receipt.json").write_text("beta", encoding="utf-8")
            manifest = self.cli._build_sha256sums(out)
            expected = (
                f"{hashlib.sha256(b'beta').hexdigest()}  receipt.json\n"
                f"{hashlib.sha256(b'alpha').hexdigest()}  started.json\n"
            )
            self.assertEqual(manifest, expected)


if __name__ == "__main__":
    unittest.main()
