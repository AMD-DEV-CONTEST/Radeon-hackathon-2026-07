from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation import aggregate_stability
from evaluation.aggregate_stability import ValidatedBundle, build_stability_report


def _bundle(root: Path, index: int) -> ValidatedBundle:
    run_id = f"stable-{index}"
    binding_path = root / f"bundle-{index}" / "binding-manifest.txt"
    benchmark = {
        "run_id": run_id,
        "suite_version": "30-case-p0-v3",
        "suite_sha256": "1" * 64,
        "policy_corpus_sha256": "2" * 64,
        "model_name": "local-model",
        "model_base_url": "http://127.0.0.1:8000/v1",
        "case_ids": ["KQ-001"],
        "request_case_ids": ["KQ-001", "KQ-001", "KQ-001"],
        "configuration": {
            "repetitions": 3,
            "warmup": 2,
            "concurrency": [1],
            "min_success_rate": 1.0,
            "min_citation_hit_rate": 0.95,
        },
        "request_configuration": {
            "thinking_enabled": False,
            "schema_constrained": True,
        },
        "runs": [
            {
                "concurrency": 1,
                "summary": {
                    "latency_ms": {
                        "p50": 100.0 + index,
                        "p95": 200.0 + index,
                    },
                    "successful_throughput_requests_per_second": 10.0 + index,
                },
            }
        ],
    }
    return ValidatedBundle(
        binding_path=binding_path,
        bundle_sha256=f"{index:064x}",
        binding_manifest_sha256=f"{index + 10:064x}",
        binding={
            "run_id": run_id,
            "commit": "3" * 40,
            "project_tree": "4" * 40,
            "source_tree_sha256": "5" * 64,
            "model_sha256": "6" * 64,
            "llama_server_sha256": "7" * 64,
            "hardware_identity_sha256": "8" * 64,
        },
        benchmark=benchmark,
        retrieval_quality_gate={
            "recall_at_3_at_least_095": True,
            "all_results_traceable": True,
            "passed": True,
        },
        agent_quality_gates={
            "score_at_least_270": True,
            "permission_attacks_5_of_5": True,
            "all_30_cases_completed": True,
        },
        quality_score=290.0 + index,
        benchmark_quality_gate={
            "passed": True,
            "failures": [],
            "thresholds": {
                "min_success_rate": 1.0,
                "min_citation_hit_rate": 0.95,
            },
        },
        benchmark_success={
            1: {
                "requests": 24,
                "successful": 24,
                "success_rate": 1.0,
                "failed_model_calls": 0,
            }
        },
        runtime_gpu={
            "common_active_gpu_indices": [0],
            "common_active_gpu_unique_ids": ["0xabc"],
            "peak_vram_used_reported": 1000.0 + index * 100,
        },
        server_configuration={
            "ctx": "16384",
            "parallel": "4",
            "batch": "512",
            "ubatch": "128",
            "flash_attn": "on",
        },
    )


def test_build_stability_report_accepts_and_aggregates_ranges(tmp_path: Path) -> None:
    bundles = [_bundle(tmp_path, index) for index in range(1, 6)]

    report = build_stability_report(bundles)

    assert report["accepted"] is True
    assert report["run_count"] == 5
    assert [item["run_id"] for item in report["bundles"]] == [
        "stable-1",
        "stable-2",
        "stable-3",
        "stable-4",
        "stable-5",
    ]
    metrics = report["aggregate"]["metrics_by_concurrency"][0]
    assert metrics["latency_p50_ms"]["minimum"] == 101.0
    assert metrics["latency_p50_ms"]["maximum"] == 105.0
    assert metrics["latency_p95_ms"]["spread"] == 4.0
    assert metrics["successful_throughput_requests_per_second"]["spread"] == 4.0
    assert report["aggregate"]["peak_vram_used_reported"]["minimum"] == 1100.0
    assert report["aggregate"]["peak_vram_used_reported"]["maximum"] == 1500.0


def test_build_stability_report_rejects_duplicate_run_id(tmp_path: Path) -> None:
    bundles = [_bundle(tmp_path, index) for index in range(1, 6)]
    duplicate_binding = {**bundles[-1].binding, "run_id": bundles[0].run_id}
    bundles[-1] = replace(bundles[-1], binding=duplicate_binding)

    with pytest.raises(ValueError, match="distinct run_id"):
        build_stability_report(bundles)


def test_build_stability_report_rejects_request_configuration_drift(
    tmp_path: Path,
) -> None:
    bundles = [_bundle(tmp_path, index) for index in range(1, 6)]
    changed_benchmark = deepcopy(bundles[-1].benchmark)
    changed_benchmark["request_configuration"]["thinking_enabled"] = True
    bundles[-1] = replace(bundles[-1], benchmark=changed_benchmark)

    with pytest.raises(ValueError, match="request configuration"):
        build_stability_report(bundles)


@pytest.mark.parametrize("failure", ["agent_gate", "benchmark_call"])
def test_build_stability_report_rejects_any_failed_gate_or_call(
    tmp_path: Path,
    failure: str,
) -> None:
    bundles = [_bundle(tmp_path, index) for index in range(1, 6)]
    if failure == "agent_gate":
        bundles[-1] = replace(
            bundles[-1],
            agent_quality_gates={**bundles[-1].agent_quality_gates, "hard_failures_zero": False},
        )
        match = "failed quality gates"
    else:
        failed = deepcopy(bundles[-1].benchmark_success)
        failed[1]["failed_model_calls"] = 1
        bundles[-1] = replace(bundles[-1], benchmark_success=failed)
        match = "not fully successful"

    with pytest.raises(ValueError, match=match):
        build_stability_report(bundles)


def test_main_writes_machine_readable_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_bundle(tmp_path, index) for index in range(1, 6)]
    for bundle in bundles:
        bundle.bundle_dir.mkdir()
        bundle.binding_path.touch()
    by_path = {bundle.binding_path.resolve(): bundle for bundle in bundles}

    monkeypatch.setattr(
        aggregate_stability,
        "load_stability_bundle",
        lambda path, _label: by_path[path],
    )
    output = tmp_path / "stability.json"
    argv = [item for bundle in bundles for item in ("--binding", str(bundle.binding_path))]
    argv.extend(("--output", str(output)))

    assert aggregate_stability.main(argv) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["accepted"] is True
    assert len(payload["bundles"]) == 5


def test_main_requires_exactly_five_binding_arguments(tmp_path: Path) -> None:
    argv = [
        item
        for index in range(4)
        for item in ("--binding", str(tmp_path / f"bundle-{index}" / "binding-manifest.txt"))
    ]
    argv.extend(("--output", str(tmp_path / "stability.json")))

    with pytest.raises(ValueError, match="exactly five"):
        aggregate_stability.main(argv)
