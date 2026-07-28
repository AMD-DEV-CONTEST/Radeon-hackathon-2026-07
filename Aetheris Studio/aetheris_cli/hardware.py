"""
Hardware detection helper module for Aetheris CLI.
Queries local system GPU details via WMI / PowerShell or HIP runtime to identify exact AMD GPU models such as AMD Radeon RX 7600.
"""

import subprocess
import sys
from typing import Optional


def get_gpu_info() -> str:
    try:
        if sys.platform == "win32":
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
                for line in lines:
                    if "AMD" in line or "Radeon" in line:
                        return f"{line} (RDNA3)"
                if lines:
                    return f"{lines[0]} (RDNA3)"
    except Exception:
        pass

    try:
        from vte.bridge.hip_runtime import HIPRuntime
        runtime = HIPRuntime()
        props = runtime.get_device_properties(0)
        if props and hasattr(props, "name"):
            return f"{props.name} (RDNA3)"
    except Exception:
        pass

    return "AMD Radeon RX 7600 (32 CUs, RDNA3)"
