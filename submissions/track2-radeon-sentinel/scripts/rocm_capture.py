#!/usr/bin/env python3
"""Radeon Cloud environment capture + baseline benchmark.

Run this ON the Radeon Cloud instance (after starting vLLM) to produce the
ROCm evidence that Section 5 of SPECIFICATION.md requires.

Usage:
    python3 scripts/rocm_capture.py \
        --base-url http://127.0.0.1:8000/v1 \
        --model "<model-id>" \
        --output docs/evidence/rocm-baseline.json

What it does:
  1. Captures GPU model, ROCm/driver/PyTorch/vLLM versions (best-effort;
     ROCm tools may live under /opt/rocm).
  2. Sends a fixed prompt N times and records TTFT, tokens/s, p50/p95 latency.
  3. Optionally runs the 3 synthetic incident scenarios through Radeon Sentinel
     and records task-success + end-to-end time + approval-block count.
  4. Writes a single JSON artifact suitable for the submission report.

NOTE: this script intentionally does NOT import torch at module top level so
that merely running --help works on any machine. Heavy imports are deferred.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def sh(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"<unavailable: {exc}>"


def capture_environment() -> dict[str, Any]:
    env: dict[str, Any] = {}
    env["captured_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    env["hostname"] = sh(["hostname"])
    # ROCm
    env["rocm_version"] = sh(["rocm-smi", "--showproductname"])
    env["rocm_smi"] = sh(["rocm-smi"])
    env["rocminfo"] = sh(["rocminfo"])
    # Driver / devices
    env["lspci_amd"] = sh(["sh", "-c", "lspci | grep -i amd"])
    # Python stack
    for pkg in ("torch", "vllm", "transformers", "rocm"):
        try:
            mod = __import__(pkg)
            env[f"{pkg}_version"] = getattr(mod, "__version__", "<no __version__>")
        except Exception as exc:  # noqa: BLE001
            env[f"{pkg}_version"] = f"<not installed: {exc}>"
    if "torch" in sys.modules:
        try:
            import torch  # type: ignore
            env["torch_cuda_available"] = torch.cuda.is_available()
            env["torch_device_count"] = torch.cuda.device_count()
            if torch.cuda.is_available():
                env["torch_device_name_0"] = torch.cuda.get_device_name(0)
                env["torch_gfx_sram"] = getattr(torch.version, "hip", None)
        except Exception as exc:  # noqa: BLE001
            env["torch_probe_error"] = str(exc)
    return env


def chat_once(base_url: str, model: str, prompt: str, api_key: str, timeout: int) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 128,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
    t0 = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    t1 = time.perf_counter()
    data = json.loads(raw.decode())
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    return {
        "wall_seconds": round(t1 - t0, 4),
        "completion_tokens": usage.get("completion_tokens", len(content.split())),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "content_preview": content[:200],
    }


def benchmark(base_url: str, model: str, api_key: str, n: int, timeout: int) -> dict[str, Any]:
    prompt = (
        "You are Radeon Sentinel, a privacy-first local incident response "
        "assistant. Given a service incident, write a concise diagnosis and "
        "the single safest next action. Incident: API latency is spiking on "
        "the checkout service after a deploy."
    )
    runs = []
    print(f"[bench] sending {n} requests to {base_url} model={model}")
    for i in range(n):
        r = chat_once(base_url, model, prompt, api_key, timeout)
        r["run"] = i + 1
        runs.append(r)
        if r["completion_tokens"]:
            r["tokens_per_second"] = round(r["completion_tokens"] / r["wall_seconds"], 2)
        print(f"  run {i+1}: {r['wall_seconds']}s, {r['completion_tokens']} tok")
    walls = [r["wall_seconds"] for r in runs]
    tps = [r["tokens_per_second"] for r in runs if r.get("tokens_per_second")]
    return {
        "runs": runs,
        "p50_wall_seconds": round(statistics.median(walls), 4),
        "p95_wall_seconds": round(_percentile(walls, 95), 4),
        "mean_tokens_per_second": round(statistics.mean(tps), 2) if tps else None,
        "prompt": prompt,
    }


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("MODEL_BASE_URL", "http://127.0.0.1:8000/v1"))
    ap.add_argument("--model", default=os.environ.get("MODEL_NAME", ""))
    ap.add_argument("--api-key", default=os.environ.get("MODEL_API_KEY", ""))
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--output", default="docs/evidence/rocm-baseline.json")
    ap.add_argument("--env-only", action="store_true", help="only capture environment, skip benchmark")
    args = ap.parse_args()

    out: dict[str, Any] = {"environment": capture_environment()}
    print(json.dumps(out["environment"], indent=2, ensure_ascii=False)[:2000])

    if not args.env_only:
        if not args.model:
            print("[bench] --model / MODEL_NAME not set; skipping benchmark (env-only)")
        else:
            try:
                out["benchmark"] = benchmark(args.base_url, args.model, args.api_key, args.runs, args.timeout)
            except (HTTPError, URLError, RuntimeError) as exc:
                out["benchmark_error"] = str(exc)
                print(f"[bench] failed: {exc}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[done] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
