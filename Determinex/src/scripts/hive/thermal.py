"""
scripts/hive/thermal.py — Hardware-agnostic thermal monitor
=============================================================
Reads temperatures from whatever sources are available on the host machine.
Works on any OS, any GPU vendor.  Never crashes the build — every failure
mode degrades gracefully to "temperature unknown."

Source priority order:
  1. NVIDIA  — nvidia-smi (Windows / Linux / macOS)
  2. AMD GPU — rocm-smi   (Linux AMD rigs)
  3. CPU/all — psutil.sensors_temperatures (Linux, macOS)
  4. CPU/all — WMI MSAcpi_ThermalZoneTemperature (Windows, best-effort)
  5. CPU proxy — psutil.cpu_percent (always available — heat correlates with load)

Standalone daemon:
  python -m hive.thermal               # poll every 30s, print to stdout
  python -m hive.thermal --interval 10 --danger-gpu 85 --danger-cpu 90

Build loop integration (from executor.py):
  from hive.thermal import check_temps_or_pause
  check_temps_or_pause(session_id="abc123")  # blocks until safe, or raises if critical
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("hive.thermal")

# ── Safety thresholds (°C) ────────────────────────────────────────────────────
GPU_WARN_C = 80  # log warning
GPU_DANGER_C = 85  # pause build loop until cool
GPU_CRITICAL_C = 90  # abort session

CPU_WARN_C = 85
CPU_DANGER_C = 92
CPU_CRITICAL_C = 95

# Proxy: if we can't read CPU temp, treat >90% sustained CPU usage as "hot"
CPU_USAGE_PROXY_WARN = 85.0
CPU_USAGE_PROXY_DANGER = 93.0

# How long to sleep between poll retries when cooling down
COOLDOWN_SLEEP_S = 30
MAX_COOLDOWN_POLLS = 10  # give up waiting after this many polls


@dataclass
class ThermalSnapshot:
    """One point-in-time temperature reading from all available sources."""

    timestamp: float = field(default_factory=time.time)

    gpu_temps: list[float] = field(default_factory=list)  # °C, one per GPU
    cpu_temps: list[float] = field(default_factory=list)  # °C, one per chip/core
    cpu_usage: float = 0.0  # 0-100 %

    sources_tried: list[str] = field(default_factory=list)
    sources_ok: list[str] = field(default_factory=list)

    @property
    def max_gpu(self) -> float | None:
        return max(self.gpu_temps) if self.gpu_temps else None

    @property
    def max_cpu(self) -> float | None:
        return max(self.cpu_temps) if self.cpu_temps else None

    @property
    def summary(self) -> str:
        parts = []
        if self.max_gpu is not None:
            parts.append(f"GPU={self.max_gpu:.0f}°C")
        if self.max_cpu is not None:
            parts.append(f"CPU={self.max_cpu:.0f}°C")
        parts.append(f"CPU%={self.cpu_usage:.0f}%")
        parts.append(f"[via {','.join(self.sources_ok) or 'none'}]")
        return " ".join(parts)

    @property
    def danger_level(self) -> str:
        """'ok', 'warn', 'danger', or 'critical'"""
        gpu = self.max_gpu
        cpu = self.max_cpu

        # Critical check first
        if (gpu is not None and gpu >= GPU_CRITICAL_C) or (
            cpu is not None and cpu >= CPU_CRITICAL_C
        ):
            return "critical"

        # Danger
        if (
            (gpu is not None and gpu >= GPU_DANGER_C)
            or (cpu is not None and cpu >= CPU_DANGER_C)
            or self.cpu_usage >= CPU_USAGE_PROXY_DANGER
        ):
            return "danger"

        # Warn
        if (
            (gpu is not None and gpu >= GPU_WARN_C)
            or (cpu is not None and cpu >= CPU_WARN_C)
            or self.cpu_usage >= CPU_USAGE_PROXY_WARN
        ):
            return "warn"

        return "ok"


# ── Reader implementations ────────────────────────────────────────────────────


def _read_nvidia_smi() -> list[float]:
    """NVIDIA: parse nvidia-smi --query-gpu=temperature.gpu"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return []
        temps = []
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.lstrip("-").isdigit() or (line.replace(".", "").isdigit()):
                try:
                    temps.append(float(line))
                except ValueError:
                    pass
        return temps
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _read_rocm_smi() -> list[float]:
    """AMD GPU (Linux): parse rocm-smi --showtemp"""
    try:
        r = subprocess.run(
            ["rocm-smi", "--showtemp", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return []
        import json

        data = json.loads(r.stdout)
        temps = []
        for card_data in data.values():
            for key, val in card_data.items():
                if "temp" in key.lower():
                    try:
                        temps.append(float(str(val).rstrip("c°C ")))
                    except ValueError:
                        pass
        return temps
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, Exception):
        return []


def _read_psutil_cpu() -> list[float]:
    """psutil.sensors_temperatures — works on Linux and macOS."""
    try:
        import psutil

        sensors = psutil.sensors_temperatures()
        if not sensors:
            return []
        temps = []
        # Prefer coretemp, k10temp, cpu_thermal
        priority_keys = ["coretemp", "k10temp", "cpu_thermal", "acpitz"]
        all_keys = list(sensors.keys())
        ordered = [k for k in priority_keys if k in all_keys] + [
            k for k in all_keys if k not in priority_keys
        ]
        for key in ordered[:3]:  # top 3 sensor groups
            for entry in sensors[key]:
                if entry.current and entry.current > 0:
                    temps.append(float(entry.current))
        return temps
    except (AttributeError, ImportError, Exception):
        return []


def _read_wmi_cpu() -> list[float]:
    """Windows WMI thermal zones — best effort, often returns nothing on Win11."""
    if sys.platform != "win32":
        return []
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi "
                "-ErrorAction SilentlyContinue).CurrentTemperature",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        temps = []
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                # WMI reports in tenths of Kelvin
                kelvin_tenths = int(line)
                celsius = (kelvin_tenths / 10.0) - 273.15
                if 0 < celsius < 120:
                    temps.append(celsius)
        return temps
    except (subprocess.TimeoutExpired, OSError, Exception):
        return []


def _read_cpu_usage() -> float:
    """psutil CPU % — universally available, used as load proxy."""
    try:
        import psutil

        return psutil.cpu_percent(interval=0.5)
    except (ImportError, Exception):
        return 0.0


# ── Public API ────────────────────────────────────────────────────────────────


def read_temps() -> ThermalSnapshot:
    """
    Collect temperatures from all available sources.
    Never raises — all failures are silently captured in sources_tried.
    """
    snap = ThermalSnapshot()

    # GPU sources
    snap.sources_tried.append("nvidia-smi")
    gpu_nv = _read_nvidia_smi()
    if gpu_nv:
        snap.gpu_temps.extend(gpu_nv)
        snap.sources_ok.append("nvidia-smi")

    if not snap.gpu_temps:
        snap.sources_tried.append("rocm-smi")
        gpu_amd = _read_rocm_smi()
        if gpu_amd:
            snap.gpu_temps.extend(gpu_amd)
            snap.sources_ok.append("rocm-smi")

    # CPU sources
    snap.sources_tried.append("psutil")
    cpu_ps = _read_psutil_cpu()
    if cpu_ps:
        snap.cpu_temps.extend(cpu_ps)
        snap.sources_ok.append("psutil")

    if not snap.cpu_temps:
        snap.sources_tried.append("wmi")
        cpu_wmi = _read_wmi_cpu()
        if cpu_wmi:
            snap.cpu_temps.extend(cpu_wmi)
            snap.sources_ok.append("wmi")

    # CPU usage proxy (always)
    snap.cpu_usage = _read_cpu_usage()

    return snap


def check_temps_or_pause(
    session_id: str = "",
    gpu_danger: float = GPU_DANGER_C,
    gpu_critical: float = GPU_CRITICAL_C,
    cpu_danger: float = CPU_DANGER_C,
    cpu_critical: float = CPU_CRITICAL_C,
    cooldown_sleep: float = COOLDOWN_SLEEP_S,
    max_polls: int = MAX_COOLDOWN_POLLS,
) -> ThermalSnapshot:
    """
    Called by the build executor before each step.

    - ok / warn:    return immediately (warn gets logged)
    - danger:       sleep and poll until cool, then return
    - critical:     raise ThermalCriticalError — caller should abort session

    Returns the ThermalSnapshot from when temps were safe (or last reading).
    """
    for poll in range(max_polls):
        snap = read_temps()
        level = snap.danger_level

        prefix = f"[thermal{f' session={session_id}' if session_id else ''}]"

        if level == "ok":
            if poll > 0:
                log.info("%s cooled down — resuming build. %s", prefix, snap.summary)
            return snap

        if level == "warn":
            log.warning("%s temps elevated — %s", prefix, snap.summary)
            return snap  # warn but don't block

        if level == "critical":
            log.error("%s CRITICAL TEMP — aborting. %s", prefix, snap.summary)
            raise ThermalCriticalError(
                f"Temperature critical — build aborted to protect hardware. "
                f"{snap.summary}. Session {session_id} can be resumed once cool."
            )

        # danger: pause
        if poll == 0:
            log.warning(
                "%s DANGER: temps too high — pausing build for %ds. %s",
                prefix,
                int(cooldown_sleep),
                snap.summary,
            )
        else:
            log.info("%s still hot (poll %d/%d) — %s", prefix, poll + 1, max_polls, snap.summary)

        time.sleep(cooldown_sleep)

    # max_polls exhausted: take one more reading and decide
    snap = read_temps()
    if snap.danger_level == "critical":
        raise ThermalCriticalError(
            f"Temperature still critical after {max_polls} cooldown polls. "
            f"Build aborted. {snap.summary}"
        )
    # still danger but we've waited long enough — log and continue
    log.warning(
        "[thermal] Resuming after %d cooldown polls (still warm). %s", max_polls, snap.summary
    )
    return snap


def thermal_throttle_factor(snap: ThermalSnapshot | None = None) -> float:
    """
    #39: Return a [0.0, 1.0] throttle factor based on current thermal state.
    0.0 = cool, no throttling.  1.0 = near-danger, heavy throttling.

    Use this to scale IPC timeouts so that thermally-throttled hardware doesn't
    cause spurious timeout failures when model inference is running slow:
        timeout = base_timeout * (1 + thermal_throttle_factor())

    At 'ok': factor ≈ 0.0   → timeout unchanged
    At 'warn': factor ≈ 0.3  → timeout +30%
    At 'danger': factor ≈ 0.8 → timeout +80%  (after which we'd pause anyway)
    """
    if snap is None:
        try:
            snap = read_temps()
        except Exception:
            return 0.0

    gpu = snap.max_gpu
    cpu = snap.max_cpu
    usage = snap.cpu_usage

    factor = 0.0

    # GPU-based scaling: linearly from warn_threshold → danger_threshold maps 0.0 → 0.8
    if gpu is not None:
        if gpu >= GPU_DANGER_C:
            factor = max(factor, 0.8)
        elif gpu >= GPU_WARN_C:
            factor = max(factor, 0.3 + 0.5 * (gpu - GPU_WARN_C) / (GPU_DANGER_C - GPU_WARN_C))

    # CPU-based scaling
    if cpu is not None:
        if cpu >= CPU_DANGER_C:
            factor = max(factor, 0.8)
        elif cpu >= CPU_WARN_C:
            factor = max(factor, 0.3 + 0.5 * (cpu - CPU_WARN_C) / (CPU_DANGER_C - CPU_WARN_C))

    # CPU load proxy (when temperature sensors unavailable)
    if usage >= CPU_USAGE_PROXY_DANGER:
        factor = max(factor, 0.7)
    elif usage >= CPU_USAGE_PROXY_WARN:
        factor = max(
            factor,
            0.2
            + 0.5
            * (usage - CPU_USAGE_PROXY_WARN)
            / (CPU_USAGE_PROXY_DANGER - CPU_USAGE_PROXY_WARN),
        )

    return min(factor, 1.0)


def dynamic_ipc_timeout(base_timeout: float, snap: ThermalSnapshot | None = None) -> float:
    """
    #39: Return a thermally-adjusted IPC timeout.

    Thermally throttled hardware runs inference slower than spec. Static timeouts
    cause spurious failures when the GPU is at 83°C and throttling inference by 20%.

    Formula: timeout = base_timeout * (1 + throttle_factor)

    The executor should call this before every Ollama/llama-cpp IPC call:
        timeout = dynamic_ipc_timeout(base_timeout=90.0)

    The snap argument allows passing a pre-read ThermalSnapshot to avoid
    reading sensors twice in the same executor step.
    """
    factor = thermal_throttle_factor(snap)
    scaled = base_timeout * (1.0 + factor)
    if factor > 0.1:
        log.debug(
            "IPC timeout scaled: %.0fs → %.0fs (throttle_factor=%.2f)", base_timeout, scaled, factor
        )
    return scaled


def thermal_hard_halt(
    session_id: str = "",
    gpu_danger: float = GPU_DANGER_C,
) -> ThermalSnapshot:
    """
    #23: Hard thermal DAG halt — GPU danger = immediate session abort.

    Unlike check_temps_or_pause() which treats "danger" as a cooldown + retry,
    this function treats GPU >= gpu_danger as a HARD abort.

    Why "danger" is already too late for inference quality:
      At 85°C, NVIDIA GPUs activate thermal throttling, reducing clock speed
      by 10-20%. This doesn't just slow inference down — it changes the
      numerical behavior of FP16/BF16 tensor cores. The reduced mantissa
      precision at lower clock frequencies introduces rounding noise that
      accumulates through transformer attention heads. The model literally
      produces dumber output at high temps, and no amount of retrying will
      fix it because the hardware is degraded.

    The safe sequence is:
      1. Abort the DAG immediately (no retry).
      2. Let the GPU cool below GPU_WARN_C organically.
      3. User (or daemon) resumes the session when hardware is healthy.
    """
    snap = read_temps()
    gpu = snap.max_gpu

    prefix = f"[thermal{f' session={session_id}' if session_id else ''}]"

    if gpu is not None and gpu >= gpu_danger:
        log.error(
            "%s #23 HARD THERMAL HALT: GPU at %.0f°C (limit=%.0f°C) — "
            "aborting DAG to protect inference quality. %s",
            prefix,
            gpu,
            gpu_danger,
            snap.summary,
        )
        raise ThermalCriticalError(
            f"#23 GPU temperature {gpu:.0f}°C exceeds hard limit {gpu_danger:.0f}°C. "
            f"Inference quality is degraded by thermal throttling. "
            f"Session {session_id} aborted — resume when GPU cools below {GPU_WARN_C}°C. "
            f"{snap.summary}"
        )

    # If GPU is OK, fall through to the regular check for CPU temps
    return check_temps_or_pause(
        session_id=session_id,
        gpu_danger=gpu_danger,
    )


class ThermalCriticalError(RuntimeError):
    """Raised when temperatures reach a level that risks hardware damage."""


# ── Standalone daemon mode ────────────────────────────────────────────────────


def _run_daemon(interval: int, danger_gpu: float, danger_cpu: float) -> None:
    """Poll temperatures on a fixed interval and print alerts."""
    import signal

    print(f"[thermal] Determinex thermal monitor — polling every {interval}s")
    print(
        f"[thermal] Thresholds: GPU warn={GPU_WARN_C}°C danger={danger_gpu}°C critical={GPU_CRITICAL_C}°C"
    )
    print(
        f"[thermal] Thresholds: CPU warn={CPU_WARN_C}°C danger={danger_cpu}°C critical={CPU_CRITICAL_C}°C"
    )
    print("[thermal] Ctrl+C to stop\n")

    def _signal_handler(sig, frame):
        print("\n[thermal] Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)

    log_path = Path(__file__).resolve().parent.parent.parent / "logs" / "thermal.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        snap = read_temps()
        level = snap.danger_level

        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {snap.summary}"

        if level == "critical":
            msg = f"🔴 CRITICAL {line}"
        elif level == "danger":
            msg = f"🟠 DANGER   {line}"
        elif level == "warn":
            msg = f"🟡 WARN     {line}"
        else:
            msg = f"🟢 OK       {line}"

        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

        time.sleep(interval)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Determinex thermal monitor daemon")
    p.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default 30)")
    p.add_argument(
        "--danger-gpu",
        type=float,
        default=GPU_DANGER_C,
        help=f"GPU danger threshold °C (default {GPU_DANGER_C})",
    )
    p.add_argument(
        "--danger-cpu",
        type=float,
        default=CPU_DANGER_C,
        help=f"CPU danger threshold °C (default {CPU_DANGER_C})",
    )
    p.add_argument("--once", action="store_true", help="Print one reading and exit")
    args = p.parse_args()

    if args.once:
        snap = read_temps()
        print(snap.summary)
        print(f"Level: {snap.danger_level}")
        sys.exit(0)

    _run_daemon(args.interval, args.danger_gpu, args.danger_cpu)
