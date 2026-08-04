"""
THEMIS Benchmark Router
Runs and returns AMD ROCm performance benchmarks.
This is the data source for the frontend Benchmark Panel.
"""

import time
import asyncio
from fastapi import APIRouter
from openai import AsyncOpenAI

from backend.config import get_settings

settings = get_settings()
router = APIRouter()

# Test prompts of varying sizes for throughput benchmarking
_BENCHMARK_PROMPTS = [
    {
        "name": "short_review",
        "tokens": "~100",
        "content": "Review this Python function for security issues:\n\ndef get_user(id):\n    return db.execute(f'SELECT * FROM users WHERE id={id}')",
    },
    {
        "name": "medium_review",
        "tokens": "~500",
        "content": """Review this authentication module for vulnerabilities:

import hashlib
import sqlite3

def authenticate(username, password):
    conn = sqlite3.connect('users.db')
    query = f"SELECT * FROM users WHERE username='{username}'"
    user = conn.execute(query).fetchone()
    if user:
        stored_hash = user[2]
        input_hash = hashlib.md5(password.encode()).hexdigest()
        if stored_hash == input_hash:
            return {"token": username + "_" + password, "admin": user[3]}
    return None

def reset_password(email):
    import random
    token = str(random.randint(1000, 9999))
    send_email(email, f"Your reset token: {token}")
    db.store_reset_token(email, token)
""",
    },
]


async def _benchmark_single(client: AsyncOpenAI, prompt: dict) -> dict:
    """Run a single benchmark inference and return timing metrics."""
    start = time.perf_counter()
    first_token_time = None

    try:
        stream = await client.chat.completions.create(
            model=settings.vllm_model_name,
            messages=[
                {"role": "system", "content": "You are an expert security code reviewer."},
                {"role": "user", "content": prompt["content"]},
            ],
            max_tokens=512,
            temperature=0.1,
            stream=True,
        )

        output_tokens = 0
        async for chunk in stream:
            if first_token_time is None and chunk.choices[0].delta.content:
                first_token_time = time.perf_counter()
            if chunk.choices[0].delta.content:
                output_tokens += 1

        total_time = time.perf_counter() - start
        ttft = (first_token_time - start) * 1000 if first_token_time else None

        return {
            "prompt_name": prompt["name"],
            "prompt_tokens_approx": prompt["tokens"],
            "output_tokens": output_tokens,
            "total_time_s": round(total_time, 3),
            "ttft_ms": round(ttft, 1) if ttft else None,
            "tokens_per_second": round(output_tokens / total_time, 1) if total_time > 0 else 0,
            "status": "success",
        }

    except Exception as e:
        return {
            "prompt_name": prompt["name"],
            "status": "error",
            "error": str(e)[:200],
        }


@router.get("/run")
async def run_benchmark():
    """
    Run THEMIS performance benchmark suite against the live vLLM server.
    Returns tokens/sec, TTFT, and per-prompt timing.
    Used by the frontend Benchmark Panel.
    """
    client = AsyncOpenAI(
        base_url=settings.vllm_base_url,
        api_key="not-needed",
        timeout=120,
    )

    results = []
    for prompt in _BENCHMARK_PROMPTS:
        result = await _benchmark_single(client, prompt)
        results.append(result)

    # Summary statistics
    successful = [r for r in results if r["status"] == "success"]
    avg_tps = (
        sum(r["tokens_per_second"] for r in successful) / len(successful)
        if successful else 0
    )
    avg_ttft = (
        sum(r["ttft_ms"] for r in successful if r.get("ttft_ms"))
        / len([r for r in successful if r.get("ttft_ms")])
        if successful else 0
    )

    return {
        "model": settings.vllm_model_name,
        "gpu": "AMD Radeon PRO W7900D",
        "rocm_version": "7.2.1",
        "vllm_version": "0.16.1.dev0",
        "quantization": "AWQ INT4",
        "results": results,
        "summary": {
            "avg_tokens_per_second": round(avg_tps, 1),
            "avg_ttft_ms": round(avg_ttft, 1),
            "successful_runs": len(successful),
            "total_runs": len(results),
        },
    }


@router.get("/health")
async def benchmark_health():
    """Quick health check — ping the vLLM server."""
    client = AsyncOpenAI(
        base_url=settings.vllm_base_url,
        api_key="not-needed",
        timeout=10,
    )
    try:
        models = await client.models.list()
        return {
            "vllm_status": "online",
            "models": [m.id for m in models.data],
        }
    except Exception as e:
        return {"vllm_status": "offline", "error": str(e)}
