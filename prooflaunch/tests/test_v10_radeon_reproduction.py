from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_radeon_reproduction import (
    CacheKey,
    CacheLayer,
    CacheValue,
    CleanInstanceContract,
    FailureKind,
    LayeredContentCache,
    MemoryOptimizationPolicy,
    OfflineArtifact,
    OfflineBundleManifest,
    RadeonPerformanceObservation,
    RadeonRuntimeObservation,
    build_recovery_plan,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_radeon_reproduction_contract.json"
FIXTURE = ROOT / "evidence/v10/radeon-reproduction-mechanical-fixture.json"
SCRIPT = ROOT / "scripts/run_v10_clean_radeon_instance.sh"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def policy() -> MemoryOptimizationPolicy:
    return MemoryOptimizationPolicy(
        1,
        (
            "drop_model_references",
            "gc_collect",
            "empty_device_cache",
            "synchronize_device",
            "measure_free_memory",
        ),
        True,
        "cpu",
        True,
        (1024, 1024),
        128,
        True,
        "auto",
    )


def key(layer: CacheLayer, revision: str = "r1", input_sha: str = SHA_B) -> CacheKey:
    return CacheKey(layer, revision, SHA_A, input_sha, SHA_C, "rocm7.2.1-bf16")


class MemoryAndCacheTests(unittest.TestCase):
    def test_single_model_release_cpu_offload_vae_tiling_and_attention_slicing_are_mandatory(self) -> None:
        value = policy()
        self.assertEqual(value.maximum_resident_heavy_models, 1)
        self.assertEqual(value.release_sequence[-1], "measure_free_memory")
        self.assertTrue(value.cpu_offload_enabled)
        self.assertTrue(value.vae_tiling_enabled)
        self.assertTrue(value.attention_slicing_enabled)
        with self.assertRaises(V10ContractError):
            MemoryOptimizationPolicy(
                2,
                value.release_sequence,
                True,
                "cpu",
                True,
                (1024, 1024),
                128,
                True,
                "auto",
            )
        with self.assertRaises(V10ContractError):
            MemoryOptimizationPolicy(
                1,
                value.release_sequence[:-1],
                True,
                "cpu",
                True,
                (1024, 1024),
                128,
                True,
                "auto",
            )

    def test_prompt_embedding_kv_and_workflow_caches_are_content_addressed_and_revision_safe(self) -> None:
        cache = LayeredContentCache(1024)
        for layer in CacheLayer:
            value = CacheValue.from_bytes(layer.value.encode("utf-8"))
            cache.put(key(layer), value)
            self.assertEqual(cache.get(key(layer)), value.payload)
            self.assertIsNone(cache.get(key(layer, revision="r2")))
            self.assertIsNone(cache.get(key(layer, input_sha="d" * 64)))
        self.assertEqual({item.value for item in CacheLayer}, {"prompt", "embedding", "kv", "workflow"})

    def test_cache_is_byte_bounded_lru_and_rejects_oversized_values(self) -> None:
        cache = LayeredContentCache(5)
        first = key(CacheLayer.PROMPT)
        second = key(CacheLayer.EMBEDDING)
        cache.put(first, CacheValue.from_bytes(b"123"))
        cache.put(second, CacheValue.from_bytes(b"456"))
        self.assertIsNone(cache.get(first))
        self.assertEqual(cache.get(second), b"456")
        with self.assertRaises(V10ContractError):
            cache.put(key(CacheLayer.KV), CacheValue.from_bytes(b"123456"))


class RecoveryAndOfflineTests(unittest.TestCase):
    def test_oom_recovery_releases_memory_reduces_work_and_resumes_only_unfinished_unit(self) -> None:
        plan = build_recovery_plan(FailureKind.OOM, 1)
        self.assertIn("empty_device_cache", plan.actions)
        self.assertIn("halve_microbatch_or_tile", plan.actions)
        self.assertFalse(plan.replay_successful_work)
        with self.assertRaises(V10ContractError):
            build_recovery_plan(FailureKind.OOM, 3)

    def test_kernel_recovery_verifies_checkpoint_and_restores_complete_training_state(self) -> None:
        plan = build_recovery_plan(FailureKind.KERNEL, 2)
        self.assertTrue(plan.checkpoint_required)
        self.assertTrue(plan.exact_hash_required)
        self.assertIn("restore_rng_optimizer_scheduler", plan.actions)
        self.assertIn("resume_unfinished_unit", plan.actions)

    def test_download_recovery_is_range_resumable_hash_verified_and_atomic(self) -> None:
        plan = build_recovery_plan(FailureKind.DOWNLOAD, 1)
        self.assertFalse(plan.checkpoint_required)
        self.assertTrue(plan.exact_hash_required)
        self.assertTrue(plan.atomic_commit_required)
        self.assertEqual(plan.actions[-1], "atomic_rename_after_verification")

    def test_offline_manifest_rejects_network_traversal_duplicates_and_unbound_dependencies(self) -> None:
        artifact = OfflineArtifact("models/base.safetensors", SHA_A, 100)
        manifest = OfflineBundleManifest((artifact,), False, True, SHA_B)
        self.assertEqual(len(manifest.content_sha256), 64)
        with self.assertRaises(V10ContractError):
            OfflineBundleManifest((artifact,), True, True, SHA_B)
        with self.assertRaises(V10ContractError):
            OfflineArtifact("../secret", SHA_A, 1)
        with self.assertRaises(V10ContractError):
            OfflineBundleManifest((artifact, artifact), False, True, SHA_B)

    def test_clean_instance_contract_and_script_pin_inputs_before_offline_execution(self) -> None:
        contract = CleanInstanceContract(
            "amd-image:rocm7.2.1",
            "sha256:" + SHA_A,
            SHA_B,
            SHA_C,
            (("verify_archive_sha256",), ("run_local_suite",)),
        )
        self.assertEqual(len(contract.content_sha256), 64)
        with self.assertRaises(V10ContractError):
            CleanInstanceContract("amd-image:latest", "mutable", SHA_B, SHA_C, (("run",),))
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("archive SHA-256 mismatch", script)
        self.assertIn("HF_HUB_OFFLINE=1", script)
        self.assertIn("PROOFLAUNCH_NETWORK_ALLOWED=0", script)
        self.assertLess(script.index("archive SHA-256 mismatch"), script.index("tar -xzf"))
        self.assertNotIn("curl ", script)
        self.assertNotIn("wget ", script)
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            archive = temp / "bundle.tar.gz"
            checksum = temp / "bundle.sha256"
            archive.write_bytes(b"not-an-archive")
            checksum.write_text(f"{SHA_B}  bundle.tar.gz\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["PROOFLAUNCH_CONTAINER_DIGEST"] = "sha256:" + SHA_A
            result = subprocess.run(
                (str(SCRIPT), str(archive), str(checksum), str(temp / "target")),
                capture_output=True,
                check=False,
                env=environment,
            )
        self.assertEqual(result.returncode, 65)
        self.assertIn(b"archive SHA-256 mismatch", result.stderr)


class ObservationBoundaryTests(unittest.TestCase):
    def test_runtime_and_performance_require_real_complete_observations(self) -> None:
        runtime = RadeonRuntimeObservation(None, None, None, None, None, None, None, None, None, None, None, {"flux": None}, False)
        performance = RadeonPerformanceObservation((), None, None, None, None, None, None, None, None, None, False)
        self.assertFalse(runtime.complete)
        self.assertFalse(performance.complete)
        complete_runtime = RadeonRuntimeObservation("AMD Radeon", 1000, 500, "7.2.1", "7.2.1", "2.8", True, True, True, True, True, {"flux": True}, True)
        self.assertTrue(complete_runtime.complete)
        complete_performance = RadeonPerformanceObservation((10.0, 20.0), 900, 90.0, 50.0, 10, 20, 30.0, SHA_A, 0.9, 0.9, True)
        self.assertTrue(complete_performance.complete)

    def test_mechanical_fixture_does_not_claim_radeon_or_reproduction_execution(self) -> None:
        contract = json.loads(CONFIG.read_text(encoding="utf-8"))
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(contract["schema"], "ProofLaunchRadeonReproductionContractV1")
        self.assertEqual(fixture["status"], "mechanical_controls_passed")
        self.assertFalse(fixture["runtime_observation_complete"])
        self.assertFalse(fixture["performance_observation_complete"])
        self.assertFalse(fixture["clean_instance_executed"])
        self.assertFalse(fixture["archive_reproduction_executed"])
        self.assertFalse(fixture["radeon_report_frozen"])


if __name__ == "__main__":
    unittest.main()
