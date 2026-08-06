#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_causal_twin_training import (  # noqa: E402
    CONFOUNDERS,
    CORPUS_LICENSE,
    CORPUS_LICENSE_LOCATOR,
    MARKETS,
    PRODUCT_KINDS,
    corpus_digest,
    evaluate_estimators,
    generate_causal_time_series,
    hierarchical_cold_start_transfer,
)
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    text = json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)
    return hashlib.sha256(text.encode()).hexdigest()


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> str:
    text = "\n".join(
        json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) for row in rows
    ) + "\n"
    atomic_write_text(path, text)
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    rows = generate_causal_time_series()
    train = tuple(row for row in rows if row.split == "train")
    validation = tuple(row for row in rows if row.split == "validation")
    test = tuple(row for row in rows if row.split == "test")
    output = ROOT / "data/v10_causal_twin_timeseries"
    evidence = ROOT / "evidence/v10"
    output.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)

    row_payloads = [asdict(row) for row in rows]
    rows_sha = _write_jsonl(output / "rows.jsonl", row_payloads)
    benchmark = asdict(evaluate_estimators(train, test))
    benchmark_payload = {
        "schema": "ProofLaunchCausalTwinEstimatorBenchmarkV1",
        "evaluation_protocol": {
            "training_days": [0, 79],
            "validation_days": [80, 99],
            "sealed_test_days": [100, 119],
            "split_strategy": "strict_temporal_holdout_no_random_shuffle",
            "known_truth_available": True,
            "negative_control_retained": "estimated_propensity_ipw",
        },
        "result": benchmark,
        "acceptance": {
            "aipw_lower_error_than_naive": (
                benchmark["doubly_robust_absolute_error"] < benchmark["naive_absolute_error"]
            ),
            "propensity_overlap_observed": (
                0.02 < benchmark["propensity_minimum"]
                and benchmark["propensity_maximum"] < 0.98
            ),
            "business_effect_claim_allowed": False,
        },
        "truth_boundary": (
            "All outcomes and treatment effects are deterministic project-owned simulations. "
            "The benchmark validates estimator behavior against known synthetic truth only; it "
            "does not establish campaign lift, conversion, revenue, or deployment performance."
        ),
    }
    benchmark_payload["content_sha256"] = stable_sha256(benchmark_payload)
    benchmark_sha = _write_json(evidence / "causal-twin-estimator-benchmark.json", benchmark_payload)

    target_profile = {name: 0.0 for name in CONFOUNDERS}
    transfer = asdict(
        hierarchical_cold_start_transfer(
            train,
            target_product_kind="ai_agent",
            target_profile=target_profile,
        )
    )
    transfer_payload = {
        "schema": "ProofLaunchCausalTwinColdStartTransferV1",
        "method": "global_product_kind_similar_market_hierarchical_blend",
        "target": {
            "product_kind": "ai_agent",
            "target_market_observations": 0,
            "profile": target_profile,
        },
        "result": transfer,
        "leakage_controls": {
            "fit_split": "train_only",
            "validation_used": False,
            "test_used": False,
            "target_outcomes_used": False,
        },
        "truth_boundary": (
            "This is a deterministic simulated prior-transfer fixture. It proves cold-start "
            "mechanics and source-market traceability, not real-market generalization."
        ),
    }
    transfer_payload["content_sha256"] = stable_sha256(transfer_payload)
    transfer_sha = _write_json(output / "cold-start-transfer.json", transfer_payload)

    manifest: dict[str, Any] = {
        "schema": "ProofLaunchCausalTwinTimeSeriesCorpusV1",
        "record_count": len(rows),
        "product_kinds": list(PRODUCT_KINDS),
        "markets": list(MARKETS),
        "confounders": list(CONFOUNDERS),
        "split_counts": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "temporal_boundaries": {
            "train": [0, 79],
            "validation": [80, 99],
            "test": [100, 119],
        },
        "rights": {
            "owner": "ProofLaunch contributors",
            "license_id": CORPUS_LICENSE,
            "license_locator": CORPUS_LICENSE_LOCATOR,
            "external_training_material_count": 0,
        },
        "artifacts": {
            "rows": {"path": "data/v10_causal_twin_timeseries/rows.jsonl", "sha256": rows_sha},
            "benchmark": {
                "path": "evidence/v10/causal-twin-estimator-benchmark.json",
                "sha256": benchmark_sha,
            },
            "cold_start_transfer": {
                "path": "data/v10_causal_twin_timeseries/cold-start-transfer.json",
                "sha256": transfer_sha,
            },
        },
        "corpus_content_sha256": corpus_digest(rows),
        "DAIE": {
            "deconstruct": {
                "reused_mechanism": "CausalMarketTwin evidence-class isolation and IPW contract",
                "new_dependency_count": 0,
                "negative_control": "standalone estimated-propensity IPW is retained even when it underperforms",
            },
            "analyze": {
                "hypothesis": "AIPW should reduce confounding error relative to naive correlation under the registered DGP",
                "assumptions": [
                    "consistency",
                    "conditional exchangeability under the five registered confounders",
                    "positivity inside the measured propensity interval",
                    "no temporal leakage",
                ],
                "falsifier": "AIPW absolute error is not lower than naive absolute error on the sealed test period",
            },
            "innovate": {
                "two_product_families": True,
                "rights_bound_rows": True,
                "hierarchical_zero_observation_transfer": True,
                "causal_evidence_isolated_from_observed_business_evidence": True,
            },
            "evaluate": {
                "strict_temporal_holdout": True,
                "known_simulated_truth": True,
                "artifact_hashes_present": True,
                "real_business_effect_claim_allowed": False,
            },
        },
        "truth_boundary": (
            "Every row is evidence_class=simulated. This corpus may test causal training and "
            "evaluation code, but cannot support a real campaign, conversion, revenue, product, "
            "Radeon, or model-quality claim."
        ),
    }
    manifest["content_sha256"] = stable_sha256(manifest)
    manifest_sha = _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "records": len(rows),
                "manifest_sha256": manifest_sha,
                "benchmark_sha256": benchmark_sha,
                "aipw_error": benchmark["doubly_robust_absolute_error"],
                "naive_error": benchmark["naive_absolute_error"],
                "real_business_effect_claim_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
