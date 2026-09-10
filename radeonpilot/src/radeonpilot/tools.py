"""Deterministic GPU-ops tools.

These tools compute facts from the local machine and never let the model invent
readings. In demo mode (no Radeon present) they return clearly-labelled synthetic
telemetry so the full workflow stays inspectable on a development machine.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable

DEMO_VRAM_BYTES = 51522830336  # 48 GiB, mirrors the competition Radeon instance


@dataclass
class ToolResult:
    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_json(self) -> str:
        payload = {"tool": self.tool, "ok": self.ok, "data": self.data}
        if self.error:
            payload["error"] = self.error
        return json.dumps(payload, indent=2)


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def _run(binary: str, args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:  # pragma: no cover - env dependent
        return 127, "", str(exc)


def detect_mode() -> str:
    """Return 'pi' when a Radeon endpoint toolchain is present, else 'demo'."""
    if os.environ.get("RADEONPILOT_MODE"):
        return os.environ["RADEONPILOT_MODE"]
    if _which("rocm-smi") or _which("amd-smi"):
        return "pi"
    return "demo"


def gpu_environment(runner: Callable[..., tuple[int, str, str]] = _run) -> ToolResult:
    """Collect deterministic GPU environment facts via rocm-smi / amd-smi."""
    mode = detect_mode()
    if mode == "demo":
        return ToolResult(
            tool="gpu_environment",
            ok=True,
            data={
                "mode": "demo",
                "label": "SYNTHETIC (no Radeon detected)",
                "gpu_name": "AMD Radeon Graphics (synthetic)",
                "gfx": "gfx1100",
                "rocm_version": "7.2.1",
                "vram_total_bytes": DEMO_VRAM_BYTES,
                "vram_used_bytes": 28_000_000,
            },
        )
    if not _which("rocm-smi"):
        return ToolResult(tool="gpu_environment", ok=False, error="rocm-smi not found on PATH")
    code, out, err = runner("rocm-smi", ["--showproductname", "--showmeminfo", "vram", "--json"])
    if code != 0:
        return ToolResult(tool="gpu_environment", ok=False, error=err.strip() or "rocm-smi failed")
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        return ToolResult(tool="gpu_environment", ok=False, error=f"rocm-smi returned invalid JSON: {exc}")
    return ToolResult(tool="gpu_environment", ok=True, data={"mode": "pi", "raw": payload})


def endpoint_status(base_url: str | None = None) -> ToolResult:
    """Probe the local OpenAI-compatible model endpoint health."""
    import urllib.request

    base_url = (base_url or os.environ.get("VLLM_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
    url = base_url + "/models"
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
        models = [item.get("id") for item in body.get("data", [])]
        return ToolResult(
            tool="endpoint_status",
            ok=True,
            data={"base_url": base_url, "reachable": True, "models": models},
        )
    except Exception as exc:  # noqa: BLE001 - endpoint probe must never raise
        return ToolResult(
            tool="endpoint_status",
            ok=True,
            data={"base_url": base_url, "reachable": False, "models": [], "note": str(exc)},
        )


# Least-privilege gate: dangerous GPU-changing actions require explicit approval.
DANGEROUS_ACTIONS = {"restart_endpoint", "apply_quantization", "kill_process", "reset_gpu"}


def permission_check(action: str, role: str = "operator") -> ToolResult:
    action = str(action or "").strip()
    role = str(role or "operator").strip()
    if action in DANGEROUS_ACTIONS and role not in {"sre", "ops_commander", "approver"}:
        return ToolResult(
            tool="permission_check",
            ok=True,
            data={
                "action": action,
                "allowed": False,
                "reason": f"Action '{action}' is hazardous and requires sre/ops_commander approval.",
            },
        )
    return ToolResult(tool="permission_check", ok=True, data={"action": action, "allowed": True, "role": role})


def quick_benchmark(
    base_url: str | None = None,
    prompt: str = "Explain how ROCm schedules kernels on a Radeon GPU.",
    max_tokens: int = 128,
) -> ToolResult:
    """Measure one real request against the endpoint: TTFT and total latency."""
    import urllib.request

    base_url = (base_url or os.environ.get("VLLM_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
    payload = {
        "model": os.environ.get("RADEONPILOT_MODEL", "qwen3-8b"),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120.0) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = body.get("usage", {})
        completion_tokens = int(usage.get("completion_tokens", 0))
        return ToolResult(
            tool="quick_benchmark",
            ok=True,
            data={
                "base_url": base_url,
                "latency_ms": elapsed_ms,
                "completion_tokens": completion_tokens,
                "tokens_per_second": round(completion_tokens / (elapsed_ms / 1000.0), 2) if elapsed_ms else 0.0,
                "measured": True,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(tool="quick_benchmark", ok=False, error=f"benchmark failed: {exc}")
