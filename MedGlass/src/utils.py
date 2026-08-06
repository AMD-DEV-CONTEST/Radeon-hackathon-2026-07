"""Utility helpers: GPU detection, benchmarking, logging, audio IO."""

from __future__ import annotations

import contextlib
import json
import logging
import platform
import random as _random
import shutil
import subprocess
import time
from pathlib import Path

LOG = logging.getLogger("medglass")

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)


class MedGlassError(Exception):
    """Base error for the MedGlass pipeline."""


# --------------------------------------------------------------------------
# GPU detection
# --------------------------------------------------------------------------

def detect_gpu() -> dict:
    """Probe for an AMD GPU / ROCm stack.

    Prefers the authoritative ``rocm-smi`` when the ROCm userspace is
    installed, and otherwise falls back to kernel-level detection
    (``/dev/kfd`` + amdgpu sysfs + lspci), which works on this rig even
    before ROCm is installed. Returns a dict like::

        {"available": True, "name": "AMD Radeon AI PRO R9700",
         "vram_gb": 32.0, "rocm_version": "7.2", "driver": "amdgpu (kernel)"}
    """
    info = {"available": False, "name": None, "vram_gb": None,
            "rocm_version": None, "driver": None}

    # Kernel-level detection (amdgpu + KFD) is the most stable source of
    # truth: it yields the lspci product name, VRAM from the KFD framebuffer
    # heap and the driver without depending on ROCm-SMI output formats.
    kernel = _detect_gpu_kernel()
    if kernel.get("available"):
        if kernel.get("name"):
            kernel["rocm_version"] = rocm_version()
            return kernel

    # Fall back to rocm-smi parsing when the kernel path cannot identify the
    # card (e.g. no /dev/kfd).
    rocm_smi = shutil.which("rocm-smi")
    if rocm_smi is not None:
        try:
            out = subprocess.run(
                [rocm_smi, "--showproductname", "--showmeminfo", "vram",
                 "--showdriver"],
                capture_output=True, text=True, timeout=15,
            ).stdout
        except (subprocess.SubprocessError, OSError) as exc:
            LOG.warning("rocm-smi probe failed: %s", exc)
            out = ""
        if out:
            name = None
            vram = None
            driver = None
            for line in out.splitlines():
                line = line.strip()
                if "Card Series" in line:
                    name = line.split(":", 1)[1].strip()
                elif "VRAM Total Memory (B)" in line or \
                        "VRAM Size" in line:
                    vram = _parse_vram(line)
                if "Driver Version" in line or \
                        ("KFD" in line and "Version" in line):
                    driver = line.split(":", 1)[1].strip()
            if name:
                info.update(available=True, name=name, vram_gb=vram,
                            driver=driver)
                info["rocm_version"] = rocm_version()
                return info
    return info


# Navi 48 RDNA4 product names for device-id lookup (lspci is preferred).
_AMD_DEVICE_NAMES = {
    0x7551: "AMD Radeon AI PRO R9700 (Navi 48)",
}


def _detect_gpu_kernel() -> dict:
    """Kernel-level AMD GPU detection for boxes without the ROCm userspace."""
    info = {"available": False, "name": None, "vram_gb": None,
            "rocm_version": None, "driver": None}
    if not Path("/dev/kfd").exists():
        LOG.info("no /dev/kfd; amdgpu compute (KFD) not present")
        return info

    # Find the amdgpu DRM card.
    amd_card = None
    device_id = None
    for card in sorted(Path("/sys/class/drm").glob("card*")):
        dev = card / "device"
        try:
            vendor = (dev / "vendor").read_text().strip()
        except OSError:
            continue
        if vendor == "0x1002":
            amd_card = card
            try:
                device_id = int((dev / "device").read_text().strip(), 16)
            except (OSError, ValueError):
                device_id = None
            break
    if amd_card is None:
        LOG.info("no amdgpu DRM card found")
        return info

    info["driver"] = "amdgpu (kernel)"
    info["rocm_version"] = rocm_version() or _ollama_rocm_version()
    info["vram_gb"] = _sysfs_vram_gb()
    name = _lspci_vga_name() or _AMD_DEVICE_NAMES.get(device_id or 0)
    if name:
        info["name"] = name
    info["available"] = True
    LOG.info("detected AMD GPU at kernel level: %s", info["name"])
    return info


def _sysfs_vram_gb() -> float | None:
    """VRAM size (GB) from the kernel (works without ROCm userspace).

    Prefers the KFD framebuffer heap (``heap_type 1`` = VRAM); falls back to
    the amdgpu ``mem_info/vram_total`` attribute when present.
    """
    for props in Path("/sys/class/kfd/kfd/topology").glob(
            "nodes/*/mem_banks/*/properties"):
        try:
            text = props.read_text()
        except OSError:
            continue
        if "heap_type 1" in text:  # HSA_MEMORY_HEAP_TYPE_FRAMEBUFFER
            for line in text.splitlines():
                if line.startswith("size_in_bytes"):
                    try:
                        return round(int(line.split()[-1]) / 1024**3, 1)
                    except ValueError:
                        return None
    total = 0
    found = False
    for card in Path("/sys/class/drm").glob("card*"):
        mem = card / "device" / "mem_info" / "vram_total"
        if mem.exists():
            try:
                total += int(mem.read_text().strip())
                found = True
            except (OSError, ValueError):
                continue
    return round(total / 1024**3, 1) if found else None


