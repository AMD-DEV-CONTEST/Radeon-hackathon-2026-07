from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.create_amd_experiment_backup_bundle import create_bundle
from tools.verify_amd_experiment_backup_bundle import verify_bundle


ROOT = Path(__file__).resolve().parents[1]


class AmdExperimentBackupTests(unittest.TestCase):
    def test_frozen_contract_has_independent_destination(self) -> None:
        contract = json.loads(
            (ROOT / "configs/amd-experiment-backup-219-v1.json").read_text()
        )
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(contract["source"]["persistent_root"], "/workspace")
        self.assertEqual(
            contract["destination"]["ssh_target"], "mid8@192.168.0.219"
        )
        self.assertEqual(
            contract["destination"]["root"],
            "/data/mid8/backups/mantis-track3/amd/u-11422-e97d3fd5",
        )
        self.assertTrue(contract["bundle"]["exclusive_output"])
        self.assertTrue(
            contract["bundle"]["destination_independent_verification_required"]
        )
        self.assertNotIn(
            "/workspace/rdna", [entry["path"] for entry in contract["source_roots"]]
        )

    def test_persistence_v2_template_is_frozen_and_non_executable(self) -> None:
        path = ROOT / "configs/amd-experiment-backup-219-v2.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            contract["source"]["persistent_root"], "/workspace/persistence"
        )
        self.assertFalse(contract["execution"]["authorized"])
        self.assertTrue(
            all(
                entry["path"].startswith(
                    "/workspace/persistence/mantis-track3/"
                )
                for entry in contract["source_roots"]
            )
        )
        with self.assertRaisesRegex(ValueError, "not execution-authorized"):
            create_bundle(path, ROOT / ".never-created-by-test")

    def test_create_and_verify_small_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            (source / "alpha.txt").write_text("alpha\n", encoding="utf-8")
            nested = source / "nested"
            nested.mkdir()
            (nested / "beta.bin").write_bytes(b"\x00\x01\x02")
            contract = {
                "schema_version": 1,
                "backup_id": "fixture",
                "source": {"instance_id": "fixture-instance"},
                "bundle": {
                    "archive_format": "tar",
                    "one_archive_per_source_root": True,
                    "exclusive_output": True,
                    "atomic_destination_publish": True,
                    "source_file_sha256_required": True,
                    "archive_sha256_required": True,
                    "destination_independent_verification_required": True,
                    "forbid_symlinks": True,
                    "forbid_special_files": True,
                },
                "source_roots": [
                    {
                        "artifact_id": "fixture_root",
                        "path": str(source),
                        "required": True,
                        "class": "fixture",
                    }
                ],
                "claim_boundary": "fixture only",
            }
            contract_path = base / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            output = base / "bundle"
            result = create_bundle(contract_path, output)
            self.assertEqual(result["artifacts"][0]["file_count"], 2)
            verification = verify_bundle(output)
            self.assertTrue(verification["pass"], verification["errors"])
            self.assertEqual(
                verification["artifacts"][0]["verified_file_count"], 2
            )
            with self.assertRaises(FileExistsError):
                create_bundle(contract_path, output)

    def test_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            target = source / "target"
            target.write_text("data", encoding="utf-8")
            (source / "link").symlink_to(target)
            contract = {
                "schema_version": 1,
                "backup_id": "fixture",
                "source": {"instance_id": "fixture-instance"},
                "bundle": {
                    "archive_format": "tar",
                    "one_archive_per_source_root": True,
                    "exclusive_output": True,
                    "atomic_destination_publish": True,
                    "source_file_sha256_required": True,
                    "archive_sha256_required": True,
                    "destination_independent_verification_required": True,
                    "forbid_symlinks": True,
                    "forbid_special_files": True,
                },
                "source_roots": [
                    {
                        "artifact_id": "fixture_root",
                        "path": str(source),
                        "required": True,
                        "class": "fixture",
                    }
                ],
                "claim_boundary": "fixture only",
            }
            contract_path = base / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "symlink forbidden"):
                create_bundle(contract_path, base / "bundle")


if __name__ == "__main__":
    unittest.main()
