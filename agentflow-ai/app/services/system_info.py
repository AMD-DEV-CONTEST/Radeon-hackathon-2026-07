from __future__ import annotations

from ctypes import Structure, byref, c_ulong, c_ulonglong, sizeof
import ctypes
import os
import platform
import shutil
import subprocess
from typing import Any

from app.services.ollama_client import OllamaClient


class MEMORYSTATUSEX(Structure):
    _fields_ = [
        ("dwLength", c_ulong),
        ("dwMemoryLoad", c_ulong),
        ("ullTotalPhys", c_ulonglong),
        ("ullAvailPhys", c_ulonglong),
        ("ullTotalPageFile", c_ulonglong),
        ("ullAvailPageFile", c_ulonglong),
        ("ullTotalVirtual", c_ulonglong),
        ("ullAvailVirtual", c_ulonglong),
        ("ullAvailExtendedVirtual", c_ulonglong),
    ]


def collect_system_info(ollama: OllamaClient) -> dict[str, Any]:
    cpu = {
        "name": platform.processor() or platform.machine() or "Unknown CPU",
        "logical_cores": os.cpu_count() or 1,
    }
    memory = _memory_info()
    gpu = _gpu_info()
    ollama_status = ollama.health()
    return {
        "cpu": cpu,
        "memory": memory,
        "gpu": gpu,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "ollama": {
            "running": ollama_status.running,
            "message": ollama_status.message,
            "available_models": ollama_status.available_models,
            "selected_model": ollama_status.selected_model,
        },
    }


def _memory_info() -> dict[str, Any]:
    system = platform.system().lower()
    try:
        if system == "windows":
            stat = MEMORYSTATUSEX()
            stat.dwLength = sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(stat))
            total = int(stat.ullTotalPhys)
            available = int(stat.ullAvailPhys)
        elif hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            available_pages_key = "SC_AVPHYS_PAGES" if "SC_AVPHYS_PAGES" in os.sysconf_names else "SC_PHYS_PAGES"
            available = os.sysconf("SC_PAGE_SIZE") * os.sysconf(available_pages_key)
        else:
            total = 0
            available = 0
    except Exception:
        total = 0
        available = 0
    return {
        "total_gb": round(total / (1024**3), 2) if total else None,
        "available_gb": round(available / (1024**3), 2) if available else None,
    }


def _gpu_info() -> list[dict[str, Any]]:
    probes = [
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        ["ollama", "ps"],
        ["wmic", "path", "win32_VideoController", "get", "name"],
        ["powershell", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
        ["lspci"],
    ]

    for command in probes:
        if shutil.which(command[0]) is None:
            continue
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=4)
            output = (completed.stdout or completed.stderr or "").strip()
            if not output:
                continue
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            if command[0] == "nvidia-smi":
                return [
                    {
                        "name": parts[0].strip(),
                        "memory_total": parts[1].strip() if len(parts) > 1 else None,
                        "driver": parts[2].strip() if len(parts) > 2 else None,
                    }
                    for parts in [line.split(",") for line in lines]
                ]
            if command[0] == "ollama":
                matching = [line for line in lines if "gpu" in line.lower()]
                if matching:
                    return [{"name": "Ollama Runtime", "details": line} for line in matching]
            if command[0] in {"wmic", "powershell"}:
                cards = [line for line in lines if "name" not in line.lower()]
                if cards:
                    return [{"name": line} for line in cards]
            if command[0] == "lspci":
                gpus = [line for line in lines if "vga" in line.lower() or "3d controller" in line.lower()]
                if gpus:
                    return [{"name": line} for line in gpus]
        except Exception:
            continue
    return [{"name": "GPU information not detected", "details": "AgentFlow AI falls back gracefully to CPU execution."}]
