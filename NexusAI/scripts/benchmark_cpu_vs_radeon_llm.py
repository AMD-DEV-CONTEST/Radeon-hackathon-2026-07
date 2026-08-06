import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
RUNS = 5
MAX_NEW_TOKENS = 100

MESSAGES = [
    {
        "role": "system",
        "content": "You are NexusAI, a local agentic AI assistant."
    },
    {
        "role": "user",
        "content": (
            "Explain briefly how an intelligent AI agent can reason, plan, "
            "use tools, and execute a task."
        )
    }
]


def benchmark(device):
    print(f"\nLoading model on {device.upper()}...")

    tokenizer = AutoTokenizer.from_pretrained(MODEL)

    dtype = torch.float16 if device == "cuda" else torch.float32

    model = AutoModelForCausalLM.from_pretrained(
        MODEL,
        torch_dtype=dtype,
    ).to(device)

    model.eval()

    text = tokenizer.apply_chat_template(
        MESSAGES,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = tokenizer(
        text,
        return_tensors="pt"
    ).to(device)

    # Warm-up run
    print(f"Warming up {device.upper()}...")

    with torch.inference_mode():
        model.generate(
            **inputs,
            max_new_tokens=20,
            do_sample=False
        )

    if device == "cuda":
        torch.cuda.synchronize()

    times = []
    token_counts = []

    for run in range(RUNS):
        if device == "cuda":
            torch.cuda.synchronize()

        start = time.perf_counter()

        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False
            )

        if device == "cuda":
            torch.cuda.synchronize()

        elapsed = time.perf_counter() - start

        generated_tokens = (
            outputs.shape[1] - inputs["input_ids"].shape[1]
        )

        times.append(elapsed)
        token_counts.append(generated_tokens)

        tokens_per_second = generated_tokens / elapsed

        print(
            f"{device.upper()} run {run + 1}/{RUNS}: "
            f"{elapsed:.4f}s | "
            f"{generated_tokens} tokens | "
            f"{tokens_per_second:.2f} tokens/sec"
        )

    mean_seconds = statistics.mean(times)
    mean_tokens = statistics.mean(token_counts)
    tokens_per_second = mean_tokens / mean_seconds

    del model
    del inputs

    if device == "cuda":
        torch.cuda.empty_cache()

    return {
        "device": device,
        "model": MODEL,
        "runs": RUNS,
        "max_new_tokens": MAX_NEW_TOKENS,
        "mean_generated_tokens": mean_tokens,
        "mean_seconds": mean_seconds,
        "min_seconds": min(times),
        "max_seconds": max(times),
        "tokens_per_second": tokens_per_second,
    }


def main():
    if not torch.cuda.is_available():
        raise RuntimeError(
            "AMD Radeon ROCm accelerator was not detected."
        )

    print("=" * 60)
    print("NEXUSAI CPU VS AMD RADEON LLM BENCHMARK")
    print("=" * 60)

    print("\nModel:", MODEL)
    print("GPU:", torch.cuda.get_device_name(0))
    print("PyTorch:", torch.__version__)
    print("HIP:", torch.version.hip)

    print("\nStarting CPU benchmark...")
    cpu_result = benchmark("cpu")

    print("\nStarting AMD Radeon ROCm benchmark...")
    gpu_result = benchmark("cuda")

    speedup = (
        gpu_result["tokens_per_second"]
        / cpu_result["tokens_per_second"]
    )

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmark_type": "same-model-cpu-vs-amd-radeon-llm",
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "hip": torch.version.hip,
            "gpu": torch.cuda.get_device_name(0),
        },
        "configuration": {
            "model": MODEL,
            "runs": RUNS,
            "max_new_tokens": MAX_NEW_TOKENS,
        },
        "cpu": cpu_result,
        "amd_radeon_rocm": gpu_result,
        "gpu_speedup_vs_cpu": speedup,
    }

    output_path = Path(
        "benchmarks/cpu_vs_radeon_llm_benchmark.json"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path.write_text(
        json.dumps(results, indent=2)
    )

    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)

    print(
        f"CPU throughput: "
        f"{cpu_result['tokens_per_second']:.2f} tokens/sec"
    )

    print(
        f"Radeon throughput: "
        f"{gpu_result['tokens_per_second']:.2f} tokens/sec"
    )

    print(
        f"GPU speedup: "
        f"{speedup:.2f}x"
    )

    print(
        "\nResults saved to:",
        output_path
    )


if __name__ == "__main__":
    main()
