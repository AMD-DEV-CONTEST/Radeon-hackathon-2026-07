from __future__ import annotations

import copy
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import (
    ContractError,
    load_json,
    validate_contract_pair,
    validate_fixed_base_plan,
    validate_source_task_contract,
    validate_scene_gate_contracts,
)
from mantis_rocm_bridge.stack_bowls_env import validate_genesis_scene_contract


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = load_json(ROOT / "configs/mantis-port-config.json")
        self.task = load_json(ROOT / "configs/task-pack-v1.json")
        self.source_task = load_json(ROOT / "configs/source-task-stack-bowls-three.json")
        self.asset_plan = load_json(ROOT / "configs/fixed-base-plan.json")
        self.control_resampling = load_json(ROOT / "configs/control-resampling-v1.json")
        self.camera_extrinsics = load_json(ROOT / "configs/camera-extrinsics-v1.json")
        self.bowl_asset_plan = load_json(ROOT / "configs/bowl-asset-plan.json")
        self.genesis_scene = load_json(ROOT / "configs/stack-bowls-genesis-v1.json")

    def test_checked_in_contracts_are_consistent_but_blocked(self) -> None:
        blockers = validate_contract_pair(self.port, self.task, self.source_task)
        self.assertIn("gripper_mapping_unverified", blockers)
        self.assertNotIn("target_camera_extrinsics_not_frozen", blockers)
        self.assertNotIn("bowl_asset_license_missing", blockers)
        self.assertNotIn("source_variable_duration_control_requires_resampling", blockers)
        self.assertNotIn("bowl_asset_not_materialized_for_genesis", blockers)
        self.assertEqual(self.port["port"]["mode"], "new_robot_same_task")
        self.assertEqual(self.port["target"]["joint_order"][4:7], [
            "left_wrist_roll_joint",
            "left_wrist_pitch_joint",
            "left_wrist_yaw_joint",
        ])

    def test_joint_map_must_cover_every_target_joint(self) -> None:
        broken = copy.deepcopy(self.port)
        broken["joint_map"]["wrist_yaw_L_Joint"] = "left_wrist_roll_joint"
        with self.assertRaises(ContractError):
            validate_contract_pair(broken, self.task)

    def test_camera_order_mismatch_is_rejected(self) -> None:
        broken = copy.deepcopy(self.task)
        broken["policy_observations"][1:3] = reversed(broken["policy_observations"][1:3])
        with self.assertRaises(ContractError):
            validate_contract_pair(self.port, broken)

    def test_ready_contract_cannot_retain_blockers(self) -> None:
        broken = copy.deepcopy(self.port)
        broken["status"] = "ready"
        with self.assertRaises(ContractError):
            validate_contract_pair(broken, self.task)

    def test_target_task_must_match_task_contract(self) -> None:
        broken = copy.deepcopy(self.port)
        broken["target"]["task_id"] = "different_task"
        with self.assertRaises(ContractError):
            validate_contract_pair(broken, self.task)

    def test_same_task_mode_rejects_task_change(self) -> None:
        broken = copy.deepcopy(self.port)
        broken["target"]["task_id"] = "different_task"
        with self.assertRaises(ContractError):
            validate_contract_pair(broken, self.task)

    def test_pending_normalization_requires_blocker(self) -> None:
        broken = copy.deepcopy(self.port)
        broken["training"]["normalization_recomputed"] = False
        self.assertNotIn("normalization_stats_not_generated", broken["blockers"])
        with self.assertRaises(ContractError):
            validate_contract_pair(broken, self.task)

    def test_unresolved_camera_mount_requires_blocker(self) -> None:
        broken = copy.deepcopy(self.port)
        broken["target"]["camera_extrinsics"]["left_wrist_cam"] = {
            "status": "unresolved_hardware_mount"
        }
        with self.assertRaises(ContractError):
            validate_contract_pair(broken, self.task)

    def test_scene_gate_contracts_are_frozen(self) -> None:
        validate_scene_gate_contracts(
            self.port,
            self.control_resampling,
            self.camera_extrinsics,
            self.bowl_asset_plan,
        )

    def test_genesis_task_scene_contract_is_frozen(self) -> None:
        validate_genesis_scene_contract(self.genesis_scene, self.source_task, self.port)

    def test_genesis_bimanual_grasp_geometry_drift_is_rejected(self) -> None:
        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_contact_probe"]["grasp_half_span_m"] = 0.15
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_contact_probe"]["orientations_wxyz"]["right"] = [
            1.0,
            0.0,
            0.0,
            0.0,
        ]
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

    def test_genesis_bimanual_rim_hook_geometry_drift_is_rejected(self) -> None:
        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_rim_hook_probe"]["gripper_hold_open_fraction"] = 0.5
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_rim_hook_probe"]["lift_distance_m"] = 0.02
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_rim_hook_probe"]["minimum_lift_delta_m"] = 0.009
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_rim_hook_probe"]["transport_target_xy_m"] = [0.01, -0.1]
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_rim_hook_probe"]["grasp_half_span_m"] = 0.15
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

        broken = copy.deepcopy(self.genesis_scene)
        broken["bimanual_rim_hook_probe"]["orientations_wxyz"]["left"] = [
            1.0,
            0.0,
            0.0,
            0.0,
        ]
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

    def test_genesis_scene_rejects_table_or_base_quaternion_drift(self) -> None:
        broken = copy.deepcopy(self.genesis_scene)
        broken["world"]["table_plane_z_m"] = 0.75
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)
        broken = copy.deepcopy(self.genesis_scene)
        broken["world"]["mantis_base"]["quaternion_wxyz"][0] = 0.5
        with self.assertRaises(ContractError):
            validate_genesis_scene_contract(broken, self.source_task, self.port)

    def test_control_joint_order_drift_is_rejected(self) -> None:
        broken = copy.deepcopy(self.control_resampling)
        broken["target"]["joint_order"][0:2] = reversed(
            broken["target"]["joint_order"][0:2]
        )
        with self.assertRaises(ContractError):
            validate_scene_gate_contracts(
                self.port, broken, self.camera_extrinsics, self.bowl_asset_plan
            )

    def test_materialized_bowl_requires_runtime_receipt(self) -> None:
        broken = copy.deepcopy(self.port)
        broken["runtime_validation"]["genesis_scene_cpu"]["status"] = "failed"
        with self.assertRaises(ContractError):
            validate_contract_pair(broken, self.task)

    def test_source_contract_preserves_legacy_evidence_boundary(self) -> None:
        validate_source_task_contract(self.source_task)
        legacy = self.source_task["evaluation_protocols"]["legacy_source_v1"]
        self.assertEqual(legacy["stable_frame_requirement"], 0)
        self.assertIn("actual_z_minus_target_z", legacy["height_comparison"])

    def test_source_contract_rejects_invalid_hash(self) -> None:
        broken = copy.deepcopy(self.source_task)
        broken["source_revision"]["task_source_sha256"] = "not-a-hash"
        with self.assertRaises(ContractError):
            validate_source_task_contract(broken)

    def test_fixed_base_plan_matches_physical_contract(self) -> None:
        validate_fixed_base_plan(self.asset_plan, self.port)

    def test_fixed_base_plan_rejects_missing_joint_limit(self) -> None:
        broken = copy.deepcopy(self.asset_plan)
        broken["joint_limits"].pop("left_elbow_joint")
        with self.assertRaises(ContractError):
            validate_fixed_base_plan(broken, self.port)

    def test_cuda_reference_keeps_version_boundary_explicit(self) -> None:
        runtime = self.port["runtime_validation"]
        cuda = runtime["genesis_cuda"]
        quadrants = runtime["genesis_cuda_quadrants"]
        self.assertEqual(cuda["status"], "passed_compatibility_reference")
        self.assertTrue(cuda["runtime_gate_pass"])
        self.assertIn("not the AMD target runtime", cuda["evidence_boundary"])
        self.assertEqual(quadrants["status"], "blocked_by_host_driver")
        self.assertEqual(quadrants["missing_driver_symbol"], "cuGraphConditionalHandleCreate")
        self.assertFalse(quadrants["system_driver_upgrade_performed"])


if __name__ == "__main__":
    unittest.main()
