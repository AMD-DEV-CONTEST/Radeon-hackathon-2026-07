"""
scripts/hive/hardware.py — Hardware profiler, communication layer, adjudication
================================================================================
Moved from determinex_hive.py (lines ~370-516).
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger("hive")


# ── Adjudication weights (updated 2026-04-17 post ceiling-check analysis) ────
# A/B eval ceiling check: nomic-embed-text cosine separation between intentionally
# different approaches (Result<T,E> vs panic!) = 0.074 — BELOW 0.15 threshold.
# Conclusion: semantic similarity (beta) is unreliable for Rust/Go architectural choices.
# Global default reduces beta from 0.25 → 0.15 to reflect this finding.
ADJUDICATION_WEIGHTS = {
    "alpha": 0.70,  # compile_pass_rate — Compiler Oracle is ground truth
    "beta": 0.15,  # semantic_similarity — reduced: nomic coarse on arch choices
    "gamma": 0.10,  # test_pass_rate — when tests exist
    "delta": 0.05,  # complexity_penalty — tiebreaker
}

# Language-calibrated defaults.
# Compiler Oracle strength varies by language:
#   Rust/Go/TS: compiler verifies types, lifetimes, imports — near-complete truth.
#   Python:  py_compile checks syntax only — cannot catch ImportError, missing methods.
# When the compiler is weak (Python), semantic similarity carries more weight.
ADJUDICATION_WEIGHTS_BY_LANG: dict[str, dict] = {
    "rust": {"alpha": 0.80, "beta": 0.15, "gamma": 0.00, "delta": 0.05},
    "go": {"alpha": 0.80, "beta": 0.15, "gamma": 0.00, "delta": 0.05},
    "typescript": {"alpha": 0.75, "beta": 0.20, "gamma": 0.00, "delta": 0.05},
    "python": {"alpha": 0.45, "beta": 0.45, "gamma": 0.00, "delta": 0.10},
}


def effective_adjudication_weights(tests_exist: bool = False, lang: str = "") -> dict:
    """
    Return effective adjudication weights.

    If lang is provided and in ADJUDICATION_WEIGHTS_BY_LANG, use language-calibrated
    defaults (the compiler's actual verification power varies dramatically by language).
    Otherwise fall back to the generic ADJUDICATION_WEIGHTS.

    When tests are absent, γ redistributes proportionally to α and β.
    """
    base = ADJUDICATION_WEIGHTS_BY_LANG.get(lang.lower(), ADJUDICATION_WEIGHTS)
    w = dict(base)
    if not tests_exist and w.get("gamma", 0) > 0:
        redistributable = w["gamma"]
        non_gamma_sum = w["alpha"] + w["beta"]
        w["alpha"] += redistributable * (w["alpha"] / non_gamma_sum)
        w["beta"] += redistributable * (w["beta"] / non_gamma_sum)
        w["gamma"] = 0.0
    return w


# ── nomic-embed-text adjudication embedder (Gap 4 — locked: fastembed) ───────
_nomic_model = None


def get_adjudication_embedder():
    """
    Singleton loader for nomic-embed-text via fastembed.
    fastembed is already in the Determinex dependency chain (knowledge layer vector engine).
    ONNX-based, runs on CPU without PyTorch overhead.
    """
    global _nomic_model
    if _nomic_model is None:
        try:
            from fastembed import TextEmbedding

            _nomic_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5")
        except ImportError:
            log.warning(
                "fastembed not installed — adjudication scoring unavailable. "
                "Install with: pip install fastembed"
            )
            return None
        except Exception as exc:
            log.warning("adjudication embedder unavailable: %s", exc)
            return None
    return _nomic_model


def adjudication_cosine(text_a: str, text_b: str) -> float:
    """
    Compute cosine similarity between two text passages using nomic-embed-text.
    Used for semantic_similarity component of the adjudication score (β weight).
    Returns 0.0 if embedder is unavailable.
    """
    try:
        model = get_adjudication_embedder()
        if model is None:
            return 0.0
        embs = list(model.embed([text_a, text_b]))
        a, b = embs[0], embs[1]
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))
    except Exception as exc:
        log.warning("adjudication cosine unavailable: %s", exc)
        return 0.0


# ── Rosetta dispatch guard (Gap 1 — locked 2026-04-14) ──────────────────────


def select_communication_layer(
    sender_is_local: bool,
    receiver_is_local: bool,
    rosetta_available: bool = False,
) -> int:
    """
    Determine which communication layer to use for a role→role channel.
    Returns 1 (DSL text) or 2 (soft prefix injection via Rosetta).
    """
    if sender_is_local and receiver_is_local and rosetta_available:
        return 2
    return 1


@dataclass
class ModelLifecyclePolicy:
    """Explicit VRAM model lifecycle policy — config-as-code."""

    keep_hot: list[str] = field(
        default_factory=list
    )  # role names that must never be unloaded mid-session
    max_loaded: int = 0  # max simultaneous models in VRAM (tier-derived)
    swap_strategy: str = "role_priority"  # "lru" | "role_priority"


def _lifecycle_for_tier(tier: int) -> ModelLifecyclePolicy:
    """Map a capacity tier to its model-residency policy.

    Tier 0 claimed max_loaded=2 and kept BOTH the builder and the monitor resident. On the ~6 GB
    card that defines the tier that is not true: builder (1.8 GB) + observer (3.5 GB) + a step's KV
    cache exceeds what is available, so Ollama runs the observer's prefill on the CPU instead.
    Measured 2026-07-31 -- a session stalled 19 minutes in step 2's Monitor call with zero CPU
    movement and no error; the same call with the observer evicted returned in 39s. Keeping the
    monitor hot there was buying a cache hit with an indefinite hang.

    `max_loaded` is load-bearing rather than decorative: `api_client._ollama_extra` reads it to
    decide the monitor eviction, so raising tier 0 back to 2 reintroduces the stall. The builder
    stays in keep_hot -- it reloads in a couple of seconds from page cache between steps, which is
    the cost worth paying.

    Lives at module scope so the policy can be read and tested without probing hardware; it was
    previously a dict inside `profile_hardware()`, reachable only by running a real detection.
    """
    return {
        -1: ModelLifecyclePolicy(keep_hot=[], max_loaded=0, swap_strategy="role_priority"),
        0: ModelLifecyclePolicy(keep_hot=["builder"], max_loaded=1, swap_strategy="role_priority"),
        1: ModelLifecyclePolicy(keep_hot=["builder", "monitor"], max_loaded=4, swap_strategy="lru"),
        2: ModelLifecyclePolicy(
            keep_hot=["builder", "monitor", "oracle", "architect"],
            max_loaded=5,
            swap_strategy="lru",
        ),
    }.get(tier, ModelLifecyclePolicy(keep_hot=[], max_loaded=0, swap_strategy="role_priority"))


@dataclass
class ThermalProfile:
    """Idle-time thermal baseline captured once at profile_hardware() call."""

    idle_gpu_c: float | None = None  # °C idle GPU temp (None = not readable)
    idle_cpu_c: float | None = None  # °C idle CPU temp (None = not readable)
    source: str = "none"  # which reader produced the data
    gpu_layer_factor: float = 1.0  # multiplier applied to num_gpu (1.0 = full, 0.7 = conservative)
    recommendation: str = ""  # human-readable note for install flow

    @classmethod
    def measure(cls) -> ThermalProfile:
        """
        Take one thermal snapshot at idle.  Used during hardware profiling and
        install-time calibration to decide how aggressively to push the GPU.
        Gracefully returns all-None if no sensors are readable.
        """
        try:
            from hive.thermal import read_temps

            snap = read_temps()
        except Exception:
            return cls()

        gpu_c = snap.max_gpu
        cpu_c = snap.max_cpu
        source = ",".join(snap.sources_ok) or "none"

        # Derive GPU layer factor from idle temperature
        # "If it's already hot at idle, it'll run hotter under load"
        if gpu_c is not None:
            if gpu_c >= 75:
                factor = 0.60
                note = (
                    f"GPU idle at {gpu_c:.0f}°C — very warm at rest. "
                    f"num_gpu reduced to 60%% of capacity to leave thermal headroom. "
                    f"Consider improving case airflow."
                )
            elif gpu_c >= 65:
                factor = 0.75
                note = (
                    f"GPU idle at {gpu_c:.0f}°C — warm at rest. "
                    f"num_gpu reduced to 75%% capacity as a thermal precaution."
                )
            elif gpu_c >= 55:
                factor = 0.90
                note = (
                    f"GPU idle at {gpu_c:.0f}°C — slightly elevated. num_gpu set to 90%% capacity."
                )
            else:
                factor = 1.0
                note = f"GPU idle at {gpu_c:.0f}°C — thermal headroom is healthy."
        else:
            factor = 1.0
            note = "GPU temperature not readable — using full GPU layers (monitor manually)."

        return cls(
            idle_gpu_c=gpu_c,
            idle_cpu_c=cpu_c,
            source=source,
            gpu_layer_factor=factor,
            recommendation=note,
        )


@dataclass
class HardwareProfile:
    tier: int  # -1, 0, 1, 2
    vram_gb: float
    ram_gb: float
    gpu_count: int
    lifecycle: ModelLifecyclePolicy = field(default_factory=ModelLifecyclePolicy)
    thermal: ThermalProfile = field(default_factory=ThermalProfile)
    #: Which accelerator answered: "nvidia" | "amd" | "apple" | "cpu". Defaulted so any existing
    #: construction site (tests, fixtures) keeps working without naming it.
    accelerator: str = "cpu"
    #: What to hand PyTorch. "cuda" for both NVIDIA and AMD -- a ROCm build of torch deliberately
    #: keeps the `cuda` device name, which is why vendor and device are recorded separately rather
    #: than one being inferred from the other.
    torch_device: str = "cpu"
    #: Which memory pool `tier` was derived from: "vram" (an accelerator answered), "system_ram"
    #: (no accelerator, so capacity comes from RAM the way Ollama/llama.cpp actually use it), or
    #: "none" (nothing readable). Recorded because "tier 1" means something different in each case
    #: and a reader should not have to guess which.
    capacity_basis: str = "vram"
    #: Free-form platform note, e.g. "ARM64" or "Qualcomm Snapdragon (ARM64)". Display only.
    platform_note: str = ""

    @property
    def tier_label(self) -> str:
        return {-1: "CPU-only", 0: "Constrained (~6GB)", 1: "Mid-range", 2: "Full rig"}.get(
            self.tier, "Unknown"
        )

    @property
    def accelerator_label(self) -> str:
        """Human-readable, for the status surface."""
        names = {
            "nvidia": "NVIDIA (CUDA)",
            "amd": "AMD (ROCm)",
            "intel": "Intel Arc (XPU)",
            "apple": "Apple Silicon (Metal)",
            "cpu": "CPU only",
        }
        base = names.get(self.accelerator, self.accelerator)
        if self.accelerator == "cpu":
            if self.platform_note:
                base = f"{base} ({self.platform_note})"
            # Say what the capacity is based on. A CPU-only host is no longer automatically the
            # weakest possible one, so "CPU only" alone now understates a 64 GB box.
            if self.capacity_basis == "system_ram" and self.ram_gb > 0:
                return f"{base} — {self.ram_gb:.1f} GB system RAM"
            return base
        unit = "unified memory" if self.accelerator == "apple" else "VRAM"
        return f"{base} — {self.vram_gb:.1f} GB {unit}, {self.gpu_count} device(s)"

    def max_local_models(self) -> int:
        if self.tier == -1:
            return 0
        if self.tier == 0:
            return 2
        if self.tier == 1:
            return 4
        return 5

    @property
    def max_parallel_steps(self) -> int:
        """Max DAG steps to execute concurrently in a wave.

        Tier -1/0: 1 — single GPU (or CPU-only); Ollama serialises LLM calls
                       anyway, and concurrent cargo builds would race on target/.
        Tier 1:    2 — two independent branches can safely run; Compiler Oracle
                       calls are serialised per-session via compiler_lock.
        Tier 2:    gpu_count (at least 2) — one active branch per GPU.

        The reasoning above is about the DEVICE, not the tier, so `gpu_count == 0` returns 1
        whatever the tier says. That matters now that a CPU-only host can reach tier 1 on system
        RAM: nothing about having RAM makes concurrent branches safe when there is one shared
        CPU to run them on.
        """
        if self.gpu_count <= 0:
            return 1
        if self.tier <= 0:
            return 1
        if self.tier == 1:
            return 2
        return max(2, self.gpu_count)


# ── Accelerator detection, per vendor ────────────────────────────────────────────────────────────
#
# This used to probe `nvidia-smi` and nothing else, so on an AMD or Apple machine it fell through to
# tier -1 "CPU-only" -- a 24 GB Radeon or a 64 GB M3 Max was invisible, `max_local_models()` returned
# 0, `max_parallel_steps` returned 1, and the lifecycle policy kept nothing hot. The rig was treated
# as the weakest possible host while sitting on more VRAM than the tier-2 threshold.
#
# Each probe returns (vram_gb, device_count) and is expected to fail on hardware it does not describe,
# so "the tool is absent" and "the tool ran and found nothing" both mean the same thing here: try the
# next vendor. Order is by how definitive the answer is, not by preference.


def _csv_column_values(text: str, header_names: tuple[str, ...]) -> list[int]:
    """Integer values from the first CSV column whose header matches one of `header_names`.

    Parsed by COLUMN rather than by regex. The first version of this used
    `re.findall(r"vram_size[^0-9]{0,12}(\\d+)", ...)`, which cannot work on real CSV: between the
    header cell and the value there is a newline and a device index, and `[^0-9]` stops dead on that
    index digit. It matched nothing and the probe silently fell through to the older tool -- a parser
    that always returns "no AMD GPU" is indistinguishable from having no AMD GPU. Caught by its own
    test before shipping.
    """
    rows = [line.split(",") for line in text.strip().splitlines() if line.strip()]
    if len(rows) < 2:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    index = next((i for i, cell in enumerate(header) if cell in header_names), None)
    if index is None:
        return []
    out: list[int] = []
    for row in rows[1:]:
        if index >= len(row):
            continue
        digits = re.sub(r"[^0-9]", "", row[index])
        if digits:
            out.append(int(digits))
    return out


def _probe_nvidia() -> tuple[float, int]:
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if r.returncode != 0:
        return 0.0, 0
    values = [int(l.strip()) for l in r.stdout.strip().splitlines() if l.strip().isdigit()]
    return (max(values) / 1024, len(values)) if values else (0.0, 0)


def _probe_amd() -> tuple[float, int]:
    """AMD, via amd-smi (ROCm 6+) then rocm-smi (older).

    Both print MiB. `rocm-smi --showmeminfo vram --csv` emits a header plus one row per GPU with the
    total in bytes, while `amd-smi static` reports MB -- so each is parsed on its own terms rather
    than through one regex that would silently mis-scale by 1024x and land a 24 GB card in tier 0.
    """
    try:
        r = subprocess.run(
            ["amd-smi", "static", "--csv"], capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            mb = _csv_column_values(r.stdout, ("vram_size", "vram_total", "size"))
            if mb:
                return max(mb) / 1024, len(mb)
    except Exception:
        pass
    r = subprocess.run(
        ["rocm-smi", "--showmeminfo", "vram", "--csv"], capture_output=True, text=True, timeout=8
    )
    if r.returncode != 0:
        return 0.0, 0
    # "VRAM Total Memory (B)" column, one row per card.
    byte_values = [int(m) for m in re.findall(r",\s*(\d{9,})", r.stdout)]
    if byte_values:
        return max(byte_values) / (1024**3), len(byte_values)
    return 0.0, 0


def _probe_intel() -> tuple[float, int]:
    """Intel Arc / Data Center GPU, via xpu-smi.

    `xpu-smi discovery --dump` emits CSV; memory is reported in MiB. Intel is a separate torch device
    ("xpu"), not a CUDA alias the way ROCm is -- handing "cuda" to a caller on Arc would fail, which
    is why the device string is carried per-vendor rather than inferred.
    """
    r = subprocess.run(
        ["xpu-smi", "discovery", "--dump", "-1"], capture_output=True, text=True, timeout=8
    )
    if r.returncode != 0:
        return 0.0, 0
    mib = _csv_column_values(r.stdout, ("memory physical size", "memory_physical_size", "memory"))
    if mib:
        return max(mib) / 1024, len(mib)
    return 0.0, 0


def _probe_apple() -> tuple[float, int]:
    """Apple Silicon: unified memory, so 'VRAM' is a share of system RAM rather than a separate pool.

    Reported as ~75% of total RAM, which is roughly what Metal will allow a single process to hold.
    Claiming all of it would put an 8 GB Mac in tier 0 and start swapping under a 3B model.
    """
    if platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64"):
        return 0.0, 0
    r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        return 0.0, 0
    return (int(r.stdout.strip()) / (1024**3)) * 0.75, 1


#: (vendor, torch_device, probe). `torch_device` is what a caller hands to PyTorch / a ROCm build.
_ACCELERATORS: tuple[tuple[str, str, Callable[[], tuple[float, int]]], ...] = (
    ("nvidia", "cuda", _probe_nvidia),
    ("amd", "cuda", _probe_amd),  # ROCm builds of torch deliberately expose AMD as "cuda"
    ("intel", "xpu", _probe_intel),  # Intel is its OWN device, not a cuda alias
    ("apple", "mps", _probe_apple),
)


def detect_accelerator() -> tuple[str, str, float, int]:
    """(vendor, torch_device, vram_gb, device_count). ("cpu", "cpu", 0.0, 0) when nothing is found."""
    for vendor, torch_device, probe in _ACCELERATORS:
        try:
            vram_gb, count = probe()
        except Exception:
            continue
        if vram_gb > 0 and count > 0:
            return vendor, torch_device, vram_gb, count
    return "cpu", "cpu", 0.0, 0


def _detect_ram_gb() -> float:
    """Total physical RAM in GiB, or 0.0 if it genuinely cannot be read.

    Windows used to go through `wmic ComputerSystem get TotalPhysicalMemory`. WMIC is deprecated and
    is ABSENT from Windows 11 24H2 and later, so the call failed, the bare `except Exception: pass`
    swallowed it, and the profile reported `ram_gb=0.0` -- indistinguishable from a machine with no
    memory. Found 2026-07-30 when the new capability surface printed 0.0 GB on a working box.

    `GlobalMemoryStatusEx` is a kernel32 call, so it needs no external binary and cannot be removed by
    a Windows release. The POSIX paths are kept as they were.
    """
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return status.ullTotalPhys / (1024**3)
            return 0.0
        if system == "Darwin":
            r = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0 and r.stdout.strip().isdigit():
                return int(r.stdout.strip()) / (1024**3)
            return 0.0
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024**2)
    except Exception as exc:
        log.debug("[hardware] RAM detection failed: %s", exc)
    return 0.0


#: Held back from the model-capacity budget on an accelerator-less host: the OS, the Tauri app
#: itself, and whatever cargo/rustc/Docker need during the same session. A CPU-only hive session
#: competes with its own compiler for this RAM, which a GPU host does not.
_CPU_RESERVE_GB = 8.0


def _tier_for_memory(gb: float) -> int:
    """Tier from an amount of usable inference memory, wherever it came from.

    One function so the VRAM path and the system-RAM path cannot drift to different thresholds.
    """
    if gb >= 23.5:
        return 2
    if gb >= 11.5:
        return 1
    if gb >= 3.5:
        return 0
    return -1


def _platform_note() -> str:
    """Display-only platform detail. Never used to claim an accelerator.

    Windows-on-ARM is worth naming because a Snapdragon user otherwise sees a bare "CPU only" and
    reasonably concludes Determinex failed to detect their machine. It did detect it -- there is
    simply no NPU/GPU path for it here, and saying so is better than implying a miss.
    """
    machine = (platform.machine() or "").upper()
    if machine not in ("ARM64", "AARCH64"):
        return ""
    processor = platform.processor() or ""
    if re.search(r"snapdragon|qualcomm", processor, re.IGNORECASE):
        return "Qualcomm Snapdragon, ARM64"
    return "ARM64"


def profile_hardware() -> HardwareProfile:
    """Detect the accelerator across vendors. Falls back to system-RAM capacity when there is none."""
    vendor, torch_device, vram_gb, gpu_count = detect_accelerator()
    if vendor != "cpu":
        log.info(
            "[hardware] accelerator: %s (%.1f GB, %d device(s), torch device '%s')",
            vendor,
            vram_gb,
            gpu_count,
            torch_device,
        )

    ram_gb = _detect_ram_gb()

    # Thresholds sit just BELOW the advertised sizes on purpose. A card sold as 24 GB reports
    # 24564 MiB = 23.99 GiB, so a literal `>= 24` put every 24 GB card -- an RTX 4090 included, not
    # just AMD -- into tier 1 instead of tier 2, halving max_parallel_steps and dropping two roles
    # out of keep_hot. The same rounding hid one tier down at 12 GB and 4 GB. Found 2026-07-30 while
    # adding multi-vendor detection: the simulated 24 GB Radeon landed in tier 1 and the test that
    # said "the tier must follow the memory" failed on the arithmetic rather than the parsing.
    tier = _tier_for_memory(vram_gb)
    capacity_basis = "vram"

    # No accelerator is NOT the same as no capacity. Found 2026-07-31: `tier` came only from
    # `vram_gb`, so every host without a discrete GPU got tier -1 -- `max_local_models()` 0,
    # `keep_hot` empty -- and a 128 GB workstation was treated identically to an 8 GB laptop. RAM
    # was already being detected, and then never used for anything.
    #
    # That is wrong on its own terms: Ollama and llama.cpp run models out of system RAM, which is
    # exactly how a CPU-only install of Determinex works. It also made `keep_hot=[]` backwards --
    # reloading a model costs MORE on a CPU host, not less, so the machine that most needs the
    # builder kept resident was the one told to keep nothing.
    #
    # This is the whole story on Windows-on-ARM too. Snapdragon X has an Adreno GPU and a Hexagon
    # NPU, and Determinex uses NEITHER: there is no PyTorch backend for them on Windows ARM64 and
    # Ollama runs the ARM64 CPU path. So a Snapdragon box is precisely "no accelerator, plenty of
    # RAM", and it is fixed by this rather than by a probe that would claim an NPU we never call.
    if vendor == "cpu":
        usable = max(0.0, ram_gb - _CPU_RESERVE_GB)
        # Capped at tier 1 deliberately. Tier 2's defining property is one branch per GPU, and
        # keeping four models resident buys nothing when execution is serialised on one CPU --
        # it just takes RAM that cargo and Docker want during the same session.
        tier = min(1, _tier_for_memory(usable))
        capacity_basis = "system_ram" if ram_gb > 0 else "none"
        log.info(
            "[hardware] no accelerator; capacity from system RAM: %.1f GB total, "
            "%.1f GB usable after %.1f GB reserve -> tier %d",
            ram_gb,
            usable,
            _CPU_RESERVE_GB,
            tier,
        )

    lifecycle = _lifecycle_for_tier(tier)

    thermal = ThermalProfile.measure()
    if thermal.recommendation:
        log.info("[thermal] %s", thermal.recommendation)

    return HardwareProfile(
        tier=tier,
        vram_gb=vram_gb,
        ram_gb=ram_gb,
        gpu_count=gpu_count,
        lifecycle=lifecycle,
        thermal=thermal,
        accelerator=vendor,
        torch_device=torch_device,
        capacity_basis=capacity_basis,
        platform_note=_platform_note() if vendor == "cpu" else "",
    )


_HW_PROFILE: HardwareProfile | None = None
_HW_PROFILE_TS: float = 0.0
_HW_PROFILE_TTL: float = 300.0  # G6: re-probe hardware every 5 min (GPU hotplug, suspend/resume)


def get_hw_profile() -> HardwareProfile:
    """Lazy singleton with TTL — reprofile after 5 minutes to catch GPU hotplug / VRAM changes."""
    global _HW_PROFILE, _HW_PROFILE_TS
    import time as _time_hw

    now = _time_hw.monotonic()
    if _HW_PROFILE is None or (now - _HW_PROFILE_TS) > _HW_PROFILE_TTL:
        _HW_PROFILE = profile_hardware()
        _HW_PROFILE_TS = now
    return _HW_PROFILE


def get_free_vram_gb() -> float:
    """
    L1-A: Query current free VRAM via nvidia-smi at runtime.
    Unlike profile_hardware() (which reads total VRAM once at startup), this
    samples the live free memory so the executor can warn before dispatching
    a Builder call into a nearly-full GPU.
    Returns 0.0 when nvidia-smi is unavailable or no GPU is present.
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            values = [
                int(line.strip())
                for line in r.stdout.strip().splitlines()
                if line.strip().isdigit()
            ]
            if values:
                return max(values) / 1024  # MiB → GB, report headroom on best GPU
    except Exception:
        pass
    return 0.0


# ── Ollama Modelfile auto-calibration ─────────────────────────────────────────
#
# Called during model registration so every user gets a Modelfile tuned to
# their hardware.  Two problems this solves:
#
# 1. VRAM starvation (DWM lag):
#    num_gpu 99 tries to load ALL layers into VRAM. When the model is larger
#    than the card (e.g. 7.2 GB sentinel on a 6 GB card), Windows DWM is left
#    with <0.6 GB of VRAM — causing UI stuttering and mouse lag.
#    Fix: reserve 1.0 GB for DWM on Windows, 0.5 GB on Linux/Mac.
#    If the model fits after reserving headroom → num_gpu 99.
#    If not → compute the fraction of layers that fits and use that count.
#
# 2. CPU chokehold at ~50% utilisation:
#    50–51 % CPU with hyperthreading = 100 % of physical cores pinned.
#    Fix: cap inference threads at (physical_cores − 2), leaving two physical
#    cores permanently free for the OS and UI.

# Approximate transformer layer counts by model size class.
# Used only when the model doesn't fit in VRAM and we need to compute a layer
# fraction.  Close enough for Modelfile generation; not used in scoring.
_APPROX_LAYERS_BY_SIZE: list[tuple[float, int]] = [
    (1.0, 22),  # <1 GB   — tiny (e.g. 0.5B)
    (2.0, 28),  # 1–2 GB  — 1.5B class (Qwen2.5-Coder-1.5B)
    (4.0, 36),  # 2–4 GB  — 3B class (Qwen2.5-3B)
    (9.0, 32),  # 4–9 GB  — 7B class (Mistral-7B, Llama-3-8B)
    (17.0, 40),  # 9–17 GB — 13B class
    (35.0, 62),  # 17–35 GB — 34B class
    (99.0, 80),  # 35+ GB  — 70B class
]

# VRAM headroom to reserve for the OS display stack.
# DWM on Windows needs ~0.6 GB; we reserve 0.6 GB so the OS stays smooth
# while still leaving as much VRAM as possible for the model.
_VRAM_HEADROOM_GB: dict[str, float] = {
    "Windows": 0.6,
    "Linux": 0.3,
    "Darwin": 0.3,
}

# KV cache overhead (GB) per 1024 tokens of context, by model size class.
# KV = 2 × n_heads × head_dim × seq_len × bytes × n_layers.
# These are empirical approximations per 1024 context tokens.
_KV_CACHE_PER_1K_CTX_BY_SIZE: list[tuple[float, float]] = [
    (2.0, 0.10),  # <2 GB  — 1.5B class
    (4.0, 0.25),  # 2–4 GB — 3B class
    (9.0, 0.50),  # 4–9 GB — 7B class
    (17.0, 0.85),  # 9–17 GB — 13B class
    (99.0, 1.50),  # 17+ GB
]


def _cpu_physical_cores() -> int:
    """
    Return the number of physical CPU cores.

    Windows: uses PowerShell Get-CimInstance (wmic is deprecated on Win11).
    Linux:   reads /proc/cpuinfo core id deduplication.
    Fallback: os.cpu_count() // 2 (assumes hyperthreading, safe underestimate).
    """
    import os

    try:
        if platform.system() == "Windows":
            # PowerShell is available on all supported Windows versions.
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum",
                ],
                capture_output=True,
                text=True,
                timeout=8,
            )
            val = r.stdout.strip()
            if val.isdigit():
                return int(val)
        else:
            # Count unique (physical id, core id) pairs in /proc/cpuinfo
            r = subprocess.run(
                ["grep", "-E", "^core id|^physical id", "/proc/cpuinfo"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                lines = r.stdout.strip().splitlines()
                pairs: set[tuple[str, str]] = set()
                phys = core = None
                for line in lines:
                    if line.startswith("physical id"):
                        phys = line.split(":")[1].strip()
                    elif line.startswith("core id"):
                        core = line.split(":")[1].strip()
                        if phys is not None and core is not None:
                            pairs.add((phys, core))
                            phys = core = None
                if pairs:
                    return len(pairs)
    except Exception:
        pass
    # Safe fallback: assume hyperthreading (logical // 2)
    logical = os.cpu_count() or 4
    return max(1, logical // 2)


def _approx_layer_count(model_size_gb: float) -> int:
    """Return approximate transformer layer count for a model of given size."""
    for threshold, layers in _APPROX_LAYERS_BY_SIZE:
        if model_size_gb <= threshold:
            return layers
    return 80


def _kv_cache_gb(model_size_gb: float, num_ctx: int) -> float:
    """Estimate KV cache VRAM (GB) for a model at a given context length."""
    per_1k = 0.10
    for threshold, rate in _KV_CACHE_PER_1K_CTX_BY_SIZE:
        if model_size_gb <= threshold:
            per_1k = rate
            break
    return per_1k * (num_ctx / 1024)


def _disk_type_for_path(path: Path) -> str:
    """Return 'SSD', 'HDD', or 'Unknown' for the drive containing path."""
    try:
        if platform.system() == "Windows":
            drive_letter = Path(path).resolve().drive.rstrip(":\\")
            r = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f"$p=Get-Partition | Where-Object {{$_.DriveLetter -eq '{drive_letter}'}};"
                    "$d=Get-PhysicalDisk | Where-Object {$_.DeviceId -eq (Get-Disk -Number $p.DiskNumber).Number};"
                    "if ($d) {{ $d.MediaType }} else {{ 'Unknown' }}",
                ],
                capture_output=True,
                text=True,
                timeout=8,
            )
            t = r.stdout.strip()
            if "SSD" in t:
                return "SSD"
            if "HDD" in t:
                return "HDD"
    except Exception:
        pass
    return "Unknown"


def _estimated_load_seconds(model_size_gb: float, disk_type: str) -> float:
    """Rough cold-load time estimate based on disk type and model size."""
    # Observed rates: NVMe SSD ~1500 MB/s effective, HDD ~50 MB/s effective (with random I/O overhead)
    mb_per_sec = {"SSD": 1500.0, "HDD": 50.0}.get(disk_type, 200.0)
    return (model_size_gb * 1024) / mb_per_sec


def get_vram_warnings(model_path: str | Path, num_ctx: int = 2048) -> list[str]:
    """
    Return a list of warning strings for the user based on their hardware and
    the model they are about to load.  Empty list = no issues detected.

    Warnings are shown:
    - Once at model registration time (printed by _cmd_register)
    - At session start if a constrained condition is detected
    - NOT shown if the hardware is adequate (no unnecessary noise)
    """
    warnings: list[str] = []
    hw = get_hw_profile()
    model_path = Path(model_path)
    model_size_gb = model_path.stat().st_size / (1024**3)
    headroom_gb = _VRAM_HEADROOM_GB.get(platform.system(), 0.6)
    kv_gb = _kv_cache_gb(model_size_gb, num_ctx)
    available_gb = max(0.0, hw.vram_gb - headroom_gb - kv_gb)
    disk_type = _disk_type_for_path(model_path)
    load_secs = _estimated_load_seconds(model_size_gb, disk_type)

    # 1. Model larger than VRAM (partial offload → GPU saturation → compositor lag)
    if hw.vram_gb > 0 and model_size_gb > hw.vram_gb:
        offload_gb = model_size_gb - available_gb
        warnings.append(
            f"MODEL EXCEEDS VRAM: {model_size_gb:.1f} GB model on a {hw.vram_gb:.1f} GB card. "
            f"~{offload_gb:.1f} GB of layers will run on CPU (slower inference). "
            f"During inference the GPU runs near 100% utilisation — your OS compositor "
            f"(DWM on Windows, Wayland/X11 on Linux) competes for GPU time. "
            f"You may experience UI lag, mouse stuttering, or temporary loss of window control. "
            f"This is expected. num_batch has been set to 128 to reduce the effect."
        )

    # 2. Low VRAM headroom after model + KV cache
    vram_remaining = hw.vram_gb - headroom_gb - kv_gb - min(model_size_gb, available_gb)
    if 0 < vram_remaining < 0.4:
        warnings.append(
            f"LOW VRAM HEADROOM: Only {vram_remaining * 1024:.0f} MB free after model load. "
            f"UI (DWM/compositor) may stutter or lag during inference. "
            f"If you experience mouse lag or window slowness, this is why."
        )

    # 3. Model on HDD (slow cold load)
    if disk_type == "HDD" and load_secs > 30:
        warnings.append(
            f"SLOW STORAGE: Model is on an HDD ({model_path.drive}). "
            f"Estimated cold-load time: {load_secs:.0f}s (~{load_secs / 60:.1f} min). "
            f"After the first load, the model stays in RAM and is fast. "
            f"Consider moving models to an SSD for instant cold starts."
        )

    # 4. CPU-only (no GPU)
    if hw.vram_gb == 0:
        warnings.append(
            f"CPU-ONLY MODE: No GPU detected. Inference will be slow "
            f"({model_size_gb:.1f} GB model running entirely on CPU). "
            f"All roles will use API models — local inference is disabled."
        )

    return warnings


def compute_ollama_params(
    model_path: str | Path,
    vram_gb: float | None = None,
    num_ctx: int = 2048,
) -> dict[str, int | str]:
    """
    Compute num_gpu, num_thread, and num_ctx for a GGUF model based on this
    machine's hardware.  Called during model registration so every user gets
    calibrated parameters automatically.  No hardcoded values.

    Logic:
    - VRAM budget  = total_vram - os_headroom - kv_cache_estimate
    - num_gpu      = 99 if model fits, else floor(budget/model_size * approx_layers)
    - num_thread   = logical_cores - (2 * hyperthreading_factor), min 2
    - num_ctx      = passed through (caller controls context size)

    Returns dict with keys: num_gpu, num_thread, num_ctx
    """
    hw = get_hw_profile()
    vram_gb = vram_gb if vram_gb is not None else hw.vram_gb

    model_path = Path(model_path)
    model_size_gb = model_path.stat().st_size / (1024**3)
    headroom_gb = _VRAM_HEADROOM_GB.get(platform.system(), 0.6)
    kv_gb = _kv_cache_gb(model_size_gb, num_ctx)
    available_gb = max(0.0, vram_gb - headroom_gb - kv_gb)

    # Thermal factor: if the GPU is already warm at idle, reduce layer count
    # to leave thermal headroom during inference.
    thermal_factor = hw.thermal.gpu_layer_factor if hw is not None else 1.0

    if vram_gb == 0.0:
        num_gpu = 0  # CPU-only
    elif model_size_gb <= available_gb:
        if thermal_factor >= 1.0:
            num_gpu = 99  # full GPU offload, healthy temps
        else:
            # Model fits in VRAM but thermals say to back off: compute a layer count
            approx_layers = _approx_layer_count(model_size_gb)
            num_gpu = max(1, int(approx_layers * thermal_factor))
    else:
        approx_layers = _approx_layer_count(model_size_gb)
        fraction = max(0.0, available_gb / model_size_gb) * thermal_factor
        num_gpu = max(1, int(fraction * approx_layers))

    # num_thread: logical_cores minus reserved logical cores for OS.
    # Reserve 2 physical cores = 2 × hyperthreading_factor logical cores.
    import os

    logical_cores = os.cpu_count() or 4
    physical_cores = _cpu_physical_cores()
    ht_factor = max(1, logical_cores // max(1, physical_cores))  # 2 if HT, 1 if not
    reserved_logical = 2 * ht_factor  # keep 2 physical cores for OS
    num_thread = max(2, logical_cores - reserved_logical)

    # num_batch: tokens processed per GPU pass.
    # Large models at high GPU utilisation starve the OS compositor (DWM/Wayland)
    # of GPU execution time, causing UI lag and loss of mouse/window control.
    # Smaller batches give the compositor more frequent GPU time between passes.
    #
    # Threshold: if the model needs partial offload (doesn't fit fully in VRAM),
    # the GPU is running near saturation during inference → use 128.
    # If the model fits entirely in VRAM, the GPU isn't as saturated → use 512.
    #
    # A user with 24 GB VRAM running a 7 B model has plenty of headroom — they
    # get the fast 512 batch automatically.  A 6 GB user running sentinel gets
    # 128 to keep the system responsive.
    if num_gpu != 99:
        num_batch = 128  # partial offload → GPU near saturation → throttle batches
    else:
        num_batch = 512  # full VRAM fit → GPU has headroom → full speed

    return {
        "num_gpu": num_gpu,
        "num_thread": num_thread,
        "num_ctx": num_ctx,
        "num_batch": num_batch,
    }


def generate_modelfile(
    gguf_path: str | Path,
    vram_gb: float | None = None,
    temperature: float = 0,
    num_ctx: int = 2048,
    repeat_penalty: float = 1.1,
) -> str:
    """
    Generate a complete Ollama Modelfile string with hardware-calibrated
    num_gpu, num_thread, num_batch, and num_ctx parameters.

    All values are computed from the local hardware profile — nothing is
    hardcoded.  Users on different machines get different values automatically.
    A user with 24 GB VRAM gets full-speed settings; a constrained user gets
    settings that keep the system responsive during inference.
    """
    gguf_path = Path(gguf_path)
    params = compute_ollama_params(gguf_path, vram_gb=vram_gb, num_ctx=num_ctx)
    lines = [
        f"FROM {gguf_path.as_posix()}",
        f"PARAMETER temperature {temperature}",
        f"PARAMETER num_ctx {params['num_ctx']}",
        f"PARAMETER num_gpu {params['num_gpu']}",
        f"PARAMETER num_thread {params['num_thread']}",
        f"PARAMETER num_batch {params['num_batch']}",
        f"PARAMETER repeat_penalty {repeat_penalty}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    hw = profile_hardware()
    print(f"Tier: {hw.tier} ({hw.tier_label})")
    print(f"VRAM: {hw.vram_gb:.1f} GB  |  RAM: {hw.ram_gb:.1f} GB  |  GPUs: {hw.gpu_count}")
    print(f"Keep hot: {hw.lifecycle.keep_hot}")
    print(f"Max loaded: {hw.lifecycle.max_loaded}")
    print(f"Swap strategy: {hw.lifecycle.swap_strategy}")
    print(
        f"CPU physical cores: {_cpu_physical_cores()}  →  num_thread: {max(2, _cpu_physical_cores() - 2)}"
    )
    headroom = _VRAM_HEADROOM_GB.get(platform.system(), 1.0)
    print(
        f"VRAM headroom reserved for OS: {headroom:.1f} GB  →  available for models: {max(0.0, hw.vram_gb - headroom):.1f} GB"
    )
    if len(sys.argv) > 1:
        gguf = sys.argv[1]
        params = compute_ollama_params(gguf, vram_gb=hw.vram_gb)
        print(f"\nModelfile params for {gguf}:")
        print(f"  num_gpu  = {params['num_gpu']}")
        print(f"  num_thread = {params['num_thread']}")
