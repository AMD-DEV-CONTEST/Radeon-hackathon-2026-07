#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
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
    stable_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_radeon_reproduction_contract.json"
EVIDENCE = ROOT / "evidence/v10/radeon-reproduction-mechanical-fixture.json"


def main() -> int:
    policy = MemoryOptimizationPolicy(
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
    cache = LayeredContentCache(4096)
    cache_receipts = []
    for index, layer in enumerate(CacheLayer, start=1):
        key = CacheKey(
            layer,
            "fixture-model-r1",
            f"{index}" * 64,
            f"{index + 4}" * 64,
            policy.content_sha256,
            "rocm-fixture-runtime",
        )
        value = CacheValue.from_bytes(f"{layer.value}-fixture".encode("utf-8"))
        cache.put(key, value)
        cache_receipts.append(
            {
                "layer": layer.value,
                "key_sha256": key.digest,
                "value_sha256": value.payload_sha256,
                "exact_hit": cache.get(key) == value.payload,
                "model_drift_hit": cache.get(
                    CacheKey(
                        layer,
                        "fixture-model-r2",
                        key.adapter_sha256,
                        key.input_sha256,
                        key.policy_sha256,
                        key.runtime_fingerprint,
                    )
                )
                is not None,
            }
        )
    recovery = [asdict(build_recovery_plan(kind, 1)) for kind in FailureKind]
    for item in recovery:
        item["kind"] = item["kind"].value

    artifact_paths = (
        ROOT / "pyproject.toml",
        ROOT / "notebooks/prooflaunch_cortex_x_v10_radeon.ipynb",
        ROOT / "scripts/run_v10_local_suite.py",
    )
    artifacts = tuple(
        OfflineArtifact(
            str(path.relative_to(ROOT)),
            sha256_file(path),
            path.stat().st_size,
        )
        for path in artifact_paths
    )
    offline = OfflineBundleManifest(
        artifacts,
        False,
        True,
        sha256_file(ROOT / "pyproject.toml"),
    )
    clean = CleanInstanceContract(
        "amd-oneclick-base:rocm7.2.1-py3.12-v20260416",
        "sha256:" + "a" * 64,
        stable_sha256({"source_archive": "runtime-supplied-and-checksummed"}),
        offline.content_sha256,
        (
            ("verify_archive_sha256",),
            ("extract_archive_atomically",),
            ("verify_offline_artifacts",),
            ("run_radeon_preflight",),
            ("run_local_suite",),
        ),
    )
    runtime = RadeonRuntimeObservation(
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        {
            "flux": None,
            "wan": None,
            "ltx": None,
            "seedvr2": None,
            "real_esrgan": None,
            "qwen3_vl": None,
            "gemma4_critic": None,
            "adapter_hotswap": None,
        },
        False,
    )
    performance = RadeonPerformanceObservation(
        (), None, None, None, None, None, None, None, None, None, False
    )
    contract = {
        "schema": "ProofLaunchRadeonReproductionContractV1",
        "memory_optimization_policy": {
            **asdict(policy),
            "content_sha256": policy.content_sha256,
        },
        "cache_layers": [item.value for item in CacheLayer],
        "cache_key_fields": [
            "layer",
            "model_revision",
            "adapter_sha256",
            "input_sha256",
            "policy_sha256",
            "runtime_fingerprint",
        ],
        "recovery_plans": recovery,
        "offline_manifest": {
            "artifacts": [asdict(item) for item in offline.artifacts],
            "network_allowed": offline.network_allowed,
            "local_files_only": offline.local_files_only,
            "dependency_lock_sha256": offline.dependency_lock_sha256,
            "content_sha256": offline.content_sha256,
        },
        "clean_instance_contract": {
            **asdict(clean),
            "content_sha256": clean.content_sha256,
            "container_digest_status": "fixture_only_not_observed",
        },
        "runtime_required_fields": list(runtime.__dict__),
        "performance_required_fields": list(performance.__dict__),
        "clean_instance_script": "scripts/run_v10_clean_radeon_instance.sh",
        "truth_boundary": (
            "The control mechanics are executable locally. Radeon runtime, model, "
            "performance, clean-instance and archive-reproduction observations remain mandatory."
        ),
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CONFIG, json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    fixture = {
        "schema": "ProofLaunchRadeonReproductionMechanicalFixtureV1",
        "status": "mechanical_controls_passed",
        "contract_sha256": sha256_file(CONFIG),
        "cache_receipts": cache_receipts,
        "cache_resident_bytes": cache.resident_bytes,
        "recovery_plans": recovery,
        "offline_manifest_sha256": offline.content_sha256,
        "clean_instance_contract_sha256": clean.content_sha256,
        "runtime_observation_complete": runtime.complete,
        "performance_observation_complete": performance.complete,
        "clean_instance_executed": False,
        "archive_reproduction_executed": False,
        "radeon_report_frozen": False,
        "truth_boundary": (
            "Project-owned fixtures prove deterministic control mechanics only; no GPU, "
            "ROCm, model quality, latency, utilization, clean-instance run or final Radeon Evidence is inferred."
        ),
    }
    atomic_write_text(EVIDENCE, json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "contract_sha256": sha256_file(CONFIG),
                "fixture_sha256": sha256_file(EVIDENCE),
                "cache_layers": len(cache_receipts),
                "recovery_plans": len(recovery),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
