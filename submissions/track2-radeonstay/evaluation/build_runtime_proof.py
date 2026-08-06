#!/usr/bin/env python3
"""Build an accepted runtime proof and frozen restore profile from bound evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evaluation.compare_benchmarks import (
        EXPECTED_OFFLOADED_MODEL_LAYERS,
        GPU_OFFLOAD_RE,
        OFFICIAL_CONCURRENCY,
        load_binding,
        load_report,
        normalized_report_service_configuration,
        validate_binding,
        validate_request_configuration,
    )
    from evaluation.configuration import (
        request_configuration_sha256,
        service_configuration_sha256,
    )
    from evaluation.quality_negative_evidence import load_quality_negative_bundle
    from evaluation.select_winner import build_winner_report
    from evaluation.validate_soak import (
        FORMAL_MAX_VRAM_PERCENT,
        FORMAL_MIN_DURATION_SECONDS,
        _load_stability_runtime_proofs,
        _validate_stability,
    )
except ModuleNotFoundError:  # Direct ``python evaluation/build_runtime_proof.py``.
    from compare_benchmarks import (  # type: ignore[no-redef]
        EXPECTED_OFFLOADED_MODEL_LAYERS,
        GPU_OFFLOAD_RE,
        OFFICIAL_CONCURRENCY,
        load_binding,
        load_report,
        normalized_report_service_configuration,
        validate_binding,
        validate_request_configuration,
    )
    from configuration import (  # type: ignore[no-redef]
        request_configuration_sha256,
        service_configuration_sha256,
    )
    from quality_negative_evidence import (  # type: ignore[no-redef]
        load_quality_negative_bundle,
    )
    from select_winner import build_winner_report  # type: ignore[no-redef]
    from validate_soak import (  # type: ignore[no-redef]
        FORMAL_MAX_VRAM_PERCENT,
        FORMAL_MIN_DURATION_SECONDS,
        _load_stability_runtime_proofs,
        _validate_stability,
    )

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$")
MATRIX_LABELS = tuple("ABCDEFGH")
RUNTIME_PROOF_SCHEMA_VERSION = 2
RELEASE_PROFILE_SCHEMA_VERSION = 4


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def _safe_output(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() or resolved.is_symlink():
        raise FileExistsError(f"Refusing to overwrite {label}: {resolved}")
    if not resolved.parent.is_dir():
        raise FileNotFoundError(f"{label} parent does not exist: {resolved.parent}")
    return resolved


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(rendered)


def _summary_by_concurrency(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    summaries = {
        int(run["concurrency"]): run["summary"]
        for run in report["runs"]
        if isinstance(run, dict)
    }
    if tuple(sorted(summaries)) != OFFICIAL_CONCURRENCY:
        raise ValueError("Benchmark report must contain concurrency 1, 2 and 4")
    return summaries


def _core_improvements(
    baseline: dict[str, Any],
    winner: dict[str, Any],
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    left = _summary_by_concurrency(baseline)
    right = _summary_by_concurrency(winner)
    improvements: list[tuple[str, float]] = []
    regressions: list[tuple[str, float]] = []
    for concurrency in OFFICIAL_CONCURRENCY:
        metrics = {
            "latency_p50_ms": (
                left[concurrency]["latency_ms"]["p50"],
                right[concurrency]["latency_ms"]["p50"],
                True,
            ),
            "latency_p95_ms": (
                left[concurrency]["latency_ms"]["p95"],
                right[concurrency]["latency_ms"]["p95"],
                True,
            ),
            "successful_throughput_requests_per_second": (
                left[concurrency]["successful_throughput_requests_per_second"],
                right[concurrency]["successful_throughput_requests_per_second"],
                False,
            ),
            "effective_output_tokens_per_second_p50": (
                left[concurrency]["model_call_metrics"][
                    "effective_output_tokens_per_second_p50"
                ],
                right[concurrency]["model_call_metrics"][
                    "effective_output_tokens_per_second_p50"
                ],
                False,
            ),
            "effective_output_tokens_per_second_p95": (
                left[concurrency]["model_call_metrics"][
                    "effective_output_tokens_per_second_p95"
                ],
                right[concurrency]["model_call_metrics"][
                    "effective_output_tokens_per_second_p95"
                ],
                False,
            ),
        }
        for metric, (baseline_value, winner_value, lower_is_better) in metrics.items():
            if (
                isinstance(baseline_value, bool)
                or isinstance(winner_value, bool)
                or not isinstance(baseline_value, (int, float))
                or not isinstance(winner_value, (int, float))
                or not math.isfinite(float(baseline_value))
                or not math.isfinite(float(winner_value))
                or float(baseline_value) <= 0
            ):
                raise ValueError(f"Invalid core metric c{concurrency}.{metric}")
            baseline_number = float(baseline_value)
            winner_number = float(winner_value)
            delta = (
                (baseline_number - winner_number) / baseline_number * 100.0
                if lower_is_better
                else (winner_number - baseline_number) / baseline_number * 100.0
            )
            qualified = f"c{concurrency}.{metric}"
            if delta >= 5.0:
                improvements.append((qualified, delta))
            elif delta <= -5.0:
                regressions.append((qualified, abs(delta)))
    return improvements, regressions


def _key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key and key not in values:
            values[key] = value
    return values


def _hardware_identity(bundle_dir: Path) -> dict[str, Any]:
    rocminfo = (bundle_dir / "rocminfo.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    rocm_smi = (bundle_dir / "rocm-smi.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    monitor = (bundle_dir / "rocm-monitor.log").read_text(
        encoding="utf-8", errors="replace"
    )
    version = _key_values(bundle_dir / "rocm-version.txt")

    accelerator = re.search(
        r"^[ \t]*Name:[ \t]*(gfx[0-9A-Za-z]+)[ \t]*$"
        r"(?:(?!^[ \t]*Name:).)*?"
        r"^[ \t]*Marketing Name:[ \t]*(.+?)[ \t]*$"
        r"(?:(?!^[ \t]*Name:).)*?"
        r"^[ \t]*Compute Unit:[ \t]*([1-9][0-9]*)[ \t]*$",
        rocminfo,
        re.MULTILINE | re.DOTALL,
    )
    if accelerator is None:
        raise ValueError("Winner rocminfo lacks a parseable gfx accelerator block")
    gpu_arch, gpu_name, compute_units_text = accelerator.groups()
    vram_values = [
        int(value)
        for value in re.findall(
            r"VRAM Total Memory \(B\):[ \t]*([1-9][0-9]*)",
            rocm_smi + "\n" + monitor,
            re.IGNORECASE,
        )
    ]
    if not vram_values:
        raise ValueError("Winner ROCm evidence lacks total VRAM bytes")
    rocm_version = version.get("rocm_version")
    if not isinstance(rocm_version, str) or not rocm_version.strip():
        raise ValueError("Winner evidence lacks a ROCm version")
    return {
        "rocm_version": rocm_version.strip(),
        "gpu_name": gpu_name.strip(),
        "gpu_arch": gpu_arch,
        "compute_units": int(compute_units_text),
        "vram_bytes": max(vram_values),
    }


def _offload_identity(server_text: str) -> tuple[int, int]:
    matches = [(int(left), int(right)) for left, right in GPU_OFFLOAD_RE.findall(server_text)]
    full = [
        (left, right)
        for left, right in matches
        if left == right == EXPECTED_OFFLOADED_MODEL_LAYERS
    ]
    if not full:
        raise ValueError(
            "Winner server log lacks the pinned model's exact "
            f"{EXPECTED_OFFLOADED_MODEL_LAYERS}/"
            f"{EXPECTED_OFFLOADED_MODEL_LAYERS} offload record"
        )
    return full[-1]


def _source_matches(
    source: Any,
    *,
    label: str,
    benchmark_path: Path,
    binding_path: Path,
) -> bool:
    return isinstance(source, dict) and source == {
        "label": label,
        "benchmark_basename": benchmark_path.name,
        "benchmark_sha256": file_sha256(benchmark_path),
        "binding_basename": binding_path.name,
        "binding_sha256": file_sha256(binding_path),
    }


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _require_regular_file(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise FileNotFoundError(f"{label} must be a regular non-symlink file")
    return expanded.resolve()


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA256")
    return value


def _safe_basename(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        raise ValueError(f"{label} must be a path-safe basename")
    return value


def _winner_matrix_contract(
    winner_report: dict[str, Any],
) -> tuple[str, list[str], list[str]]:
    matrix = winner_report.get("matrix_completeness")
    if not isinstance(matrix, dict):
        raise ValueError("Winner report lacks matrix completeness evidence")
    reference_label = matrix.get("reference_experiment")
    if reference_label == "A":
        qualified_labels = list(MATRIX_LABELS)
        negative_labels: list[str] = []
        optimized_count = 7
    elif reference_label == "B":
        qualified_labels = list("BCDEFGH")
        negative_labels = ["A"]
        optimized_count = 6
    else:
        raise ValueError("Winner reference experiment must be A or B")
    if not (
        winner_report.get("schema_version") == 2
        and winner_report.get("selection") == "radeonstay-a-h-winner"
        and matrix.get("required_labels") == list(MATRIX_LABELS)
        and matrix.get("observed_labels") == list(MATRIX_LABELS)
        and matrix.get("quality_qualified_labels") == qualified_labels
        and matrix.get("quality_negative_labels") == negative_labels
        and matrix.get("missing_labels") == []
        and matrix.get("reference_complete") is True
        and matrix.get("baseline_complete") is True
        and matrix.get("optimized_complete_count") == optimized_count
        and matrix.get("selection_candidate_set_complete") is True
        and matrix.get("complete") is True
    ):
        raise ValueError("Winner report has an inconsistent A-H quality contract")
    return reference_label, qualified_labels, negative_labels


def _recompute_winner_report(
    winner_report: dict[str, Any],
    raw_candidates: list[list[str]],
    raw_quality_negatives: list[list[str]],
) -> tuple[
    dict[str, Any],
    dict[str, tuple[Path, Path]],
    set[str],
    str | None,
]:
    reference_label, qualified_labels, negative_labels = _winner_matrix_contract(
        winner_report
    )
    expected_labels = set(qualified_labels)
    candidates: dict[
        str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]
    ] = {}
    candidate_sources: dict[str, dict[str, str]] = {}
    candidate_paths: dict[str, tuple[Path, Path]] = {}
    used_paths: set[Path] = set()
    run_ids: set[str] = set()
    for raw_label, raw_benchmark, raw_binding in raw_candidates:
        label = raw_label.upper()
        if label not in expected_labels or label in candidates:
            raise ValueError(f"Unexpected or duplicate winner candidate: {raw_label}")
        benchmark_path = _require_regular_file(
            Path(raw_benchmark), f"{label} candidate benchmark"
        )
        binding_path = _require_regular_file(
            Path(raw_binding), f"{label} candidate binding"
        )
        if benchmark_path in used_paths or binding_path in used_paths:
            raise ValueError("Winner candidate paths must be distinct")
        used_paths.update({benchmark_path, binding_path})
        report = load_report(benchmark_path, label)
        binding = load_binding(binding_path, label)
        runtime = validate_binding(
            report,
            benchmark_path,
            binding_path,
            binding,
            label,
        )
        run_id = binding.get("run_id")
        if (
            not isinstance(run_id, str)
            or RUN_ID_RE.fullmatch(run_id) is None
            or run_id in run_ids
        ):
            raise ValueError("Winner candidates must use unique valid run IDs")
        run_ids.add(run_id)
        candidates[label] = (report, runtime, binding)
        candidate_paths[label] = (benchmark_path, binding_path)
        candidate_sources[label] = {
            "label": label,
            "benchmark_basename": benchmark_path.name,
            "benchmark_sha256": file_sha256(benchmark_path),
            "binding_basename": binding_path.name,
            "binding_sha256": file_sha256(binding_path),
        }
    if set(candidates) != expected_labels:
        raise ValueError(
            "--candidate labels must exactly match winner quality_qualified_labels"
        )

    quality_negatives: dict[str, dict[str, Any]] = {}
    quality_negative_sources: dict[str, dict[str, str]] = {}
    quality_negative_manifest_sha256: str | None = None
    for raw_label, raw_manifest in raw_quality_negatives:
        label = raw_label.upper()
        if label not in negative_labels or label in quality_negatives:
            raise ValueError(f"Unexpected or duplicate quality negative: {raw_label}")
        manifest_path = _require_regular_file(
            Path(raw_manifest), f"{label} quality-negative manifest"
        )
        if manifest_path in used_paths:
            raise ValueError("Quality-negative and candidate paths must be distinct")
        used_paths.add(manifest_path)
        negative = load_quality_negative_bundle(manifest_path, expected_label=label)
        negative_run_id = negative.get("run_id")
        if (
            not isinstance(negative_run_id, str)
            or RUN_ID_RE.fullmatch(negative_run_id) is None
            or negative_run_id in run_ids
        ):
            raise ValueError(
                "Quality-negative and candidate evidence require distinct run IDs"
            )
        run_ids.add(negative_run_id)
        quality_negatives[label] = negative
        quality_negative_manifest_sha256 = file_sha256(manifest_path)
        quality_negative_sources[label] = {
            "label": label,
            "manifest_basename": manifest_path.name,
            "manifest_sha256": quality_negative_manifest_sha256,
        }
    if set(quality_negatives) != set(negative_labels):
        required = "none" if not negative_labels else ",".join(negative_labels)
        raise ValueError(
            f"--quality-negative labels must match the Reference contract: {required}"
        )

    rules = winner_report.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("Winner report rules are missing")
    recomputed = build_winner_report(
        candidates,
        candidate_sources=candidate_sources,
        material_threshold_percent=rules.get("material_threshold_percent"),
        maximum_vram_percent=rules.get("maximum_vram_percent_strict"),
        p95_slack_percent=rules.get("single_request_p95_slack_percent"),
        quality_negatives=quality_negatives,
        quality_negative_sources=quality_negative_sources,
    )
    expected = dict(winner_report)
    expected.pop("created_at_utc", None)
    observed = dict(recomputed)
    observed.pop("created_at_utc", None)
    if observed != expected:
        raise ValueError(
            "Winner report differs from the complete source-bound recomputation"
        )
    if recomputed["matrix_completeness"]["reference_experiment"] != reference_label:
        raise ValueError("Recomputed Winner reference changed")
    return recomputed, candidate_paths, run_ids, quality_negative_manifest_sha256


def _validate_soak_acceptance(
    soak: dict[str, Any],
    *,
    winner_report: dict[str, Any],
    winner_report_path: Path,
    stability_report_path: Path,
    stability_evidence: dict[str, Any],
    prior_run_ids: set[str],
) -> dict[str, Any]:
    assessment = winner_report["assessment"]
    reference_label = assessment["reference_experiment"]
    winner_label = assessment["winner_experiment"]
    gates = soak.get("gates")
    required_gates = {
        "duration_at_least_minimum",
        "all_requests_succeeded",
        "all_model_calls_succeeded_without_repair_failure",
        "no_oom_fatal_or_crash_marker",
        "winner_source_artifact_hardware_hashes_unchanged",
        "winner_request_configuration_unchanged",
        "winner_service_configuration_unchanged",
        "benchmark_quality_gate_passed",
        "peak_vram_strictly_below_limit",
        "same_gpu_energy_window_evidence_available",
        "official_16_case_workload_at_all_concurrency_levels",
        "five_or_more_independent_stability_lifecycles_passed",
    }
    if not (
        soak.get("schema_version") == 1
        and soak.get("report") == "radeonstay-final-winner-long-soak"
        and soak.get("passed") is True
        and soak.get("failures") == []
        and isinstance(gates, dict)
        and set(gates) == required_gates
        and all(value is True for value in gates.values())
        and soak.get("reference_experiment") == reference_label
        and soak.get("reference_source") == assessment["reference_source"]
        and soak.get("winner_experiment") == winner_label
        and soak.get("winner_source") == assessment["winner_source"]
        and soak.get("stability") == stability_evidence
    ):
        raise ValueError("Long-soak report is not an accepted bound final report")
    soak_run_id = soak.get("soak_run_id")
    if (
        not isinstance(soak_run_id, str)
        or RUN_ID_RE.fullmatch(soak_run_id) is None
        or soak_run_id in prior_run_ids
    ):
        raise ValueError("Long-soak run ID is invalid or not fresh")
    minimum_duration = soak.get("minimum_duration_seconds")
    duration = soak.get("measurement_duration_seconds")
    maximum_vram = soak.get("maximum_vram_percent_strict")
    peak_vram = soak.get("peak_vram_percent")
    numeric_values = (minimum_duration, duration, maximum_vram, peak_vram)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in numeric_values
    ):
        raise ValueError("Long-soak duration or VRAM evidence is invalid")
    if not (
        float(minimum_duration) >= FORMAL_MIN_DURATION_SECONDS
        and float(duration) >= float(minimum_duration)
        and 0 < float(maximum_vram) <= FORMAL_MAX_VRAM_PERCENT
        and 0 < float(peak_vram) < float(maximum_vram)
    ):
        raise ValueError("Long-soak duration or VRAM gate was weakened")
    raw_health = soak.get("raw_health")
    if not (
        isinstance(raw_health, dict)
        and isinstance(raw_health.get("request_count"), int)
        and not isinstance(raw_health.get("request_count"), bool)
        and raw_health["request_count"] > 0
        and raw_health.get("successful_request_count") == raw_health["request_count"]
        and raw_health.get("request_success_rate") == 1.0
        and isinstance(raw_health.get("model_call_count"), int)
        and raw_health["model_call_count"] > 0
        and raw_health.get("failed_model_call_count") == 0
        and raw_health.get("request_errors") == []
        and raw_health.get("model_errors") == []
    ):
        raise ValueError("Long-soak raw request/model health did not fully pass")
    workload = soak.get("workload")
    fixed_workload = winner_report.get("fixed_workload")
    if not isinstance(workload, dict) or not isinstance(fixed_workload, dict):
        raise ValueError("Long-soak workload binding is missing")
    for field in ("case_ids", "request_case_ids", "configuration"):
        if workload.get(field) != fixed_workload.get(field):
            raise ValueError(f"Long-soak workload differs from Winner: {field}")
    sources = soak.get("sources")
    required_source_fields = {
        "winner_report_basename",
        "winner_report_sha256",
        "stability_report_basename",
        "stability_report_sha256",
        "benchmark_basename",
        "benchmark_sha256",
        "binding_basename",
        "binding_sha256",
        "server_log_basename",
        "server_log_sha256",
    }
    if not isinstance(sources, dict) or set(sources) != required_source_fields:
        raise ValueError("Long-soak source index is incomplete")
    for field in (
        "winner_report_basename",
        "stability_report_basename",
        "benchmark_basename",
        "binding_basename",
        "server_log_basename",
    ):
        _safe_basename(sources.get(field), f"long-soak {field}")
    for field in (
        "winner_report_sha256",
        "stability_report_sha256",
        "benchmark_sha256",
        "binding_sha256",
        "server_log_sha256",
    ):
        _require_sha256(sources.get(field), f"long-soak {field}")
    if not (
        sources["winner_report_basename"] == winner_report_path.name
        and sources["winner_report_sha256"] == file_sha256(winner_report_path)
        and sources["stability_report_basename"] == stability_report_path.name
        and sources["stability_report_sha256"] == file_sha256(stability_report_path)
    ):
        raise ValueError("Long-soak Winner or Stability source hash changed")
    return {
        "run_id": soak_run_id,
        "duration_seconds": float(duration),
        "peak_vram_percent": float(peak_vram),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--winner-report", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        action="append",
        nargs=3,
        metavar=("LABEL", "BENCHMARK", "BINDING"),
        required=True,
        help="Repeat for every quality-qualified Winner candidate",
    )
    parser.add_argument(
        "--quality-negative",
        action="append",
        nargs=2,
        metavar=("LABEL", "MANIFEST"),
        default=[],
        help="Required exactly once for A when the performance Reference is B",
    )
    parser.add_argument("--stability-report", type=Path, required=True)
    parser.add_argument("--soak-report", type=Path, required=True)
    reference = parser.add_mutually_exclusive_group(required=True)
    reference.add_argument("--reference-binding", type=Path)
    reference.add_argument(
        "--baseline-binding",
        dest="reference_binding",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--winner-binding", type=Path, required=True)
    parser.add_argument("--runtime-proof-output", type=Path, required=True)
    parser.add_argument("--release-profile-output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    winner_report_path = _require_regular_file(args.winner_report, "winner report")
    stability_report_path = _require_regular_file(
        args.stability_report, "stability report"
    )
    soak_report_path = _require_regular_file(args.soak_report, "long-soak report")
    reference_binding_path = _require_regular_file(
        args.reference_binding, "reference binding"
    )
    winner_binding_path = _require_regular_file(args.winner_binding, "winner binding")
    runtime_output = _safe_output(args.runtime_proof_output, "runtime proof")
    profile_output = _safe_output(args.release_profile_output, "release profile")
    if runtime_output == profile_output:
        raise ValueError("Runtime proof and release profile outputs must differ")
    immutable_inputs = {
        winner_report_path,
        stability_report_path,
        soak_report_path,
        reference_binding_path,
        winner_binding_path,
    }
    if runtime_output in immutable_inputs or profile_output in immutable_inputs:
        raise ValueError("Outputs must differ from every immutable evidence input")

    winner_report = load_json_object(winner_report_path, "winner report")
    recomputed_winner, candidate_paths, matrix_run_ids, quality_negative_sha256 = (
        _recompute_winner_report(
            winner_report,
            args.candidate,
            args.quality_negative,
        )
    )
    assessment = recomputed_winner.get("assessment")
    if not (
        isinstance(assessment, dict)
        and assessment.get("accepted") is True
        and assessment.get("optimization_winner") == "optimized"
    ):
        raise ValueError("Winner report is not an accepted optimized selection")
    matrix = recomputed_winner["matrix_completeness"]
    reference_label = matrix["reference_experiment"]
    quality_qualified_labels = matrix["quality_qualified_labels"]
    winner_label = assessment.get("winner_experiment")
    eligible_winner_labels = "BCDEFGH" if reference_label == "A" else "CDEFGH"
    if not isinstance(winner_label, str) or winner_label not in eligible_winner_labels:
        raise ValueError("Winner report does not select an experiment after its reference")
    if reference_binding_path != candidate_paths[reference_label][1]:
        raise ValueError("--reference-binding must be the matching --candidate binding")
    if winner_binding_path != candidate_paths[winner_label][1]:
        raise ValueError("--winner-binding must be the selected --candidate binding")

    reference_binding = load_binding(reference_binding_path, "reference")
    winner_binding = load_binding(winner_binding_path, "winner")
    reference_report_path = candidate_paths[reference_label][0]
    winner_benchmark_path = candidate_paths[winner_label][0]
    reference_report = load_report(reference_report_path, "reference")
    winner_benchmark = load_report(winner_benchmark_path, "winner")
    validate_binding(
        reference_report,
        reference_report_path,
        reference_binding_path,
        reference_binding,
        "reference",
    )
    winner_runtime = validate_binding(
        winner_benchmark,
        winner_benchmark_path,
        winner_binding_path,
        winner_binding,
        "winner",
    )
    if (
        reference_report.get("service_configuration", {}).get("experiment")
        != reference_label
    ):
        raise ValueError("Reference binding does not match the winner report")
    if winner_benchmark.get("service_configuration", {}).get("experiment") != winner_label:
        raise ValueError("Winner binding does not match the selected experiment")
    if reference_binding.get("commit") != winner_binding.get("commit"):
        raise ValueError("Reference and winner do not share the frozen C2 commit")

    sources = recomputed_winner.get("candidate_sources")
    rows = recomputed_winner.get("candidates")
    if not isinstance(sources, dict) or not isinstance(rows, dict):
        raise ValueError("Winner report lacks its candidate source index")
    expected_labels = set(quality_qualified_labels)
    if set(sources) != expected_labels or set(rows) != expected_labels:
        raise ValueError("Winner report sources must match quality-qualified rows")
    for label in sorted(expected_labels):
        row = rows.get(label)
        if not isinstance(row, dict) or row.get("source") != sources.get(label):
            raise ValueError(f"Winner report {label} row source is not bound")
        if not isinstance(row.get("run_id"), str) or not row["run_id"]:
            raise ValueError(f"Winner report {label} row lacks a run ID")
    if rows[reference_label].get("run_id") != reference_binding.get("run_id"):
        raise ValueError("Winner report reference run ID differs from its bundle")
    if rows[winner_label].get("run_id") != winner_binding.get("run_id"):
        raise ValueError("Winner report selected run ID differs from its bundle")

    fixed_binding = recomputed_winner.get("fixed_binding")
    fixed_binding_fields = (
        "commit",
        "project_tree",
        "source_tree_sha256",
        "hardware_identity_sha256",
        "model_sha256",
        "llama_server_sha256",
        "model_repository",
        "model_revision",
        "model_quantization",
        "llama_cpp_commit",
    )
    if not isinstance(fixed_binding, dict) or set(fixed_binding) != set(
        fixed_binding_fields
    ):
        raise ValueError("Winner report fixed binding is incomplete")
    for field in fixed_binding_fields:
        expected = reference_binding.get(field)
        if fixed_binding.get(field) != expected or winner_binding.get(field) != expected:
            raise ValueError(f"Winner report fixed binding mismatch: {field}")

    fixed_workload = recomputed_winner.get("fixed_workload")
    fixed_workload_fields = (
        "suite_version",
        "suite_sha256",
        "policy_corpus_sha256",
        "case_ids",
        "request_case_ids",
        "configuration",
    )
    if not isinstance(fixed_workload, dict) or set(fixed_workload) != set(
        fixed_workload_fields
    ):
        raise ValueError("Winner report fixed workload is incomplete")
    for field in fixed_workload_fields:
        expected = reference_report.get(field)
        if fixed_workload.get(field) != expected or winner_benchmark.get(field) != expected:
            raise ValueError(f"Winner report fixed workload mismatch: {field}")
    if not _source_matches(
        sources.get(reference_label),
        label=reference_label,
        benchmark_path=reference_report_path,
        binding_path=reference_binding_path,
    ):
        raise ValueError("Winner report reference source does not match the supplied bundle")
    if not _source_matches(
        sources.get(winner_label),
        label=winner_label,
        benchmark_path=winner_benchmark_path,
        binding_path=winner_binding_path,
    ):
        raise ValueError("Selected winner source does not match the supplied bundle")
    if assessment.get("winner_source") != sources[winner_label]:
        raise ValueError("Winner assessment source does not match the source index")
    if not (
        assessment.get("reference_experiment") == reference_label
        and assessment.get("reference_source") == sources[reference_label]
    ):
        raise ValueError("Winner assessment reference does not match its source index")
    winner_row = rows.get(winner_label)
    if not isinstance(winner_row, dict) or winner_row.get("eligible") is not True:
        raise ValueError("Selected winner row is not eligible")

    improvements, regressions = _core_improvements(reference_report, winner_benchmark)
    if regressions:
        raise ValueError(f"Selected winner has material core regressions: {regressions}")
    if not improvements:
        raise ValueError("Selected winner has no measured core improvement of at least 5%")
    winning_metric, winning_percent = max(improvements, key=lambda item: item[1])

    stability = load_json_object(stability_report_path, "stability report")
    if stability.get("run_count") != 5:
        raise ValueError("Final Stability report must contain exactly five lifecycles")
    stability_runtime_proofs = _load_stability_runtime_proofs(stability)
    stability_evidence = _validate_stability(
        stability,
        recomputed_winner,
        winner_row,
        stability_runtime_proofs,
        maximum_vram_percent=FORMAL_MAX_VRAM_PERCENT,
    )
    stability_run_ids = stability_evidence.get("run_ids")
    if not (
        isinstance(stability_run_ids, list)
        and len(stability_run_ids) == 5
        and len(set(stability_run_ids)) == 5
        and all(
            isinstance(run_id, str) and RUN_ID_RE.fullmatch(run_id) is not None
            for run_id in stability_run_ids
        )
        and not (set(stability_run_ids) & matrix_run_ids)
    ):
        raise ValueError(
            "Stability lifecycles must be five fresh runs after the Winner matrix"
        )
    soak = load_json_object(soak_report_path, "long-soak report")
    soak_summary = _validate_soak_acceptance(
        soak,
        winner_report=recomputed_winner,
        winner_report_path=winner_report_path,
        stability_report_path=stability_report_path,
        stability_evidence=stability_evidence,
        prior_run_ids=matrix_run_ids | set(stability_run_ids),
    )

    bundle_dir = winner_binding_path.parent
    server_text = (bundle_dir / winner_binding["server_log"]).read_text(
        encoding="utf-8", errors="replace"
    )
    server_values = _key_values(bundle_dir / winner_binding["server_log"])
    model_alias = server_values.get("model_alias")
    if not isinstance(model_alias, str) or not model_alias:
        raise ValueError("Winner server evidence lacks the model alias")
    offloaded_layers, total_layers = _offload_identity(server_text)
    hardware = _hardware_identity(bundle_dir)
    if not (
        winner_runtime.get("peak_gpu_use_percent", 0) > 0
        and winner_runtime.get("gpu_use_observations", 0) > 0
        and winner_runtime.get("common_active_gpu_indices")
    ):
        raise ValueError("Winner bundle lacks active same-GPU telemetry")
    c2_commit = winner_binding.get("commit")
    if not isinstance(c2_commit, str) or COMMIT_RE.fullmatch(c2_commit) is None:
        raise ValueError("Winner binding has an invalid C2 commit")
    winner_report_sha256 = file_sha256(winner_report_path)
    stability_report_sha256 = file_sha256(stability_report_path)
    soak_report_sha256 = file_sha256(soak_report_path)
    candidate_source_index_sha256 = _canonical_sha256(
        {
            "candidate_sources": recomputed_winner["candidate_sources"],
            "quality_negative_sources": recomputed_winner[
                "quality_negative_sources"
            ],
        }
    )
    stability_run_ids_sha256 = _canonical_sha256(stability_run_ids)
    quality_negative_label = "A" if reference_label == "B" else "none"
    final_evidence = {
        "candidate_source_index_sha256": candidate_source_index_sha256,
        "quality_qualified_candidate_count": len(quality_qualified_labels),
        "quality_negative_label": quality_negative_label,
        "quality_negative_manifest_sha256": quality_negative_sha256,
        "stability_report_sha256": stability_report_sha256,
        "stability_run_count": len(stability_run_ids),
        "stability_run_ids_sha256": stability_run_ids_sha256,
        "soak_report_sha256": soak_report_sha256,
        "soak_run_id": soak_summary["run_id"],
        "soak_duration_seconds": soak_summary["duration_seconds"],
        "final_evidence_accepted": True,
    }

    runtime_proof = {
        "schema_version": RUNTIME_PROOF_SCHEMA_VERSION,
        "status": "accepted_final",
        "run_id": winner_binding["run_id"],
        "captured_at_utc": winner_binding["created_at_utc"],
        **hardware,
        "offloaded_layers": offloaded_layers,
        "total_layers": total_layers,
        "model_alias": model_alias,
        "model_sha256": winner_binding["model_sha256"],
        "llama_server_sha256": winner_binding["llama_server_sha256"],
        "binding_valid": True,
        "telemetry_active": True,
        "c2_commit": c2_commit,
        "reference_label": reference_label,
        "winner_label": winner_label,
        "winner_assessment_accepted": True,
        "winner_report_sha256": winner_report_sha256,
        "winner_core_metric": winning_metric,
        "winner_core_improvement_percent": round(winning_percent, 6),
        **final_evidence,
    }

    model_filename = Path(winner_binding["model_file"]).name
    if SAFE_NAME_RE.fullmatch(model_filename) is None:
        raise ValueError("Winner model filename is not safe for recovery")
    request_configuration = winner_row.get("request_configuration")
    service_configuration = winner_row.get("service_configuration")
    if not isinstance(request_configuration, dict) or not isinstance(
        service_configuration, dict
    ):
        raise ValueError("Winner row lacks frozen request/service configuration")
    bound_request_configuration = validate_request_configuration(
        winner_benchmark,
        "winner benchmark",
    )
    bound_service_configuration = normalized_report_service_configuration(
        winner_benchmark,
        "winner benchmark service_configuration",
    )
    if request_configuration != bound_request_configuration:
        raise ValueError(
            "Winner row request configuration differs from the bound benchmark"
        )
    if service_configuration != bound_service_configuration:
        raise ValueError(
            "Winner row service configuration differs from the bound benchmark"
        )
    if winner_benchmark.get("service_configuration", {}).get(
        "experiment"
    ) != winner_label:
        raise ValueError("Bound winner benchmark has the wrong experiment label")
    if assessment.get("recommended_request_configuration") != request_configuration:
        raise ValueError("Winner assessment request configuration differs from its row")
    if assessment.get("recommended_service_configuration") != service_configuration:
        raise ValueError("Winner assessment service configuration differs from its row")
    frozen_service_configuration_sha256 = service_configuration_sha256(
        bound_service_configuration,
        "winner service configuration",
    )
    frozen_request_configuration_sha256 = request_configuration_sha256(
        bound_request_configuration,
        "winner request configuration",
    )
    runtime_proof["request_configuration_sha256"] = (
        frozen_request_configuration_sha256
    )
    runtime_proof["service_configuration_sha256"] = (
        frozen_service_configuration_sha256
    )
    release_service_configuration = {
        "experiment": winner_label,
        **bound_service_configuration,
    }
    release_profile = {
        "schema_version": RELEASE_PROFILE_SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "reference_label": reference_label,
        "winner_label": winner_label,
        "winner_report_sha256": winner_report_sha256,
        **final_evidence,
        "c2_commit": c2_commit,
        "request_configuration": bound_request_configuration,
        "request_configuration_sha256": frozen_request_configuration_sha256,
        "service_configuration": release_service_configuration,
        "service_configuration_sha256": frozen_service_configuration_sha256,
        "hardware": hardware,
        "model": {
            "alias": model_alias,
            "repository": winner_binding["model_repository"],
            "revision": winner_binding["model_revision"],
            "filename": model_filename,
            "sha256": winner_binding["model_sha256"],
            "quantization": winner_binding["model_quantization"],
            "license": winner_binding.get("model_license", "unknown"),
        },
        "llama_cpp": {
            "commit": winner_binding["llama_cpp_commit"],
            "server_sha256": winner_binding["llama_server_sha256"],
        },
    }
    _write_private_json(profile_output, release_profile)
    try:
        _write_private_json(runtime_output, runtime_proof)
    except Exception:
        profile_output.unlink(missing_ok=True)
        raise
    print(
        json.dumps(
            {
                "runtime_proof": str(runtime_output),
                "runtime_proof_sha256": file_sha256(runtime_output),
                "release_profile": str(profile_output),
                "release_profile_sha256": file_sha256(profile_output),
                "winner_label": winner_label,
                "reference_label": reference_label,
                "stability_report_sha256": stability_report_sha256,
                "soak_report_sha256": soak_report_sha256,
                "soak_run_id": soak_summary["run_id"],
                "winner_core_metric": winning_metric,
                "winner_core_improvement_percent": round(winning_percent, 6),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
