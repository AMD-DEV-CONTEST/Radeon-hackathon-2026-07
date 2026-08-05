"""Verify public headline claims against frozen machine-readable evidence."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECK_COUNT = 0


def load_json(relative: str) -> dict[str, Any]:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def check_equal(label: str, actual: Any, expected: Any) -> None:
    global CHECK_COUNT
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, found {actual!r}")
    CHECK_COUNT += 1


def check_close(
    label: str,
    actual: float,
    expected: float,
    *,
    tolerance: float = 5e-7,
) -> None:
    global CHECK_COUNT
    if not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=tolerance):
        raise AssertionError(f"{label}: expected {expected}, found {actual}")
    CHECK_COUNT += 1


def sha256_file(relative: str) -> str:
    digest = hashlib.sha256()
    with (PROJECT_ROOT / relative).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dataset_and_split() -> None:
    dataset = load_json("data/chronosafe_nuscenes_trainval_timing_v3.json")
    split = load_json("configs/nuscenes_trainval_v3_split.json")
    check_equal("nuScenes scene count", dataset["scene_count"], 850)
    check_equal("aligned camera/LiDAR pairs", dataset["synchronized_real_pairs"], 34149)
    check_equal("degradation samples", dataset["samples"], 239043)
    check_equal("temporal tracks", dataset["tracks"], 5950)
    check_equal("feature dimension", len(dataset["features"]), 15)
    check_equal("raw data redistribution", dataset["raw_data_redistributed"], False)
    check_equal("split scene count", split["scene_count"], 850)
    check_equal(
        "split scene counts",
        split["actual_scene_counts"],
        {"train": 592, "calibration": 128, "test": 130},
    )


def verify_timestamp_robustness() -> None:
    standard = load_json(
        "results/timestamp_robustness_v3/timestamp_robustness.json"
    )
    robust = load_json(
        "results/timestamp_robustness_v4_robust_aggregate/timestamp_robustness.json"
    )
    standard_rows = {row["condition"]: row for row in standard["summary"]}
    robust_rows = {row["condition"]: row for row in robust["summary"]}
    expected = {
        "intact": (0.998271, 0.9934463333333333, 0.0010930308016397924),
        "missing_burst_50pct": (0.8478283333333333, 0.977715, 0.0007304128969288175),
        "timestamp_jitter_2frames": (0.853047, 0.9668683333333333, 0.0049451904243753165),
        "timestamp_channels_swapped": (0.720202, 0.9934463333333333, 0.0010930308016397924),
        "timestamps_spoofed_clean": (0.679637, 0.9508183333333333, 0.0006817663333821332),
    }
    check_equal("timestamp test scenes", robust["test_scene_count"], 95)
    check_equal("timestamp evaluation is causal", robust["timestamp_corruption_is_causal"], True)
    for condition, (standard_mean, robust_mean, robust_std) in expected.items():
        check_close(
            f"{condition} standard accuracy",
            standard_rows[condition]["scenario_accuracy_mean"],
            standard_mean,
        )
        check_close(
            f"{condition} robust accuracy",
            robust_rows[condition]["scenario_accuracy_mean"],
            robust_mean,
        )
        check_close(
            f"{condition} robust accuracy SD",
            robust_rows[condition]["scenario_accuracy_std"],
            robust_std,
        )
        sequences = {
            run["metrics"]["sequences"] for run in robust["conditions"][condition]
        }
        check_equal(f"{condition} sequence count", sequences, {21973})


def verify_fair_comparison() -> None:
    result = load_json("results/fair_trainval_timestamp_robust_aggregate/aggregate.json")
    rows = {row["metric"]: row for row in result["rows"]}
    check_equal("fair comparison training seeds", result["training_seed_count"], 3)
    check_equal("fair comparison test scenes", result["test_scene_count"], 95)
    check_equal("fair comparison test logs", result["test_log_count"], 8)
    check_equal("fair comparison bootstrap resamples", result["bootstrap_resamples"], 10000)
    expected = {
        "scenario_accuracy": (0.805762, 0.9934463333333333, 18.768433333333334),
        "camera_accuracy": (0.949438, 0.9978156666666665, 4.837766666666655),
        "lidar_accuracy": (0.857097, 0.9999846666666666, 14.288766666666664),
        "risk_mae": (0.060401, 0.012067666666666666, 80.0207502083299),
        "conformal_radius": (0.251078, 0.05843433333333333, 76.72662147486704),
    }
    for metric, (baseline, challenger, effect) in expected.items():
        check_close(f"{metric} baseline", rows[metric]["baseline"], baseline)
        check_close(f"{metric} robust mean", rows[metric]["challenger_mean"], challenger)
        check_close(f"{metric} effect", rows[metric]["effect"], effect)


def verify_closed_loop() -> None:
    result = load_json(
        "results/closed_loop_xvfb_timestamp_robust_seed2026/aggregate.json"
    )
    check_equal("closed-loop runs", result["runs"], 20)
    check_equal("closed-loop external seeds", len(result["seeds"]), 20)
    check_close("MRM success rate", result["mrm_success_rate"], 1.0)
    check_close("MRM reached rate", result["mrm_reached_rate"], 1.0)
    check_close("premature MRM rate", result["premature_mrm_rate"], 0.0)
    expected_metrics = {
        "scenario_accuracy": (0.970714, 0.028541),
        "risk_mae": (0.020637, 0.003302),
        "upper_risk_coverage": (0.998333, 0.002796),
        "mrm_trigger_delay_steps": (14.05, 2.114486),
        "stopping_steps": (8.55, 3.153528),
        "final_speed_km_h": (0.013786, 0.002101),
        "normal_fraction": (0.532619, 0.051549),
        "degraded_fraction": (0.248571, 0.051811),
        "minimal_risk_fraction": (0.21881, 0.010069),
    }
    for metric, (mean, std) in expected_metrics.items():
        check_close(f"closed-loop {metric} mean", result["metrics"][metric]["mean"], mean)
        check_close(f"closed-loop {metric} SD", result["metrics"][metric]["std"], std)


def verify_mrm_calibration() -> None:
    result = load_json(
        "results/mrm_threshold_calibration_xvfb_timestamp_robust_seed2026/calibration.json"
    )
    check_equal("MRM calibration seeds", result["calibration_seeds"], [113, 127])
    check_equal("MRM calibration valid", result["selection_valid"], True)
    check_close("selected MRM threshold", result["selected_threshold"], 0.62)
    selected = next(
        row for row in result["candidate_summaries"] if row["threshold"] == 0.62
    )
    check_close("calibration MRM success", selected["mrm_success_rate"], 1.0)
    check_close("calibration premature MRM", selected["premature_mrm_rate"], 0.0)
    check_close("calibration trigger delay", selected["mean_trigger_delay_steps"], 17.5)


def verify_rocm_benchmark() -> None:
    result = load_json("results/rocm_inference_benchmark_seed2026/benchmark.json")
    check_equal("ROCm benchmark status", result["status"], "PASS")
    check_equal("GPU name", result["hardware"]["gpu_name"], "AMD Radeon Graphics")
    check_equal("GPU architecture", result["hardware"]["gcn_arch"], "gfx1100")
    check_close("GPU VRAM", result["hardware"]["total_vram_gib"], 47.984)
    check_equal("ROCm test scenes", result["dataset"]["test_scene_count"], 130)
    check_equal("ROCm test sequences", result["dataset"]["test_sequences"], 30142)
    check_equal("model parameters", result["model"]["parameters"], 56968)
    rows = {
        (row["precision"], row["batch_size"]): row for row in result["benchmarks"]
    }
    expected = {
        ("fp32", 1): (0.558821, 0.95458, 1.019299, 1632.89, 77.312),
        ("fp32", 32): (0.571206, 0.974368, 1.056337, 51199.8, 77.794),
        ("fp32", 256): (0.636986, 1.010295, 1.078844, 367947.68, 82.494),
        ("fp32", 1024): (0.714952, 1.003659, 1.064934, 1371235.75, 98.604),
        ("amp_fp16", 1024): (0.694567, 1.086294, 1.201812, 1364850.7, 88.6),
    }
    for key, values in expected.items():
        row = rows[key]
        for field, expected_value in zip(
            (
                "latency_p50_ms",
                "latency_p95_ms",
                "latency_p99_ms",
                "throughput_sequences_per_s",
                "peak_allocated_mib",
            ),
            values,
            strict=True,
        ):
            check_close(f"{key} {field}", row[field], expected_value)
    amp = result["amp_verification"]
    check_equal("AMP verification samples", amp["samples"], 8192)
    check_close("AMP joint diagnostic agreement", amp["joint_factor_classification_agreement"], 1.0)
    check_close("AMP risk MAE", amp["risk_mean_absolute_error"], 0.00008262)
    check_close("AMP risk p99 error", amp["risk_p99_absolute_error"], 0.00033322)
    check_close("AMP risk max error", amp["risk_max_absolute_error"], 0.00064528)
    check_equal("AMP verification status", amp["passed"], True)


def verify_frozen_hashes() -> None:
    check_equal(
        "selected checkpoint SHA-256",
        sha256_file("artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt"),
        "2e3eeb470ebba19f2b7bfc3f94a7c346f34a9634f91743a06a61a05baec62c5d",
    )
    check_equal(
        "split manifest SHA-256",
        sha256_file("configs/nuscenes_trainval_v3_split.json"),
        "1ec33bd7cd404438f47d06607710ae143d1a95e83603f61df7b457cd11607cac",
    )


def main() -> None:
    verify_dataset_and_split()
    verify_timestamp_robustness()
    verify_fair_comparison()
    verify_mrm_calibration()
    verify_closed_loop()
    verify_rocm_benchmark()
    verify_frozen_hashes()
    print(f"SUBMISSION CLAIMS PASS: {CHECK_COUNT} frozen evidence checks")


if __name__ == "__main__":
    main()
