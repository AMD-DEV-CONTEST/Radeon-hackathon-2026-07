#!/usr/bin/env python3
"""Measure Radeon vLLM concurrency with one frozen Case Capsule request."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.memory.evaluation import evaluate_answer  # noqa: E402
from experiments.memory.experiment import (  # noqa: E402
    SYSTEM_PROMPT,
    TASK,
    _allowed_ids,
)
from experiments.memory.gpu import AmdGpuSampler  # noqa: E402
from experiments.memory.streaming import model_name, stream_chat  # noqa: E402


def _messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"task": TASK, "context": payload},
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def percentile(values: list[float], quantile: float) -> float | None:
    """Return an interpolated percentile without a NumPy dependency."""

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
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _metric_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": round(mean(values), 6) if values else None,
        "p50": round(median(values), 6) if values else None,
        "p95": round(percentile(values, 0.95) or 0.0, 6) if values else None,
        "min": round(min(values), 6) if values else None,
        "max": round(max(values), 6) if values else None,
    }


def summarize_level(
    *,
    concurrency: int,
    wall_seconds: float,
    runs: list[dict[str, Any]],
    gpu: dict[str, Any],
) -> dict[str, Any]:
    completed = [item for item in runs if item.get("success", True)]
    output_tokens = sum(int(item.get("output_tokens") or 0) for item in completed)
    input_tokens = sum(int(item.get("input_tokens") or 0) for item in completed)

    def floats(key: str) -> list[float]:
        return [float(item[key]) for item in completed if item.get(key) is not None]

    oom_count = sum(
        "out of memory" in str(item.get("error", "")).lower()
        or "oom" in str(item.get("error", "")).lower()
        for item in runs
    )

    return {
        "concurrency": concurrency,
        "request_count": len(runs),
        "completed_requests": len(completed),
        "failed_requests": len(runs) - len(completed),
        "success_rate": round(len(completed) / max(1, len(runs)), 6),
        "oom_count": oom_count,
        "wall_seconds": round(wall_seconds, 6),
        "input_tokens_total": input_tokens,
        "input_tokens_mean": round(input_tokens / max(1, len(completed)), 3),
        "output_tokens_total": output_tokens,
        "output_tokens_mean": round(output_tokens / max(1, len(completed)), 3),
        "aggregate_output_tokens_per_second": round(
            output_tokens / max(0.000001, wall_seconds), 6
        ),
        "ttft_seconds": _metric_summary(floats("ttft_seconds")),
        "tpot_seconds": _metric_summary(floats("tpot_seconds")),
        "total_latency_seconds": _metric_summary(
            floats("total_latency_seconds")
        ),
        "verifier_pass_rate": round(
            sum(bool(item["quality"]["verifier_pass"]) for item in completed)
            / max(1, len(completed)),
            6,
        ),
        "quality_score_mean": round(
            mean(float(item["quality"]["quality_score"]) for item in completed), 6
        ) if completed else 0.0,
        "gpu": gpu,
    }


def _run_level(
    payload: dict[str, Any],
    *,
    concurrency: int,
    request_count: int,
    max_tokens: int,
) -> dict[str, Any]:
    messages = _messages(payload)
    allowed = _allowed_ids(payload)
    barrier = threading.Barrier(concurrency)

    def measured_request(request_index: int) -> dict[str, Any]:
        barrier.wait(timeout=30)
        try:
            result = stream_chat(messages, max_tokens=max_tokens)
            quality = evaluate_answer(
                result.content,
                allowed_fact_ids=allowed[0],
                allowed_evidence_ids=allowed[1],
                allowed_law_ids=allowed[2],
            )
            return {
                "request_index": request_index,
                "success": True,
                **result.as_dict(),
                "quality": quality,
            }
        except Exception as exc:  # noqa: BLE001 - failures are benchmark data
            return {
                "request_index": request_index,
                "success": False,
                "error": repr(exc),
            }

    started = time.perf_counter()
    with AmdGpuSampler() as sampler:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            runs = list(executor.map(measured_request, range(request_count)))
    wall_seconds = time.perf_counter() - started
    return {
        "summary": summarize_level(
            concurrency=concurrency,
            wall_seconds=wall_seconds,
            runs=runs,
            gpu=sampler.summary(),
        ),
        "runs": runs,
    }


def _add_scaling(levels: list[dict[str, Any]]) -> None:
    baseline = float(
        levels[0]["summary"]["aggregate_output_tokens_per_second"]
    )
    for level in levels:
        summary = level["summary"]
        speedup = float(summary["aggregate_output_tokens_per_second"]) / max(
            0.000001, baseline
        )
        summary["throughput_speedup_vs_c1"] = round(speedup, 6)
        summary["scaling_efficiency"] = round(
            speedup / int(summary["concurrency"]), 6
        )


def _write_csv(path: Path, levels: list[dict[str, Any]]) -> None:
    fields = [
        "concurrency",
        "request_count",
        "completed_requests",
        "failed_requests",
        "success_rate",
        "oom_count",
        "wall_seconds",
        "input_tokens_mean",
        "output_tokens_mean",
        "ttft_p50_seconds",
        "ttft_p95_seconds",
        "tpot_p50_seconds",
        "tpot_p95_seconds",
        "latency_p50_seconds",
        "latency_p95_seconds",
        "aggregate_output_tokens_per_second",
        "throughput_speedup_vs_c1",
        "scaling_efficiency",
        "verifier_pass_rate",
        "quality_score_mean",
        "gpu_utilization_mean_pct",
        "gpu_utilization_peak_pct",
        "vram_used_peak_mb",
        "socket_power_mean_w",
        "socket_power_peak_w",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for level in levels:
            row = level["summary"]
            metrics = row["gpu"]["metrics"]
            writer.writerow(
                {
                    "concurrency": row["concurrency"],
                    "request_count": row["request_count"],
                    "completed_requests": row["completed_requests"],
                    "failed_requests": row["failed_requests"],
                    "success_rate": row["success_rate"],
                    "oom_count": row["oom_count"],
                    "wall_seconds": row["wall_seconds"],
                    "input_tokens_mean": row["input_tokens_mean"],
                    "output_tokens_mean": row["output_tokens_mean"],
                    "ttft_p50_seconds": row["ttft_seconds"]["p50"],
                    "ttft_p95_seconds": row["ttft_seconds"]["p95"],
                    "tpot_p50_seconds": row["tpot_seconds"]["p50"],
                    "tpot_p95_seconds": row["tpot_seconds"]["p95"],
                    "latency_p50_seconds": row["total_latency_seconds"]["p50"],
                    "latency_p95_seconds": row["total_latency_seconds"]["p95"],
                    "aggregate_output_tokens_per_second": row[
                        "aggregate_output_tokens_per_second"
                    ],
                    "throughput_speedup_vs_c1": row[
                        "throughput_speedup_vs_c1"
                    ],
                    "scaling_efficiency": row["scaling_efficiency"],
                    "verifier_pass_rate": row["verifier_pass_rate"],
                    "quality_score_mean": row["quality_score_mean"],
                    "gpu_utilization_mean_pct": metrics[
                        "gpu_utilization_pct"
                    ]["mean"],
                    "gpu_utilization_peak_pct": metrics[
                        "gpu_utilization_pct"
                    ]["peak"],
                    "vram_used_peak_mb": metrics["vram_used_mb"]["peak"],
                    "socket_power_mean_w": metrics["socket_power_w"]["mean"],
                    "socket_power_peak_w": metrics["socket_power_w"]["peak"],
                }
            )


def _render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# AMD Radeon 并发性能实验",
        "",
        (
            "所有数值来自同一 Case Capsule、同一模型和本次 Radeon 运行日志；"
            "每档使用相同请求数，Prefix Cache 在统一预热后开启。"
        ),
        "",
        f"- Model: `{payload['model']}`",
        f"- Source commit: `{payload['source_commit']}`",
        f"- Requests per level: {payload['requests_per_level']}",
        f"- Max output tokens: {payload['max_tokens']}",
        "",
        "| Concurrency | Completed | Success | TTFT p50/p95 | TPOT p50/p95 | Latency p50/p95 | Output tok/s | Speedup | Efficiency | OOM | Verifier | GPU mean/peak | VRAM peak |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for level in payload["levels"]:
        row = level["summary"]
        metrics = row["gpu"]["metrics"]
        lines.append(
            "| {concurrency} | {completed}/{requested} | {success:.1%} | {ttft50:.3f}/{ttft95:.3f}s | "
            "{tpot50:.4f}/{tpot95:.4f}s | {lat50:.3f}/{lat95:.3f}s | "
            "{throughput:.2f} | {speedup:.2f}x | {efficiency:.1%} | {oom} | "
            "{verifier:.1%} | {gpu_mean:.1f}/{gpu_peak:.0f}% | {vram:.0f} MB |".format(
                concurrency=row["concurrency"],
                completed=row["completed_requests"],
                requested=row["request_count"],
                success=row["success_rate"],
                ttft50=row["ttft_seconds"]["p50"],
                ttft95=row["ttft_seconds"]["p95"],
                tpot50=row["tpot_seconds"]["p50"],
                tpot95=row["tpot_seconds"]["p95"],
                lat50=row["total_latency_seconds"]["p50"],
                lat95=row["total_latency_seconds"]["p95"],
                throughput=row["aggregate_output_tokens_per_second"],
                speedup=row["throughput_speedup_vs_c1"],
                efficiency=row["scaling_efficiency"],
                oom=row["oom_count"],
                verifier=row["verifier_pass_rate"],
                gpu_mean=metrics["gpu_utilization_pct"]["mean"] or 0,
                gpu_peak=metrics["gpu_utilization_pct"]["peak"] or 0,
                vram=metrics["vram_used_mb"]["peak"] or 0,
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("experiments/results/memory/case_capsule_input.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/results/amd_concurrency"),
    )
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--requests-per-level", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--source-commit", default="unknown")
    args = parser.parse_args()
    if any(level < 1 for level in args.levels):
        parser.error("all concurrency levels must be positive")
    if args.requests_per_level < max(args.levels):
        parser.error("requests-per-level must be >= the highest concurrency")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected_model = model_name()
    warmup_runs = [
        stream_chat(_messages(payload), max_tokens=args.max_tokens).as_dict()
        for _ in range(args.warmup)
    ]
    started_at = datetime.now(timezone.utc)
    levels = [
        _run_level(
            payload,
            concurrency=level,
            request_count=args.requests_per_level,
            max_tokens=args.max_tokens,
        )
        for level in args.levels
    ]
    _add_scaling(levels)
    result = {
        "schema_version": 1,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": selected_model,
        "source_commit": args.source_commit,
        "input": str(args.input),
        "max_tokens": args.max_tokens,
        "requests_per_level": args.requests_per_level,
        "warmup_runs": warmup_runs,
        "levels": levels,
    }
    (args.output_dir / "amd_concurrency_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(args.output_dir / "amd_concurrency_results.csv", levels)
    (args.output_dir / "report.md").write_text(
        _render_report(result), encoding="utf-8"
    )
    print(json.dumps([item["summary"] for item in levels], ensure_ascii=False, indent=2))
    return 0 if all(
        item["summary"]["success_rate"] >= 0.95
        and item["summary"]["oom_count"] == 0
        and item["summary"]["verifier_pass_rate"] == 1.0
        for item in levels
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
