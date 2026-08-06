#!/usr/bin/env python3
"""
ROCm / Radeon performance benchmark for RadeonAgents.

Measures:
- Device detection
- VRAM usage
- Generation latency
- Tokens per second

This script is intentionally simple and reproducible so judges can
run it on real AMD hardware and obtain concrete numbers.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch
from src.core.llm import LLMEngine


def print_header():
    print("=" * 70)
    print("RadeonAgents – ROCm / AMD Radeon Inference Benchmark")
    print("=" * 70)


def detect_environment():
    print("\n[1] Environment Detection")
    print(f"   PyTorch version : {torch.__version__}")
    print(f"   CUDA available  : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"   Device name     : {torch.cuda.get_device_name(0)}")
        print(f"   Device count    : {torch.cuda.device_count()}")
        # ROCm often reports a version string via torch.version.hip or cuda
        hip = getattr(torch.version, "hip", None)
        cuda = torch.version.cuda
        print(f"   HIP version     : {hip}")
        print(f"   CUDA/ROCm tag   : {cuda}")
    else:
        print("   WARNING: No GPU detected – benchmark will run on CPU (very slow)")


def run_benchmark(model_name: str = "microsoft/Phi-3-mini-4k-instruct", quantize: str = "4bit"):
    print(f"\n[2] Loading model: {model_name} (quantize={quantize})")
    t0 = time.time()
    engine = LLMEngine(model_name=model_name, quantize=quantize, device="auto")
    load_time = time.time() - t0
    print(f"   Load time: {load_time:.1f}s")
    print(f"   Stats    : {engine.get_stats()}")

    prompt = [
        {
            "role": "user",
            "content": (
                "Explain the concept of hierarchical task planning for AI agents "
                "in approximately 150 words. Include one concrete example."
            ),
        }
    ]

    # Warm-up
    print("\n[3] Warm-up generation...")
    _ = engine.generate(prompt, max_new_tokens=32)

    # Measured run
    print("\n[4] Measured generation (max_new_tokens=256)...")
    torch.cuda.synchronize() if torch.cuda.is_available() else None
    start = time.perf_counter()
    output = engine.generate(prompt, max_new_tokens=256, temperature=0.3)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    # Token count (approximate via tokenizer)
    num_tokens = len(engine.tokenizer.encode(output))
    tokens_per_sec = num_tokens / elapsed if elapsed > 0 else 0.0

    print("\n[5] Results")
    print(f"   Generated tokens : {num_tokens}")
    print(f"   Wall time        : {elapsed:.3f} s")
    print(f"   Throughput       : {tokens_per_sec:.1f} tokens/s")
    print(f"   Final stats      : {engine.get_stats()}")
    print("\n   Sample output (first 300 chars):")
    print("   " + output[:300].replace("\n", "\n   ") + "...")

    print("\n" + "=" * 70)
    print("Benchmark complete. Higher tokens/s and lower VRAM = better ROCm optimization.")
    print("=" * 70)

    return {
        "tokens": num_tokens,
        "seconds": elapsed,
        "tokens_per_sec": tokens_per_sec,
        "stats": engine.get_stats(),
    }


if __name__ == "__main__":
    print_header()
    detect_environment()
    run_benchmark()
