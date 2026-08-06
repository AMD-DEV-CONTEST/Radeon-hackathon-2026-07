"""Read-only Radeon environment probe for the SpriteFusion 2D stack.

The probe answers "can this box run the Radeon pipeline" in one pass: Python,
lazily imported PyTorch, HIP build detection, GPU visibility, VRAM, a
subprocess operator smoke test with a timeout, ComfyUI health, and the
generation checkpoint (presence plus optional SHA-256).

Design constraints (luna-workpack R01):

* This module is standard-library-only.  Importing it never imports torch,
  numpy, or any project module, so a bare Python environment can still run
  every check to a structured conclusion.
* Torch is imported lazily inside ``check_torch``; the probe never pays a
  multi-second import when torch is absent.
* Outputs are masked by default: filesystem paths and non-loopback endpoints
  are replaced with ``<redacted>`` in both the human summary and the JSON
  receipt.  ``--reveal-paths`` / ``--reveal-endpoints`` opt into the real
  values for private debugging.
* Exit codes aligned with ``sprite_workshop.errors.ExitCode``: 0 pass, 2
  argparse/usage error only, 4 runtime/environment error (incl. SHA-256
  mismatch), 5 missing dependency / backend unavailable (no torch, no
  HIP/GPU, requested ComfyUI/model missing).  The worst failed check wins.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Exit-code contract, aligned with ``sprite_workshop.errors.ExitCode``:
#   0 OK, 2 USAGE (argparse/usage errors only), 4 FAILED (runtime or
#   environment errors, incl. SHA-256 mismatch), 5 BACKEND_UNAVAILABLE
#   (missing dependency: no torch, no HIP/GPU, requested ComfyUI/model).
EXIT_PASS = 0
EXIT_ENVIRONMENT = 4
EXIT_BACKEND_UNAVAILABLE = 5

VERDICTS: dict[int, str] = {
    EXIT_PASS: "PASS",
    EXIT_ENVIRONMENT: "ENVIRONMENT_ERROR",
    EXIT_BACKEND_UNAVAILABLE: "BACKEND_UNAVAILABLE",
}

MASKED = "<redacted>"

# Public knowledge: SHA-256 of the SDXL-Turbo fp16 checkpoint.  Only consulted
# when SHA-256 verification is explicitly enabled and no override is provided.
DEFAULT_EXPECTED_SHA256 = (
    "e869ac7d6942cb327d68d5ed83a40447aadf20e0c3358d98b2cc9e270db0da26"
)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Operator smoke: a small self-contained script run in a child interpreter.
# It always exercises a CPU matmul and runs a GPU matmul when a device is
# visible, so a broken HIP runtime surfaces as a nonzero exit or a timeout.
SMOKE_SCRIPT = """\
import json
import torch

report = {"torch": torch.__version__}
a = torch.randn(256, 256)
b = torch.randn(256, 256)
report["cpu_matmul"] = float((a @ b).abs().sum().item())
if torch.cuda.is_available() and torch.cuda.device_count() > 0:
    torch.cuda.init()
    x = torch.randn(256, 256, device="cuda")
    y = torch.randn(256, 256, device="cuda")
    z = x @ y
    torch.cuda.synchronize()
    report["gpu_matmul"] = float(z.abs().sum().item())
    report["gpu"] = torch.cuda.get_device_name(0)
print(json.dumps(report))
"""


@dataclass(frozen=True, slots=True)
class HttpResult:
    """Outcome of one HTTP probe request."""

    status: int | None
    payload: Any
    error: str | None
    elapsed: float = 0.0


@dataclass(frozen=True, slots=True)
class SubprocessResult:
    """Outcome of one subprocess invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    elapsed: float = 0.0
    timed_out: bool = False
    spawn_error: str | None = None


def _default_run_subprocess(argv: Sequence[str], timeout: float) -> SubprocessResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return SubprocessResult(
            proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started
        )
    except subprocess.TimeoutExpired:
        return SubprocessResult(-1, "", "", time.monotonic() - started, timed_out=True)
    except Exception as exc:
        return SubprocessResult(
            -2, "", "", time.monotonic() - started, spawn_error=type(exc).__name__
        )


