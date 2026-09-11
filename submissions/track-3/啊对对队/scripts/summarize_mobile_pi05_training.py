#!/usr/bin/env python3
"""Create an auditable numerical summary from a LeRobot PI0.5 training log."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any


TRAINING_RECORD = re.compile(
    r"loss:(?P<loss>[-+0-9.eE]+)\s+grdn:(?P<gradient_norm>[-+0-9.eE]+)\s+"
    r"lr:(?P<learning_rate>[-+0-9.eE]+)"
)
AUXILIARY_METRICS = (
    "mode_cross_entropy",
    "mode_accuracy",
    "mode_margin",
    "mode_cross_entropy_weight",
    "mode_cross_entropy_time",
    "mode_head_cross_entropy",
    "mode_head_accuracy",
    "mode_head_margin",
    "mode_head_cross_entropy_weight",
    "stage_selected_weight_mean",
    "stage_unweighted_loss",
    "stage_weighted_loss",
    "mode_flow_loss_population_normalizer",
    "mode_flow_selected_weight_mean",
    "mode_flow_input_loss",
    "mode_flow_weighted_loss",
    "flow_loss_unweighted",
    "flow_loss",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-steps", type=int, required=True)
    parser.add_argument("--starting-step", type=int, default=0)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--adapter", type=Path)
    args = parser.parse_args()

    payload = summarize_training_log(
        args.log,
        expected_steps=args.expected_steps,
        starting_step=args.starting_step,
        checkpoint=args.checkpoint,
        adapter=args.adapter,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "records"}, indent=2))
    return 0 if payload["status"] == "completed" else 2


def summarize_training_log(
    path: Path,
    *,
    expected_steps: int,
    starting_step: int = 0,
    checkpoint: Path | None = None,
    adapter: Path | None = None,
) -> dict[str, Any]:
    if expected_steps <= 0:
        raise ValueError("expected_steps must be positive")
    if starting_step < 0:
        raise ValueError("starting_step cannot be negative")
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    records = []
    for match in TRAINING_RECORD.finditer(text):
        line_end = text.find("\n", match.end())
        record_text = text[match.start() : line_end if line_end >= 0 else len(text)]
        record = {
            "step": starting_step + len(records) + 1,
            "loss": float(match.group("loss")),
            "gradient_norm": float(match.group("gradient_norm")),
            "learning_rate": float(match.group("learning_rate")),
        }
        for name in AUXILIARY_METRICS:
            auxiliary = re.search(rf"(?:^|\s){name}:(?P<value>[-+0-9.eE]+)", record_text)
            if auxiliary is not None:
                record[name] = float(auxiliary.group("value"))
        records.append(record)
    values = [record["loss"] for record in records]
    gradients = [record["gradient_norm"] for record in records]
    auxiliary_metrics = {
        name: _metric_summary(
            [float(record[name]) for record in records if name in record]
        )
        for name in AUXILIARY_METRICS
    }
    all_finite = all(math.isfinite(value) for value in (*values, *gradients))
    completed_marker = "End of training" in text
    checkpoint_exists = checkpoint is None or checkpoint.is_dir()
    adapter_exists = adapter is None or adapter.is_file()
    status = (
        "completed"
        if len(records) == expected_steps
        and completed_marker
        and checkpoint_exists
        and adapter_exists
        else "in_progress_or_failed"
    )
    return {
        "schema_version": 1,
        "protocol": "pi05-training-log-summary-v1",
        "status": status,
        "log": str(path.resolve()),
        "log_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_steps": expected_steps,
        "observed_steps": len(records),
        "starting_step": starting_step,
        "ending_step": starting_step + len(records),
        "completed_marker": completed_marker,
        "checkpoint": str(checkpoint.resolve()) if checkpoint is not None else None,
        "checkpoint_exists": checkpoint_exists,
        "adapter": str(adapter.resolve()) if adapter is not None else None,
        "adapter_exists": adapter_exists,
        "adapter_sha256": _sha256_file(adapter) if adapter is not None and adapter_exists else None,
        "metrics": {
            "all_loss_and_gradient_values_finite": all_finite,
            "loss_min": min(values) if values else None,
            "loss_max": max(values) if values else None,
            "loss_median": statistics.median(values) if values else None,
            "gradient_norm_min": min(gradients) if gradients else None,
            "gradient_norm_max": max(gradients) if gradients else None,
            "gradient_norm_median": statistics.median(gradients) if gradients else None,
            "loss_outliers": _robust_outliers(
                records, "loss", scale_multiplier=20.0
            ),
            "gradient_norm_outliers": _robust_outliers(
                records, "gradient_norm", scale_multiplier=50.0
            ),
            "auxiliary": auxiliary_metrics,
            "blocks": _blocks(records, size=100),
        },
        "records": records,
        "claim_boundary": "Offline numerical optimization evidence only; robot capability requires closed-loop evaluation.",
    }


def _blocks(records: list[dict[str, float]], *, size: int) -> list[dict[str, float | int]]:
    result = []
    for start in range(0, len(records), size):
        block = records[start : start + size]
        losses = [record["loss"] for record in block]
        gradients = [record["gradient_norm"] for record in block]
        summary = {
            "start_step": int(block[0]["step"]),
            "end_step": int(block[-1]["step"]),
            "loss_mean": statistics.fmean(losses),
            "loss_median": statistics.median(losses),
            "gradient_norm_mean": statistics.fmean(gradients),
            "gradient_norm_median": statistics.median(gradients),
        }
        for name in AUXILIARY_METRICS:
            values = [float(record[name]) for record in block if name in record]
            if values:
                summary[f"{name}_mean"] = statistics.fmean(values)
        result.append(summary)
    return result


def _metric_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "records": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "last": values[-1] if values else None,
    }


def _robust_outliers(
    records: list[dict[str, float]],
    field: str,
    *,
    mad_multiplier: float = 20.0,
    scale_multiplier: float = 20.0,
    maximum_warmup_records: int = 1000,
) -> dict[str, Any]:
    """Report strong post-warmup spikes without declaring capability failure."""

    warmup_records = min(maximum_warmup_records, len(records) // 4)
    analyzed_records = records[warmup_records:]
    values = [float(record[field]) for record in analyzed_records]
    if not values:
        return {
            "warmup_records_excluded": warmup_records,
            "threshold": None,
            "count": 0,
            "records": [],
        }
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    robust_sigma = 1.4826 * mad
    threshold = max(
        median * scale_multiplier,
        median + mad_multiplier * robust_sigma,
        1e-12,
    )
    outliers = [
        {"step": int(record["step"]), "value": float(record[field])}
        for record in analyzed_records
        if float(record[field]) >= threshold
    ]
    return {
        "warmup_records_excluded": warmup_records,
        "median": median,
        "mad": mad,
        "threshold": threshold,
        "count": len(outliers),
        "records": outliers[:20],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
