"""Shared request, statistics, and artifact helpers for AMD benchmarks."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any

from experiments.memory.evaluation import evaluate_answer
from experiments.memory.experiment import SYSTEM_PROMPT, TASK, _allowed_ids
from experiments.memory.streaming import stream_chat


def messages_for(
    payload: dict[str, Any], question: str = TASK
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"case_context": payload}, ensure_ascii=False, sort_keys=True
            ),
        },
        {"role": "user", "content": question},
    ]


def run_request(
    payload: dict[str, Any],
    *,
    max_tokens: int,
    question: str = TASK,
) -> dict[str, Any]:
    try:
        result = stream_chat(
            messages_for(payload, question), max_tokens=max_tokens
        )
        allowed = _allowed_ids(payload)
        quality = evaluate_answer(
            result.content,
            allowed_fact_ids=allowed[0],
            allowed_evidence_ids=allowed[1],
            allowed_law_ids=allowed[2],
        )
        return {
            "success": True,
            **result.as_dict(),
            "quality": quality,
        }
    except Exception as exc:  # noqa: BLE001 - failures are benchmark results
        return {"success": False, "error": repr(exc)}


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )


def metric(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": round(mean(values), 6) if values else None,
        "p50": round(median(values), 6) if values else None,
        "p95": round(percentile(values, 0.95) or 0.0, 6)
        if values
        else None,
        "min": round(min(values), 6) if values else None,
        "max": round(max(values), 6) if values else None,
    }


def summarize_runs(
    runs: list[dict[str, Any]], wall_seconds: float
) -> dict[str, Any]:
    completed = [item for item in runs if item.get("success")]

    def values(key: str) -> list[float]:
        return [
            float(item[key])
            for item in completed
            if item.get(key) is not None
        ]

    output_tokens = sum(int(item.get("output_tokens") or 0) for item in completed)
    input_tokens = sum(int(item.get("input_tokens") or 0) for item in completed)
    errors = [str(item.get("error", "")) for item in runs if not item.get("success")]
    oom_count = sum(
        "out of memory" in error.lower() or "oom" in error.lower()
        for error in errors
    )
    qualities = [item["quality"] for item in completed if item.get("quality")]
    return {
        "request_count": len(runs),
        "completed_requests": len(completed),
        "failed_requests": len(runs) - len(completed),
        "success_rate": round(len(completed) / max(1, len(runs)), 6),
        "oom_count": oom_count,
        "wall_seconds": round(wall_seconds, 6),
        "input_tokens_mean": round(input_tokens / max(1, len(completed)), 3),
        "output_tokens_mean": round(output_tokens / max(1, len(completed)), 3),
        "aggregate_output_tokens_per_second": round(
            output_tokens / max(0.000001, wall_seconds), 6
        ),
        "ttft_seconds": metric(values("ttft_seconds")),
        "tpot_seconds": metric(values("tpot_seconds")),
        "total_latency_seconds": metric(values("total_latency_seconds")),
        "verifier_pass_rate": round(
            sum(bool(item.get("verifier_pass")) for item in qualities)
            / max(1, len(qualities)),
            6,
        ),
        "quality_score_mean": round(
            mean(float(item.get("quality_score", 0.0)) for item in qualities), 6
        )
        if qualities
        else 0.0,
        "errors": errors,
    }


def write_gpu_csv(
    path: Path,
    samples: list[dict[str, float | int]],
    *,
    label: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "label",
        "timestamp_unix",
        "gpu_utilization_pct",
        "vram_used_mb",
        "socket_power_w",
        "edge_temperature_c",
        "hotspot_temperature_c",
        "vram_temperature_c",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for sample in samples:
            writer.writerow({"label": label, **sample})
