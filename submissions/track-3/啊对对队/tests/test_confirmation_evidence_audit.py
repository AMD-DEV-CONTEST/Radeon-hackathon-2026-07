from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.confirmation_evidence_audit import audit_confirmation_evidence
from parcel_sorter.grasp_scoring import canonical_payload_sha256, sha256_file
from scripts.audit_controller_probe_confirmation_evidence import run


def _fixtures():
    protocol = {
        "platform": {
            "backend": "rocm",
            "device": "cuda:0",
            "single_gpu": True,
            "gpu_count": 1,
        },
        "population": {"expected_groups": 2, "episodes_per_profile": 1},
        "splits": [
            {"name": "confirmation", "profile_id": "a", "episode_ids": [10]},
            {"name": "confirmation", "profile_id": "b", "episode_ids": [20]},
        ],
    }
    manifest = {
        "split": "confirmation",
        "backend": "rocm",
        "dry_run": False,
        "planning_activation_policy": "all-boxes",
        "planned_episode_count": 2,
        "complete_episode_count": 2,
        "runs": [
            {
                "profile": "a",
                "episode": 10,
                "output": "/run/a.json",
                "status": "complete",
                "source_status": "complete",
                "sha256": "a",
            },
            {
                "profile": "b",
                "episode": 20,
                "output": "/run/b.json",
                "status": "reused",
                "source_status": "complete",
                "sha256": "b",
            },
        ],
    }
    dataset = {
        "split": "confirmation",
        "policy": "veto-static",
        "group_count": 2,
        "profiles": ["a", "b"],
        "source_artifacts": [
            {"path": "/run/a.json", "sha256": "a"},
            {"path": "/run/b.json", "sha256": "b"},
        ],
    }
    result = {
        "source_artifact_count": 2,
        "policy": "veto-static",
        "summary": {
            "group_count": 2,
            "by_profile": {"a": {"group_count": 1}, "b": {"group_count": 1}},
        },
        "decision": {
            "status": "confirmation_failed",
            "passes": False,
            "online_parallel_probe_authorized": False,
            "runtime_activation_authorized": False,
            "v2_holdout_opened": False,
        },
    }
    return protocol, manifest, dataset, result


class ConfirmationEvidenceAuditTests(unittest.TestCase):
    def test_complete_exact_population_and_failed_terminal_decision_are_valid(self) -> None:
        audit = audit_confirmation_evidence(*_fixtures())

        self.assertEqual(audit["status"], "evidence_valid")
        self.assertEqual(audit["errors"], [])
        self.assertFalse(audit["contract"]["policy_reselected"])

    def test_duplicate_or_substituted_manifest_key_is_rejected(self) -> None:
        protocol, manifest, dataset, result = _fixtures()
        manifest["runs"][1]["profile"] = "a"
        manifest["runs"][1]["episode"] = 10

        audit = audit_confirmation_evidence(protocol, manifest, dataset, result)

        self.assertEqual(audit["status"], "evidence_invalid")
        self.assertIn("manifest_duplicate_key", audit["errors"])
        self.assertIn("manifest_population_mismatch", audit["errors"])

    def test_profile_count_and_runtime_authorization_drift_are_rejected(self) -> None:
        protocol, manifest, dataset, result = _fixtures()
        result = deepcopy(result)
        result["summary"]["by_profile"]["a"]["group_count"] = 2
        result["decision"]["runtime_activation_authorized"] = True

        audit = audit_confirmation_evidence(protocol, manifest, dataset, result)

        self.assertIn("result_profile_count:a", audit["errors"])
        self.assertIn("runtime_activation_boundary_violated", audit["errors"])

    def test_passing_decision_requires_online_pilot_authorization_only(self) -> None:
        protocol, manifest, dataset, result = _fixtures()
        result["decision"]["status"] = "confirmation_passed"
        result["decision"]["passes"] = True

        invalid = audit_confirmation_evidence(protocol, manifest, dataset, result)
        result["decision"]["online_parallel_probe_authorized"] = True
        valid = audit_confirmation_evidence(protocol, manifest, dataset, result)

        self.assertIn("online_authorization_inconsistent", invalid["errors"])
        self.assertEqual(valid["status"], "evidence_valid")

    def test_dataset_source_substitution_is_rejected(self) -> None:
        protocol, manifest, dataset, result = _fixtures()
        dataset["source_artifacts"][1]["sha256"] = "substituted"

        audit = audit_confirmation_evidence(protocol, manifest, dataset, result)

        self.assertIn("dataset_source_manifest_mismatch", audit["errors"])

    def test_cpu_or_dry_run_evidence_is_rejected(self) -> None:
        protocol, manifest, dataset, result = _fixtures()
        protocol["platform"]["backend"] = "cpu"
        manifest["dry_run"] = True

        audit = audit_confirmation_evidence(protocol, manifest, dataset, result)

        self.assertIn("protocol_backend_mismatch", audit["errors"])
        self.assertIn("manifest_not_physical_run", audit["errors"])


class ConfirmationEvidenceAuditRunnerTests(unittest.TestCase):
    def test_file_and_payload_hash_chain_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol_path = root / "protocol.toml"
            manifest_path = root / "manifest.json"
            dataset_path = root / "dataset.json"
            result_path = root / "result.json"
            output_path = root / "audit.json"
            protocol_path.write_text(
                """
[platform]
backend = "rocm"
device = "cuda:0"
single_gpu = true
gpu_count = 1

[population]
expected_groups = 2
episodes_per_profile = 1

[[splits]]
name = "confirmation"
profile_id = "a"
episode_ids = [10]

[[splits]]
name = "confirmation"
profile_id = "b"
episode_ids = [20]
""".strip()
                + "\n",
                encoding="utf-8",
            )
            protocol, manifest, dataset, result = _fixtures()
            manifest["protocol"] = str(protocol_path.resolve())
            manifest["protocol_sha256"] = sha256_file(protocol_path)
            dataset["dataset_sha256"] = canonical_payload_sha256(dataset)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
            result.update(
                {
                    "protocol": str(protocol_path.resolve()),
                    "protocol_sha256": sha256_file(protocol_path),
                    "manifest": str(manifest_path.resolve()),
                    "manifest_sha256": sha256_file(manifest_path),
                    "dataset": str(dataset_path.resolve()),
                    "dataset_sha256": sha256_file(dataset_path),
                }
            )
            result_path.write_text(json.dumps(result), encoding="utf-8")
            args = argparse.Namespace(
                protocol=protocol_path,
                manifest=manifest_path,
                dataset=dataset_path,
                result=result_path,
                output=output_path,
            )

            valid = run(args)
            dataset["dataset_sha256"] = "0" * 64
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
            result["dataset_sha256"] = sha256_file(dataset_path)
            result_path.write_text(json.dumps(result), encoding="utf-8")
            invalid = run(args)

            self.assertEqual(valid["status"], "evidence_valid")
            self.assertIn("dataset_payload_hash_mismatch", invalid["errors"])


if __name__ == "__main__":
    unittest.main()
