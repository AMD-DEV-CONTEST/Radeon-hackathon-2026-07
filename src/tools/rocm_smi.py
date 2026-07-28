"""
Wrapper for rocm-smi CLI inspection tool.

Returns a structured dict of GPU utilization, VRAM usage, temperature, and clocks.
Includes mock mode for development on systems without ROCm.
"""

import json
import subprocess
from typing import Optional


MOCK_SMI_OUTPUT = {
    "device_count": 1,
    "devices": [
        {
            "id": 0,
            "name": "AMD Radeon RX 7900 XTX (mock)",
            "utilization_gpu_pct": 87,
            "utilization_mem_pct": 63,
            "vram_total_mb": 24576,
            "vram_used_mb": 15523,
            "vram_free_mb": 9053,
            "temperature_c": 72,
            "power_draw_w": 315.0,
            "clock_gpu_mhz": 2500,
            "clock_mem_mhz": 2400,
            "pcie_bandwidth_gbps": None,
        }
    ],
}


def run_rocm_smi(mock: bool = False) -> dict:
    """
    Query rocm-smi and return a structured dict.

    Args:
        mock: If True, return synthetic data (for development without a Radeon GPU).

    Returns:
        {
            "device_count": int,
            "devices": [
                {
                    "id": int,
                    "name": str,
                    "utilization_gpu_pct": int,
                    "utilization_mem_pct": int,
                    "vram_total_mb": int,
                    "vram_used_mb": int,
                    "vram_free_mb": int,
                    "temperature_c": int | None,
                    "power_draw_w": float | None,
                    "clock_gpu_mhz": int | None,
                    "clock_mem_mhz": int | None,
                }
            ],
            "error": str | None  # present only on failure
        }
    """
    if mock:
        return MOCK_SMI_OUTPUT

    try:
        result = subprocess.run(
            ["rocm-smi", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return _error_result("rocm-smi not found — is ROCm installed?")
    except subprocess.TimeoutExpired:
        return _error_result("rocm-smi timed out after 10 seconds.")

    if result.returncode != 0:
        return _error_result(f"rocm-smi exited with code {result.returncode}: {result.stderr.strip()}")

    return _parse_rocm_smi_json(result.stdout)


def _parse_rocm_smi_json(raw_json: str) -> dict:
    """Parse the JSON output from `rocm-smi --json`."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        return _error_result(f"Failed to parse rocm-smi JSON: {e}")

    devices = []
    for device_key, device_data in data.items():
        if not device_key.startswith("card") and device_key != "system":
            continue
        if device_key == "system":
            continue

        try:
            device_id = int(device_key.replace("card", ""))
        except ValueError:
            device_id = len(devices)

        def _get(field: str, cast=None) -> Optional[object]:
            val = device_data.get(field)
            if val is None or val == "N/A":
                return None
            try:
                return cast(val) if cast else val
            except (ValueError, TypeError):
                return None

        vram_total = _parse_mb(_get("VRAM Total Memory (B)"))
        vram_used = _parse_mb(_get("VRAM Total Used Memory (B)"))
        vram_free = (vram_total - vram_used) if (vram_total and vram_used) else None

        devices.append({
            "id": device_id,
            "name": _get("Card series") or _get("Card model") or f"GPU card{device_id}",
            "utilization_gpu_pct": _get("GPU use (%)", int),
            "utilization_mem_pct": _get("GPU memory use (%)", int),
            "vram_total_mb": vram_total,
            "vram_used_mb": vram_used,
            "vram_free_mb": vram_free,
            "temperature_c": _get("Temperature (Sensor junction) (C)", int),
            "power_draw_w": _get("Average Graphics Package Power (W)", float),
            "clock_gpu_mhz": _get("sclk clock speed:", int),
            "clock_mem_mhz": _get("mclk clock speed:", int),
            "pcie_bandwidth_gbps": None,
        })

    return {"device_count": len(devices), "devices": devices, "error": None}


def _parse_mb(bytes_val) -> Optional[int]:
    """Convert bytes value to MB."""
    try:
        return int(bytes_val) // (1024 * 1024)
    except (TypeError, ValueError):
        return None


def _error_result(msg: str) -> dict:
    return {"device_count": 0, "devices": [], "error": msg}


def format_smi_summary(smi_data: dict) -> str:
    """Format rocm-smi output as a concise text summary for the LLM prompt."""
    if smi_data.get("error"):
        return f"[rocm-smi error] {smi_data['error']}"

    lines = []
    for dev in smi_data["devices"]:
        lines.append(
            f"GPU {dev['id']} ({dev['name']}): "
            f"util={dev['utilization_gpu_pct']}% | "
            f"VRAM {dev['vram_used_mb']}MB/{dev['vram_total_mb']}MB | "
            f"temp={dev['temperature_c']}°C | "
            f"power={dev['power_draw_w']}W | "
            f"sclk={dev['clock_gpu_mhz']}MHz mclk={dev['clock_mem_mhz']}MHz"
        )
    return "\n".join(lines) if lines else "No GPU devices found."
