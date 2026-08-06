"""Strict aggregation of real ablation runs; fixtures can never become evidence."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

import orjson
from pydantic import Field, model_validator

from buildguard.logging_system.jsonl_writer import atomic_write_json
from buildguard.schemas.common import StrictSchema


class MeasuredAblationRun(StrictSchema):
    group: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    status: Literal["PASS"]
    source: Literal["measured"]
    mock: Literal[False]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_revision: str = Field(min_length=7)
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    host: str = Field(min_length=1)
    gpu_name: str = Field(min_length=1)
    rocm_version: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime
    sample_count: int = Field(gt=0)
    metrics: dict[str, float]
    artifact_paths: list[Path] = Field(min_length=1)
    artifact_sha256: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_measurement(self) -> MeasuredAblationRun:
        if self.finished_at <= self.started_at:
            raise ValueError("ablation finished_at must be after started_at")
        if not self.metrics or any(value < 0 for value in self.metrics.values()):
            raise ValueError("ablation metrics must be non-empty and non-negative")
        expected_paths = {str(path) for path in self.artifact_paths}
        if set(self.artifact_sha256) != expected_paths:
            raise ValueError("every ablation artifact must have exactly one SHA-256")
        if any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in self.artifact_sha256.values()
        ):
            raise ValueError("ablation artifact SHA-256 values must be lowercase hex")
        return self


class AblationGroupReport(StrictSchema):
    group: str
    baseline: str
    required_variants: list[str]
    observed_variants: list[str]
    missing_variants: list[str]
    metrics: dict[str, dict[str, float]]
    deltas_from_baseline: dict[str, dict[str, float]]
    complete: bool


class AblationSuiteReport(StrictSchema):
    status: Literal["PASS", "INCOMPLETE"]
    measured_only: bool
    run_count: int = Field(ge=0)
    groups: list[AblationGroupReport]
    errors: list[str] = Field(default_factory=list)


REQUIRED_GROUPS: dict[str, tuple[str, tuple[str, ...], set[str]]] = {
    "retrieval": (
        "bm25",
        ("bm25", "dense", "hybrid", "hybrid-reranker"),
        {"recall_at_5", "mrr", "latency_ms"},
    ),
    "advanced-rag": (
        "baseline",
        ("baseline", "corrective-grounded"),
        {"grounded_answer_rate", "refusal_accuracy", "latency_ms"},
    ),
    "routing": (
        "full-all",
        ("full-all", "rule", "cost-aware", "cost-aware-guard"),
        {"high_risk_recall", "model_calls", "latency_ms"},
    ),
    "reasoning": (
        "non-thinking",
        ("non-thinking", "thinking", "dynamic"),
        {"task_success_rate", "latency_ms"},
    ),
    "prefix-cache": (
        "off",
        ("off", "on"),
        {"ttft_seconds", "tokens_per_second"},
    ),
    "context": (
        "full",
        ("full", "compressed"),
        {"task_success_rate", "prompt_tokens", "latency_ms"},
    ),
    "residency": (
        "on-demand",
        ("on-demand", "resident"),
        {"latency_ms", "peak_vram_mb"},
    ),
    "quantization": (
        "Q4_K_M",
        ("Q4_K_M", "Q8_0"),
        {"task_success_rate", "ttft_seconds", "tokens_per_second", "peak_vram_mb"},
    ),
}


def build_ablation_report(runs: list[MeasuredAblationRun]) -> AblationSuiteReport:
    indexed: dict[tuple[str, str], MeasuredAblationRun] = {}
    errors: list[str] = []
    for run in runs:
        key = (run.group, run.variant)
        if key in indexed:
            errors.append(f"duplicate measured run: {run.group}/{run.variant}")
        indexed[key] = run

    groups: list[AblationGroupReport] = []
    for group, (baseline, variants, required_metrics) in REQUIRED_GROUPS.items():
        group_runs = {
            variant: indexed[(group, variant)]
            for variant in variants
            if (group, variant) in indexed
        }
        missing = [variant for variant in variants if variant not in group_runs]
        if group_runs:
            dataset_hashes = {run.dataset_sha256 for run in group_runs.values()}
            revisions = {run.code_revision for run in group_runs.values()}
            if len(dataset_hashes) != 1:
                errors.append(f"{group}: variants did not use the same dataset")
            if len(revisions) != 1:
                errors.append(f"{group}: variants did not use the same code revision")
            for variant, run in group_runs.items():
                absent = required_metrics - set(run.metrics)
                if absent:
                    errors.append(
                        f"{group}/{variant}: missing metrics {sorted(absent)}"
                    )
        metrics = {variant: run.metrics for variant, run in group_runs.items()}
        deltas: dict[str, dict[str, float]] = {}
        baseline_metrics = metrics.get(baseline, {})
        for variant, values in metrics.items():
            deltas[variant] = {
                key: value - baseline_metrics[key]
                for key, value in values.items()
                if key in baseline_metrics
            }
        group_errors = any(
            message.startswith((f"{group}:", f"{group}/")) for message in errors
        )
        groups.append(
            AblationGroupReport(
                group=group,
                baseline=baseline,
                required_variants=list(variants),
                observed_variants=sorted(group_runs),
                missing_variants=missing,
                metrics=metrics,
                deltas_from_baseline=deltas,
                complete=not missing and not group_errors,
            )
        )
    complete = all(group.complete for group in groups) and not errors
    return AblationSuiteReport(
        status="PASS" if complete else "INCOMPLETE",
        measured_only=True,
        run_count=len(runs),
        groups=groups,
        errors=errors,
    )


def _digest_path(path: Path) -> str:
    digest = hashlib.sha256()
    candidates = (
        [path]
        if path.is_file()
        else sorted(item for item in path.rglob("*") if item.is_file())
    )
    for candidate in candidates:
        if path.is_dir():
            digest.update(candidate.relative_to(path).as_posix().encode())
        with candidate.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def aggregate_ablation_directory(input_dir: Path, output_path: Path) -> AblationSuiteReport:
    runs = [
        MeasuredAblationRun.model_validate(orjson.loads(path.read_bytes()))
        for path in sorted(input_dir.glob("*.run.json"))
    ]
    report = build_ablation_report(runs)
    evidence_errors: list[str] = []
    for run in runs:
        for path in run.artifact_paths:
            if not path.exists():
                evidence_errors.append(f"missing ablation artifact: {path}")
                continue
            expected = run.artifact_sha256[str(path)]
            if _digest_path(path) != expected:
                evidence_errors.append(f"ablation artifact hash mismatch: {path}")
    if evidence_errors:
        report = report.model_copy(
            update={
                "status": "INCOMPLETE",
                "errors": [*report.errors, *evidence_errors],
            }
        )
    atomic_write_json(output_path, report)
    return report
