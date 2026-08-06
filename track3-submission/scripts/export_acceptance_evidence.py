#!/usr/bin/env python3
"""Export auditable acceptance evidence from existing local artifacts.

This script performs no training and runs no benchmark. It only parses and hashes
files already present in the repository. Outputs are deterministic for identical
inputs and are replaced deterministically for normal local use.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ITERATION_RE = re.compile(r"Learning iteration\s+(\d+)/(\d+)")
FIELD_PATTERNS = {
    "total_steps": re.compile(r"Total steps:\s*(\d+)"),
    "steps_per_second": re.compile(r"Steps per second:\s*(\d+(?:\.\d+)?)"),
    "mean_reward": re.compile(r"Mean reward:\s*(-?\d+(?:\.\d+)?)"),
    "goal_per_1k_steps": re.compile(r"Mean episode goal_per_1k_steps:\s*(-?\d+(?:\.\d+)?)"),
    "mean_dist_to_ball": re.compile(r"Mean episode mean_dist_to_ball:\s*(-?\d+(?:\.\d+)?)"),
    "mean_episode_goals_total": re.compile(r"Mean episode goals_total:\s*(-?\d+(?:\.\d+)?)"),
    "iteration_time_seconds": re.compile(r"Iteration time:\s*(\d+(?:\.\d+)?)s"),
    "elapsed": re.compile(r"Time elapsed:\s*(\d+):(\d+):(\d+)"),
}

# The acceptance rubric requests five component values. The aggregate training
# log has none of them, so these names are emitted explicitly as missing rather
# than reconstructed from configuration weights or aggregate reward.
REQUIRED_REWARD_COMPONENTS = (
    "approach_ball",
    "ball_control",
    "ball_progress",
    "ball_contact",
    "goal_scored",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_training_log(path: Path) -> list[dict[str, Any]]:
    text = ANSI_RE.sub("", path.read_text(encoding="utf-8", errors="replace"))
    matches = list(ITERATION_RE.finditer(text))
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        block = text[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        row: dict[str, Any] = {"iteration": int(match.group(1)), "configured_iterations": int(match.group(2))}
        for key, pattern in FIELD_PATTERNS.items():
            found = pattern.search(block)
            if not found:
                missing_key = "elapsed_seconds" if key == "elapsed" else key
                raise ValueError(
                    f"iteration {row['iteration']} is missing required field {missing_key}"
                )
            elif key == "elapsed":
                hours, minutes, seconds = map(int, found.groups())
                row["elapsed_seconds"] = hours * 3600 + minutes * 60 + seconds
            elif key == "total_steps":
                row[key] = int(found.group(1))
            else:
                row[key] = float(found.group(1))
        rows.append(row)
    if not rows:
        raise ValueError(f"no learning iterations found in {path}")
    iterations = [row["iteration"] for row in rows]
    if iterations != list(range(iterations[0], iterations[0] + len(iterations))):
        raise ValueError("training iterations must be unique and contiguous")
    configured = {row["configured_iterations"] for row in rows}
    if len(configured) != 1 or iterations[0] != 0 or iterations[-1] != configured.pop() - 1:
        raise ValueError("training log is incomplete or has inconsistent configured iterations")
    for field in ("total_steps", "elapsed_seconds"):
        values = [row[field] for row in rows]
        if any(current <= previous for previous, current in zip(values, values[1:])):
            raise ValueError(f"{field} must increase strictly across iterations")
    return rows


def parse_gpu_csv(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            clean = dict(raw)
            clean["train_log"] = ANSI_RE.sub("", clean.get("train_log", "")).strip()
            for key in ("gpu_util_pct", "vram_used_mb", "vram_total_mb", "temp_c", "power_w"):
                clean[key] = float(clean[key])
            iteration = ITERATION_RE.search(clean["train_log"])
            clean["training_iteration_label"] = int(iteration.group(1)) if iteration else None
            rows.append(clean)
    if not rows:
        raise ValueError(f"no GPU samples found in {path}")
    labeled = [row["training_iteration_label"] for row in rows if row["training_iteration_label"] is not None]
    summary = {
        "sample_count": len(rows),
        "first_timestamp": rows[0]["timestamp"],
        "last_timestamp": rows[-1]["timestamp"],
        "peak_gpu_util_pct": max(row["gpu_util_pct"] for row in rows),
        "peak_vram_used_mb": max(row["vram_used_mb"] for row in rows),
        "vram_total_mb_reported": max(row["vram_total_mb"] for row in rows),
        "labeled_iteration_min": min(labeled) if labeled else None,
        "labeled_iteration_max": max(labeled) if labeled else None,
    }
    return rows, summary


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / "acceptance"
    training_log = root / "archive/train_v8.log"
    gpu_csv = root / "track3-data/benchmark/gpu_samples.csv"
    manifest_path = root / "reports/model_manifest.json"
    for source in (training_log, gpu_csv, manifest_path):
        if not source.is_file():
            raise FileNotFoundError(source)

    curve = parse_training_log(training_log)
    gpu_rows, gpu_summary = parse_gpu_csv(gpu_csv)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    model_specs = (
        ("checkpoint_model_499", root / "track3-data/runs/hierarchical_soccer_chase_hl/model_499.pt", None),
        ("onnx_chase_v8", root / "models/chase_v8_policy.onnx", "onnx_chase_v8"),
        ("base_t1_walk", root / "models/pretrained/t1_walk.pt", "base_t1_walk"),
    )
    model_rows = []
    for name, path, manifest_key in model_specs:
        if not path.is_file():
            raise FileNotFoundError(path)
        claimed = manifest.get("models", {}).get(manifest_key, {}) if manifest_key else {}
        local_hash = sha256(path)
        claimed_hash = claimed.get("sha256")
        model_rows.append(
            {
                "name": name,
                "local_path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "local_sha256": local_hash,
                "manifest_sha256": claimed_hash,
                "manifest_hash_matches_local": claimed_hash == local_hash if claimed_hash else None,
                "provenance": "local bytes hashed by exporter",
            }
        )

    curve_fields = [
        "iteration", "configured_iterations", "total_steps", "steps_per_second",
        "mean_reward", "mean_dist_to_ball", "goal_per_1k_steps", "mean_episode_goals_total",
        "iteration_time_seconds", "elapsed_seconds",
    ]
    write_csv(out / "training/training_curve.csv", curve, curve_fields)
    write_csv(
        out / "performance/gpu_telemetry.csv",
        gpu_rows,
        ["timestamp", "gpu_util_pct", "vram_used_mb", "vram_total_mb", "temp_c", "power_w", "training_iteration_label", "train_log"],
    )
    write_csv(
        out / "training/model_hashes.csv",
        model_rows,
        ["name", "local_path", "size_bytes", "local_sha256", "manifest_sha256", "manifest_hash_matches_local", "provenance"],
    )

    final = curve[-1]
    training_summary = {
        "source": training_log.relative_to(root).as_posix(),
        "source_sha256": sha256(training_log),
        "iteration_count": len(curve),
        "iteration_min": min(row["iteration"] for row in curve),
        "iteration_max": max(row["iteration"] for row in curve),
        "final_total_steps": final["total_steps"],
        "duration_seconds": final.get("elapsed_seconds"),
        "final_steps_per_second": final["steps_per_second"],
        "mean_steps_per_second": round(sum(row["steps_per_second"] for row in curve) / len(curve), 3),
        "peak_steps_per_second": max(row["steps_per_second"] for row in curve),
        "final_mean_reward": final["mean_reward"],
        "final_mean_dist_to_ball": final["mean_dist_to_ball"],
        "final_goal_per_1k_steps": final["goal_per_1k_steps"],
        "final_mean_episode_goals_total": final["mean_episode_goals_total"],
        "required_reward_components": {
            name: {"status": "missing", "value": None, "reason": "not emitted by aggregate training log"}
            for name in REQUIRED_REWARD_COMPONENTS
        },
    }
    gpu_summary.update(
        {
            "source": gpu_csv.relative_to(root).as_posix(),
            "source_sha256": sha256(gpu_csv),
            "provenance_limit": "collector samples are labeled with training log text but cover only labeled iterations 60-499 and include post-training idle samples; they are not a stress test",
        }
    )
    summary = {
        "schema_version": 1,
        "evidence_kind": "historical artifact export; not a current acceptance rerun",
        "training": training_summary,
        "gpu_telemetry": gpu_summary,
        "models": model_rows,
        "manifest": {
            "source": manifest_path.relative_to(root).as_posix(),
            "source_sha256": sha256(manifest_path),
            "limitation": "remote paths and metadata are historical claims; only local hashes in model_hashes.csv were recomputed",
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    missing = ", ".join(REQUIRED_REWARD_COMPONENTS)
    report = f"""# Acceptance Evidence Export

