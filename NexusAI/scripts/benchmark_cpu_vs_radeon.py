import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
BATCH_SIZE = 64
RUNS = 5

SAMPLES = [
    "Aria lives in Kochi and leads the NexusAI research team.",
    "Noah maintains the NexusAI backend and travels to Bengaluru.",
    "The Nexus Research Lab is located in Bengaluru.",
    "Maya advises the NexusAI project.",
    "Aurora is connected to NexusAI.",
] * 200


def benchmark(model, device_name):
    # Warm-up run, excluded from measurements
    model.encode(
        SAMPLES[:64],
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    times = []

    for i in range(RUNS):
        if device_name == "rocm":
            torch.cuda.synchronize()

        start = time.perf_counter()

        vectors = model.encode(
            SAMPLES,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        if device_name == "rocm":
            torch.cuda.synchronize()

        elapsed = time.perf_counter() - start
        times.append(elapsed)

        print(
            f"{device_name.upper()} run {i + 1}/{RUNS}: "
            f"{elapsed:.4f}s"
        )

    mean_time = statistics.mean(times)

    return {
        "device": device_name,
        "model": MODEL_NAME,
        "documents": len(SAMPLES),
        "batch_size": BATCH_SIZE,
        "runs": RUNS,
        "embedding_dimension": int(vectors.shape[1]),
        "mean_seconds": mean_time,
        "min_seconds": min(times),
        "max_seconds": max(times),
        "documents_per_second": len(SAMPLES) / mean_time,
    }


print("Loading CPU model...")
cpu_model = SentenceTransformer(MODEL_NAME, device="cpu")

print("\nBenchmarking CPU...")
cpu_results = benchmark(cpu_model, "cpu")

del cpu_model

print("\nLoading Radeon GPU model...")
gpu_model = SentenceTransformer(MODEL_NAME, device="cuda")

print("\nBenchmarking AMD Radeon GPU...")
gpu_results = benchmark(gpu_model, "rocm")

speedup = (
    gpu_results["documents_per_second"]
    / cpu_results["documents_per_second"]
)

results = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "benchmark_type": "same-model-cpu-vs-amd-radeon",
    "system": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "gpu": torch.cuda.get_device_name(0),
    },
    "configuration": {
        "model": MODEL_NAME,
        "documents": len(SAMPLES),
        "batch_size": BATCH_SIZE,
        "runs": RUNS,
    },
    "cpu": cpu_results,
    "amd_radeon_rocm": gpu_results,
    "gpu_speedup_vs_cpu": speedup,
}

output = Path(
    "benchmarks/cpu_vs_radeon_embedding_benchmark.json"
)

output.parent.mkdir(parents=True, exist_ok=True)

output.write_text(
    json.dumps(results, indent=2),
    encoding="utf-8",
)

print("\n" + "=" * 60)
print("NEXUSAI CPU VS AMD RADEON BENCHMARK")
print("=" * 60)

print(
    f"CPU throughput: "
    f"{cpu_results['documents_per_second']:.2f} docs/sec"
)

print(
    f"Radeon throughput: "
    f"{gpu_results['documents_per_second']:.2f} docs/sec"
)

print(
    f"GPU speedup: {speedup:.2f}x"
)

print(
    "\nResults saved to:",
    output,
)
