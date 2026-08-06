from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.amd_persistence import (
    PERSISTENT_ROOT,
    build_persistence_audit,
    is_strict_descendant,
    load_json,
    validate_durable_output_path,
    validate_persistence_contract,
    validate_runtime_against_persistence,
    verify_legacy_contract_hashes,
)
from mantis_rocm_bridge.contracts import ContractError


ROOT = Path(__file__).resolve().parents[1]
PERSISTENCE = ROOT / "configs/amd-persistence-layout-v2.json"
RUNTIME_V3 = ROOT / "configs/amd-cloud-runtime-v3.json"


class AmdPersistenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(PERSISTENCE)
        self.runtime = load_json(RUNTIME_V3)

    def test_checked_in_contract_and_runtime_are_consistent(self) -> None:
        validate_persistence_contract(self.contract)
        validate_runtime_against_persistence(self.runtime, self.contract)

    def test_legacy_contract_hashes_are_unchanged(self) -> None:
        results = verify_legacy_contract_hashes(
            self.contract, repository_root=ROOT
        )
        self.assertEqual(len(results), 5)
        self.assertTrue(all(item["verified"] for item in results))

    def test_old_workspace_children_fail_closed(self) -> None:
        for path in (
            "/workspace/rdna",
            "/workspace/dataset",
            "/workspace/checkpoints/060000",
            "/workspace/persistent-escape/output",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    validate_durable_output_path(path)

    def test_persistence_descendants_pass(self) -> None:
        path = "/workspace/persistent/mantis-track3/training/run-v1"
        self.assertEqual(validate_durable_output_path(path), path)
        self.assertTrue(is_strict_descendant(path))
        self.assertFalse(is_strict_descendant(PERSISTENT_ROOT))

    def test_traversal_and_root_itself_fail_closed(self) -> None:
        for path in (
            "/workspace/persistent",
            "/workspace/persistent/../escape",
            "/workspace/persistent/",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    validate_durable_output_path(path)

    def test_runtime_path_drift_is_rejected(self) -> None:
        broken = copy.deepcopy(self.runtime)
        broken["platform"]["virtual_environment"] = "/workspace/rdna"
        with self.assertRaises(ContractError):
            validate_runtime_against_persistence(broken, self.contract)

    def test_layout_policy_cannot_disable_no_clobber(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["migration_policy"]["no_clobber"] = False
        with self.assertRaises(ContractError):
            validate_persistence_contract(broken)

    def test_contract_only_audit_does_not_claim_filesystem(self) -> None:
        audit = build_persistence_audit(
            self.contract,
            runtime=self.runtime,
            durable_paths={
                "training": (
                    "/workspace/persistent/mantis-track3/training/test-run"
                )
            },
        )
        self.assertEqual(audit["status"], "PASS")
        self.assertFalse(audit["filesystem"]["checked"])
        self.assertIsNone(audit["filesystem"]["persistent_root_exists"])

    def test_filesystem_gate_fails_off_cloud(self) -> None:
        if Path(PERSISTENT_ROOT).exists():
            self.skipTest("test host unexpectedly has the cloud persistence root")
        with self.assertRaises(ContractError):
            build_persistence_audit(
                self.contract,
                runtime=self.runtime,
                check_filesystem=True,
            )

    def test_output_receipt_can_be_exclusively_created_by_caller(self) -> None:
        audit = build_persistence_audit(self.contract, runtime=self.runtime)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            output.write_text(str(audit), encoding="utf-8")
            with self.assertRaises(FileExistsError):
                output.open("x", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