def _lspci_vga_name() -> str | None:
    """Best-effort GPU product name from lspci (no ROCm needed)."""
    import re
    lspci = shutil.which("lspci")
    if lspci is None:
        return None
    try:
        out = subprocess.run(
            [lspci, "-nn"], capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    for line in out.splitlines():
        if "VGA compatible controller" in line and "AMD" in line:
            # e.g. "... [AMD/ATI] Navi 48 [Radeon AI PRO R9700] [1002:7551] (rev c0)"
            m = re.search(
                r"\[AMD/ATI\]\s*(.*?)"
                r"(?:\s*\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\])?"
                r"(?:\s*\(rev[^)]*\))?\s*$",
                line)
            if m:
                return m.group(1).strip() or None
    return None


def _ollama_rocm_version() -> str | None:
    """Report the ROCm runtime version bundled with a local Ollama install."""
    for pattern in ("/usr/lib/ollama/rocm_v*",
                    "/usr/local/lib/ollama/rocm_v*"):
        hits = sorted(Path("/").glob(pattern.lstrip("/")))
        for hit in reversed(hits):
            version = hit.name.replace("rocm_v", "").replace("_", ".")
            return f"{version} (bundled with ollama)"
    return None


def _parse_vram(line: str) -> float | None:
    """Parse a VRAM line into GB.

    Handles both historical ('VRAM Size ... (12345 MB)') and current
    ROCm-SMI formats ('VRAM Total Memory (B): 34208743424').
    """
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*MB", line)
    if m:
        return round(float(m.group(1)) / 1024, 1)
    m = re.search(r":\s*(\d+(?:\.\d+)?)", line)
    if m:
        return round(float(m.group(1)) / 1024**3, 1)
    return None


def rocm_version() -> str | None:
    """Report the ROCm compute-stack version.

    Prefers the HIP compiler version (authoritative for the compute stack),
    then rocm-smi, then the runtime bundled with a local Ollama install.
    """
    hipcc = shutil.which("hipcc")
    if hipcc is not None:
        try:
            out = subprocess.run(
                [hipcc, "--version"], capture_output=True, text=True,
                timeout=10,
            ).stdout
        except (subprocess.SubprocessError, OSError):
            out = ""
        for line in out.splitlines():
            if line.lower().startswith("hip version"):
                ver = line.split(":", 1)[1].strip()
                base = ver.split("-")[0].split(".")[:2]
                if base:
                    return ".".join(base) + " (system ROCm)"
    rocm_smi = shutil.which("rocm-smi")
    if rocm_smi is not None:
        try:
            out = subprocess.run(
                [rocm_smi, "--version"], capture_output=True, text=True,
                timeout=10,
            ).stdout
        except (subprocess.SubprocessError, OSError):
            out = ""
        if out:
            first = out.strip().splitlines()[0].strip()
            if first:
                return first
    return _ollama_rocm_version()


# --------------------------------------------------------------------------
# Benchmarking helpers
# --------------------------------------------------------------------------

class Timer:
    """Context manager that records elapsed wall time into a dict (ms)."""

    def __init__(self, results: dict, key: str) -> None:
        self.results = results
        self.key = key
        self._start = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.results[self.key] = round((time.perf_counter() - self._start) * 1000, 2)


def write_json(path: Path | str, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


def read_json(path: Path | str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Audio IO
# --------------------------------------------------------------------------

def pcm16_to_wav(pcm: bytes, sample_rate: int = 16000,
                 channels: int = 1) -> bytes:
    """Wrap raw 16-bit little-endian PCM into a WAV container.

    Whisper.cpp's --file accepts raw PCM with -t raw, but a WAV is portable
    and lets us feed whisper.cpp without special flags.
    """
    import wave
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def write_wav(path: Path | str, pcm: bytes, sample_rate: int = 16000) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(pcm16_to_wav(pcm, sample_rate))
    return path


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------

def platform_label() -> str:
    return f"{platform.system()}/{platform.machine()}"


# Synthetic (clearly fictional) patient names used when the operator does not
# provide a real one, so the demo never leaks a real patient identity.
_FIRST_NAMES = [
    "Alex", "Jamie", "Taylor", "Jordan", "Morgan", "Casey", "Riley",
    "Avery", "Quinn", "Parker", "Rowan", "Sage", "Skyler", "Reese",
    "Emerson", "Hayden", "Cameron", "Logan", "Drew", "Marlowe",
]
_LAST_NAMES = [
    "Brooks", "Carter", "Hayes", "Reed", "Ellis", "Grant", "Hughes",
    "Mills", "Palmer", "Rhodes", "Stone", "Vaughn", "Ward", "Mercer",
    "Bishop", "Frost", "Nash", "Spencer", "Wells", "Yates",
]


def random_patient_name() -> str:
    """Return a random synthetic patient name (never a real person)."""
    return f"{_random.choice(_FIRST_NAMES)} {_random.choice(_LAST_NAMES)}"
