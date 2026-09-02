from __future__ import annotations

import random

from autotuner.models import BenchmarkResult, Candidate


def mock_benchmark(candidate: Candidate) -> BenchmarkResult:
    score = 25.0
    score *= {
        "auto": 1.0,
        "ROCM_ATTN": 1.08,
        "TRITON_ATTN": 1.13,
        "ROCM_AITER_FA": 1.17,
        "ROCM_AITER_UNIFIED_ATTN": 1.2,
    }.get(candidate.attention_backend, 0.98)
    if candidate.kv_cache_dtype == "fp8":
        score *= 1.11
    score *= {
        4: 0.86,
        8: 1.0,
        16: 1.15,
        32: 1.2,
    }.get(candidate.max_num_seqs, 0.9)
    score *= 1.0 + (candidate.gpu_memory_utilization - 0.82) * 0.7
    if candidate.speculative_model:
        score *= {
            2: 1.12,
            4: 1.27,
            6: 1.2,
        }.get(candidate.num_speculative_tokens, 1.0)
    if candidate.quantization in {"awq", "gptq"}:
        score *= 1.18
    noise = random.Random(candidate.key()).uniform(0.985, 1.015)
    score *= noise
    error_rate = 0.0
    if (
        candidate.attention_backend == "auto"
        and candidate.kv_cache_dtype == "fp8"
    ):
        error_rate = 0.08
    if (
        candidate.gpu_memory_utilization >= 0.95
        and candidate.max_num_seqs >= 32
    ):
        error_rate = 0.08
    quality = 0.99 if candidate.kv_cache_dtype == "fp8" else 1.0
    output_tokens = 1024
    duration = output_tokens / score
    latency_p95 = 1250.0 * (25.0 / score)
    return BenchmarkResult(
        output_tokens=output_tokens,
        duration_seconds=duration,
        tokens_per_second=score,
        latency_p50_ms=latency_p95 * 0.72,
        latency_p95_ms=latency_p95,
        error_rate=error_rate,
        quality_score=quality,
        peak_vram_mb=18400.0
        + candidate.gpu_memory_utilization * 2800.0,
        responses=[
            "AMD ROCm benchmark response from the simulated local endpoint."
        ],
    )
