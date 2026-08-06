"""Atomic JSON and Markdown experiment report export."""

from __future__ import annotations

import os
import tarfile
from pathlib import Path

import orjson
from pydantic import BaseModel

from buildguard.logging_system.jsonl_writer import atomic_write_json, redact


def render_markdown(report: BaseModel) -> str:
    payload = redact(report)
    data = payload if isinstance(payload, dict) else {}
    lines = [
        "# BuildGuard-Radeon Benchmark Suite",
        "",
        f"- Status: `{data.get('status', 'unknown')}`",
        f"- Competition ready: `{data.get('competition_ready', False)}`",
        f"- Mock only: `{data.get('mock_only', False)}`",
        f"- Generated at: `{data.get('created_at', '')}`",
        "",
        "## Metrics",
        "",
        "```json",
        orjson.dumps(
            data.get("metrics", {}),
            option=orjson.OPT_INDENT_2,
        ).decode(),
        "```",
        "",
        "## ROCm benchmark",
        "",
        "```json",
        orjson.dumps(
            data.get("rocm", []),
            option=orjson.OPT_INDENT_2,
        ).decode(),
        "```",
        "",
        "## Warnings",
        "",
    ]
    warnings = data.get("warnings", [])
    lines.extend(
        [f"- {item}" for item in warnings]
        if isinstance(warnings, list) and warnings
        else ["- None"]
    )
    return "\n".join(lines) + "\n"


def export_report(
    report: BaseModel,
    output_dir: Path,
) -> tuple[Path, Path]:
    target_dir = output_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "benchmark-suite.json"
    markdown_path = target_dir / "benchmark-suite.md"
    atomic_write_json(json_path, report)
    temporary = markdown_path.with_name(
        f".{markdown_path.name}.{os.getpid()}.tmp"
    )
    try:
        temporary.write_text(render_markdown(report), encoding="utf-8")
        temporary.replace(markdown_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return json_path, markdown_path


def export_competition_archive(
    output_dir: Path,
    workspace_root: Path,
) -> Path:
    from buildguard.evaluation.experiment_runner import BenchmarkSuiteReport

    root = workspace_root.resolve()
    target_dir = output_dir.resolve()
    try:
        target_dir.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            "Competition output directory must remain inside workspace"
        ) from exc
    json_candidate = target_dir / "benchmark-suite.json"
    markdown_candidate = target_dir / "benchmark-suite.md"
    if not json_candidate.is_file() or not markdown_candidate.is_file():
        raise FileNotFoundError("Benchmark JSON and Markdown reports are required")
    json_path = json_candidate.resolve(strict=True)
    markdown_path = markdown_candidate.resolve(strict=True)
    for report_path in (json_path, markdown_path):
        try:
            report_path.relative_to(target_dir)
        except ValueError as exc:
            raise PermissionError(
                "Competition report files must remain inside the output directory"
            ) from exc
    payload = orjson.loads(json_path.read_bytes())
    if not isinstance(payload, dict):
        raise TypeError("Benchmark JSON root must be an object")
    report = BenchmarkSuiteReport.model_validate(payload)
    if report.mock_only:
        raise PermissionError("Mock result cannot be exported as a competition result")
    if not report.competition_ready:
        raise PermissionError("Benchmark is not competition-ready")
    required_metrics = {"agent", "rag", "vision", "realtime", "security"}
    if (
        report.status != "completed"
        or report.section != "all"
        or set(report.metrics) != required_metrics
        or len(report.rocm) != 3
        or any(item.status != "completed" for item in report.rocm)
        or not report.stability
        or any(item.status != "validated" for item in report.stability)
    ):
        raise PermissionError(
            "Competition export requires complete metrics, ROCm runs, and stability checks"
        )
    archive = target_dir / "buildguard-competition-results.tar.gz"
    temporary = archive.with_name(f".{archive.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as bundle:
            bundle.add(json_path, arcname=json_path.name, recursive=False)
            bundle.add(markdown_path, arcname=markdown_path.name, recursive=False)
        temporary.replace(archive)
    finally:
        if temporary.exists():
            temporary.unlink()
    return archive
