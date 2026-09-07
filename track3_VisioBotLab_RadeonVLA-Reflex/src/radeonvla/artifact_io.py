"""Deterministic hashes and small, reviewable evaluation artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def sha256_path(path: str | Path) -> str:
    """Hash one file or a directory tree in stable relative-path order."""
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(root)

    digest = hashlib.sha256()
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    for file_path in files:
        relative = file_path.name if root.is_file() else file_path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def atomic_write_text(path: str | Path, text: str) -> Path:
    """Write text beside the destination, then atomically replace it."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    return atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def validate_evaluation_payload(payload: Mapping[str, Any], schema_path: str | Path) -> None:
    """Raise a concise error when formal evaluation evidence violates its schema."""
    from jsonschema import Draft202012Validator

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors)
        raise ValueError(f"Evaluation payload does not match {schema_path}: {details}")


def _episode_row(episode: Mapping[str, Any]) -> dict[str, Any]:
    latencies = [float(value) for value in episode.get("inference_latency_ms", [])]
    sorted_latencies = sorted(latencies)
    p95_index = max(0, min(len(sorted_latencies) - 1, round(0.95 * (len(sorted_latencies) - 1))))
    return {
        "episode_id": episode.get("episode_id"),
        "seed": episode.get("seed"),
        "task_id": episode.get("task_id"),
        "tier": episode.get("tier"),
        "scenario": episode.get("scenario", "normal"),
        "reflex_enabled": episode.get("reflex_enabled", True),
        "success": episode.get("success"),
        "object_correct": episode.get("object_correct"),
        "target_correct": episode.get("target_correct"),
        "first_attempt_success": episode.get("first_attempt_success"),
        "retry_count": episode.get("retry_count", 0),
        "recovery_success": episode.get("recovery_success", False),
        "precision_recovery_attempted": episode.get("precision_recovery_attempted", False),
        "precision_recovery_success": episode.get("precision_recovery_success", False),
        "interrupted": episode.get("interrupted", False),
        "safe_interrupt": episode.get("safe_interrupt", False),
        "interrupt_response_steps": episode.get("interrupt_response_steps"),
        "unprotected_post_interrupt_steps": episode.get("unprotected_post_interrupt_steps", 0),
        "perturbation_applied": episode.get("perturbation_applied", False),
        "completion_time_s": episode.get("completion_time_s"),
        "mean_inference_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "p95_inference_latency_ms": sorted_latencies[p95_index] if sorted_latencies else 0.0,
        "failure_reason": episode.get("failure_reason"),
        "video_uri": episode.get("video_uri"),
    }


def _csv_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _summary_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary", {})
    checkpoint = payload.get("checkpoint", {})
    environment = payload.get("environment", {})

    def metric(name: str, *, percent: bool = False) -> str:
        value = summary.get(name)
        if value is None:
            return "n/a"
        if percent:
            return f"{float(value) * 100:.1f}%"
        return f"{float(value):.3f}"

    lines = [
        "# RadeonVLA-Reflex Evaluation Summary",
        "",
        f"- Experiment: `{payload.get('experiment_id', 'unknown')}`",
        f"- Git commit: `{payload.get('git_commit', 'unknown')}`",
        f"- GPU: `{environment.get('gpu', 'unknown')}`",
        f"- ROCm: `{environment.get('rocm', 'unknown')}`",
        f"- Checkpoint SHA256: `{checkpoint.get('sha256', 'unknown')}`",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Episodes | {summary.get('num_episodes', 0)} |",
        f"| Final success | {metric('final_success', percent=True)} |",
        f"| First-attempt success | {metric('first_attempt_success', percent=True)} |",
        f"| Recovery success | {metric('recovery_success', percent=True)} |",
        f"| Precision recovery success | {metric('precision_recovery_success', percent=True)} |",
        f"| Precision recovery contribution | {metric('precision_recovery_contribution', percent=True)} |",
        f"| Safe interrupt rate | {metric('safe_interrupt_rate', percent=True)} |",
        f"| P50 inference latency (ms) | {metric('p50_inference_latency_ms')} |",
        f"| P95 inference latency (ms) | {metric('p95_inference_latency_ms')} |",
        "",
        "## Per-task success",
        "",
        "| Task | Success |",
        "|---|---:|",
    ]
    for task_id, rate in sorted(summary.get("success_by_task", {}).items()):
        lines.append(f"| `{task_id}` | {float(rate) * 100:.1f}% |")
    return "\n".join(lines) + "\n"


def write_evaluation_bundle(payload: Mapping[str, Any], output: str | Path) -> dict[str, Path]:
    """Write canonical JSON plus a flattened CSV and human summary."""
    json_path = Path(output)
    if json_path.name == "evaluation.json":
        csv_path = json_path.with_name("evaluation.csv")
        summary_path = json_path.with_name("summary.md")
    else:
        csv_path = json_path.with_suffix(".csv")
        summary_path = json_path.with_suffix(".summary.md")

    rows = [_episode_row(episode) for episode in payload.get("episodes", [])]
    atomic_write_json(json_path, payload)
    atomic_write_text(csv_path, _csv_text(rows))
    atomic_write_text(summary_path, _summary_markdown(payload))
    return {"json": json_path, "csv": csv_path, "summary": summary_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="File or directory to hash deterministically.")
    args = parser.parse_args(argv)
    print(sha256_path(args.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