def _default_http_get(url: str, timeout: float) -> HttpResult:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            return HttpResult(
                getattr(response, "status", 200),
                payload,
                None,
                time.monotonic() - started,
            )
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        return HttpResult(None, None, type(exc).__name__, time.monotonic() - started)


@dataclass(frozen=True, slots=True)
class ProbeEnv:
    """Injectable environment so every check runs without a real GPU.

    ``import_torch``, ``run_subprocess`` and ``http_get`` are seams for unit
    tests; production uses the real lazy import, subprocess and urllib.
    """

    environ: Mapping[str, str] = field(default_factory=dict)
    sys_executable: str = sys.executable
    reveal_paths: bool = False
    reveal_endpoints: bool = False
    model_path: Path | None = None
    comfyui_endpoint: str = "http://127.0.0.1:8188"
    smoke_timeout: float = 120.0
    http_timeout: float = 5.0
    expected_sha256: str | None = None
    verify_sha256: bool = False
    import_torch: Callable[[], Any] | None = None
    run_subprocess: Callable[[Sequence[str], float], SubprocessResult] = (
        _default_run_subprocess
    )
    http_get: Callable[[str, float], HttpResult] = _default_http_get

    @classmethod
    def from_os(
        cls, environ: Mapping[str, str] | None = None, **overrides: Any
    ) -> "ProbeEnv":
        """Build an Env from ``os.environ`` (or a test snapshot) + overrides."""
        source = dict(os.environ if environ is None else environ)
        values: dict[str, Any] = {
            "environ": dict(source),
            "sys_executable": sys.executable,
            "reveal_paths": _flag(source.get("RADEON_PROBE_REVEAL_PATHS")),
            "reveal_endpoints": _flag(source.get("RADEON_PROBE_REVEAL_ENDPOINTS")),
            "model_path": _path(source.get("RADEON_PROBE_MODEL_PATH")),
            "comfyui_endpoint": source.get(
                "RADEON_PROBE_COMFYUI_ENDPOINT", "http://127.0.0.1:8188"
            ),
            "smoke_timeout": _float(source.get("RADEON_PROBE_SMOKE_TIMEOUT"), 120.0),
            "http_timeout": _float(source.get("RADEON_PROBE_HTTP_TIMEOUT"), 5.0),
            "expected_sha256": source.get("RADEON_PROBE_EXPECTED_SHA256")
            or DEFAULT_EXPECTED_SHA256,
            "verify_sha256": _flag(source.get("RADEON_PROBE_VERIFY_SHA256")),
            "import_torch": None,
            "run_subprocess": _default_run_subprocess,
            "http_get": _default_http_get,
        }
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True, slots=True)
class ProbeCheck:
    """One probe result.  ``exit_code`` is the code this check contributes."""

    name: str
    status: str
    summary: str
    detail: dict[str, Any]
    exit_code: int = EXIT_PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "detail": dict(self.detail),
            "exit_code": self.exit_code,
        }


