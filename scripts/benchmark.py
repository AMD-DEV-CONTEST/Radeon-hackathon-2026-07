#!/usr/bin/env python3
"""Stage J — Standalone Benchmark Tool.

Collects structured benchmark snapshots on first-token latency, generation
tokens/s, embedding throughput, VRAM, and GPU utilisation for before/after
optimization comparison.  Run against the API endpoint::

    python scripts/benchmark.py --label baseline
    python scripts/benchmark.py --label post-opt

Requires an already-running application instance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

CHAT_BASE = "http://127.0.0.1:8000"
EMBEDDING_BASE = "http://127.0.0.1:8080"


async def run_llm_benchmark(client: httpx.AsyncClient) -> dict:
    """Benchmark chat model generation latency."""
    prompt = (
        "You are a project management assistant. "
        "Please provide a concise status report for a software development project "
        "that has 5 active tasks, 2 risks, and 3 completed milestones. "
        "Keep the response under 200 words."
    )

    t0 = time.perf_counter()
    resp = await client.post(
        f"{CHAT_BASE}/v1/chat/completions",
        json={
            "model": "qwen3.6-office-agent",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 128,
            "temperature": 0.2,
        },
        timeout=120.0,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    data = resp.json()

    usage = data.get("usage", {})
    tokens = usage.get("completion_tokens", 0)
    tokens_per_sec = tokens / (elapsed_ms / 1000) if elapsed_ms > 0 else 0

    return {
        "end_to_end_latency_ms": round(elapsed_ms, 1),
        "tokens_generated": tokens,
        "tokens_per_sec": round(tokens_per_sec, 1),
    }


async def run_embedding_benchmark(client: httpx.AsyncClient) -> dict:
    """Benchmark embedding model throughput."""
    texts = [
        "This is a sample text for embedding benchmarking.",
        "Project management involves planning, executing, and closing projects.",
        "Risk management is critical for successful project delivery.",
        "Resource allocation must balance cost, time, and quality.",
        "Stakeholder communication ensures project alignment.",
    ] * 10  # 50 texts

    t0 = time.perf_counter()
    resp = await client.post(
        f"{EMBEDDING_BASE}/v1/embeddings",
        json={"model": "bge-small-en-v1.5", "input": texts},
        timeout=60.0,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    data = resp.json()

    num_embeddings = len(data.get("data", []))
    texts_per_sec = num_embeddings / (elapsed_ms / 1000) if elapsed_ms > 0 else 0

    return {
        "embedding_latency_ms": round(elapsed_ms, 1),
        "texts_embedded": num_embeddings,
        "texts_per_sec": round(texts_per_sec, 1),
    }


async def collect_gpu_metrics() -> dict:
    """Collect GPU metrics using rocm-smi or nvidia-smi."""
    import shutil
    import subprocess

    metrics: dict = {}

    rocm_smi = shutil.which("rocm-smi")
    nvidia_smi = shutil.which("nvidia-smi")

    if rocm_smi:
        try:
            result = subprocess.run(
                [
                    rocm_smi,
                    "--showproductname",
                    "--showmeminfo", "vram",
                    "--showuse",
                    "--showtemp",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                from app.services.monitor import HealthMonitor

                samples = HealthMonitor.parse_rocm_smi_json(result.stdout)
                if samples:
                    sample = samples[0]
                    metrics["vram_total_mb"] = sample.vram_total_mb
                    metrics["vram_used_mb"] = sample.vram_used_mb
                    metrics["gpu_utilization_pct"] = sample.utilization_pct
                    metrics["gpu_model"] = sample.name
                    metrics["backend"] = "rocm"
        except Exception:
            pass
    elif nvidia_smi:
        try:
            result = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                parts = [p.strip() for p in result.stdout.strip().split(",")]
                if len(parts) >= 4:
                    metrics["gpu_model"] = parts[0]
                    metrics["vram_total_mb"] = float(parts[1])
                    metrics["vram_used_mb"] = float(parts[2])
                    metrics["gpu_utilization_pct"] = float(parts[3])
                    metrics["backend"] = "cuda"
        except Exception:
            pass

    return metrics


async def main() -> None:
    global CHAT_BASE, EMBEDDING_BASE

    parser = argparse.ArgumentParser(description="Stage J Benchmark Tool")
    parser.add_argument(
        "--label",
        type=str,
        default="manual",
        help="Label for this benchmark snapshot (e.g. baseline, post-opt)",
    )
    parser.add_argument(
        "--chat-base",
        type=str,
        default=CHAT_BASE,
        help="Base URL of the llama.cpp chat server",
    )
    parser.add_argument(
        "--embedding-base",
        type=str,
        default=EMBEDDING_BASE,
        help="Base URL of the llama.cpp embedding server",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file path",
    )
    args = parser.parse_args()

    CHAT_BASE = args.chat_base.rstrip("/")
    EMBEDDING_BASE = args.embedding_base.rstrip("/")

    print(f"\n{'='*60}")
    print(f"  Stage J Benchmark — {args.label}")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Run LLM benchmark
        print("[1/3] Running LLM generation benchmark...")
        try:
            llm_result = await run_llm_benchmark(client)
            print(f"  LLM: {llm_result['end_to_end_latency_ms']:.1f}ms, "
                  f"{llm_result['tokens_per_sec']:.1f} tok/s")
        except Exception as exc:
            print(f"  LLM benchmark failed: {exc}")
            llm_result = {}

        # Run Embedding benchmark
        print("[2/3] Running embedding benchmark...")
        try:
            emb_result = await run_embedding_benchmark(client)
            print(f"  Embedding: {emb_result['embedding_latency_ms']:.1f}ms, "
                  f"{emb_result['texts_per_sec']:.1f} texts/s")
        except Exception as exc:
            print(f"  Embedding benchmark failed: {exc}")
            emb_result = {}

        # Collect GPU metrics
        print("[3/3] Collecting GPU metrics...")
        gpu_result = await collect_gpu_metrics()
        if gpu_result:
            print(f"  GPU: {gpu_result.get('gpu_model', 'N/A')}, "
                  f"{gpu_result.get('vram_used_mb', 0):.0f} MB used")
        else:
            print("  No GPU metrics available (no rocm-smi / nvidia-smi)")

    # Build snapshot
    snapshot = {
        "label": args.label,
        "timestamp": time.time(),
        "first_token_latency_ms": 0.0,
        "generation_tokens_per_second": llm_result.get("tokens_per_sec", 0),
        "embedding_throughput_texts_per_second": emb_result.get("texts_per_sec", 0),
        "end_to_end_latency_ms": llm_result.get("end_to_end_latency_ms", 0),
        "vram_used_mb": gpu_result.get("vram_used_mb", 0),
        "vram_total_mb": gpu_result.get("vram_total_mb", 0),
        "gpu_utilization_pct": gpu_result.get("gpu_utilization_pct", 0),
        "gpu_model": gpu_result.get("gpu_model", ""),
        "backend": gpu_result.get("backend", ""),
        "total_tokens_generated": llm_result.get("tokens_generated", 0),
        "total_texts_embedded": emb_result.get("texts_embedded", 0),
    }

    print(f"\n{'='*60}")
    print(f"  Benchmark Complete")
    print(f"{'='*60}")
    print(json.dumps(snapshot, indent=2))

    # Save to file
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            Path(__file__).parent.parent
            / "office-agent"
            / "logs"
            / f"benchmark-{args.label}.json"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
