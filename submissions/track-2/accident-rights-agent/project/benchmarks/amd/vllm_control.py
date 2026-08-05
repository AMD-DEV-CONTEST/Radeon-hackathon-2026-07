#!/usr/bin/env python3
"""Safely switch the single local vLLM process between benchmark configs."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESS_PATTERN = "/opt/venv/bin/vllm serve /persistent/models/Qwen3-VL-8B-Instruct"
HEALTH_URL = "http://127.0.0.1:8000/v1/models"


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def vllm_pids() -> list[int]:
    completed = subprocess.run(
        ["pgrep", "-f", PROCESS_PATTERN],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(item) for item in completed.stdout.split() if item.isdigit()]


def stop_vllm(timeout: int = 120) -> dict[str, Any]:
    pids = vllm_pids()
    for pid in pids:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while vllm_pids() and time.monotonic() < deadline:
        time.sleep(1)
    remaining = vllm_pids()
    if remaining:
        raise RuntimeError(
            f"vLLM did not stop after {timeout}s; refusing SIGKILL: {remaining}"
        )
    return {"stopped_pids": pids, "remaining_pids": remaining}


def healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - false means not yet healthy
        return False


def start_vllm(
    config: dict[str, Any], *, label: str, results_dir: Path, timeout: int
) -> dict[str, Any]:
    if vllm_pids():
        raise RuntimeError("Refusing to start a second vLLM process")
    logs = results_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"vllm-{label}.log"
    launcher_path = logs / f"vllm-{label}-launcher.log"
    env = dict(os.environ)
    env.update(
        {
            "MODEL_ID": str(config["model"]),
            "SERVED_MODEL_NAME": str(config["served_model_name"]),
            "ENABLE_PREFIX_CACHING": "1"
            if config.get("enable_prefix_caching")
            else "0",
            "VLLM_MAX_MODEL_LEN": str(config["max_model_len"]),
            "VLLM_GPU_MEMORY_UTILIZATION": str(
                config["gpu_memory_utilization"]
            ),
            "VLLM_TEE_LOG": "0",
            "VLLM_LOG_PATH": str(log_path),
        }
    )
    batch_tokens = config.get("max_num_batched_tokens")
    if batch_tokens is None:
        env.pop("VLLM_MAX_NUM_BATCHED_TOKENS", None)
    else:
        env["VLLM_MAX_NUM_BATCHED_TOKENS"] = str(batch_tokens)
    with launcher_path.open("a", encoding="utf-8") as launcher:
        process = subprocess.Popen(  # noqa: S603 - fixed local script
            ["bash", "scripts/serve_vllm.sh"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=launcher,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"vLLM exited with {process.returncode}: {tail}")
        if healthy():
            return {
                "launcher_pid": process.pid,
                "vllm_pids": vllm_pids(),
                "log_path": str(log_path),
                "launcher_log_path": str(launcher_path),
                "healthy": True,
            }
        time.sleep(2)
    raise RuntimeError(f"vLLM did not become healthy after {timeout}s: {log_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "stop", "start", "switch"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--label", default="benchmark")
    parser.add_argument("--results-dir", type=Path, default=Path("benchmarks/results"))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--gpu-memory-utilization", type=float)
    parser.add_argument("--max-num-batched-tokens", type=int)
    parser.add_argument("--max-model-len", type=int)
    parser.add_argument("--enable-prefix-caching", choices=["0", "1"])
    args = parser.parse_args()
    if args.action == "status":
        print(json.dumps({"pids": vllm_pids(), "healthy": healthy()}))
        return 0 if healthy() else 2
    if args.action == "stop":
        print(json.dumps(stop_vllm(args.timeout)))
        return 0
    if not args.config:
        parser.error("--config is required for start and switch")
    config = load_config(args.config)
    if args.gpu_memory_utilization is not None:
        config["gpu_memory_utilization"] = args.gpu_memory_utilization
    if args.max_num_batched_tokens is not None:
        config["max_num_batched_tokens"] = args.max_num_batched_tokens
    if args.max_model_len is not None:
        config["max_model_len"] = args.max_model_len
    if args.enable_prefix_caching is not None:
        config["enable_prefix_caching"] = args.enable_prefix_caching == "1"
    stopped: dict[str, Any] | None = None
    if args.action == "switch":
        stopped = stop_vllm(args.timeout)
    result = start_vllm(
        config, label=args.label, results_dir=args.results_dir, timeout=args.timeout
    )
    result["stopped"] = stopped
    result["config"] = config
    runtime_path = args.results_dir / "runtime" / f"{args.label}.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
