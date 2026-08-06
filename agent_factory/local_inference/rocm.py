from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any


_ROCM_VERSION_PATHS = (
    Path("/opt/rocm/.info/version"),
    Path("/opt/rocm/.info/version-dev"),
)
_AMD_SMI_TIMEOUT_SECONDS = 5
_PLACEHOLDER_VALUES = {"", "n/a", "na", "none", "unknown"}


@dataclass(frozen=True, slots=True)
class RocmDeviceInfo:
    index: int
    name: str
    total_memory_bytes: int
    used_memory_bytes: int | None = None
    gpu_utilization_percent: float | None = None
    gpu_utilization_source: str = ""
    memory_activity_percent: float | None = None
    temperature_edge_celsius: float | None = None
    temperature_hotspot_celsius: float | None = None
    temperature_memory_celsius: float | None = None
    power_watts: float | None = None
    architecture: str = ""
    pci_bus: str = ""
    pci_device_id: str = ""
    vram_type: str = ""
    compute_units: int | None = None


@dataclass(frozen=True, slots=True)
class RocmRuntimeInfo:
    available: bool
    torch_version: str
    hip_version: str
    rocm_version: str
    device_count: int
    devices: tuple[RocmDeviceInfo, ...]
    telemetry_source: str = ""
    error: str = ""

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def inspect_rocm_runtime(*, require_available: bool = False) -> RocmRuntimeInfo:
    rocm_version = _read_rocm_version()
    try:
        import torch
    except ImportError as exc:
        info = RocmRuntimeInfo(
            available=False,
            torch_version="",
            hip_version="",
            rocm_version=rocm_version,
            device_count=0,
            devices=(),
            error="PyTorch is not installed",
        )
        return _require(info, require_available=require_available, cause=exc)

    hip_version = str(getattr(torch.version, "hip", "") or "")
    torch_version = str(getattr(torch, "__version__", "") or "")
    if not hip_version:
        info = RocmRuntimeInfo(
            available=False,
            torch_version=torch_version,
            hip_version="",
            rocm_version=rocm_version,
            device_count=0,
            devices=(),
            error="PyTorch is not a ROCm build",
        )
        return _require(info, require_available=require_available)
    if not torch.cuda.is_available():
        info = RocmRuntimeInfo(
            available=False,
            torch_version=torch_version,
            hip_version=hip_version,
            rocm_version=rocm_version,
            device_count=0,
            devices=(),
            error="ROCm device is not available",
        )
        return _require(info, require_available=require_available)

    static_devices = _amd_smi_devices(
        "static",
        "--asic",
        "--bus",
        "--vram",
    )
    metric_devices = _amd_smi_devices(
        "metric",
        "--usage",
        "--power",
        "--temperature",
        "--mem-usage",
    )
    kernel_busy_devices = _kernel_gpu_busy_devices()
    rocm_smi_busy_devices = _rocm_smi_busy_devices()

    devices: list[RocmDeviceInfo] = []
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        static = static_devices.get(index, {})
        metrics = metric_devices.get(index, {})
        asic = _mapping(static.get("asic"))
        bus = _mapping(static.get("bus"))
        vram = _mapping(static.get("vram"))
        architecture = _text(asic.get("target_graphics_version"))
        pci_bus = _text(bus.get("bdf"))
        pci_device_id = _text(asic.get("device_id"))
        gpu_utilization, gpu_utilization_source = _gpu_utilization(
            index=index,
            pci_bus=pci_bus,
            kernel_devices=kernel_busy_devices,
            rocm_smi_devices=rocm_smi_busy_devices,
            amd_smi_metrics=metrics,
        )

        torch_name = _text(getattr(properties, "name", ""))
        name = _device_name(
            market_name=_text(asic.get("market_name")),
            torch_name=torch_name,
            pci_bus=pci_bus,
            pci_device_id=pci_device_id,
            architecture=architecture,
        )
        total_memory_bytes = int(getattr(properties, "total_memory", 0) or 0)
        if total_memory_bytes <= 0:
            total_memory_bytes = _memory_bytes(metrics, "mem_usage", "total_vram") or 0

        devices.append(
            RocmDeviceInfo(
                index=index,
                name=name,
                total_memory_bytes=total_memory_bytes,
                used_memory_bytes=_memory_bytes(metrics, "mem_usage", "used_vram"),
                gpu_utilization_percent=gpu_utilization,
                gpu_utilization_source=gpu_utilization_source,
                memory_activity_percent=_number(metrics, "usage", "umc_activity"),
                temperature_edge_celsius=_number(metrics, "temperature", "edge"),
                temperature_hotspot_celsius=_number(metrics, "temperature", "hotspot"),
                temperature_memory_celsius=_number(metrics, "temperature", "mem"),
                power_watts=_number(metrics, "power", "socket_power"),
                architecture=architecture,
                pci_bus=pci_bus,
                pci_device_id=pci_device_id,
                vram_type=_text(vram.get("type")),
                compute_units=_integer(asic.get("num_compute_units")),
            )
        )

    info = RocmRuntimeInfo(
        available=True,
        torch_version=torch_version,
        hip_version=hip_version,
        rocm_version=rocm_version,
        device_count=len(devices),
        devices=tuple(devices),
        telemetry_source=_telemetry_source(
            kernel_busy_devices=kernel_busy_devices,
            rocm_smi_busy_devices=rocm_smi_busy_devices,
            amd_smi_available=bool(metric_devices),
        ),
    )
    return _require(info, require_available=require_available)