This directory is a deterministic export of existing historical artifacts, **not a new training or acceptance run**.

## Training

- Source: `{training_summary['source']}` (SHA-256 recorded in `summary.json`)
- Parsed iterations: {training_summary['iteration_min']}–{training_summary['iteration_max']} ({training_summary['iteration_count']} rows)
- Final: {training_summary['final_total_steps']:,} steps, reward {training_summary['final_mean_reward']}, mean distance {training_summary['final_mean_dist_to_ball']} m, mean episode `goals_total` metric {training_summary['final_mean_episode_goals_total']}
- Throughput: final {training_summary['final_steps_per_second']:,.0f}, mean {training_summary['mean_steps_per_second']:,.3f}, peak {training_summary['peak_steps_per_second']:,.0f} steps/s
- Log-reported duration: {training_summary['duration_seconds']:,} seconds
- Curve: `training/training_curve.csv`

The five requested reward components are **missing**, because the log emits only aggregate reward: {missing}. Configuration terms or weights are not measurements and were not substituted.
The custom `Mean episode goals_total` value is preserved with its original mean-episode semantics; it is not an independently counted number of scored goals.

## GPU telemetry

- Source: `{gpu_summary['source']}` ({gpu_summary['sample_count']} samples)
- Observed peak utilization: {gpu_summary['peak_gpu_util_pct']:.1f}%
- Observed peak VRAM: {gpu_summary['peak_vram_used_mb']:.3f} MB of {gpu_summary['vram_total_mb_reported']:.3f} MB reported
- Labeled iteration range: {gpu_summary['labeled_iteration_min']}–{gpu_summary['labeled_iteration_max']}

The collector starts after training began and includes idle samples after iteration 499. These values are historical training-labeled telemetry, not full-window telemetry and **not a GPU stress-test result**.

## Models and provenance limits

`training/model_hashes.csv` contains SHA-256 values recomputed from local bytes. Manifest hashes are retained only for comparison. The manifest describes remote paths and historical metadata; this export does not independently verify those remote claims, checkpoint quality, evaluation performance, or checkpoint-to-ONNX lineage.
"""
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
