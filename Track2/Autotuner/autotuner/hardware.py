from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _run(command: List[str], timeout: int = 15) -> Tuple[int, str]:
    try:
        process = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    output = process.stdout.strip() or process.stderr.strip()
    return process.returncode, output


def _version(command: str, arguments: List[str]) -> str:
    path = shutil.which(command)
    if not path:
        return "not found"
    code, output = _run([path] + arguments)
    if code != 0:
        return "available"
    return output.splitlines()[0] if output else "available"


def inspect_hardware() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "rocm_smi": _version("rocm-smi", ["--version"]),
        "rocprofv3": _version("rocprofv3", ["--version"]),
        "vllm": _version("vllm", ["--version"]),
        "gpu_names": [],
        "gfx_targets": [],
        "raw": {},
    }
    amd_smi = shutil.which("amd-smi")
    if amd_smi:
        code, output = _run([amd_smi, "static", "--json"])
        if code == 0:
            try:
                result["raw"]["amd_smi"] = json.loads(output)
            except json.JSONDecodeError:
                result["raw"]["amd_smi"] = output
    rocm_smi = shutil.which("rocm-smi")
    if rocm_smi:
        code, output = _run(
            [
                rocm_smi,
                "--showproductname",
                "--showmeminfo",
                "vram",
                "--showdriverversion",
                "--json",
            ]
        )
        if code == 0:
            try:
                payload = json.loads(output)
                result["raw"]["rocm_smi"] = payload
                names = _find_values(payload, ("card series", "card model"))
                result["gpu_names"] = sorted(set(str(item) for item in names))
            except json.JSONDecodeError:
                result["raw"]["rocm_smi"] = output
    rocminfo = shutil.which("rocminfo")
    if rocminfo:
        code, output = _run([rocminfo])
        if code == 0:
            targets = re.findall(r"\b(gfx[0-9a-z]+)\b", output)
            result["gfx_targets"] = sorted(set(targets))
            if not result["gpu_names"]:
                names = re.findall(r"Marketing Name:\s*(.+)", output)
                result["gpu_names"] = sorted(
                    set(name.strip() for name in names if name.strip())
                )
    return result


def _find_values(value: Any, needles: Iterable[str]) -> List[Any]:
    lowered = tuple(item.lower() for item in needles)
    found: List[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if any(needle in str(key).lower() for needle in lowered):
                found.append(child)
            found.extend(_find_values(child, needles))
    elif isinstance(value, list):
        for child in value:
            found.extend(_find_values(child, needles))
    return found


def _number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value).replace(",", ""))
    return float(match.group(1)) if match else 0.0


class TelemetrySampler:
    def __init__(self, interval_seconds: float = 0.5) -> None:
        self.interval_seconds = interval_seconds
        self.samples: List[Dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not shutil.which("rocm-smi"):
            return
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def peak_vram_mb(self) -> float:
        values = [sample.get("vram_used_mb", 0.0) for sample in self.samples]
        return max(values, default=0.0)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf8") as handle:
            json.dump(self.samples, handle, indent=2)
            handle.write("\n")

    def _sample_loop(self) -> None:
        command = [
            "rocm-smi",
            "--showuse",
            "--showmeminfo",
            "vram",
            "--showpower",
            "--json",
        ]
        while not self._stop.wait(self.interval_seconds):
            code, output = _run(command, timeout=5)
            if code != 0:
                continue
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                continue
            used = _find_values(
                payload,
                (
                    "vram total used memory",
                    "vram used memory",
                    "vram memory used",
                ),
            )
            use = _find_values(payload, ("gpu use", "gpu utilization"))
            power = _find_values(payload, ("average graphics package power",))
            used_value = max((_number(item) for item in used), default=0.0)
            if used_value > 1024 * 1024:
                used_value /= 1024 * 1024
            self.samples.append(
                {
                    "vram_used_mb": used_value,
                    "gpu_use_percent": max(
                        (_number(item) for item in use), default=0.0
                    ),
                    "power_watts": max(
                        (_number(item) for item in power), default=0.0
                    ),
                }
            )