def _read_rocm_version() -> str:
    for path in _ROCM_VERSION_PATHS:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value.splitlines()[0].strip()
    return ""


def _amd_smi_devices(command: str, *arguments: str) -> dict[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            ["amd-smi", command, *arguments, "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_AMD_SMI_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}
    raw_devices = payload.get("gpu_data") if isinstance(payload, dict) else None
    if not isinstance(raw_devices, list):
        return {}
    devices: dict[int, dict[str, Any]] = {}
    for raw_device in raw_devices:
        if not isinstance(raw_device, dict):
            continue
        index = _integer(raw_device.get("gpu"))
        if index is not None:
            devices[index] = raw_device
    return devices


def _kernel_gpu_busy_devices() -> dict[str, float]:
    devices: dict[str, float] = {}
    for busy_path in sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")):
        value = _percent(_read_text(busy_path))
        if value is None:
            continue
        pci_bus = _pci_bus_from_sysfs_device(busy_path.parent)
        if pci_bus:
            devices[pci_bus] = value
    return devices


def _rocm_smi_busy_devices() -> dict[int, float]:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showuse", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_AMD_SMI_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    devices: dict[int, float] = {}
    for card_name, metrics in payload.items():
        match = re.fullmatch(r"card(\d+)", str(card_name).strip().lower())
        if match is None or not isinstance(metrics, dict):
            continue
        value = next(
            (
                _percent(metric_value)
                for metric_name, metric_value in metrics.items()
                if "gpu use" in str(metric_name).strip().lower()
            ),
            None,
        )
        if value is not None:
            devices[int(match.group(1))] = value
    return devices


def _gpu_utilization(
    *,
    index: int,
    pci_bus: str,
    kernel_devices: dict[str, float],
    rocm_smi_devices: dict[int, float],
    amd_smi_metrics: dict[str, Any],
) -> tuple[float | None, str]:
    value = _percent(_number(amd_smi_metrics, "usage", "gfx_activity"))
    if value is not None:
        return value, "amd-smi"
    if index in rocm_smi_devices:
        return rocm_smi_devices[index], "rocm-smi"
    normalized_bus = _normalize_pci_bus(pci_bus)
    if normalized_bus and normalized_bus in kernel_devices:
        return kernel_devices[normalized_bus], "linux-sysfs"
    return None, ""


def _telemetry_source(
    *,
    kernel_busy_devices: dict[str, float],
    rocm_smi_busy_devices: dict[int, float],
    amd_smi_available: bool,
) -> str:
    sources = [
        source
        for available, source in (
            (amd_smi_available, "amd-smi"),
            (bool(rocm_smi_busy_devices), "rocm-smi"),
            (bool(kernel_busy_devices), "linux-sysfs"),
        )
        if available
    ]
    return "+".join(sources) if sources else "torch"


def _pci_bus_from_sysfs_device(device_path: Path) -> str:
    try:
        resolved_name = device_path.resolve(strict=True).name
    except OSError:
        return ""
    return _normalize_pci_bus(resolved_name)


def _normalize_pci_bus(value: str) -> str:
    match = re.search(r"(?:[0-9a-fA-F]{4}:)?[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", value)
    if match is None:
        return ""
    bus = match.group(0).lower()
    return bus if bus.count(":") == 2 else f"0000:{bus}"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _percent(value: object) -> float | None:
    try:
        number = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 100.0 else None


def _device_name(
    *,
    market_name: str,
    torch_name: str,
    pci_bus: str,
    pci_device_id: str,
    architecture: str,
) -> str:
    if _usable_name(market_name):
        return market_name
    if _usable_name(torch_name):
        return torch_name
    pci_name = _lspci_name(pci_bus)
    if pci_name:
        return pci_name
    identity = [value for value in (pci_device_id, architecture) if value]
    return " · ".join(("AMD GPU", *identity))


def _usable_name(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized not in _PLACEHOLDER_VALUES and re.fullmatch(r"0x[0-9a-f]+", normalized) is None


def _lspci_name(pci_bus: str) -> str:
    if not pci_bus:
        return ""
    try:
        result = subprocess.run(
            ["lspci", "-s", pci_bus, "-nn"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_AMD_SMI_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    description = result.stdout.strip().partition(": ")[2]
    description = re.sub(r"\s+\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\].*$", "", description).strip()
    if not description or re.search(r"\bDevice\b", description):
        return ""
    return description


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _PLACEHOLDER_VALUES else text


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(payload: dict[str, Any], *path: str) -> float | None:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _memory_bytes(payload: dict[str, Any], *path: str) -> int | None:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if not isinstance(value, dict):
        return None
    amount = _number(value)
    if amount is None:
        return None
    unit = _text(value.get("unit")).lower()
    multipliers = {
        "b": 1,
        "kb": 1024,
        "mb": 1024**2,
        "gb": 1024**3,
        "tb": 1024**4,
    }
    multiplier = multipliers.get(unit)
    return int(amount * multiplier) if multiplier is not None else None


def _require(
    info: RocmRuntimeInfo,
    *,
    require_available: bool,
    cause: Exception | None = None,
) -> RocmRuntimeInfo:
    if require_available and not info.available:
        error = RuntimeError(info.error or "ROCm runtime is unavailable")
        if cause is not None:
            raise error from cause
        raise error
    return info
