"""
scripts/hardware_profiler.py — Determinex Auto-Hardware Profiling & Tier Selection

On first launch, Determinex silently profiles the system (VRAM, OS, CPU, CUDA version)
and selects the optimal operational tier without any user intervention.

The tier determines:
  - Which model GGUFs to download (1.5B, 3B, 7B, or 13B+)
  - Which llama-cpp-python wheel to install (CUDA, Metal, Vulkan, CPU-only)
  - Whether to enable GPU offloading and how many layers
  - API fallback behavior when local capability is insufficient

Tiers:
    Tier 3 — High-end (≥24GB VRAM): 13B+ models, full GPU, all features
    Tier 2 — Mid-range (8–24GB VRAM): 7B models, full GPU offload
    Tier 1 — Entry (4–8GB VRAM): 3B model, partial GPU offload
    Tier 0 — Minimal (<4GB VRAM / CPU): 1.5B model + API fallback

Usage:
    profiler = HardwareProfiler()
    profile  = profiler.profile()
    tier     = TierProfile.from_system_profile(profile)
    print(tier.summary())

    # Auto-install the correct llama-cpp-python build:
    tier.install_llama_cpp()
"""

import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------


@dataclass
class GPUInfo:
    vendor: str = "unknown"  # "nvidia", "amd", "apple", "intel", "none"
    name: str = ""
    vram_gb: float = 0.0
    cuda_version: str = ""  # e.g. "12.1" — empty if no CUDA
    compute_capability: str = ""  # e.g. "8.6" for RTX 30xx
    driver_version: str = ""
    metal_supported: bool = False  # macOS Apple Silicon / AMD
    vulkan_supported: bool = False  # AMD / Intel on Linux/Windows


@dataclass
class CPUInfo:
    name: str = ""
    cores: int = 1
    avx2: bool = False
    avx512: bool = False
    arch: str = ""  # "x86_64", "arm64"


@dataclass
class OSInfo:
    platform: str = ""  # "windows", "linux", "darwin"
    version: str = ""
    arch: str = ""
    python_version: str = ""


