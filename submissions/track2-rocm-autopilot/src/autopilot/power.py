"""GPU energy measurement (amdsmi) and power-cap control.

Ported from the NVML backend (Gemma-squared, H100). EnergyMeter prefers a
cumulative energy counter when the hardware exposes one; on the Radeon
Cloud gfx1100 SKU the amdsmi accumulator exists but never increments
(verified live: 0 delta across idle and loaded windows), so the meter
falls back to integrating socket power over the measured window at 2 Hz.
Every measurement carries `method` ("energy_counter" or
"power_integration") so reports state how the joules were obtained.
Backend is injectable for tests.
"""

from __future__ import annotations

import subprocess
import threading
import time


class AmdSmiBackend:
    """energy() mJ (or None if the counter is dead), power_w(), gpu_name(), vram_gb()."""

    def __init__(self, index: int = 0):
        import amdsmi

        try:
            amdsmi.amdsmi_init()
        except amdsmi.AmdSmiException:
            pass  # already initialized in this process
        self._smi = amdsmi
        self._h = amdsmi.amdsmi_get_processor_handles()[index]

    def energy(self) -> int | None:
        d = self._smi.amdsmi_get_energy_count(self._h)
        acc = d.get("energy_accumulator", 0)
        if not acc:
            return None
        res_uj = d.get("counter_resolution", 15.3)  # microjoules per count
        return int(acc * res_uj / 1000.0)

    def power_w(self) -> float:
        info = self._smi.amdsmi_get_power_info(self._h)
        p = info.get("average_socket_power")
        if p in (None, "N/A"):
            p = info.get("socket_power", 0)
        return float(p)

    def gpu_name(self) -> str:
        try:
            asic = self._smi.amdsmi_get_gpu_asic_info(self._h)
            name = str(asic.get("market_name") or "")
            gfx = str(asic.get("target_graphics_version") or "")
            if name and not name.startswith("0x"):
                return name
            if gfx:
                return f"AMD Radeon {gfx} ({name or 'unknown DID'})"
        except Exception:
            pass
        return "AMD Radeon (unidentified)"

    def vram_gb(self) -> int:
        try:
            total = self._smi.amdsmi_get_gpu_memory_total(
                self._h, self._smi.AmdSmiMemoryType.VRAM)
            return round(total / 1024**3)
        except Exception:
            return 0


class EnergyMeter:
    """Context manager: joules, mean_power_w and method over the with-block."""

    SAMPLE_PERIOD_S = 0.5

    def __init__(self, _backend=None, index: int = 0):
        self._b = _backend or AmdSmiBackend(index)
        self.joules: float = 0.0
        self.mean_power_w: float = 0.0
        self.method: str = "unknown"
        self._t0 = 0.0
        self._e0: int | None = None

    def __enter__(self):
        self._t0 = time.monotonic()
        self._e0 = self._b.energy()
        if self._e0 is not None:
            self.method = "energy_counter"
        else:
            self.method = "power_integration"
            self._integrated_j = 0.0
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._sample_loop, daemon=True)
            self._thread.start()
        return self

    def _sample_loop(self):
        last = time.monotonic()
        while not self._stop.wait(self.SAMPLE_PERIOD_S):
            now = time.monotonic()
            self._integrated_j += self._b.power_w() * (now - last)
            last = now
        now = time.monotonic()
        self._integrated_j += self._b.power_w() * (now - last)

    def __exit__(self, *exc):
        elapsed = max(time.monotonic() - self._t0, 1e-9)
        if self.method == "energy_counter":
            e1 = self._b.energy()
            self.joules = ((e1 or self._e0) - self._e0) / 1000.0
        else:
            self._stop.set()
            self._thread.join(timeout=2.0)
            self.joules = self._integrated_j
        self.mean_power_w = self.joules / elapsed
        return False


def set_power_cap(watts: int, index: int = 0) -> bool:
    """Set the GPU power limit. Returns False on any failure (never raises).

    Expected to be denied on cloud instances (no CAP_SYS_ADMIN); the agent
    reports the denial honestly, same as nvidia-smi -pl on the H100 pods.
    """
    for cmd in (["rocm-smi", "-d", str(index), "--setpoweroverdrive", str(watts)],
                ["amd-smi", "set", "-g", str(index), "-o", str(watts)]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and "denied" not in (r.stdout + r.stderr).lower():
                return True
        except Exception:
            continue
    return False


def hardware_info(index: int = 0) -> dict:
    try:
        b = AmdSmiBackend(index)
        return {"gpu": b.gpu_name(), "vram_gb": b.vram_gb()}
    except Exception:
        return {"gpu": "unknown", "vram_gb": 0}


if __name__ == "__main__":
    with EnergyMeter() as m:
        time.sleep(5)
    print(f"5s window [{m.method}]: {m.joules:.1f} J, mean {m.mean_power_w:.1f} W")
    print(hardware_info())
