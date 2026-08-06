#!/usr/bin/env python3
"""Bunker AMD ROCm Benchmarking Script.

Measures TTFT, throughput, and captures ROCm GPU metrics.
Outputs machine-readable JSON to artifacts/benchmark_<timestamp>.json
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bunker AMD ROCm Benchmark",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model",
        type=str,
        default="Qwen/Qwen3-30B-A3B",
        help="Model name as served by vLLM",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of benchmark iterations per test",
    )
    parser.add_argument(
        "--vllm-url",
        type=str,
        default="http://localhost:8000",
        help="vLLM OpenAI-compatible endpoint base URL",
    )
    parser.add_argument(
        "--prompt-tokens",
        type=int,
        default=1024,
        help="Input prompt length in tokens for TTFT test",
    )
    parser.add_argument(
        "--completion-tokens",
        type=int,
        default=256,
        help="Target completion tokens for throughput test",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Sampling temperature",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=0.9,
        help="Top-p sampling",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts",
        help="Directory for JSON artifacts",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds",
    )
    return parser.parse_args()


def check_vllm_health(base_url: str, timeout: int) -> bool:
    """Check if vLLM server is healthy."""
    try:
        resp = requests.get(f"{base_url}/health", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def get_rocm_smi_output() -> Optional[str]:
    """Capture rocm-smi output if available."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--showuse", "--showtemp"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def generate_prompt(token_count: int) -> str:
    """Generate a prompt of approximately token_count tokens."""
    words = ["benchmark", "test", "ROCm", "AMD", "GPU", "inference", "performance"]
    text = " ".join(words * ((token_count // len(words)) + 1))
    return text[: token_count * 4]


def measure_ttft(
    base_url: str,
    model: str,
    prompt: str,
    temperature: float,
    top_p: float,
    timeout: int,
) -> tuple[float, int]:
    """Measure Time to First Token (streaming) from first non-empty token.
    
    Returns (ttft_seconds, completion_tokens)
    """
    url = f"{base_url}/v1/completions"
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": 1,
        "temperature": temperature,
        "top_p": top_p,
        "stream": True,
    }
    
    start = time.perf_counter()
    ttft = None
    completion_tokens = 0
    
    with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choices = chunk.get("choices", [])
                        if choices:
                            text = choices[0].get("text", "")
                            if text and ttft is None:
                                ttft = time.perf_counter() - start
                            if text:
                                completion_tokens += 1
                    except json.JSONDecodeError:
                        continue
    
    if ttft is None:
        ttft = time.perf_counter() - start
    
    return ttft, completion_tokens


def measure_throughput(
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    timeout: int,
) -> tuple[float, int, float]:
    """Measure throughput using streaming completion.
    
    Returns (total_time_seconds, completion_tokens, tokens_per_second)
    """
    url = f"{base_url}/v1/completions"
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": True,
    }
    
    start = time.perf_counter()
    completion_tokens = 0
    first_token_time = None
    
    with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choices = chunk.get("choices", [])
                        if choices:
                            text = choices[0].get("text", "")
                            if text:
                                if first_token_time is None:
                                    first_token_time = time.perf_counter()
                                completion_tokens += len(text.split())
                    except json.JSONDecodeError:
                        continue
    
    end = time.perf_counter()
    total_time = end - start
    tokens_per_second = completion_tokens / total_time if total_time > 0 else 0
    
    return total_time, completion_tokens, tokens_per_second


def run_benchmark(
    base_url: str,
    model: str,
    iterations: int,
    prompt_tokens: int,
    completion_tokens: int,
    temperature: float,
    top_p: float,
    timeout: int,
) -> dict[str, Any]:
    """Run full benchmark suite."""
    results = {
        "metadata": {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model": model,
            "vllm_url": base_url,
            "iterations": iterations,
            "prompt_tokens": prompt_tokens,
            "target_completion_tokens": completion_tokens,
            "temperature": temperature,
            "top_p": top_p,
        },
        "ttft": [],
        "throughput": [],
        "rocm_smi": get_rocm_smi_output(),
    }
    
    # Generate test prompts
    ttft_prompt = generate_prompt(prompt_tokens)
    throughput_prompt = generate_prompt(prompt_tokens)
    
    print(f"\nRunning {iterations} iterations per test...")
    print(f"Model: {model}")
    print(f"Endpoint: {base_url}")
    print(f"Prompt tokens: {prompt_tokens}, Completion tokens: {completion_tokens}\n")
    
    # TTFT Benchmark
    print("=" * 60)
    print("TTFT Benchmark (streaming, first non-empty token)")
    print("=" * 60)
    for i in range(iterations):
        print(f"  Iteration {i+1}/{iterations}...", end=" ", flush=True)
        try:
            ttft, tokens = measure_ttft(
                base_url, model, ttft_prompt, temperature, top_p, timeout
            )
            results["ttft"].append({
                "iteration": i + 1,
                "ttft_seconds": ttft,
                "ttft_ms": ttft * 1000,
                "completion_tokens": tokens,
            })
            print(f"TTFT = {ttft*1000:.1f} ms")
        except Exception as e:
            print(f"FAILED: {e}")
            results["ttft"].append({
                "iteration": i + 1,
                "error": str(e),
            })
    
    # Throughput Benchmark
    print("\n" + "=" * 60)
    print("Throughput Benchmark (streaming, tokens/sec)")
    print("=" * 60)
    for i in range(iterations):
        print(f"  Iteration {i+1}/{iterations}...", end=" ", flush=True)
        try:
            total_time, tokens, tps = measure_throughput(
                base_url,
                model,
                throughput_prompt,
                completion_tokens,
                temperature,
                top_p,
                timeout,
            )
            results["throughput"].append({
                "iteration": i + 1,
                "total_time_seconds": total_time,
                "completion_tokens": tokens,
                "tokens_per_second": tps,
            })
            print(f"{tokens} tokens in {total_time:.2f}s = {tps:.1f} tok/s")
        except Exception as e:
            print(f"FAILED: {e}")
            results["throughput"].append({
                "iteration": i + 1,
                "error": str(e),
            })
    
    return results


def compute_summary(results: dict[str, Any]) -> dict[str, Any]:
    """Compute summary statistics from benchmark results."""
    summary = {}
    
    # TTFT summary
    ttft_values = [r["ttft_ms"] for r in results["ttft"] if "ttft_ms" in r]
    if ttft_values:
        summary["ttft"] = {
            "mean_ms": statistics.mean(ttft_values),
            "median_ms": statistics.median(ttft_values),
            "stdev_ms": statistics.stdev(ttft_values) if len(ttft_values) > 1 else 0,
            "min_ms": min(ttft_values),
            "max_ms": max(ttft_values),
            "successful_runs": len(ttft_values),
        }
    
    # Throughput summary
    tps_values = [r["tokens_per_second"] for r in results["throughput"] if "tokens_per_second" in r]
    if tps_values:
        summary["throughput"] = {
            "mean_tok_s": statistics.mean(tps_values),
            "median_tok_s": statistics.median(tps_values),
            "stdev_tok_s": statistics.stdev(tps_values) if len(tps_values) > 1 else 0,
            "min_tok_s": min(tps_values),
            "max_tok_s": max(tps_values),
            "successful_runs": len(tps_values),
        }
    
    return summary


def print_summary_table(summary: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Print concise summary table."""
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"Model:          {metadata['model']}")
    print(f"Endpoint:       {metadata['vllm_url']}")
    print(f"Iterations:     {metadata['iterations']}")
    print(f"Prompt tokens:  {metadata['prompt_tokens']}")
    print(f"Completion tok: {metadata['target_completion_tokens']}")
    print("-" * 60)
    
    if "ttft" in summary:
        ttft = summary["ttft"]
        print(f"TTFT (ms):      mean={ttft['mean_ms']:.1f}  median={ttft['median_ms']:.1f}  "
              f"stdev={ttft['stdev_ms']:.1f}  min={ttft['min_ms']:.1f}  max={ttft['max_ms']:.1f}  "
              f"({ttft['successful_runs']}/{metadata['iterations']} ok)")
    
    if "throughput" in summary:
        tp = summary["throughput"]
        print(f"Throughput:     mean={tp['mean_tok_s']:.1f}  median={tp['median_tok_s']:.1f}  "
              f"stdev={tp['stdev_tok_s']:.1f}  min={tp['min_tok_s']:.1f}  max={tp['max_tok_s']:.1f}  "
              f"({tp['successful_runs']}/{metadata['iterations']} ok)")
    
    print("=" * 60)


def save_json_artifact(results: dict[str, Any], summary: dict[str, Any], output_dir: str) -> Path:
    """Save benchmark results as JSON artifact."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_{timestamp}.json"
    filepath = output_path / filename
    
    artifact = {
        "metadata": results["metadata"],
        "summary": summary,
        "raw_results": {
            "ttft": results["ttft"],
            "throughput": results["throughput"],
        },
        "rocm_smi": results["rocm_smi"],
    }
    
    with open(filepath, "w") as f:
        json.dump(artifact, f, indent=2)
    
    print(f"\nArtifact saved: {filepath}")
    return filepath


def main() -> int:
    args = parse_args()
    
    print("Bunker AMD ROCm Benchmark")
    print("=" * 60)
    
    # Health check
    print(f"Checking vLLM at {args.vllm_url}...", end=" ", flush=True)
    if not check_vllm_health(args.vllm_url, args.timeout):
        print("FAILED - server not responding")
        return 1
    print("OK")
    
    # Run benchmarks
    results = run_benchmark(
        base_url=args.vllm_url,
        model=args.model,
        iterations=args.iterations,
        prompt_tokens=args.prompt_tokens,
        completion_tokens=args.completion_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.timeout,
    )
    
    # Compute and print summary
    summary = compute_summary(results)
    print_summary_table(summary, results["metadata"])
    
    # Save artifact
    save_json_artifact(results, summary, args.output_dir)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())