from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import (
    ContractError,
    load_json,
    validate_contract_pair,
)
from mantis_rocm_bridge.port_profile import (
    audit_profile_references,
    build_port_plan,
    load_port_profile,
    validate_port_profile,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "configs/robot-port-profile-template-v1.json"
MANTIS_PATH = ROOT / "configs/robot-port-profile-mantis-stack-bowls-v1.json"
SYNTHETIC_PATH = (
    ROOT / "tests/fixtures/robot-port-profile-synthetic-v1.json"
)
WORK_PACKAGE_PATH = ROOT / "configs/framework-mvp-v2.json"
CLI_PATH = ROOT / "tools/plan_robot_port.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RobotPortProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = load_port_profile(TEMPLATE_PATH)
        self.mantis = load_port_profile(MANTIS_PATH)
        self.synthetic = load_port_profile(SYNTHETIC_PATH)

    def test_checked_in_profiles_validate(self) -> None:
        self.assertEqual(self.template["profile_kind"], "template")
        self.assertEqual(self.mantis["profile_kind"], "reference")
        self.assertEqual(self.synthetic["profile_kind"], "synthetic_fixture")

    def test_template_is_valid_but_all_execution_stages_are_blocked(self) -> None:
        plan = build_port_plan(self.template, ROOT)
        self.assertTrue(plan["valid"])
        self.assertEqual(plan["next_stage_ids"], [])
        self.assertEqual(plan["stage_counts"]["blocked"], 4)
        self.assertTrue(
            all(stage["blockers"] for stage in plan["stages"])
        )
        self.assertIn("not a robot port", plan["claim_boundary"])

    def test_synthetic_fixture_proves_only_configurable_planning(self) -> None:
        plan = build_port_plan(self.synthetic, ROOT)
        self.assertTrue(plan["valid"])
        self.assertEqual(plan["profile_id"], "synthetic-four-joint-port-v1")
        self.assertEqual(plan["next_stage_ids"], ["interface-contract"])
        self.assertNotEqual(
            self.synthetic["source"]["robot_id"],
            self.mantis["source"]["robot_id"],
        )
        self.assertNotEqual(
            self.synthetic["target"]["robot_id"],
            self.mantis["target"]["robot_id"],
        )
        self.assertIn("not a second real robot port", plan["claim_boundary"])

    def test_mantis_profile_matches_canonical_target_interface(self) -> None:
        port = load_json(ROOT / "configs/mantis-port-config.json")
        target = self.mantis["target"]
        canonical = port["target"]
        self.assertEqual(target["robot_id"], canonical["robot_id"])
        self.assertEqual(target["task_id"], canonical["task_id"])
        self.assertEqual(
            target["policy_state_dimension"], canonical["state_dim"]
        )
        self.assertEqual(
            target["policy_action_dimension"], canonical["action_dim"]
        )
        self.assertEqual(
            target["physical_state_dimension"], canonical["physical_state_dim"]
        )
        self.assertEqual(
            target["physical_action_dimension"],
            canonical["physical_action_dim"],
        )
        self.assertEqual(target["policy_state_order"], canonical["joint_order"])
        self.assertEqual(target["policy_action_order"], canonical["joint_order"])
        self.assertEqual(
            target["physical_state_order"],
            canonical["physical_joint_order"],
        )
        self.assertEqual(
            target["physical_action_order"],
            canonical["physical_joint_order"],
        )
        self.assertEqual(
            target["observation_keys"],
            canonical["policy_observation_keys"],
        )
        self.assertEqual(target["control_hz"], canonical["control_hz"])

    def test_mantis_reference_audit_and_negative_capability_boundary(self) -> None:
        audit = audit_profile_references(self.mantis, ROOT)
        plan = build_port_plan(self.mantis, ROOT)
        stages = {stage["id"]: stage for stage in plan["stages"]}
        self.assertTrue(audit["pass"])
        self.assertEqual(audit["required_reference_count"], 20)
        self.assertEqual(plan["next_stage_ids"], [])
        self.assertEqual(stages["closedloop-evaluation"]["outcome"], "negative")
        self.assertEqual(
            stages["reference-profile-parity"]["effective_state"], "complete"
        )
        self.assertEqual(
            stages["capability-promotion"]["effective_state"], "blocked"
        )
        self.assertEqual(
            stages["public-submission"]["effective_state"], "blocked"
        )
        self.assertEqual(self.mantis["evaluation"]["recorded_successes"], 0)
        self.assertEqual(self.mantis["evaluation"]["recorded_trials"], 10)
        self.assertEqual(
            self.mantis["evaluation"]["minimum_success_fraction"], 0.6
        )
        self.assertTrue(self.mantis["safety"]["zero_violation_required"])

    def test_pipeline_sections_are_explicit_and_reference_checked(self) -> None:
        for section in (
            "controller",
            "safety",
            "data",
            "policy",
            "evaluation",
        ):
            self.assertIn(section, self.mantis)
            self.assertIn(section, self.template)
            self.assertIn(section, self.synthetic)
        broken = copy.deepcopy(self.mantis)
        broken["policy"]["training_contract_ref"] = "unknown-contract"
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_existing_mantis_contracts_remain_valid_at_their_declared_boundary(
        self,
    ) -> None:
        port = load_json(ROOT / "configs/mantis-port-config.json")
        task = load_json(ROOT / "configs/task-pack-v1.json")
        source_task = load_json(
            ROOT / "configs/source-task-stack-bowls-three.json"
        )
        blockers = validate_contract_pair(port, task, source_task)
        self.assertIn("gripper_mapping_unverified", blockers)

    def test_duplicate_joint_order_is_rejected(self) -> None:
        broken = copy.deepcopy(self.synthetic)
        broken["target"]["policy_state_order"][1] = (
            broken["target"]["policy_state_order"][0]
        )
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_dimension_and_order_mismatch_is_rejected(self) -> None:
        broken = copy.deepcopy(self.synthetic)
        broken["target"]["physical_state_dimension"] = 5
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_state_and_action_dimensions_may_differ(self) -> None:
        valid = copy.deepcopy(self.synthetic)
        valid["target"]["policy_state_dimension"] = 6
        valid["target"]["policy_state_order"] = [
            "target_axis_0_position",
            "target_axis_1_position",
            "target_axis_2_position",
            "target_axis_0_velocity",
            "target_axis_1_velocity",
            "target_axis_2_velocity",
        ]
        valid["target"]["physical_state_dimension"] = 6
        valid["target"]["physical_state_order"] = list(
            valid["target"]["policy_state_order"]
        )
        validate_port_profile(valid)

    def test_same_task_mode_rejects_task_change(self) -> None:
        broken = copy.deepcopy(self.synthetic)
        broken["source"]["task_id"] = "different-task"
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_recorded_evaluation_counts_must_be_consistent(self) -> None:
        broken = copy.deepcopy(self.mantis)
        broken["evaluation"]["recorded_successes"] = 11
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

        broken = copy.deepcopy(self.mantis)
        broken["evaluation"]["recorded_trials"] = None
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_port_mode_enforces_robot_identity(self) -> None:
        broken = copy.deepcopy(self.synthetic)
        broken["target"]["robot_id"] = broken["source"]["robot_id"]
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_unknown_section_reference_is_rejected(self) -> None:
        broken = copy.deepcopy(self.synthetic)
        broken["adapters"]["joint_mapping_ref"] = "missing-reference"
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_unsafe_reference_paths_are_rejected(self) -> None:
        for unsafe_path in ("/tmp/outside.json", "../outside.json"):
            with self.subTest(unsafe_path=unsafe_path):
                broken = copy.deepcopy(self.synthetic)
                broken["references"].append(
                    {
                        "id": "unsafe-reference",
                        "path": unsafe_path,
                        "kind": "config",
                        "required": True,
                        "sha256": None,
                    }
                )
                with self.assertRaises(ContractError):
                    validate_port_profile(broken)

    def test_ready_stage_rejects_nonpromoting_dependency(self) -> None:
        broken = copy.deepcopy(self.synthetic)
        broken["stages"][0]["outcome"] = "negative"
        broken["stages"][0]["promotion"] = "blocks_downstream"
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_blocker_and_blocked_stage_must_agree_bidirectionally(self) -> None:
        broken = copy.deepcopy(self.template)
        broken["blockers"][0]["blocks_stages"].remove("source-task-audit")
        with self.assertRaises(ContractError):
            validate_port_profile(broken)

    def test_missing_required_reference_blocks_plan(self) -> None:
        broken = copy.deepcopy(self.synthetic)
        broken["references"].append(
            {
                "id": "missing-reference",
                "path": "configs/does-not-exist.json",
                "kind": "config",
                "required": True,
                "sha256": None,
            }
        )
        plan = build_port_plan(broken, ROOT)
        self.assertFalse(plan["valid"])
        self.assertEqual(plan["next_stage_ids"], [])
        self.assertEqual(
            plan["reference_audit"]["failed_reference_ids"],
            ["missing-reference"],
        )

    def test_reference_hash_mismatch_is_reported(self) -> None:
        broken = copy.deepcopy(self.mantis)
        broken["references"][0]["sha256"] = "0" * 64
        audit = audit_profile_references(broken, ROOT)
        record = audit["references"][0]
        self.assertFalse(audit["pass"])
        self.assertFalse(record["hash_matches"])
        self.assertEqual(record["actual_sha256"], _sha256(ROOT / record["path"]))

    def test_cli_is_deterministic_and_does_not_modify_profile(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        before = _sha256(MANTIS_PATH)
        command = [
            sys.executable,
            str(CLI_PATH),
            "plan",
            str(MANTIS_PATH),
        ]
        first = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        second = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(before, _sha256(MANTIS_PATH))
        self.assertTrue(json.loads(first.stdout)["valid"])

    def test_cli_exposes_no_execution_or_output_option(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [sys.executable, str(CLI_PATH), "--help"],
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        for option in ("--output", "--backend", "--remote", "--train", "--run"):
            self.assertNotIn(option, result.stdout)

    def test_runtime_files_are_byte_identical_and_do_not_import_profile(self) -> None:
        contract = load_json(WORK_PACKAGE_PATH)
        for relative_path, expected_sha256 in contract[
            "runtime_immutability"
        ].items():
            with self.subTest(path=relative_path):
                path = ROOT / relative_path
                self.assertEqual(_sha256(path), expected_sha256)
                self.assertNotIn(
                    "port_profile",
                    path.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
