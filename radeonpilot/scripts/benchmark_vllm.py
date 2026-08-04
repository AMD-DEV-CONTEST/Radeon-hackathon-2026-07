#!/usr/bin/env python3
"""Measure real inference performance against the local ROCm endpoint.

Writes one evidence-validated JSON record per profile into benchmarks/results/.
No numbers are fabricated: every sample comes from an actual HTTP request and
VRAM/attestation are captured from rocm-smi and amd-smi on the host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

PROMPTS = [
    "Explain how continuous batching improves GPU utilization for LLM serving.",
    "What does prefix caching reuse across requests in vLLM?",
    "List two risks of setting gpu-memory-utilization too high on a single GPU.",
    "How do you verify a process is GPU-resident using amd-smi?",
    "Describe one benefit of chunked prefill for time-to-first-token.",
]
PROMPT_HASH = hashlib.sha256("".join(PROMPTS).encode("utf-8")).hexdigest()


def run_command(args: list[str], timeout: float = 10.0) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.stdout
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"error: {exc}"


def capture_vram() -> dict:
    raw = run_command(["rocm-smi", "--showmeminfo", "vram", "--json"])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:500]}


def capture_attestation(pid: int) -> dict:
    if not pid:
        return {"attested": False, "reason": "VLLM_PID not provided"}
    amd = run_command(["amd-smi", "process", "--pid", str(pid), "--json"])
    try:
        payload = json.loads(amd)
        listed = str(pid) in amd
        if listed:
            return {"attested": True, "pid": pid, "amd_smi_process": payload}
    except json.JSONDecodeError:
        payload = None
    # Container fallback: amd-smi reports host PIDs; attest via device occupancy.
    listing = run_command(["amd-smi", "process", "--json"])
    try:
        entries = json.loads(listing)
    except json.JSONDecodeError:
        return {"attested": False, "pid": pid, "raw": listing[:500]}
    occupants = []
    for gpu in (entries if isinstance(entries, list) else [entries]):
        for proc in (gpu or {}).get("process_list", []):
            vram = ((proc.get("process_info") or {}).get("memory_usage") or {}).get("vram_mem", {}).get("value", 0)
            if int(vram) > 512_000_000:
                occupants.append((proc.get("process_info", {}).get("pid"), vram))
    if occupants:
        return {
            "attested": True,
            "pid": pid,
            "note": "container PID namespace; matched via amd-smi device occupancy",
            "host_occupants": [{"pid": item[0], "vram_bytes": item[1]} for item in occupants],
        }
    return {"attested": False, "pid": pid, "reason": "no VRAM-resident process reported by amd-smi"}


def stream_first_token(base_url: str, model: str, prompt: str, max_tokens: int) -> tuple[float, float, int]:
    """Return (ttft_ms, total_ms, completion_tokens) for one streamed request."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    ttft_ms = None
    completion_tokens = 0
    content_chunks = 0
    with urllib.request.urlopen(request, timeout=180.0) as response:  # noqa: S310
        for line in response:
            text = line.decode("utf-8", errors="replace").strip()
            if not text.startswith("data:"):
                continue
            data = text[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content_chunks += 1
                if ttft_ms is None:
                    ttft_ms = round((time.perf_counter() - started) * 1000, 2)
            usage = chunk.get("usage") or {}
            if usage.get("completion_tokens"):
                completion_tokens = int(usage["completion_tokens"])
    total_ms = round((time.perf_counter() - started) * 1000, 2)
    if ttft_ms is None:
        ttft_ms = total_ms
    if completion_tokens == 0:
        completion_tokens = content_chunks
    return ttft_ms, total_ms, completion_tokens


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=["baseline", "optimized", "quantized"])
    parser.add_argument("--engine", default=os.environ.get("RADEONPILOT_ENGINE", "vllm"))
    parser.add_argument("--base-url", default=os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--model", default=os.environ.get("RADEONPILOT_MODEL", "qwen3-8b"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--model-ref", default=os.environ.get("MODEL_REF", "local"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    samples = []
    # Warm-up request excluded from measurement.
    try:
        stream_first_token(base_url, args.model, PROMPTS[0], args.max_tokens)
    except Exception as exc:  # noqa: BLE001
        print(f"endpoint warm-up failed: {exc}", file=sys.stderr)
        return 1

    vram_peak = 0
    for run in range(args.runs):
        for prompt in PROMPTS:
            ttft_ms, total_ms, tokens = stream_first_token(base_url, args.model, prompt, args.max_tokens)
            vram = capture_vram()
            samples.append({
                "run": run,
                "ttft_ms": ttft_ms,
                "total_ms": total_ms,
                "completion_tokens": tokens,
                "tokens_per_second": round(tokens / (total_ms / 1000.0), 2) if total_ms else 0.0,
            })
            vram_peak = max(vram_peak, _vram_used(vram))

    ttfts = sorted(s["ttft_ms"] for s in samples)
    tps = [s["tokens_per_second"] for s in samples]
    pid = int(os.environ.get("VLLM_PID", "0") or 0)
    record = {
        "profile": args.profile,
        "engine": args.engine,
        "model": args.model,
        "model_ref": args.model_ref,
        "endpoint_base_url": base_url,
        "prompt_hash": PROMPT_HASH,
        "prompt_count": len(PROMPTS),
        "runs": args.runs,
        "max_tokens": args.max_tokens,
        "aggregate": {
            "mean_ttft_ms": round(sum(ttfts) / len(ttfts), 2),
            "p95_ttft_ms": ttfts[int(0.95 * (len(ttfts) - 1))],
            "mean_tokens_per_second": round(sum(tps) / len(tps), 2),
        },
        "vram_peak_bytes": vram_peak,
        "attestation": capture_attestation(pid),
        "gpu": run_command(["rocm-smi", "--showproductname", "--json"])[:800],
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": platform.node(),
        "samples": samples,
    }
    out = args.out or f"benchmarks/results/{args.profile}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    print(f"wrote {out}: mean_ttft={record['aggregate']['mean_ttft_ms']}ms tps={record['aggregate']['mean_tokens_per_second']}")
    return 0


def _vram_used(payload: dict) -> int:
    """Best-effort extraction of used VRAM bytes from rocm-smi JSON."""
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if "used" in str(key).lower() and isinstance(value, (int, str)):
                    try:
                        return int(str(value).replace(",", ""))
                    except ValueError:
                        continue
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
        return 0

    return walk(payload)


if __name__ == "__main__":
    raise SystemExit(main())
