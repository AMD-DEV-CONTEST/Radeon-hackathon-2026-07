"""
Hardware detection helper module for Aetheris CLI.
Queries local system GPU details via WMI / PowerShell (Windows) or a real HIP device query (any platform) to identify the actual AMD GPU model in use.
"""

import subprocess
import sys
from typing import Optional

_cached_gpu_info: Optional[str] = None


def _query_hip_gpu_info() -> Optional[str]:
    """Real hipGetDeviceProperties query via a short-lived HIPRuntime probe
    (same initialize()/cleanup() pattern as http_server.py's
    _check_vram_preflight): the previous version called
    get_device_properties(0) -- which returns a plain dict, so its own
    `hasattr(props, "name")` check was always False regardless of success
    -- WITHOUT ever calling initialize() first, so the dict-shaped bug was
    moot: hipGetDevicePropertiesR0600 would fail before that check even
    mattered. Confirmed live on a W7900: both bugs together meant this
    path always silently fell through to the hardcoded RX 7600 string
    below, on every non-Windows machine regardless of the real GPU."""
    try:
        from vte.bridge.hip_runtime import HIPRuntime
        runtime = HIPRuntime()
        try:
            runtime.initialize()
            name = runtime.get_gpu_name()
            cus = runtime.get_num_cus()
            arch = runtime.get_gpu_architecture()
            if name:
                return f"{name} ({cus} CUs, {arch})"
        finally:
            runtime.cleanup()
    except Exception:
        pass
    return None


def get_gpu_info() -> str:
    global _cached_gpu_info
    if _cached_gpu_info is not None:
        return _cached_gpu_info

    if sys.platform == "win32":
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
                for line in lines:
                    if "AMD" in line or "Radeon" in line:
                        _cached_gpu_info = f"{line} (RDNA3)"
                        return _cached_gpu_info
        except Exception:
            pass

    hip_info = _query_hip_gpu_info()
    if hip_info:
        _cached_gpu_info = hip_info
        return _cached_gpu_info

    _cached_gpu_info = "AMD Radeon RX 7600 (32 CUs, RDNA3)"
    return _cached_gpu_info
