from __future__ import annotations

import copy
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import (
    ContractError,
    load_json,
    validate_amd_cloud_runtime_contract,
    validate_competition_resources_contract,
)


ROOT = Path(__file__).resolve().parents[1]


class CompetitionResourcesContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(ROOT / "configs/competition-resources-v1.json")

    def test_frozen_resources_are_valid(self) -> None:
        validate_competition_resources_contract(self.contract)

    def test_multi_gpu_final_path_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["event"]["hardware_execution_rule"]["required_visible_gpu_count"] = 8
        with self.assertRaises(ContractError):
            validate_competition_resources_contract(broken)

    def test_deadline_or_submission_repository_drift_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["event"]["submission_deadline"] = "2026-08-07T00:00:00+08:00"
        with self.assertRaises(ContractError):
            validate_competition_resources_contract(broken)

    def test_cloud_execution_status_requires_attempted_true(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["cloud"]["instance_creation_attempted_in_this_snapshot"] = False
        with self.assertRaises(ContractError):
            validate_competition_resources_contract(broken)

    def test_maintenance_snapshot_requires_attempted_false(self) -> None:
        historical = copy.deepcopy(self.contract)
        historical["cloud"]["instance_creation_status"] = (
            "deferred_platform_maintenance"
        )
        historical["cloud"]["instance_creation_attempted_in_this_snapshot"] = False
        validate_competition_resources_contract(historical)

        historical["cloud"]["instance_creation_attempted_in_this_snapshot"] = True
        with self.assertRaises(ContractError):
            validate_competition_resources_contract(historical)

        broken = copy.deepcopy(self.contract)
        broken["submission"]["repository"] = "https://example.invalid/repo"
        with self.assertRaises(ContractError):
            validate_competition_resources_contract(broken)


class AmdCloudRuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(ROOT / "configs/amd-cloud-runtime-v1.json")

    def test_frozen_cloud_runtime_is_valid(self) -> None:
        validate_amd_cloud_runtime_contract(self.contract)

    def test_plain_pypi_torch_or_cuda_backend_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["pytorch"]["plain_pip_install_torch_forbidden"] = False
        with self.assertRaises(ContractError):
            validate_amd_cloud_runtime_contract(broken)

        broken = copy.deepcopy(self.contract)
        broken["genesis"]["backend"] = "gs.cuda"
        with self.assertRaises(ContractError):
            validate_amd_cloud_runtime_contract(broken)

    def test_nonpersistent_or_multi_gpu_cloud_path_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["platform"]["persistent_storage"] = "Local Storage"
        with self.assertRaises(ContractError):
            validate_amd_cloud_runtime_contract(broken)

        broken = copy.deepcopy(self.contract)
        broken["platform"]["required_visible_gpu_count"] = 2
        with self.assertRaises(ContractError):
            validate_amd_cloud_runtime_contract(broken)

    def test_stage0_inventory_verified_state_passes(self) -> None:
        """Current amd-cloud-runtime-v1.json with stage0_inventory_verified status should pass."""
        validate_amd_cloud_runtime_contract(self.contract)

    def test_stage0_inventory_requires_gpu_count_1(self) -> None:
        """stage0_inventory_verified requires gpu.count=1."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["gpu"]["count"] = 2
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("gpu.count must be 1", str(cm.exception))

    def test_stage0_inventory_requires_arch_name_strings(self) -> None:
        """stage0_inventory_verified requires arch and name as non-empty strings."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["gpu"]["arch"] = ""
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("arch must be a non-empty string", str(cm.exception))

        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["gpu"]["name"] = None
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("name must be a non-empty string", str(cm.exception))

    def test_stage0_inventory_requires_positive_vram_bytes(self) -> None:
        """stage0_inventory_verified requires vram_bytes as positive integer."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["gpu"]["vram_bytes"] = -1
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("vram_bytes must be a positive integer", str(cm.exception))

        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["gpu"]["vram_bytes"] = "not-an-int"
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("vram_bytes must be a positive integer", str(cm.exception))

    def test_stage0_inventory_requires_uuid_recorded_false(self) -> None:
        """stage0_inventory_verified requires uuid_recorded=false."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["gpu"]["uuid_recorded"] = True
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("uuid_recorded must be false", str(cm.exception))

    def test_stage0_inventory_requires_rocm_python_pip_strings(self) -> None:
        """stage0_inventory_verified requires ROCm/Python/pip as non-empty strings."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["rocm_version"] = ""
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("rocm_version must be a non-empty string", str(cm.exception))

        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["python_version"] = None
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("python_version must be a non-empty string", str(cm.exception))

        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["pip_version"] = ""
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("pip_version must be a non-empty string", str(cm.exception))

    def test_stage0_inventory_requires_absolute_wheel_paths(self) -> None:
        """stage0_inventory_verified requires official_wheels paths to be absolute."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["official_wheels"]["torch"]["path"] = "torch-2.9.1.whl"
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("must be an absolute path", str(cm.exception))

    def test_stage0_inventory_requires_64_char_hex_sha256(self) -> None:
        """stage0_inventory_verified requires 64-character lowercase hex sha256."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["official_wheels"]["torch"]["sha256"] = "abc123"
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("sha256 must be 64-character lowercase hex", str(cm.exception))

        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["official_wheels"]["torch"]["sha256"] = "X" * 64
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("sha256 must be 64-character lowercase hex", str(cm.exception))

    def test_stage0_inventory_requires_all_five_wheels(self) -> None:
        """stage0_inventory_verified requires apex+torch+torchvision+torchaudio+triton."""
        broken = copy.deepcopy(self.contract)
        del broken["stage0_inventory"]["official_wheels"]["triton"]
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("must contain exactly", str(cm.exception))

    def test_stage0_inventory_requires_stage1_packages_install_true(self) -> None:
        """stage0_inventory_verified requires torch/torchvision/torchaudio/triton part_of_stage1_install=true."""
        for pkg in ["torch", "torchvision", "torchaudio", "triton"]:
            broken = copy.deepcopy(self.contract)
            broken["stage0_inventory"]["official_wheels"][pkg]["part_of_stage1_install"] = False
            with self.assertRaises(ContractError) as cm:
                validate_amd_cloud_runtime_contract(broken)
            self.assertIn(f"{pkg}.part_of_stage1_install must be true", str(cm.exception))

    def test_stage0_inventory_requires_apex_install_false(self) -> None:
        """stage0_inventory_verified requires apex part_of_stage1_install=false."""
        broken = copy.deepcopy(self.contract)
        broken["stage0_inventory"]["official_wheels"]["apex"]["part_of_stage1_install"] = True
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("apex.part_of_stage1_install must be false", str(cm.exception))

    def test_stage0_inventory_requires_template_divergence_fields(self) -> None:
        """stage0_inventory_verified requires actual_template, planned_template, and template_divergence_note."""
        # Missing actual_template
        broken = copy.deepcopy(self.contract)
        del broken["platform"]["actual_template"]
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("requires actual_template", str(cm.exception))

        # Missing planned_template
        broken = copy.deepcopy(self.contract)
        del broken["platform"]["planned_template"]
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("planned_template", str(cm.exception))

        # Missing template_divergence_note
        broken = copy.deepcopy(self.contract)
        del broken["platform"]["template_divergence_note"]
        with self.assertRaises(ContractError) as cm:
            validate_amd_cloud_runtime_contract(broken)
        self.assertIn("requires template_divergence_note", str(cm.exception))

    def test_awaiting_platform_recovery_remains_compatible(self) -> None:
        """Old awaiting_platform_recovery state remains compatible."""
        old_contract = copy.deepcopy(self.contract)
        old_contract["status"] = "awaiting_platform_recovery"
        old_contract["platform"]["instance_creation_attempted"] = False
        # Remove stage0_inventory and template divergence fields for old state
        if "stage0_inventory" in old_contract:
            del old_contract["stage0_inventory"]
        if "actual_template" in old_contract["platform"]:
            del old_contract["platform"]["actual_template"]
        if "template_divergence_note" in old_contract["platform"]:
            del old_contract["platform"]["template_divergence_note"]
        # Ensure claim_boundary has the required text for awaiting_platform_recovery
        if "claim_boundary" in old_contract:
            old_contract["claim_boundary"] = "not AMD execution evidence; awaiting platform recovery"
        # Should not raise for old state without instance creation
        validate_amd_cloud_runtime_contract(old_contract)


class AmdCloudRuntimePersistenceV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(ROOT / "configs/amd-cloud-runtime-v3.json")

    def test_frozen_persistence_runtime_has_verified_single_session_canary(self) -> None:
        validate_amd_cloud_runtime_contract(self.contract)
        self.assertEqual(
            self.contract["platform"]["persistent_root"],
            "/workspace/persistent",
        )
        self.assertEqual(
            self.contract["platform"]["resolved_mount_root"],
            "/persistent",
        )
        self.assertTrue(self.contract["platform"]["instance_creation_attempted"])
        self.assertTrue(self.contract["platform"]["writability_canary_passed"])
        self.assertFalse(
            self.contract["platform"][
                "persistence_across_restart_or_recreation_verified"
            ]
        )
        self.assertIn(
            "not AMD execution evidence", self.contract["claim_boundary"]
        )

    def test_legacy_venv_path_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["platform"]["virtual_environment"] = "/workspace/rdna"
        with self.assertRaises(ContractError):
            validate_amd_cloud_runtime_contract(broken)

    def test_verified_contract_requires_instance_creation(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["platform"]["instance_creation_attempted"] = False
        with self.assertRaises(ContractError):
            validate_amd_cloud_runtime_contract(broken)

    def test_direct_local_ssd_claim_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["platform"]["direct_local_ssd_claim_supported"] = True
        with self.assertRaises(ContractError):
            validate_amd_cloud_runtime_contract(broken)


if __name__ == "__main__":
    unittest.main()
