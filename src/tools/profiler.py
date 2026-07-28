"""
Parser and runner for PyTorch / ROCm profiler traces.

Runs torch.profiler on a target script via subprocess, then parses the
resulting trace to return the top-N operations by time and memory.
Includes mock mode for development without a Radeon GPU.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


# Template script injected around the user's workload to enable profiling
_PROFILER_WRAPPER_TEMPLATE = '''
import torch
from torch.profiler import profile, record_function, ProfilerActivity

# --- User workload ---
{user_code}
# --- End user workload ---

activities = [ProfilerActivity.CPU]
if torch.cuda.is_available() or hasattr(torch, "_C") and hasattr(torch._C, "_cuda_isDriverSufficient"):
    activities.append(ProfilerActivity.CUDA)

with profile(
    activities=activities,
    record_shapes=True,
    profile_memory=True,
    with_stack=False,
) as prof:
    with record_function("omnikernel_workload"):
        {call_expr}

import json, sys
events = []
for e in prof.key_averages():
    events.append({{
        "name": e.key,
        "cpu_time_us": e.cpu_time_total,
        "cuda_time_us": e.cuda_time_total,
        "self_cpu_time_us": e.self_cpu_time_total,
        "self_cuda_time_us": e.self_cuda_time_total,
        "cpu_memory_usage": e.cpu_memory_usage,
        "cuda_memory_usage": e.cuda_memory_usage,
        "count": e.count,
    }})

print("OMNIKERNEL_PROFILE_JSON:" + json.dumps(events))
'''


MOCK_PROFILE_RESULT = {
    "top_by_time": [
        {
            "rank": 1,
            "name": "aten::convolution",
            "cpu_time_us": 18430,
            "cuda_time_us": 52100,
            "cuda_memory_usage_kb": 4096,
            "count": 8,
        },
        {
            "rank": 2,
            "name": "aten::batch_norm",
            "cpu_time_us": 3200,
            "cuda_time_us": 12400,
            "cuda_memory_usage_kb": 1024,
            "count": 8,
        },
        {
            "rank": 3,
            "name": "aten::relu_",
            "cpu_time_us": 800,
            "cuda_time_us": 3100,
            "cuda_memory_usage_kb": 0,
            "count": 16,
        },
    ],
    "top_by_memory": [
        {
            "rank": 1,
            "name": "aten::convolution",
            "cuda_memory_usage_kb": 4096,
            "cuda_time_us": 52100,
            "count": 8,
        },
    ],
    "total_cpu_time_us": 24500,
    "total_cuda_time_us": 71200,
    "error": None,
}


def profile_pytorch_trace(
    script_path: str,
    top_n: int = 10,
    mock: bool = False,
    timeout: int = 120,
) -> dict:
    """
    Run torch.profiler on a target script and return top-N ops.

    Args:
        script_path: Path to the Python script to profile.
        top_n: Number of top operations to return (by time and by memory).
        mock: If True, return synthetic data (for development).
        timeout: Max seconds to wait for profiling subprocess.

    Returns:
        {
            "top_by_time": [ {rank, name, cpu_time_us, cuda_time_us, ...} ],
            "top_by_memory": [ {rank, name, cuda_memory_usage_kb, ...} ],
            "total_cpu_time_us": int,
            "total_cuda_time_us": int,
            "error": str | None
        }
    """
    if mock:
        return MOCK_PROFILE_RESULT

    script_path = Path(script_path)
    if not script_path.exists():
        return _error_result(f"Script not found: {script_path}")

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "OMNIKERNEL_PROFILE_MODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return _error_result(f"Profiling timed out after {timeout}s.")
    except Exception as e:
        return _error_result(f"Subprocess error: {e}")

    return _parse_profile_output(result.stdout, result.stderr, top_n)


def profile_code_snippet(
    code: str,
    call_expr: str = "pass",
    top_n: int = 10,
    mock: bool = False,
    timeout: int = 60,
) -> dict:
    """
    Profile an inline code snippet by wrapping it in the profiler template
    and running it in a temp file.

    Args:
        code: Python source code defining the workload (functions, classes, etc.)
        call_expr: The expression to call inside the profiler context.
        top_n: Number of top ops to return.
        mock: Return mock data.
        timeout: Subprocess timeout.
    """
    if mock:
        return MOCK_PROFILE_RESULT

    wrapped = _PROFILER_WRAPPER_TEMPLATE.format(
        user_code=code,
        call_expr=call_expr,
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(wrapped)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _error_result(f"Profiling timed out after {timeout}s.")
    except Exception as e:
        return _error_result(f"Subprocess error: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return _parse_profile_output(result.stdout, result.stderr, top_n)


def _parse_profile_output(stdout: str, stderr: str, top_n: int) -> dict:
    """Extract the JSON payload emitted by the profiler wrapper."""
    marker = "OMNIKERNEL_PROFILE_JSON:"
    for line in stdout.splitlines():
        if line.startswith(marker):
            try:
                events = json.loads(line[len(marker):])
                return _build_result(events, top_n)
            except json.JSONDecodeError as e:
                return _error_result(f"Failed to parse profile JSON: {e}")

    # No marker found — subprocess may have crashed
    err_detail = stderr.strip()[:500] if stderr.strip() else "(no stderr)"
    return _error_result(f"Profile output not found in stdout. stderr: {err_detail}")


def _build_result(events: list[dict], top_n: int) -> dict:
    """Sort events and build the structured result dict."""
    by_time = sorted(events, key=lambda e: e.get("cuda_time_us", 0) + e.get("cpu_time_us", 0), reverse=True)
    by_mem = sorted(events, key=lambda e: e.get("cuda_memory_usage", 0), reverse=True)

    def _fmt(ranked: list, idx: int, e: dict, by: str) -> dict:
        base = {
            "rank": idx + 1,
            "name": e["name"],
            "cpu_time_us": e.get("cpu_time_us", 0),
            "cuda_time_us": e.get("cuda_time_us", 0),
            "cuda_memory_usage_kb": (e.get("cuda_memory_usage", 0) or 0) // 1024,
            "count": e.get("count", 1),
        }
        return base

    top_time = [_fmt(by_time, i, e, "time") for i, e in enumerate(by_time[:top_n])]
    top_mem = [_fmt(by_mem, i, e, "mem") for i, e in enumerate(by_mem[:top_n])]

    total_cpu = sum(e.get("cpu_time_us", 0) for e in events)
    total_cuda = sum(e.get("cuda_time_us", 0) for e in events)

    return {
        "top_by_time": top_time,
        "top_by_memory": top_mem,
        "total_cpu_time_us": total_cpu,
        "total_cuda_time_us": total_cuda,
        "error": None,
    }


def _error_result(msg: str) -> dict:
    return {
        "top_by_time": [],
        "top_by_memory": [],
        "total_cpu_time_us": 0,
        "total_cuda_time_us": 0,
        "error": msg,
    }


def format_profile_summary(profile_data: dict, top_n: int = 5) -> str:
    """Format profile output as a concise text summary for the LLM prompt."""
    if profile_data.get("error"):
        return f"[profiler error] {profile_data['error']}"

    total_ms = profile_data["total_cuda_time_us"] / 1000
    lines = [f"Profiler Summary (total CUDA time: {total_ms:.1f}ms):"]
    lines.append("  Top ops by time:")
    for op in profile_data["top_by_time"][:top_n]:
        pct = (op["cuda_time_us"] / max(profile_data["total_cuda_time_us"], 1)) * 100
        lines.append(
            f"    #{op['rank']} {op['name']}: "
            f"CUDA={op['cuda_time_us']/1000:.1f}ms ({pct:.1f}%) "
            f"x{op['count']} calls"
        )
    lines.append("  Top ops by memory:")
    for op in profile_data["top_by_memory"][:3]:
        lines.append(
            f"    #{op['rank']} {op['name']}: "
            f"{op['cuda_memory_usage_kb']}KB VRAM"
        )
    return "\n".join(lines)
