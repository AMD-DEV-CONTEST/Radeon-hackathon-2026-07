"""
Sandboxed benchmark execution engine.

Runs candidate and baseline Python scripts in isolated subprocesses and
returns a structured latency/throughput comparison. Never runs code in-process.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


MOCK_BENCHMARK_RESULT = {
    "baseline": {
        "script": "baseline.py",
        "latency_ms": 124.3,
        "throughput_items_per_sec": None,
        "peak_vram_mb": None,
        "exit_code": 0,
        "error": None,
    },
    "candidate": {
        "script": "candidate.py",
        "latency_ms": 89.7,
        "throughput_items_per_sec": None,
        "peak_vram_mb": None,
        "exit_code": 0,
        "error": None,
    },
    "comparison": {
        "speedup_ratio": 1.39,
        "latency_delta_ms": -34.6,
        "winner": "candidate",
        "verdict": "candidate is 1.39x faster (34.6ms improvement)",
    },
    "error": None,
}

# Sentinel printed by the benchmarked script to communicate its metrics
_METRICS_MARKER = "OMNIKERNEL_BENCH_METRICS:"

# Template wrapper injected around user workload to capture timing
_BENCH_WRAPPER = '''
import time as _time
import json as _json
import sys as _sys

# -- User workload --
{user_code}
# -- End user workload --

_start = _time.perf_counter()
{call_expr}
_end = _time.perf_counter()
_latency_ms = (_end - _start) * 1000.0

print("{marker}" + _json.dumps({{
    "latency_ms": round(_latency_ms, 3),
    "throughput_items_per_sec": None,
}}))
'''.replace("{marker}", _METRICS_MARKER)


def run_benchmark(
    candidate_path: str,
    baseline_path: str,
    timeout: int = 60,
    mock: bool = False,
    runs: int = 3,
) -> dict:
    """
    Run candidate and baseline scripts in sandboxed subprocesses.

    Args:
        candidate_path: Path to the candidate (optimized) script.
        baseline_path: Path to the baseline script.
        timeout: Max seconds per run.
        mock: Return synthetic data for development.
        runs: Number of repeated runs; median latency is reported.

    Returns:
        {
            "baseline": { latency_ms, throughput_items_per_sec, exit_code, error },
            "candidate": { latency_ms, ... },
            "comparison": { speedup_ratio, latency_delta_ms, winner, verdict },
            "error": str | None
        }
    """
    if mock:
        return MOCK_BENCHMARK_RESULT

    baseline_result = _run_script(baseline_path, timeout=timeout, runs=runs)
    candidate_result = _run_script(candidate_path, timeout=timeout, runs=runs)

    comparison = _compute_comparison(
        baseline_result.get("latency_ms"),
        candidate_result.get("latency_ms"),
    )

    has_error = baseline_result.get("error") or candidate_result.get("error")

    return {
        "baseline": {**baseline_result, "script": str(Path(baseline_path).name)},
        "candidate": {**candidate_result, "script": str(Path(candidate_path).name)},
        "comparison": comparison,
        "error": has_error,
    }


def _run_script(script_path: str, timeout: int, runs: int) -> dict:
    """Execute a script multiple times and return median latency."""
    script_path = Path(script_path)
    if not script_path.exists():
        return _script_error(f"Script not found: {script_path}")

    latencies = []
    last_error = None

    for _ in range(runs):
        start = time.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                # Security: inherit minimal environment
                env=_safe_env(),
            )
        except subprocess.TimeoutExpired:
            return _script_error(f"Timed out after {timeout}s")
        except Exception as e:
            return _script_error(str(e))

        elapsed_ms = (time.perf_counter() - start) * 1000.0

        if result.returncode != 0:
            last_error = result.stderr.strip()[:300]
            continue

        # Try to extract precise metrics from the script's own output
        metrics = _extract_metrics(result.stdout)
        latencies.append(metrics["latency_ms"] if metrics else elapsed_ms)

    if not latencies:
        return _script_error(last_error or "All runs failed")

    latencies.sort()
    median_latency = latencies[len(latencies) // 2]

    return {
        "latency_ms": round(median_latency, 3),
        "throughput_items_per_sec": None,
        "peak_vram_mb": None,
        "exit_code": 0,
        "error": None,
    }


def _extract_metrics(stdout: str) -> Optional[dict]:
    """Pull structured metrics from the script's stdout if present."""
    import json
    for line in stdout.splitlines():
        if line.startswith(_METRICS_MARKER):
            try:
                return json.loads(line[len(_METRICS_MARKER):])
            except Exception:
                pass
    return None


def _compute_comparison(
    baseline_ms: Optional[float],
    candidate_ms: Optional[float],
) -> dict:
    """Compute speedup ratio and human-readable verdict."""
    if baseline_ms is None or candidate_ms is None:
        return {
            "speedup_ratio": None,
            "latency_delta_ms": None,
            "winner": None,
            "verdict": "Cannot compare — one or both scripts failed.",
        }

    delta = candidate_ms - baseline_ms
    if baseline_ms > 0:
        speedup = round(baseline_ms / candidate_ms, 3)
    else:
        speedup = 1.0

    if speedup > 1.05:
        winner = "candidate"
        verdict = f"candidate is {speedup:.2f}x faster ({abs(delta):.1f}ms improvement)"
    elif speedup < 0.95:
        winner = "baseline"
        verdict = f"candidate is {1/speedup:.2f}x SLOWER ({abs(delta):.1f}ms regression)"
    else:
        winner = "tie"
        verdict = f"No meaningful difference (speedup={speedup:.2f}x, delta={delta:+.1f}ms)"

    return {
        "speedup_ratio": speedup,
        "latency_delta_ms": round(delta, 3),
        "winner": winner,
        "verdict": verdict,
    }


def _safe_env() -> dict:
    """Return a restricted environment for subprocess execution."""
    allowed_keys = {
        "PATH", "HOME", "USER", "LANG", "PYTHONPATH",
        "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES",
        "CUDA_VISIBLE_DEVICES", "LD_LIBRARY_PATH",
    }
    return {k: v for k, v in os.environ.items() if k in allowed_keys}


def _script_error(msg: str) -> dict:
    return {
        "latency_ms": None,
        "throughput_items_per_sec": None,
        "peak_vram_mb": None,
        "exit_code": 1,
        "error": msg,
    }


def format_benchmark_summary(bench_data: dict) -> str:
    """Format benchmark output as a concise text summary for the LLM prompt."""
    if bench_data.get("error") and not bench_data.get("comparison", {}).get("verdict"):
        return f"[benchmark error] {bench_data['error']}"

    comp = bench_data.get("comparison", {})
    b = bench_data.get("baseline", {})
    c = bench_data.get("candidate", {})
    lines = [
        f"Benchmark Results:",
        f"  Baseline  ({b.get('script','baseline')}): {b.get('latency_ms','?')}ms",
        f"  Candidate ({c.get('script','candidate')}): {c.get('latency_ms','?')}ms",
        f"  Verdict: {comp.get('verdict', 'N/A')}",
    ]
    return "\n".join(lines)
