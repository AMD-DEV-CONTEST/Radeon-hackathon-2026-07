"""Server-owned RAM, disk and multi-GPU resource discovery."""

from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from services.model_packages.verifier import managed_models_root
from services.model_runtime.contracts import ComputeDeviceSnapshot, ResourceSnapshot, utc_now


def _memory_snapshot_mb() -> tuple[int, int]:
    if platform.system() == "Windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys // (1024 * 1024), status.ullAvailPhys // (1024 * 1024)

    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values = {}
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, raw = line.partition(":")
            match = re.search(r"\d+", raw)
            if match:
                values[key] = int(match.group(0)) // 1024
        return values.get("MemTotal", 0), values.get("MemAvailable", 0)

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = os.sysconf("SC_PHYS_PAGES") * page_size
        available = os.sysconf("SC_AVPHYS_PAGES") * page_size
        return total // (1024 * 1024), available // (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        return 0, 0


def _as_mb(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        amount = int(value)
    else:
        match = re.search(r"\d+", str(value).replace(",", ""))
        amount = int(match.group(0)) if match else 0
    text = str(value).lower()
    if "byte" in text or amount > 1024 * 1024:
        return amount // (1024 * 1024)
    return amount


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{prefix}.{index}"))
    else:
        result[prefix.lower()] = value
    return result


def _first(flattened: dict[str, Any], *patterns: str) -> Any:
    for pattern in patterns:
        for key, value in flattened.items():
            if pattern in key and value not in (None, ""):
                return value
    return None


def _fingerprint(vendor: str, uuid_value: str | None, name: str, driver: str | None) -> str:
    raw = "\x1f".join((vendor, uuid_value or "", name, driver or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_rocm_smi_json(payload: str) -> tuple[ComputeDeviceSnapshot, ...]:
    raw = json.loads(payload)
    cards = raw if isinstance(raw, dict) else {}
    devices = []
    for index, (card_key, card) in enumerate(sorted(cards.items())):
        flattened = _flatten(card)
        name = str(
            _first(flattened, "card series", "product name", "device name")
            or card_key
            or f"AMD GPU {index}"
        )
        driver = _first(flattened, "driver version", "driver_version")
        uuid_value = _first(flattened, "unique id", "unique_id", "uuid")
        total = _as_mb(_first(flattened, "vram total memory", "vram_total", "total vram"))
        used = _as_mb(_first(flattened, "vram total used memory", "vram used", "used vram"))
        free = max(0, total - used)
        utilization = _first(flattened, "gpu use", "gpu_busy_percent", "utilization")
        utilization_match = re.search(r"\d+(?:\.\d+)?", str(utilization or ""))
        devices.append(
            ComputeDeviceSnapshot(
                device_id=f"rocm:{uuid_value or card_key or index}",
                visible_index=index,
                vendor="AMD",
                name=name,
                backend="rocm_migraphx",
                total_vram_mb=total,
                used_vram_mb=used,
                free_vram_mb=free,
                utilization_percent=float(utilization_match.group(0))
                if utilization_match
                else None,
                driver_version=str(driver) if driver else None,
                device_uuid=str(uuid_value) if uuid_value else None,
                source="rocm-smi",
                fingerprint=_fingerprint("AMD", str(uuid_value or card_key), name, str(driver or "")),
            )
        )
    return tuple(devices)


def parse_nvidia_smi_csv(payload: str) -> tuple[ComputeDeviceSnapshot, ...]:
    devices = []
    for row in csv.reader(io.StringIO(payload)):
        if len(row) < 8:
            continue
        index, uuid_value, name, total, used, free, utilization, driver = (
            item.strip() for item in row[:8]
        )
        devices.append(
            ComputeDeviceSnapshot(
                device_id=f"cuda:{uuid_value or index}",
                visible_index=int(index),
                vendor="NVIDIA",
                name=name,
                backend="cuda",
                total_vram_mb=_as_mb(total),
                used_vram_mb=_as_mb(used),
                free_vram_mb=_as_mb(free),
                utilization_percent=float(utilization) if utilization else None,
                driver_version=driver or None,
                device_uuid=uuid_value or None,
                source="nvidia-smi",
                fingerprint=_fingerprint("NVIDIA", uuid_value, name, driver),
            )
        )
    return tuple(devices)


def _json_records(payload: str) -> list[dict[str, Any]]:
    parsed = json.loads(payload)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        if all(isinstance(value, dict) for value in parsed.values()):
            return [
                {"record_key": key, **value}
                for key, value in parsed.items()
                if isinstance(value, dict)
            ]
        return [parsed]
    return []


def parse_amd_smi_json(
    list_payload: str,
    static_payload: str,
    metric_payload: str,
) -> tuple[ComputeDeviceSnapshot, ...]:
    listing = _json_records(list_payload)
    static = _json_records(static_payload)
    metrics = _json_records(metric_payload)

    def index_of(record: dict[str, Any], fallback: int) -> int:
        flattened = _flatten(record)
        return _as_mb(_first(flattened, "gpu", "gpu_id", "device_id")) or fallback

    static_by_index = {index_of(item, index): item for index, item in enumerate(static)}
    metric_by_index = {index_of(item, index): item for index, item in enumerate(metrics)}
    devices = []
    for fallback, listed in enumerate(listing):
        index = index_of(listed, fallback)
        merged = {
            "list": listed,
            "static": static_by_index.get(index, {}),
            "metric": metric_by_index.get(index, {}),
        }
        flattened = _flatten(merged)
        name = str(
            _first(
                flattened,
                "market_name",
                "product_name",
                "asic.name",
                "device_name",
            )
            or f"AMD GPU {index}"
        )
        uuid_value = _first(flattened, "uuid")
        driver = _first(
            flattened,
            "amdgpu_version",
            "driver_version",
            "driver.version",
        )
        total = _as_mb(
            _first(
                flattened,
                "vram.total",
                "vram_total",
                "vram.size.value",
                "vram.size",
            )
        )
        used = _as_mb(
            _first(
                flattened,
                "vram.used",
                "vram_used",
                "vram_usage.used.value",
            )
        )
        free = _as_mb(
            _first(
                flattened,
                "vram.free",
                "vram_free",
                "vram_usage.free.value",
            )
        )
        if not free and total:
            free = max(0, total - used)
        utilization = _first(
            flattened,
            "gfx_activity.value",
            "gfx_util",
            "gpu_use",
            "utilization",
        )
        utilization_match = re.search(r"\d+(?:\.\d+)?", str(utilization or ""))
        devices.append(
            ComputeDeviceSnapshot(
                device_id=f"rocm:{uuid_value or index}",
                visible_index=index,
                vendor="AMD",
                name=name,
                backend="rocm_migraphx",
                total_vram_mb=total,
                used_vram_mb=used,
                free_vram_mb=free,
                utilization_percent=float(utilization_match.group(0))
                if utilization_match
                else None,
                driver_version=str(driver) if driver else None,
                device_uuid=str(uuid_value) if uuid_value else None,
                source="amd-smi",
                fingerprint=_fingerprint(
                    "AMD",
                    str(uuid_value or index),
                    name,
                    str(driver or ""),
                ),
            )
        )
    return tuple(devices)


def _run_probe(command: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        check=True,
        shell=False,
    )
    return result.stdout


def collect_resource_snapshot(model_root: Path | None = None) -> ResourceSnapshot:
    devices: list[ComputeDeviceSnapshot] = []
    errors: list[str] = []

    amd_smi = shutil.which("amd-smi") or shutil.which("amd-smi.exe")
    if amd_smi:
        try:
            devices.extend(
                parse_amd_smi_json(
                    _run_probe([amd_smi, "list", "--json"]),
                    _run_probe([amd_smi, "static", "--json"]),
                    _run_probe([amd_smi, "metric", "--json"]),
                )
            )
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"amd-smi:{type(exc).__name__}")

    rocm = shutil.which("rocm-smi") or shutil.which("rocm-smi.exe")
    if rocm and not any(item.vendor == "AMD" for item in devices):
        try:
            devices.extend(
                parse_rocm_smi_json(
                    _run_probe(
                        [
                            rocm,
                            "--showproductname",
                            "--showdriverversion",
                            "--showmeminfo",
                            "vram",
                            "--showuse",
                            "--showuniqueid",
                            "--json",
                        ]
                    )
                )
            )
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"rocm-smi:{type(exc).__name__}")

    nvidia = shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe")
    if nvidia:
        try:
            known = {item.device_uuid for item in devices if item.device_uuid}
            devices.extend(
                item
                for item in parse_nvidia_smi_csv(
                    _run_probe(
                        [
                            nvidia,
                            "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,"
                            "utilization.gpu,driver_version",
                            "--format=csv,noheader,nounits",
                        ]
                    )
                )
                if item.device_uuid not in known
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            errors.append(f"nvidia-smi:{type(exc).__name__}")

    total_ram, available_ram = _memory_snapshot_mb()
    disk_root = (model_root or managed_models_root()).resolve()
    disk_root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(disk_root)
    return ResourceSnapshot(
        snapshot_id=uuid.uuid4().hex,
        captured_at=utc_now(),
        platform=platform.system(),
        architecture=platform.machine(),
        total_ram_mb=total_ram,
        available_ram_mb=available_ram,
        model_disk_total_mb=disk.total // (1024 * 1024),
        model_disk_free_mb=disk.free // (1024 * 1024),
        devices=tuple(devices),
        probe_errors=tuple(errors),
    )
