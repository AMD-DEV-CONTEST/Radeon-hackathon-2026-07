#!/usr/bin/env python3
"""Run the 30-minute AMD soak test with live service/checkpoint checks."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.amd.common import run_request, summarize_runs, write_gpu_csv  # noqa: E402
from experiments.memory.gpu import AmdGpuSampler  # noqa: E402


def http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status
    except Exception:  # noqa: BLE001 - recorded as failed health check
        return None


def vllm_pids() -> list[int]:
    completed = subprocess.run(
        ["pgrep", "-f", "/opt/venv/bin/vllm serve"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(value) for value in completed.stdout.split() if value.isdigit()]


def checkpoint_status(path: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "quick_check": None,
    }
    if not path.exists():
        return result
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result["quick_check"] = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001 - diagnostic evidence
        result["quick_check"] = repr(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("/persistent/accident-rights-agent-current/data/checkpoints/orchestrator.sqlite3"),
    )
    parser.add_argument("--vllm-log", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    initial_pids = vllm_pids()
    before: dict[str, Any] = {
        "vllm_http": http_status("http://127.0.0.1:8000/v1/models"),
        "ui_http": http_status("http://127.0.0.1:7860/"),
        "vllm_pids": initial_pids,
        "checkpoint": checkpoint_status(args.checkpoint),
    }
    runs: list[dict[str, object]] = []
    last_progress = started
    with AmdGpuSampler(interval_seconds=1.0) as sampler:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            while time.monotonic() - started < args.duration:
                batch = list(
                    executor.map(
                        lambda _index: run_request(
                            payload, max_tokens=args.max_tokens
                        ),
                        range(args.concurrency),
                    )
                )
                runs.extend(batch)
                now = time.monotonic()
                if now - last_progress >= 60:
                    completed = sum(bool(item.get("success")) for item in runs)
                    print(
                        json.dumps(
                            {
                                "elapsed_seconds": round(now - started),
                                "requests": len(runs),
                                "completed": completed,
                            }
                        ),
                        flush=True,
                    )
                    last_progress = now
    wall_seconds = time.monotonic() - started
    after: dict[str, Any] = {
        "vllm_http": http_status("http://127.0.0.1:8000/v1/models"),
        "ui_http": http_status("http://127.0.0.1:7860/"),
        "vllm_pids": vllm_pids(),
        "checkpoint": checkpoint_status(args.checkpoint),
    }
    summary = summarize_runs(runs, wall_seconds)
    summary["gpu"] = sampler.summary()
    log_oom_count = 0
    service_exit_evidence = False
    if args.vllm_log and args.vllm_log.exists():
        log_text = args.vllm_log.read_text(encoding="utf-8", errors="replace")
        log_oom_count = log_text.lower().count("out of memory")
        service_exit_evidence = "engine core proc" in log_text.lower() and "died" in log_text.lower()
    stable_pid = bool(initial_pids) and initial_pids == after["vllm_pids"]
    checkpoint_ok = before["checkpoint"]["quick_check"] == "ok" and after[
        "checkpoint"
    ]["quick_check"] == "ok"
    passed = (
        wall_seconds >= args.duration
        and summary["success_rate"] >= 0.95
        and summary["oom_count"] == 0
        and log_oom_count == 0
        and stable_pid
        and not service_exit_evidence
        and after["vllm_http"] == 200
        and after["ui_http"] == 200
        and checkpoint_ok
    )
    result = {
        "schema_version": 1,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_duration_seconds": args.duration,
        "actual_duration_seconds": round(wall_seconds, 3),
        "concurrency": args.concurrency,
        "before": before,
        "after": after,
        "stable_vllm_pid": stable_pid,
        "checkpoint_ok": checkpoint_ok,
        "vllm_log_oom_count": log_oom_count,
        "service_exit_evidence": service_exit_evidence,
        "summary": summary,
        "passed": passed,
        "runs": runs,
    }
    (args.output_dir / "stability_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    gpu = summary["gpu"]["metrics"]
    markdown = "\n".join(
        [
            "# AMD 30 分钟稳定性报告",
            "",
            f"- 结论：{'通过' if passed else '未通过'}",
            f"- 连续运行：{wall_seconds / 60:.2f} 分钟",
            f"- 请求：{summary['completed_requests']}/{summary['request_count']} 完成，成功率 {summary['success_rate']:.1%}",
            f"- OOM：请求 {summary['oom_count']}，vLLM 日志 {log_oom_count}",
            f"- vLLM PID 全程稳定：{stable_pid}",
            f"- UI/API：{after['ui_http']}/{after['vllm_http']}",
            f"- SQLite checkpoint quick_check：{after['checkpoint']['quick_check']}",
            f"- GPU 利用率均值/峰值：{gpu['gpu_utilization_pct']['mean']}/{gpu['gpu_utilization_pct']['peak']}%",
            f"- VRAM 峰值：{gpu['vram_used_mb']['peak']} MB",
            f"- 温度峰值（edge/hotspot/VRAM）：{gpu['edge_temperature_c']['peak']}/{gpu['hotspot_temperature_c']['peak']}/{gpu['vram_temperature_c']['peak']} °C",
            f"- 功耗均值/峰值：{gpu['socket_power_w']['mean']}/{gpu['socket_power_w']['peak']} W",
            "",
        ]
    )
    (args.output_dir / "stability_report.md").write_text(markdown, encoding="utf-8")
    write_gpu_csv(
        args.output_dir / "gpu_metrics.csv", sampler.samples, label="stability"
    )
    print(json.dumps({"passed": passed, "summary": summary}, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