@dataclass
class SystemProfile:
    gpu: GPUInfo = field(default_factory=GPUInfo)
    cpu: CPUInfo = field(default_factory=CPUInfo)
    os: OSInfo = field(default_factory=OSInfo)

    def to_dict(self) -> dict:
        return {
            "gpu": self.gpu.__dict__,
            "cpu": self.cpu.__dict__,
            "os": self.os.__dict__,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# WHEEL INDEX
# Maps detected CUDA version → llama-cpp-python extra-index-url
# Source: https://abetlen.github.io/llama-cpp-python/whl/
# ---------------------------------------------------------------------------

_CUDA_WHEEL_INDEX = {
    "12.5": "https://abetlen.github.io/llama-cpp-python/whl/cu125",
    "12.4": "https://abetlen.github.io/llama-cpp-python/whl/cu124",
    "12.3": "https://abetlen.github.io/llama-cpp-python/whl/cu123",
    "12.2": "https://abetlen.github.io/llama-cpp-python/whl/cu122",
    "12.1": "https://abetlen.github.io/llama-cpp-python/whl/cu121",
    "11.8": "https://abetlen.github.io/llama-cpp-python/whl/cu118",
    "11.7": "https://abetlen.github.io/llama-cpp-python/whl/cu117",
}
_METAL_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/metal"
_VULKAN_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/vulkan"
_CPU_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/cpu"

_LLAMA_CPP_PACKAGE_VERSION = "0.3.4"  # update on new stable release


# ---------------------------------------------------------------------------
# MODEL SPECS
# ---------------------------------------------------------------------------


@dataclass
class ModelSpec:
    name: str  # e.g. "determinex-7-large-v1.1"
    size_gb: float
    hf_id: str  # HuggingFace model ID for GGUF download
    n_gpu_layers: int = -1  # -1 = all layers on GPU


@dataclass
class TierProfile:
    tier: int
    label: str
    vram_gb_detected: float
    gpu_vendor: str
    models: list[ModelSpec]
    wheel_index_url: str
    n_gpu_layers: int  # recommended GPU offload layers
    api_fallback: bool  # whether to offer API fallback for heavy tasks

    def summary(self) -> str:
        lines = [
            "Determinex Hardware Profile",
            f"  Tier:        {self.tier} — {self.label}",
            f"  GPU:         {self.gpu_vendor} ({self.vram_gb_detected:.1f} GB VRAM)",
            f"  Models:      {', '.join(m.name for m in self.models)}",
            f"  GPU layers:  {self.n_gpu_layers} (-1 = all)",
            f"  API fallback:{self.api_fallback}",
            f"  Wheel index: {self.wheel_index_url}",
        ]
        return "\n".join(lines)

    def pip_install_command(self) -> str:
        """Return the exact pip command to install the correct llama-cpp-python."""
        return (
            f"pip install llama-cpp-python=={_LLAMA_CPP_PACKAGE_VERSION} "
            f"--extra-index-url {self.wheel_index_url}"
        )

    def install_llama_cpp(self, dry_run: bool = False) -> bool:
        """
        Install the correct llama-cpp-python wheel for this hardware profile.

        Args:
            dry_run: if True, print the command but don't execute.

        Returns:
            True on success, False on failure.
        """
        cmd = self.pip_install_command()
        print(f"[HardwareProfiler] Installing: {cmd}", flush=True)
        if dry_run:
            print("[HardwareProfiler] dry_run=True — skipping execution.", flush=True)
            return True
        try:
            result = subprocess.run(
                [sys.executable, "-m"] + cmd.split()[1:],
                capture_output=False,
                timeout=300,
            )
            success = result.returncode == 0
            if success:
                print("[HardwareProfiler] Install successful.", flush=True)
            else:
                print(f"[HardwareProfiler] Install failed (exit {result.returncode}).", flush=True)
            return success
        except Exception as e:
            print(f"[HardwareProfiler] Install error: {e}", flush=True)
            return False

    @classmethod
    def from_system_profile(cls, profile: "SystemProfile") -> "TierProfile":
        vram = profile.gpu.vram_gb
        vendor = profile.gpu.vendor
        cuda_v = profile.gpu.cuda_version
        metal = profile.gpu.metal_supported
        vulkan = profile.gpu.vulkan_supported

        # Select wheel index
        if vendor == "nvidia" and cuda_v:
            # Match closest CUDA minor version (round down)
            major_minor = ".".join(cuda_v.split(".")[:2])
            wheel_url = _CUDA_WHEEL_INDEX.get(major_minor)
            if wheel_url is None:
                # Try lower versions
                for v in sorted(_CUDA_WHEEL_INDEX.keys(), reverse=True):
                    if float(v) <= float(major_minor):
                        wheel_url = _CUDA_WHEEL_INDEX[v]
                        break
            wheel_url = wheel_url or _CPU_WHEEL_INDEX
        elif metal:
            wheel_url = _METAL_WHEEL_INDEX
        elif vulkan:
            wheel_url = _VULKAN_WHEEL_INDEX
        else:
            wheel_url = _CPU_WHEEL_INDEX

        # Tier classification by VRAM
        if vram >= 24.0:
            return cls(
                tier=3,
                label="High-End",
                vram_gb_detected=vram,
                gpu_vendor=vendor,
                models=[
                    ModelSpec(
                        "determinex-7-large-v1.1",
                        7.7,
                        "determinex-ai/determinex-7-large-v1.1-gguf",
                        -1,
                    ),
                ],
                wheel_index_url=wheel_url,
                n_gpu_layers=-1,
                api_fallback=False,
            )
        elif vram >= 8.0:
            return cls(
                tier=2,
                label="Mid-Range",
                vram_gb_detected=vram,
                gpu_vendor=vendor,
                models=[
                    ModelSpec(
                        "determinex-7-large-v1.1",
                        7.7,
                        "determinex-ai/determinex-7-large-v1.1-gguf",
                        -1,
                    ),
                ],
                wheel_index_url=wheel_url,
                n_gpu_layers=-1,
                api_fallback=False,
            )
        elif vram >= 4.0:
            return cls(
                tier=1,
                label="Entry",
                vram_gb_detected=vram,
                gpu_vendor=vendor,
                models=[
                    ModelSpec(
                        "determinex-3-medium-v1.1",
                        3.3,
                        "determinex-ai/determinex-3-medium-v1.1-gguf",
                        20,
                    ),
                ],
                wheel_index_url=wheel_url,
                n_gpu_layers=20,
                api_fallback=True,
            )
        else:
            return cls(
                tier=0,
                label="Minimal (CPU/API)",
                vram_gb_detected=vram,
                gpu_vendor="none" if vram == 0.0 else vendor,
                models=[
                    ModelSpec(
                        "determinex-1-tiny-v1.1",
                        1.6,
                        "determinex-ai/determinex-1-tiny-v1.1-gguf",
                        0,
                    ),
                ],
                wheel_index_url=_CPU_WHEEL_INDEX,
                n_gpu_layers=0,
                api_fallback=True,
            )


# ---------------------------------------------------------------------------
# PROFILER
# ---------------------------------------------------------------------------


class HardwareProfiler:
    """
    Silently detects system capabilities on Determinex's first launch.
    No user interaction required. Runs in < 2 seconds on any modern system.
    """

    def profile(self) -> SystemProfile:
        sp = SystemProfile()
        sp.os = self._detect_os()
        sp.cpu = self._detect_cpu()
        sp.gpu = self._detect_gpu()
        return sp

    # ── OS ────────────────────────────────────────────────────────────────────

    def _detect_os(self) -> OSInfo:
        plat = sys.platform
        if plat.startswith("win"):
            platform_name = "windows"
        elif plat == "darwin":
            platform_name = "darwin"
        else:
            platform_name = "linux"

        return OSInfo(
            platform=platform_name,
            version=platform.version(),
            arch=platform.machine().lower(),
            python_version=sys.version.split()[0],
        )

    # ── CPU ───────────────────────────────────────────────────────────────────

    def _detect_cpu(self) -> CPUInfo:
        name = ""
        avx2 = False
        avx512 = False

        try:
            import cpuinfo  # py-cpuinfo library

            info = cpuinfo.get_cpu_info()
            name = info.get("brand_raw", "")
            flags = info.get("flags", [])
            avx2 = "avx2" in flags
            avx512 = any(f.startswith("avx512") for f in flags)
        except ImportError:
            # Fallback: parse /proc/cpuinfo on Linux, use platform on Windows
            name = platform.processor()
            if sys.platform == "linux":
                try:
                    cpuinfo_txt = Path("/proc/cpuinfo").read_text()
                    flags_line = next(
                        (l for l in cpuinfo_txt.splitlines() if l.startswith("flags")), ""
                    )
                    avx2 = "avx2" in flags_line
                    avx512 = "avx512" in flags_line
                except Exception:
                    pass

        return CPUInfo(
            name=name,
            cores=os.cpu_count() or 1,
            avx2=avx2,
            avx512=avx512,
            arch=platform.machine().lower(),
        )

    # ── GPU ───────────────────────────────────────────────────────────────────

    def _detect_gpu(self) -> GPUInfo:
        gpu = GPUInfo()

        # 1. Try PyTorch CUDA (fastest path, already installed)
        try:
            import torch

            if torch.cuda.is_available():
                gpu.vendor = "nvidia"
                gpu.name = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                gpu.vram_gb = props.total_memory / (1024**3)
                gpu.cuda_version = torch.version.cuda or ""
                gpu.compute_capability = f"{props.major}.{props.minor}"
                return gpu
        except ImportError:
            pass

        # 2. Try nvidia-smi (works even without PyTorch)
        try:
            out = (
                subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,memory.total,driver_version",
                        "--format=csv,noheader,nounits",
                    ],
                    timeout=5,
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )
            if out:
                parts = [p.strip() for p in out.split(",")]
                gpu.vendor = "nvidia"
                gpu.name = parts[0] if len(parts) > 0 else ""
                gpu.vram_gb = float(parts[1]) / 1024 if len(parts) > 1 else 0.0
                gpu.driver_version = parts[2] if len(parts) > 2 else ""
                # Detect CUDA version from nvcc or nvidia-smi output
                gpu.cuda_version = self._detect_cuda_version()
                return gpu
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

        # 3. Apple Metal (macOS)
        if sys.platform == "darwin":
            try:
                out = subprocess.check_output(
                    ["system_profiler", "SPDisplaysDataType"],
                    timeout=10,
                    stderr=subprocess.DEVNULL,
                ).decode()
                if "Metal" in out or "Apple M" in out:
                    gpu.vendor = "apple"
                    gpu.metal_supported = True
                    # Extract chip name
                    match = re.search(r"Chipset Model:\s*(.+)", out)
                    gpu.name = match.group(1).strip() if match else "Apple Silicon"
                    # Unified memory — use a safe default (16GB assumed)
                    match_mem = re.search(r"(\d+)\s*GB", out)
                    gpu.vram_gb = float(match_mem.group(1)) if match_mem else 16.0
                    return gpu
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        # 4. AMD/Intel via vkDeviceInfo (Vulkan, cross-platform)
        try:
            out = subprocess.check_output(
                ["vulkaninfo", "--summary"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode()
            if "Radeon" in out or "AMD" in out:
                gpu.vendor = "amd"
                gpu.vulkan_supported = True
                match = re.search(r"deviceName\s*=\s*(.+)", out)
                gpu.name = match.group(1).strip() if match else "AMD GPU"
                # VRAM detection via rocm-smi for AMD
                gpu.vram_gb = self._detect_amd_vram()
                return gpu
            elif "Intel" in out:
                gpu.vendor = "intel"
                gpu.vulkan_supported = True
                match = re.search(r"deviceName\s*=\s*(.+)", out)
                gpu.name = match.group(1).strip() if match else "Intel GPU"
                return gpu
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # 5. No GPU found
        gpu.vendor = "none"
        gpu.vram_gb = 0.0
        return gpu

    def _detect_cuda_version(self) -> str:
        """Detect CUDA toolkit version from nvcc or nvidia-smi."""
        # Try nvcc first (most accurate)
        try:
            out = subprocess.check_output(
                ["nvcc", "--version"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode()
            match = re.search(r"release (\d+\.\d+)", out)
            return match.group(1) if match else ""
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        # Try nvidia-smi CUDA version
        try:
            out = subprocess.check_output(
                ["nvidia-smi"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode()
            match = re.search(r"CUDA Version:\s*(\d+\.\d+)", out)
            return match.group(1) if match else ""
        except (subprocess.SubprocessError, FileNotFoundError):
            return ""

    def _detect_amd_vram(self) -> float:
        """Detect AMD GPU VRAM via rocm-smi."""
        try:
            out = subprocess.check_output(
                ["rocm-smi", "--showmeminfo", "vram", "--csv"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode()
            match = re.search(r"(\d+)", out)
            if match:
                return int(match.group(1)) / (1024**3)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return 0.0


# ---------------------------------------------------------------------------
# PROFILE CACHE
# ---------------------------------------------------------------------------

_CACHE_PATH = Path("determinex_hardware_profile.json")


def load_cached_profile() -> TierProfile | None:
    """Load a previously detected profile from disk. Returns None if not cached."""
    if not _CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_CACHE_PATH.read_text())
        gpu = GPUInfo(**data["gpu"])
        cpu = CPUInfo(**data["cpu"])
        osinfo = OSInfo(**data["os"])
        sp = SystemProfile(gpu=gpu, cpu=cpu, os=osinfo)
        return TierProfile.from_system_profile(sp)
    except Exception:
        return None


def detect_and_cache(force: bool = False) -> TierProfile:
    """
    Run hardware profiling and cache the result.

    If a cached profile exists and force=False, returns the cached result.
    On first launch (or force=True), runs full detection and writes cache.

    This is the main entry point for Determinex startup:
        tier = detect_and_cache()
        print(tier.summary())
    """
    if not force:
        cached = load_cached_profile()
        if cached:
            print("[HardwareProfiler] Using cached profile.", flush=True)
            return cached

    print("[HardwareProfiler] Detecting hardware...", flush=True)
    profiler = HardwareProfiler()
    profile = profiler.profile()
    tier = TierProfile.from_system_profile(profile)

    # Cache to disk
    try:
        _CACHE_PATH.write_text(profile.to_json())
        print(f"[HardwareProfiler] Profile cached → {_CACHE_PATH}", flush=True)
    except Exception as e:
        print(f"[HardwareProfiler] Could not cache profile: {e}", flush=True)

    return tier


# ---------------------------------------------------------------------------
# SELF-TEST / CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Determinex hardware profiler")
    parser.add_argument("--force", action="store_true", help="Re-detect, ignore cache")
    parser.add_argument(
        "--install", action="store_true", help="Install llama-cpp-python for this hardware"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print install command without running it"
    )
    args = parser.parse_args()

    tier = detect_and_cache(force=args.force)
    print()
    print(tier.summary())
    print()
    print(f"  pip command: {tier.pip_install_command()}")

    if args.install or args.dry_run:
        tier.install_llama_cpp(dry_run=args.dry_run)
