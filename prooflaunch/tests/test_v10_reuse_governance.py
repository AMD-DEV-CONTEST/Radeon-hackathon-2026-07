from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError, stable_digest
from prooflaunch_remix.v10_reuse_governance import (
    AdapterBinding,
    AdapterRegistry,
    BuildObservation,
    CandidateAssessment,
    HealthObservation,
    IntegrationMode,
    MigrationPlan,
    PatchRecord,
    ReuseDecision,
    ReuseManifest,
    ReuseReview,
    RocmEvidenceLevel,
    UpstreamCategory,
    UpstreamProject,
    duplicate_function_fingerprints,
    find_unmediated_imports,
    select_build_strategy,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_reuse_manifest_v1.json"
EVIDENCE = ROOT / "evidence/v10/reuse-manifest-v1-mechanical-fixture.json"
PATCH_MANIFEST = ROOT / "upstream_patches/manifest.json"


PINNED = {
    "flux2": "50fe5162777813d869182b139e83b10743caef15",
    "wan2.2": "42bf4cfaa384bc21833865abc2f9e6c0e67233dc",
    "ltx-video": "4b2d053057623ddd4d0a1d3e9cd28890e9ef487f",
    "seedvr2": "dc248c05946b64114012ac9a0da8faf982159627",
    "real-esrgan": "a4abfb2979a7bbff3f69f58f58ae324608821e27",
    "swinir": "6545850fbf8df298df73d81f3e8cba638787c8bd",
    "grounding-dino": "856dde20aee659246248e20734ef9ba5214f5e44",
    "sam2": "2b90b9f5ceec907a1c18123530e92e794ad901a4",
    "siglip2": "0127fb6b337ee2a27bf4e54dea79cff176527356",
    "clap": "1fd4c37df5ffbfcfbad5415c170bc66cf94c9994",
    "ms-swift": "a5229fda7ebcc141e7a0d6bd12030c043ce26486",
    "peft": "ea8ebf36da98d93fdfca020ad17ab746e6994c01",
    "trl": "aa592026c7267a52a60ce751a28e90bc303531fe",
    "langgraph": "b2926a0ff9589c28c7e01fe7cdbb337b86d5a4b4",
    "agent-r1": "b124aa46534cbf2fb8bc8af11405774984c42ac7",
    "matpo": "3c41d62d96963ac0512573f9d2e51596720ab379",
    "marti": "a2fe2c7b9ec46cf24769c90575c51d847f41d04e",
    "opsd": "7448751f307a9cdbcc1246dd1565a1a605b443df",
    "tcod": "465eef4406ad0cff675b36bd46f37f28b1736ff9",
    "rcm": "ed3cb14dd936f92cdc9f9381af7369991509b41f",
    "causal-forcing": "1fc7bbc19a503c1bce80ecef08158b20e702f386",
}


def one_project(*, license_ok: bool = True, rocm: RocmEvidenceLevel = RocmEvidenceLevel.UNTESTED) -> UpstreamProject:
    return UpstreamProject(
        project_id="example",
        name="Example",
        repository_url="https://github.com/example/example",
        revision="a" * 40,
        observed_at="2026-07-31T00:00:00Z",
        pushed_at="2026-07-30T00:00:00Z",
        categories=tuple(UpstreamCategory),
        license_spdx="MIT" if license_ok else "UNRESOLVED",
        license_evidence_url="https://github.com/example/example/blob/main/LICENSE",
        license_approved_for_code_reuse=license_ok,
        integration_mode=IntegrationMode.ADAPTER,
        import_roots=("example",),
        hardware_assumption="test fixture",
        cuda_only_components=(),
        rocm_candidate_components=("tensor graph",),
        rocm_evidence_level=rocm,
        rocm_receipt_locator="evidence/rocm.json" if rocm is RocmEvidenceLevel.OBSERVED else None,
    )


def one_manifest(project: UpstreamProject | None = None) -> ReuseManifest:
    project = project or one_project()
    return ReuseManifest(
        (project,),
        (project.project_id,),
        "2026-07-31T00:00:00Z",
        "b" * 64,
    )


class ReuseGovernanceTests(unittest.TestCase):
    def test_catalog_covers_every_required_directory_and_exact_required_pins(self) -> None:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["projects"]), 28)
        self.assertEqual(set(payload["category_index"]), {item.value for item in UpstreamCategory})
        self.assertTrue(all(payload["category_index"][item.value] for item in UpstreamCategory))
        self.assertEqual(set(payload["required_pins"]), set(PINNED))
        actual = {item["project_id"]: item["revision"] for item in payload["projects"]}
        self.assertEqual({key: actual[key] for key in PINNED}, PINNED)

    def test_source_license_weight_rights_and_rocm_admission_fail_closed(self) -> None:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        by_id = {item["project_id"]: item for item in payload["projects"]}
        self.assertEqual(by_id["opsd"]["license_spdx"], "UNRESOLVED")
        self.assertFalse(by_id["opsd"]["license_approved_for_code_reuse"])
        self.assertFalse(by_id["autogen"]["license_approved_for_code_reuse"])
        self.assertTrue(all(item["rocm_evidence_level"] == "untested" for item in payload["projects"]))
        self.assertTrue(all(item["executable_admission"] is False for item in payload["projects"]))
        self.assertIn("weight/data rights", payload["truth_boundary"])
        with self.assertRaises(V10ContractError):
            one_project(rocm=RocmEvidenceLevel.OBSERVED).__class__(
                **{**one_project(rocm=RocmEvidenceLevel.OBSERVED).__dict__, "rocm_receipt_locator": None}
            )

    def test_every_upstream_records_hardware_cuda_and_rocm_candidate_fields(self) -> None:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        for item in payload["projects"]:
            self.assertTrue(item["hardware_assumption"])
            self.assertIsInstance(item["cuda_only_components"], list)
            self.assertIsInstance(item["rocm_candidate_components"], list)
            self.assertIn("rocm_evidence_level", item)

    def test_registered_adapter_is_revision_bound_and_direct_imports_are_detected(self) -> None:
        registry = AdapterRegistry(one_manifest())
        binding = AdapterBinding("example-adapter", "example", "a" * 40, "infer", "InputV1", "OutputV1")
        registry.register(binding)
        self.assertEqual(registry.resolve("example-adapter"), binding)
        with self.assertRaises(V10ContractError):
            registry.resolve("missing")
        with self.assertRaises(V10ContractError):
            AdapterRegistry(one_manifest()).register(
                AdapterBinding("wrong", "example", "c" * 40, "infer", "InputV1", "OutputV1")
            )
        self.assertEqual(
            find_unmediated_imports("import diffusers\nfrom peft import LoraConfig", ("diffusers", "peft")),
            ("diffusers", "peft"),
        )

    def test_patch_provenance_regression_and_replacement_migration_are_mandatory(self) -> None:
        patch = PatchRecord("patch-1", "example", "a" * 40, "b" * 64, "ROCm parity", "https://github.com/example/example/issues/1", ("test_rocm",))
        self.assertEqual(patch.project_id, "example")
        with self.assertRaises(V10ContractError):
            PatchRecord("patch-1", "example", "a" * 40, "b" * 64, "ROCm parity", "", ())
        migration = MigrationPlan("example", "a" * 40, "b" * 40, ("case-1",), "a" * 40)
        self.assertEqual(migration.rollback_revision, migration.from_revision)
        with self.assertRaises(V10ContractError):
            MigrationPlan("example", "a" * 40, "a" * 40, ("case-1",), "a" * 40)
        registry = json.loads(PATCH_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(registry["patch_count"], 0)
        self.assertEqual(registry["status"], "ready_empty")

    def test_health_scoring_and_maintenance_fallback_are_deterministic(self) -> None:
        healthy = HealthObservation("active", False, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", True, True, True)
        stale = HealthObservation("stale", False, "2020-01-01T00:00:00Z", "2026-07-31T00:00:00Z", True, True, False)
        archived = HealthObservation("archived", True, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", True, True, True)
        self.assertEqual(healthy.score(), 100)
        self.assertFalse(healthy.requires_fallback())
        self.assertTrue(stale.requires_fallback())
        self.assertTrue(archived.requires_fallback())

    def test_wheel_vs_source_build_requires_same_environment_and_real_observations(self) -> None:
        environment = "d" * 64
        rows = (
            BuildObservation("wheel", environment, True, 5.0, 300.0, "a" * 64),
            BuildObservation("source_build", environment, True, 50.0, 1200.0, "b" * 64),
        )
        self.assertEqual(select_build_strategy(rows), "wheel")
        with self.assertRaises(V10ContractError):
            select_build_strategy((rows[0], BuildObservation("source_build", "e" * 64, True, 2.0, 100.0, "c" * 64)))

    def test_duplicate_code_scan_fingerprints_equal_function_bodies(self) -> None:
        groups = duplicate_function_fingerprints(
            "def alpha(x):\n    return x + 1\n\ndef beta(x):\n    return x + 1\n\ndef gamma(x):\n    return x + 2\n"
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(next(iter(groups.values())), ("alpha", "beta"))

    def test_reuse_or_justify_blocks_convenient_original_builds(self) -> None:
        candidate = CandidateAssessment("example", "a" * 40, True, True, "suitable adapter exists")
        with self.assertRaises(V10ContractError):
            ReuseReview("src/new.py", "need", (candidate,), ReuseDecision.BUILD, None, "faster", "tests/test.py")
        review = ReuseReview("src/new.py", "need", (candidate,), ReuseDecision.REUSE, "example", "", "tests/test.py")
        self.assertEqual(review.selected_project_id, "example")

    def test_smoke_cli_is_secret_free_and_never_claims_runtime_or_rocm(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_v10_upstream_smoke.py"), "--project-id", "flux2"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["rows"][0]["runtime_smoke"], "not_run")
        self.assertEqual(payload["rows"][0]["rocm_smoke"], "not_run")
        self.assertFalse(payload["rows"][0]["network_checked"])

    def test_generated_receipt_is_hash_bound_and_does_not_fabricate_execution(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["manifest_sha256"], hashlib.sha256(CONFIG.read_bytes()).hexdigest())
        self.assertEqual(evidence["manifest_content_sha256"], config["content_sha256"])
        self.assertEqual(evidence["project_count"], 28)
        self.assertEqual(evidence["required_pin_count"], 21)
        self.assertEqual(evidence["rocm_observed_project_count"], 0)
        self.assertEqual(evidence["executable_admitted_project_count"], 0)
        self.assertEqual(evidence["live_upstream_smokes"], 0)
        expected = dict(evidence)
        digest = expected.pop("content_sha256")
        self.assertEqual(digest, stable_digest(expected))


if __name__ == "__main__":
    unittest.main()
