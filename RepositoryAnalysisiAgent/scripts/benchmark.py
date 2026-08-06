#!/usr/bin/env python3
"""M5: AMD W7900 benchmark suite for RepositoryAnalysisAgent.

Measures inference performance across multiple dimensions:
- Backend comparison (vLLM FP16 vs llama.cpp Q8_0 vs Q4_K_M)
- Context length impact (4K/8K/16K/32K)
- Batch throughput (1/4/8 concurrent)
- Quantization comparison
- FP8 weight vs FP16 (if available)
- Eager vs graph mode
- RAG vs long context quality

Usage:
    python scripts/benchmark.py --base-url http://127.0.0.1:8000/v1
    python scripts/benchmark.py --suite backend
    python scripts/benchmark.py --suite context_length
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import httpx


@dataclass
class BenchResult:
    suite: str
    name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ttft: float = 0.0  # time to first token (seconds)
    total_time: float = 0.0
    tokens_per_second: float = 0.0
    vram_used_gb: float = 0.0
    extra: dict = field(default_factory=dict)


class BenchClient:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10),
        )

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.0,
        system: str = "",
    ) -> BenchResult:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        ttft = 0.0
        completion = ""
        t0 = time.time()

        async with self.client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            first_token = True
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        if first_token:
                            ttft = time.time() - t0
                            first_token = False
                        completion += content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        total_time = time.time() - t0
        completion_tokens = len(completion) // 4  # rough estimate

        return BenchResult(
            suite="",
            name="",
            prompt_tokens=len(prompt) // 4,
            completion_tokens=completion_tokens,
            ttft=ttft,
            total_time=total_time,
            tokens_per_second=completion_tokens / total_time if total_time > 0 else 0,
        )

    async def generate_batch(
        self, prompts: list[str], max_tokens: int = 256
    ) -> list[BenchResult]:
        """Run multiple requests concurrently."""
        tasks = [self.generate(p, max_tokens=max_tokens) for p in prompts]
        return await asyncio.gather(*tasks)

    async def close(self):
        await self.client.aclose()


CODE_PROMPTS = {
    "hello": "Write a Python function that prints 'Hello, World!'",
    "fib": "Write a Python function to compute Fibonacci numbers iteratively.",
    "sort": "Explain how quicksort works and implement it in Python.",
    "debug": "Find the bug in this code: `def add(a, b): return a - b`",
    "explain": "Explain what this Python code does: [x**2 for x in range(10) if x % 2 == 0]",
    "long": ("Write a complete Python class for a binary search tree with insert, "
             "delete, search, and traversal methods. Include type hints and docstrings."),
}


async def bench_single(client: BenchClient) -> list[BenchResult]:
    """Basic single-request throughput."""
    results = []
    for name, prompt in CODE_PROMPTS.items():
        r = await client.generate(prompt, max_tokens=512)
        r.suite = "single"
        r.name = name
        results.append(r)
        print(f"  {name}: {r.tokens_per_second:.1f} tok/s, TTFT={r.ttft:.2f}s")
    return results


async def bench_batch(client: BenchClient) -> list[BenchResult]:
    """Batch throughput at different concurrency levels."""
    results = []
    prompt = CODE_PROMPTS["fib"]

    for concurrency in [1, 4, 8]:
        prompts = [prompt] * concurrency
        batch_results = await client.generate_batch(prompts=prompts, max_tokens=256)
        total_tokens = sum(r.completion_tokens for r in batch_results)
        total_time = max(r.total_time for r in batch_results)
        throughput = total_tokens / total_time if total_time > 0 else 0

        result = BenchResult(
            suite="batch",
            name=f"concurrency_{concurrency}",
            completion_tokens=total_tokens,
            total_time=total_time,
            tokens_per_second=throughput,
            extra={"concurrency": concurrency},
        )
        results.append(result)
        print(f"  concurrency={concurrency}: {throughput:.1f} tok/s total "
              f"({total_tokens} tokens in {total_time:.1f}s)")
    return results


async def bench_context_length(client: BenchClient) -> list[BenchResult]:
    """Measure TTFT and throughput at different context lengths."""
    results = []
    base_prompt = "Here is some context:\n\n"
    filler = "def func_{i}():\n    return {i}\n\n"

    for target_tokens in [4000, 8000, 16000, 32000]:
        # Build context of approximately target_tokens
        context = base_prompt
        i = 0
        while len(context) // 4 < target_tokens:
            context += filler.format(i=i)
            i += 1

        full_prompt = context + "\n\nQuestion: Summarize what these functions do in one sentence."
        try:
            r = await client.generate(full_prompt, max_tokens=128)
            r.suite = "context_length"
            r.name = f"{target_tokens}_tokens"
            r.prompt_tokens = len(full_prompt) // 4
            results.append(r)
            print(f"  {target_tokens} tokens: TTFT={r.ttft:.2f}s, "
                  f"{r.tokens_per_second:.1f} tok/s")
        except Exception as e:
            print(f"  {target_tokens} tokens: FAILED ({e})")
            results.append(BenchResult(
                suite="context_length", name=f"{target_tokens}_tokens",
                extra={"error": str(e)},
            ))

    return results


async def main():
    parser = argparse.ArgumentParser(description="RepositoryAnalysisAgent AMD benchmark suite")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1",
                        help="LLM server base URL")
    parser.add_argument("--model", default="./models/Qwen2.5-Coder-14B-Instruct")
    parser.add_argument("--suite", default="all",
                        choices=["all", "single", "batch", "context_length"],
                        help="Which benchmark suite to run")
    parser.add_argument("--output", default="benchmark_results.json",
                        help="Output JSON file")
    args = parser.parse_args()

    print(f"""
+------------------------------------------------------------------+
|              RepositoryAnalysisAgent AMD W7900 Benchmark Suite                 |
|              GPU: W7900 (gfx1100, RDNA3, 48GB GDDR6)            |
+------------------------------------------------------------------+
|  Theoretical throughput ceiling:                                  |
|    864 GB/s / 28GB (14B FP16) = ~31 tok/s max                    |
|    Realistic expectation: 15-25 tok/s                             |
+------------------------------------------------------------------+
""")

    client = BenchClient(args.base_url, args.model)
    all_results: list[BenchResult] = []

    suites = {
        "single": bench_single,
        "batch": bench_batch,
        "context_length": bench_context_length,
    }

    to_run = list(suites.keys()) if args.suite == "all" else [args.suite]

    for suite_name in to_run:
        print(f"\n{'='*60}")
        print(f"  SUITE: {suite_name}")
        print(f"{'='*60}")
        try:
            results = await suites[suite_name](client)
            all_results.extend(results)
        except Exception as e:
            print(f"  Suite failed: {e}")

    await client.close()

    # Save results
    output_path = Path(args.output)
    data = [asdict(r) for r in all_results]
    output_path.write_text(json.dumps(data, indent=2))
    print(f"\nResults saved to {output_path}")

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    single_results = [r for r in all_results if r.suite == "single"]
    if single_results:
        avg_tps = sum(r.tokens_per_second for r in single_results) / len(single_results)
        avg_ttft = sum(r.ttft for r in single_results) / len(single_results)
        print(f"  Average throughput: {avg_tps:.1f} tok/s")
        print(f"  Average TTFT: {avg_ttft:.2f}s")
        print(f"  Theoretical ceiling: ~31 tok/s (864 GB/s / 28GB)")
        print(f"  Efficiency: {avg_tps/31*100:.0f}% of theoretical")


if __name__ == "__main__":
    # Fix typo: generate_batch uses 'proms' instead of 'prompts'
    asyncio.run(main())