@dataclass(frozen=True, slots=True)
class ProbeReport:
    schema_version: int
    timestamp: str
    exit_code: int
    verdict: str
    masking: dict[str, str]
    checks: tuple[ProbeCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "masking": dict(self.masking),
            "checks": [check.to_dict() for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _float(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _path(value: str | None) -> Path | None:
    if not value or not value.strip():
        return None
    return Path(value).expanduser()


def is_loopback_endpoint(value: str) -> bool:
    """True when the URL targets the local machine (safe to display)."""
    try:
        host = (urllib.parse.urlsplit(value).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def mask_path(value: str | None, env: ProbeEnv) -> str | None:
    return value if env.reveal_paths and value is not None else MASKED


def mask_endpoint(value: str, env: ProbeEnv) -> str:
    if env.reveal_endpoints or is_loopback_endpoint(value):
        return value
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return MASKED
    scheme = parts.scheme or "http"
    suffix = parts.path or ""
    if parts.query:
        suffix = f"{suffix}?{parts.query}"
    return f"{scheme}://{MASKED}{suffix}"


_torch_cache: dict[str, Any] = {"module": None, "error": None}


def _real_load_torch() -> Any | None:
    if _torch_cache["error"] is not None:
        return None
    if _torch_cache["module"] is None:
        try:
            import torch

            _torch_cache["module"] = torch
        except Exception as exc:
            _torch_cache["error"] = exc
    return _torch_cache["module"]


def _load_torch(env: ProbeEnv) -> Any | None:
    if env.import_torch is not None:
        try:
            return env.import_torch()
        except Exception:
            return None
    return _real_load_torch()


def _torch_hip_version(torch: Any) -> str | None:
    version = getattr(torch, "version", None)
    if version is None:
        return None
    for attr in ("hip", "rocm"):
        value = getattr(version, attr, None)
        if value:
            return str(value)
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _diagnostics(result: SubprocessResult, env: ProbeEnv) -> dict[str, Any]:
    if env.reveal_paths and env.reveal_endpoints:
        return {
            "stdout_tail": result.stdout[-400:],
            "stderr_tail": result.stderr[-400:],
        }
    return {"diagnostics": "suppressed (use --reveal-paths --reveal-endpoints)"}


def check_python(env: ProbeEnv) -> ProbeCheck:
    detail = {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable": mask_path(env.sys_executable, env),
    }
    return ProbeCheck(
        "python",
        "ok",
        f"Python {detail['version']} ({detail['implementation']})",
        detail,
    )


def check_torch(env: ProbeEnv) -> ProbeCheck:
    try:
        torch = (
            env.import_torch() if env.import_torch is not None else _real_load_torch()
        )
    except Exception as exc:
        return ProbeCheck(
            "torch",
            "fail",
            "torch import failed",
            {"error": type(exc).__name__, "reason": str(exc)},
            EXIT_BACKEND_UNAVAILABLE,
        )
    if torch is None:
        return ProbeCheck(
            "torch",
            "fail",
            "torch import failed",
            {"error": "import raised", "reason": "torch is not available"},
            EXIT_BACKEND_UNAVAILABLE,
        )
    try:
        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count())
    except Exception:
        cuda_available = None
        device_count = None
    detail = {
        "version": str(getattr(torch, "__version__", "unknown")),
        "hip": _torch_hip_version(torch),
        "cuda_available": cuda_available,
        "device_count": device_count,
    }
    return ProbeCheck("torch", "ok", f"torch {detail['version']}", detail)


def check_hip(env: ProbeEnv) -> ProbeCheck:
    torch = _load_torch(env)
    if torch is None:
        return ProbeCheck("hip", "skip", "skipped: torch unavailable", {})
    hip = _torch_hip_version(torch)
    if not hip:
        return ProbeCheck(
            "hip",
            "fail",
            "HIP build not detected",
            {"detected": None, "note": "torch has no HIP/ROCm version marker"},
            EXIT_BACKEND_UNAVAILABLE,
        )
    return ProbeCheck("hip", "ok", f"HIP {hip}", {"version": hip})


def check_gpu(env: ProbeEnv) -> ProbeCheck:
    torch = _load_torch(env)
    if torch is None:
        return ProbeCheck("gpu", "skip", "skipped: torch unavailable", {})
    try:
        available = bool(torch.cuda.is_available())
        count = int(torch.cuda.device_count())
        names = [str(torch.cuda.get_device_name(index)) for index in range(count)]
    except Exception as exc:
        return ProbeCheck(
            "gpu",
            "fail",
            "GPU query failed",
            {"error": type(exc).__name__, "reason": str(exc)},
            EXIT_ENVIRONMENT,
        )
    if not available or count == 0:
        return ProbeCheck(
            "gpu",
            "fail",
            "no GPU visible to PyTorch",
            {"available": False, "count": 0},
            EXIT_BACKEND_UNAVAILABLE,
        )
    detail = {"available": True, "count": count, "names": names}
    summary = f"{count} device(s): {names[0] if names else 'unknown'}"
    return ProbeCheck("gpu", "ok", summary, detail)


def check_vram(env: ProbeEnv) -> ProbeCheck:
    torch = _load_torch(env)
    if torch is None:
        return ProbeCheck("vram", "skip", "skipped: torch unavailable", {})
    try:
        visible = bool(torch.cuda.is_available()) and int(torch.cuda.device_count()) > 0
    except Exception:
        visible = False
    if not visible:
        return ProbeCheck("vram", "skip", "skipped: no GPU visible", {})
    try:
        total = int(torch.cuda.get_device_properties(0).total_memory)
    except Exception as exc:
        return ProbeCheck(
            "vram",
            "fail",
            "VRAM query failed",
            {"error": type(exc).__name__, "reason": str(exc)},
            EXIT_ENVIRONMENT,
        )
    try:
        free, _ = torch.cuda.mem_get_info()
        free_bytes = int(free)
    except Exception:
        free_bytes = None
    detail = {
        "total_bytes": total,
        "total_gib": round(total / (1024**3), 2),
        "free_bytes": free_bytes,
        "free_gib": (
            round(free_bytes / (1024**3), 2) if free_bytes is not None else None
        ),
    }
    return ProbeCheck("vram", "ok", f"{detail['total_gib']} GiB total", detail)


def check_smoke(env: ProbeEnv) -> ProbeCheck:
    if _load_torch(env) is None:
        return ProbeCheck("smoke", "skip", "skipped: torch unavailable", {})
    argv = [env.sys_executable, "-c", SMOKE_SCRIPT]
    try:
        result = env.run_subprocess(argv, env.smoke_timeout)
    except Exception as exc:
        return ProbeCheck(
            "smoke",
            "fail",
            "operator smoke runner failed",
            {"error": type(exc).__name__, "reason": str(exc)},
            EXIT_ENVIRONMENT,
        )
    detail: dict[str, Any] = {
        "elapsed_seconds": round(result.elapsed, 3),
        "timeout_seconds": env.smoke_timeout,
    }
    if result.timed_out:
        detail["timed_out"] = True
        return ProbeCheck(
            "smoke",
            "fail",
            f"operator smoke timed out after {env.smoke_timeout:g}s",
            detail,
            EXIT_ENVIRONMENT,
        )
    if result.spawn_error is not None:
        detail["spawn_error"] = result.spawn_error
        return ProbeCheck(
            "smoke", "fail", "operator smoke could not start", detail, EXIT_ENVIRONMENT
        )
    if result.returncode != 0:
        detail["returncode"] = result.returncode
        detail.update(_diagnostics(result, env))
        return ProbeCheck(
            "smoke",
            "fail",
            f"operator smoke failed (exit {result.returncode})",
            detail,
            EXIT_ENVIRONMENT,
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        detail.update(_diagnostics(result, env))
        return ProbeCheck(
            "smoke",
            "fail",
            "operator smoke produced invalid output",
            detail,
            EXIT_ENVIRONMENT,
        )
    parts = ["CPU matmul"]
    if payload.get("gpu_matmul") is not None:
        parts.append("GPU matmul")
    detail["cpu_matmul"] = payload.get("cpu_matmul")
    detail["gpu_matmul"] = payload.get("gpu_matmul")
    detail["gpu_name"] = payload.get("gpu")
    detail["torch"] = payload.get("torch")
    return ProbeCheck(
        "smoke",
        "ok",
        f"operator smoke passed ({', '.join(parts)}) in {result.elapsed:.2f}s",
        detail,
    )


def check_comfyui(env: ProbeEnv) -> ProbeCheck:
    endpoint = env.comfyui_endpoint.rstrip("/")
    url = f"{endpoint}/system_stats"
    shown = mask_endpoint(url, env)
    try:
        result = env.http_get(url, env.http_timeout)
    except Exception as exc:
        return ProbeCheck(
            "comfyui",
            "fail",
            "ComfyUI health check runner failed",
            {"endpoint": shown, "error": type(exc).__name__, "reason": str(exc)},
            EXIT_ENVIRONMENT,
        )
    detail: dict[str, Any] = {
        "endpoint": shown,
        "timeout_seconds": env.http_timeout,
        "elapsed_seconds": round(result.elapsed, 3),
    }
    if result.error is not None:
        detail["error"] = result.error
        return ProbeCheck(
            "comfyui", "fail", "ComfyUI health check failed", detail, EXIT_BACKEND_UNAVAILABLE
        )
    detail["http_status"] = result.status
    if result.status != 200 or not isinstance(result.payload, dict):
        detail["note"] = "expected HTTP 200 with a JSON /system_stats body"
        return ProbeCheck(
            "comfyui",
            "fail",
            "ComfyUI health check returned an unexpected response",
            detail,
            EXIT_ENVIRONMENT,
        )
    system = result.payload.get("system")
    if isinstance(system, dict):
        for key in (
            "comfyui_version",
            "python_version",
            "torch_version",
            "vram_total",
            "vram_free",
        ):
            if system.get(key) is not None:
                detail[key] = system[key]
    devices = result.payload.get("devices")
    detail["device_count"] = len(devices) if isinstance(devices, list) else None
    return ProbeCheck("comfyui", "ok", f"ComfyUI healthy ({shown})", detail)


def check_model(env: ProbeEnv) -> ProbeCheck:
    if env.model_path is None:
        return ProbeCheck("model", "skip", "skipped: no model path configured", {})
    path = env.model_path
    detail: dict[str, Any] = {
        "path": mask_path(str(path), env),
        "exists": False,
    }
    try:
        stat = path.stat()
    except OSError:
        return ProbeCheck(
            "model", "fail", "model file not found", detail, EXIT_BACKEND_UNAVAILABLE
        )
    if not path.is_file():
        return ProbeCheck(
            "model",
            "fail",
            "model path is not a regular file",
            detail,
            EXIT_BACKEND_UNAVAILABLE,
        )
    detail["exists"] = True
    detail["size_bytes"] = int(stat.st_size)
    detail["size_gib"] = round(stat.st_size / (1024**3), 3)
    if not env.verify_sha256:
        detail["sha256"] = None
        detail["sha256_note"] = (
            "not requested (set RADEON_PROBE_VERIFY_SHA256 or pass --verify-sha256)"
        )
        return ProbeCheck(
            "model", "ok", f"model present ({detail['size_gib']} GiB)", detail
        )
    expected = (env.expected_sha256 or "").strip().lower()
    if not expected:
        detail["sha256_note"] = "verification requested but no expected hash configured"
        return ProbeCheck(
            "model",
            "warn",
            "model present; SHA-256 not verified (no expected hash)",
            detail,
        )
    actual = _sha256_file(path)
    detail["sha256"] = actual
    detail["sha256_expected"] = expected
    if actual != expected:
        return ProbeCheck(
            "model", "fail", "model SHA-256 mismatch", detail, EXIT_ENVIRONMENT
        )
    return ProbeCheck(
        "model",
        "ok",
        f"model present; SHA-256 verified ({actual[:12]}...{actual[-6:]})",
        detail,
    )


def run_probe(env: ProbeEnv) -> ProbeReport:
    checks = [
        check_python(env),
        check_torch(env),
        check_hip(env),
        check_gpu(env),
        check_vram(env),
        check_smoke(env),
        check_comfyui(env),
        check_model(env),
    ]
    exit_code = max((check.exit_code for check in checks), default=EXIT_PASS)
    return ProbeReport(
        schema_version=1,
        timestamp=datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        exit_code=exit_code,
        verdict=VERDICTS.get(exit_code, "UNKNOWN"),
        masking={
            "paths": "masked" if not env.reveal_paths else "revealed",
            "endpoints": "masked" if not env.reveal_endpoints else "revealed",
        },
        checks=tuple(checks),
    )


def probe_from_os() -> ProbeReport:
    """Convenience entry point used by adapters and smoke scripts."""
    return run_probe(ProbeEnv.from_os())


def render_human(report: ProbeReport, env: ProbeEnv) -> str:
    lines = [
        "SpriteFusion 2D - Radeon Environment Probe",
        (
            f"schema {report.schema_version} - {report.timestamp} - "
            f"paths={report.masking['paths']} endpoints={report.masking['endpoints']}"
        ),
        "",
    ]
    for check in report.checks:
        lines.append(f"  {check.name:<8} {check.status:<4} {check.summary}")
    lines.append("")
    lines.append(f"verdict: {report.verdict} (exit {report.exit_code})")
    return "\n".join(lines)
