"""Read-only hardware acceleration status for the desktop settings UI."""

from __future__ import annotations

import csv
import io
import json
import platform
import re
import shutil
import subprocess
from typing import Any

from services.vector_store import get_default_vector_store


MIGRAPHX_PROVIDER = "MIGraphXExecutionProvider"
CUDA_PROVIDER = "CUDAExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"


def _available_onnx_providers() -> list[str]:
    try:
        import onnxruntime

        return list(onnxruntime.get_available_providers())
    except (ImportError, AttributeError, RuntimeError):
        return []


def _flatten_json(value: Any, prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_json(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flattened.update(_flatten_json(item, f"{prefix}.{index}"))
    else:
        flattened[prefix.lower()] = value
    return flattened


def _first_matching(flattened: dict[str, Any], *patterns: str) -> Any:
    for pattern in patterns:
        for key, value in flattened.items():
            if pattern in key and value not in (None, ""):
                return value
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group(0)) if match else None


def _format_bytes(value: int | None) -> str | None:
    if not value:
        return None
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.0f} {unit}" if unit in {"B", "KB"} else f"{amount:.1f} {unit}"
        amount /= 1024
    return None


def _rocm_agent_details() -> dict[str, Any]:
    command = shutil.which("rocminfo") or shutil.which("rocminfo.exe")
    if not command:
        return {}
    try:
        result = subprocess.run(
            [command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    blocks = re.split(r"(?=\n\s*Agent\s+\d+)", result.stdout)
    gpu_block = next(
        (
            block
            for block in blocks
            if re.search(r"Device\s+Type\s*:\s*GPU", block, re.IGNORECASE)
            or re.search(r"Name\s*:\s*gfx\w+", block, re.IGNORECASE)
        ),
        "",
    )
    if not gpu_block:
        return {}
    name = re.search(r"Marketing\s+Name\s*:\s*(.+)", gpu_block, re.IGNORECASE)
    compute_units = re.search(r"Compute\s+Unit\s*:\s*(\d+)", gpu_block, re.IGNORECASE)
    return {
        "gpu_name": name.group(1).strip() if name else None,
        "compute_units": int(compute_units.group(1)) if compute_units else None,
    }


def _detect_rocm_hardware() -> dict[str, Any]:
    command = shutil.which("rocm-smi") or shutil.which("rocm-smi.exe")
    if not command:
        return {
            "detected": False,
            "vendor": "AMD",
            "source": None,
            "detail": "ROCm device tools were not found",
        }

    try:
        result = subprocess.run(
            [
                command,
                "--showproductname",
                "--showdriverversion",
                "--showmeminfo",
                "vram",
                "--showuniqueid",
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
            shell=False,
        )
        flattened = _flatten_json(json.loads(result.stdout))
        vram_bytes = _as_int(_first_matching(flattened, "vram total memory", "vram_total", "total vram"))
        agent = _rocm_agent_details()
        return {
            "detected": True,
            "vendor": "AMD",
            "gpu_name": _first_matching(flattened, "card series", "product name", "device name") or agent.get("gpu_name"),
            "driver_version": _first_matching(flattened, "driver version", "driver_version"),
            "vram_bytes": vram_bytes,
            "vram_human": _format_bytes(vram_bytes),
            "compute_units": _as_int(_first_matching(flattened, "compute unit", "compute_units")) or agent.get("compute_units"),
            "source": "rocm-smi",
            "detail": "ROCm device information detected",
        }
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        return {
            "detected": False,
            "vendor": "AMD",
            "source": "rocm-smi",
            "detail": f"ROCm device query failed: {type(exc).__name__}",
        }


def _detect_cuda_hardware() -> dict[str, Any]:
    command = shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe")
    if not command:
        return {
            "detected": False,
            "vendor": "NVIDIA",
            "source": None,
            "detail": "NVIDIA device tools were not found",
        }
    try:
        result = subprocess.run(
            [
                command,
                "--query-gpu=name,driver_version,memory.total,multiprocessor_count",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
            shell=False,
        )
        row = next(csv.reader(io.StringIO(result.stdout)), None)
        if not row or len(row) < 4:
            raise ValueError("NVIDIA device query returned no usable rows")
        vram_mb = _as_int(row[2])
        vram_bytes = vram_mb * 1024 * 1024 if vram_mb else None
        return {
            "detected": True,
            "vendor": "NVIDIA",
            "gpu_name": row[0].strip() or None,
            "driver_version": row[1].strip() or None,
            "vram_bytes": vram_bytes,
            "vram_human": _format_bytes(vram_bytes),
            "compute_units": _as_int(row[3]),
            "source": "nvidia-smi",
            "detail": "NVIDIA device information detected",
        }
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {
            "detected": False,
            "vendor": "NVIDIA",
            "source": "nvidia-smi",
            "detail": f"NVIDIA device query failed: {type(exc).__name__}",
        }


def build_hardware_acceleration_status(
    runtime: dict[str, Any],
    available_providers: list[str],
    hardware: dict[str, Any],
    system_name: str,
) -> dict[str, Any]:
    effective = runtime.get("execution_provider")
    detail = runtime.get("detail") or ""
    runtime_available = bool(runtime.get("available"))
    rocm_provider_available = MIGRAPHX_PROVIDER in available_providers
    cuda_provider_available = CUDA_PROVIDER in available_providers
    supported_backends = [
        backend
        for backend, available in (
            ("rocm", rocm_provider_available),
            ("cuda", cuda_provider_available),
        )
        if available
    ]
    acceleration_backend = {
        MIGRAPHX_PROVIDER: "rocm",
        CUDA_PROVIDER: "cuda",
    }.get(effective)
    acceleration_active = runtime_available and acceleration_backend is not None
    fallback_active = effective == CPU_PROVIDER and "fallback" in detail.lower()

    if acceleration_active:
        status = "active"
        backend_name = "ROCm" if acceleration_backend == "rocm" else "CUDA"
        message = f"{backend_name} hardware acceleration is active for the local BGE-M3 embedding runtime."
    elif fallback_active:
        status = "fallback"
        message = "GPU initialization failed; embedding work has visibly fallen back to CPU inference."
    elif not runtime_available:
        status = "error"
        message = detail or "The local BGE-M3 embedding runtime is unavailable."
    elif effective is None:
        status = "cold"
        message = "The local BGE-M3 runtime is ready; its execution backend will be selected by the first task."
    elif supported_backends:
        status = "available"
        message = "GPU acceleration is available, but the current BGE-M3 runtime is not using it."
    else:
        status = "unsupported"
        message = "GPU acceleration is not available in the current runtime; BGE-M3 uses CPU inference."

    return {
        "protocol_version": "1.0",
        "status": status,
        "supported": bool(supported_backends),
        "supported_backends": supported_backends,
        "rocm_supported": rocm_provider_available,
        "cuda_supported": cuda_provider_available,
        "acceleration_active": acceleration_active,
        "acceleration_backend": acceleration_backend if acceleration_active else None,
        "fallback_active": fallback_active,
        "fallback_mode": "cpu" if effective == CPU_PROVIDER or fallback_active else None,
        "message": message,
        "platform": system_name,
        "runtime": {
            "available": runtime_available,
            "model_id": runtime.get("model_id"),
            "revision": runtime.get("revision"),
            "execution_provider": effective,
            "available_providers": available_providers,
            "detail": detail,
        },
        "hardware": hardware,
    }


def get_hardware_acceleration_status() -> dict[str, Any]:
    store = get_default_vector_store()
    if store is None:
        runtime = {
            "available": False,
            "model_id": "BAAI/bge-m3",
            "revision": None,
            "execution_provider": None,
            "detail": "Embedding runtime is not initialized",
        }
    else:
        status = store.embedding.status()
        runtime = {
            "available": bool(status.available),
            "model_id": status.model_id,
            "revision": status.revision,
            "execution_provider": status.execution_provider,
            "detail": status.detail,
        }
    available_providers = _available_onnx_providers()
    if (
        runtime.get("execution_provider") == CUDA_PROVIDER
        or CUDA_PROVIDER in available_providers
        and MIGRAPHX_PROVIDER not in available_providers
    ):
        hardware = _detect_cuda_hardware()
    else:
        hardware = _detect_rocm_hardware()
    result = build_hardware_acceleration_status(
        runtime,
        available_providers,
        hardware,
        platform.system(),
    )
    from services.model_runtime.core_service import get_core_embedding_service

    result["core_service"] = get_core_embedding_service().status()
    return result
