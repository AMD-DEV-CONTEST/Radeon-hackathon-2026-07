"""
scripts/hive/offline_observer.py — Async Offline Monitor Observer
==================================================================
Plan B: When sessions run in fast_mode (Builder → Compiler only, Monitor skipped),
no DPO comparison pairs are generated. The training flywheel stalls.

This daemon fills the gap by retroactively running Monitor on completed fast-mode
steps when the GPU is idle — without blocking the original build session.

Design:
  - Scans all sessions for step_N.offline_pending WAL markers
  - Checks GPU idle: VRAM in use < _IDLE_VRAM_GB OR no nvidia-smi available
  - Runs Monitor against the saved Builder output and compiler result
  - Writes Monitor verdict to the training vault as a DPO comparison entry
  - Renames step_N.offline_pending → step_N.offline_complete

GPU idle detection:
  We use the same source priority as thermal.py (nvidia-smi → psutil).
  < _IDLE_VRAM_GB (default 2GB) in use means no active inference is running.
  This is conservative — 2GB is well below any model load.

Usage:
  python -m hive.offline_observer              # single pass, exit when done
  python -m hive.offline_observer --daemon     # continuous daemon, poll every 5 min
  python -m hive.offline_observer --interval 120 --idle-vram 1.5  # custom settings

Integration with ForgeDaemon:
  The offline observer is a separate process. ForgeDaemon handles encrypted telemetry;
  this handles Monitor retroactive evaluation. They share the sessions directory but
  write to different files (.offline_pending vs .enc) — no lock contention.

Limitations (documented, not hidden):
  "Who tests Monitor?" — Monitor may have the same blind spots as Builder if they
  share the same base model. On Tier 0 with one local model, offline Monitor is still
  useful for structural/style catches, not semantic ones.
  At Tier 1+, Monitor is a different model family — the comparison is meaningful.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("hive.offline_observer")

# ── Idle detection thresholds ────────────────────────────────────────────────
_IDLE_VRAM_GB = 2.0  # below this = "GPU is idle, safe to run Monitor"
_IDLE_CPU_PCT = 60.0  # below this = "CPU is not saturated"

# ── Paths ────────────────────────────────────────────────────────────────────
_ROOT = (
    Path(os.environ["DETERMINEX_ROOT"]).resolve()
    if os.environ.get("DETERMINEX_ROOT")
    else Path(__file__).resolve().parent.parent.parent
)
_SESSIONS_DIR = _ROOT / "sessions"
_LOCKFILE = _ROOT / ".determinex_offline_observer.lock"


# ── GPU idle detection ────────────────────────────────────────────────────────

# #45 TOCTOU: require this many seconds of physical user idle before loading weights
MIN_PHYSICAL_IDLE_SECONDS = 300  # 5 minutes AFK


def _get_physical_idle_seconds() -> float:
    """#45 TOCTOU guard: seconds elapsed since last keyboard/mouse input.

    A VRAM snapshot alone is a Time-Of-Check to Time-Of-Use (TOCTOU) race.
    The daemon checks VRAM -> finds 6 GB free -> begins loading 4 GB of weights
    over ~800 ms of NVMe I/O. The user sits back down mid-load. WDDM detects
    two processes claiming the same VRAM and triggers a Timeout Detection &
    Recovery (TDR) -- the screen goes black and the session is killed.
    A 5-minute physical idle gate is much longer than any weight-loading window.
    """
    if os.name == "nt":
        try:
            import ctypes

            class _LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]

            lii = _LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            idle_ms = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return idle_ms / 1000.0
        except Exception:
            pass
    # POSIX: try X11 idle reporter (installed on most Linux desktops)
    try:
        r = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            return int(r.stdout.strip()) / 1000.0
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    # Cannot detect -- assume idle so the daemon is not permanently blocked
    return float("inf")


def _vram_used_gb() -> float | None:
    """Return total VRAM currently in use across all GPUs, or None if unavailable."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return None
        total = 0.0
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.replace(".", "").isdigit():
                total += float(line) / 1024.0  # MiB → GiB
        return total
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _cpu_percent() -> float:
    try:
        import psutil

        return psutil.cpu_percent(interval=1.0)
    except (ImportError, Exception):
        return 0.0


def is_gpu_idle(idle_vram_gb: float = _IDLE_VRAM_GB, idle_cpu_pct: float = _IDLE_CPU_PCT) -> bool:
    """
    Return True if the GPU (and CPU) appear idle enough to run Monitor inference.

    #45 TOCTOU: Checks physical keyboard/mouse idle FIRST. A snapshot of free
    VRAM is not sufficient -- the user could return during the 800ms NVMe model
    load window, causing a WDDM TDR crash.
    """
    physical_idle = _get_physical_idle_seconds()
    if physical_idle < MIN_PHYSICAL_IDLE_SECONDS:
        log.debug(
            "Physical idle gate: user active %.0fs ago (need %.0fs) -- deferring",
            physical_idle,
            MIN_PHYSICAL_IDLE_SECONDS,
        )
        return False

    vram = _vram_used_gb()
    if vram is not None and vram >= idle_vram_gb:
        log.debug("GPU not idle: %.2fGB VRAM in use (threshold=%.1fGB)", vram, idle_vram_gb)
        return False

    cpu = _cpu_percent()
    if cpu >= idle_cpu_pct:
        log.debug("CPU not idle: %.0f%% usage (threshold=%.0f%%)", cpu, idle_cpu_pct)
        return False

    log.debug(
        "GPU idle: VRAM=%.2fGB (or unavailable), CPU=%.0f%%, physical_idle=%.0fs",
        vram if vram is not None else 0.0,
        cpu,
        physical_idle,
    )
    return True


# ── Lockfile — prevent concurrent observer runs ───────────────────────────────


# ── #22 Ephemeral worker helpers ────────────────────────────────────────────────────
# Python's GC cannot collect circular references in PyTorch/llama-cpp tensor
# graphs over long daemon uptimes. Memory balloons from 150MB to 8GB+ and
# the OS kills the app. Fix: run each batch in an isolated subprocess that
# fully exits afterward, letting the OS reclaim all memory unconditionally.


def _ephemeral_monitor_worker(
    step_data: dict,
    session_lang: str,
    model_assignments: dict,
    result_queue: multiprocessing.Queue,
) -> None:
    """Worker entrypoint. Runs _run_monitor_offline and puts result in queue."""
    try:
        score, verdict = _run_monitor_offline(step_data, session_lang, model_assignments)
        result_queue.put((score, verdict))
    except Exception as e:
        result_queue.put((0.5, f"ephemeral_worker_error: {e}"))


def _run_monitor_ephemeral(
    step_data: dict,
    session_lang: str,
    model_assignments: dict,
    timeout: float = 300.0,
) -> tuple[float, str]:
    """#22: Run heavy Monitor inference in a short-lived child process.

    The child exits completely after returning the result, guaranteeing the OS
    reclaims all tensor/model memory. No GC cycle or circular reference can
    survive a process boundary.
    """
    ctx = multiprocessing.get_context("spawn")
    q: multiprocessing.Queue = ctx.Queue()
    p = ctx.Process(
        target=_ephemeral_monitor_worker,
        args=(step_data, session_lang, model_assignments, q),
        daemon=True,
    )
    p.start()
    p.join(timeout=timeout)

    if p.is_alive():
        log.warning("#22 Ephemeral Monitor worker timed out (%.0fs) — terminating", timeout)
        p.terminate()
        p.join(timeout=5)
        if p.is_alive():
            p.kill()
        return 0.5, "monitor_timeout_ephemeral"

    if p.exitcode != 0:
        log.warning("#22 Ephemeral worker exit code %d", p.exitcode)
        return 0.5, f"monitor_worker_exit_{p.exitcode}"

    try:
        return q.get_nowait()
    except Exception:
        return 0.5, "monitor_result_unavailable"


class ObserverLock:
    """Simple PID-based lockfile. Prevents two observer processes running simultaneously."""

    def __enter__(self) -> ObserverLock:
        if _LOCKFILE.exists():
            try:
                pid = int(_LOCKFILE.read_text().strip())
                import os

                try:
                    os.kill(pid, 0)
                    # G27: PermissionError means the PID exists but is owned by another
                    # user — it IS alive and the lock is valid. Only ProcessLookupError
                    # (ESRCH) means the process is truly gone and the lock is stale.
                    raise RuntimeError(
                        f"Offline observer already running (pid={pid}). "
                        f"If it crashed, delete {_LOCKFILE} and retry."
                    )
                except ProcessLookupError:
                    log.warning("Stale lockfile (pid=%d not found) — removing", pid)
                    _LOCKFILE.unlink(missing_ok=True)
                # PermissionError → process alive, re-raise RuntimeError above
            except (ValueError, OSError):
                _LOCKFILE.unlink(missing_ok=True)

        import os

        _LOCKFILE.write_text(str(os.getpid()))
        return self

    def __exit__(self, *_) -> None:
        _LOCKFILE.unlink(missing_ok=True)


# ── Monitor call ──────────────────────────────────────────────────────────────


def _run_monitor_offline(
    step_data: dict,
    session_lang: str,
    model_assignments: dict,
) -> tuple[float, str]:
    """
    Run Monitor against a saved Builder output. Returns (score, verdict).
    This is the same logic as the live Monitor call in execute_step(),
    decoupled from the session lifecycle.
    """
    try:
        import litellm

        from hive.api_client import api_call

        monitor_model = model_assignments.get("monitor")
        if not monitor_model:
            return 0.5, "no_monitor_model_assigned"

        builder_output_path = step_data.get("builder_output_path", "")
        if builder_output_path and Path(builder_output_path).exists():
            builder_code = Path(builder_output_path).read_text(encoding="utf-8")
        else:
            # Fall back to best attempt from outputs dir
            builder_code = step_data.get("compiler_output", "")[:2000]
            if not builder_code:
                return 0.5, "no_builder_output_available"

        compiler_passed = step_data.get("compiler_result", "") == "pass"

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a code review monitor for {session_lang.capitalize()} projects. "
                    "Score the builder's output 0.0-1.0 on correctness, safety, and adherence "
                    "to the step instruction. Reply with ONLY a JSON object: "
                    '{"score": 0.0-1.0, "verdict": "one sentence", "issues": ["..."]}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Step instruction: {step_data.get('instruction', '')}\n\n"
                    f"Builder output:\n```\n{builder_code[:3000]}\n```\n\n"
                    f"Compiler result: {'PASS' if compiler_passed else 'FAIL'}\n\n"
                    f"[Offline evaluation — original session ran in fast mode]"
                ),
            },
        ]

        resp = api_call(litellm.completion, model=monitor_model, messages=messages)
        text = resp.choices[0].message.content or ""

        import re

        m = re.search(r"\{[^}]+\}", text)
        if m:
            obj = json.loads(m.group())
            return float(obj.get("score", 0.5)), obj.get("verdict", text[:200])
        return 0.5, text[:200]

    except Exception as e:
        log.warning("Offline Monitor call failed: %s", e)
        return 0.5, f"monitor_error: {e}"


# ── DPO pair writer ───────────────────────────────────────────────────────────


def _write_dpo_pair(
    session_id: str, step_id: int, step_data: dict, monitor_score: float, monitor_verdict: str
) -> None:
    """
    Write a DPO training pair to the session's training vault.

    Structure:
      - prompt: step instruction + file context (what Builder received)
      - chosen:  Builder output (compiled) + Monitor score/verdict
      - rejected: none yet — compare across steps in the same session later

    The training pipeline aggregates these pairs. A step with score < 0.6 AND
    a later step in the same session that passed both compiler + Monitor at score ≥ 0.8
    becomes a (rejected, chosen) DPO pair during the next retrain.
    """
    vault_dir = _ROOT / "sessions" / session_id / "training_vault"
    vault_dir.mkdir(parents=True, exist_ok=True)

    pair = {
        "session_id": session_id,
        "step_id": step_id,
        "instruction": step_data.get("instruction", ""),
        "builder_output": step_data.get("builder_output_path", ""),
        "compiler_result": step_data.get("compiler_result", ""),
        "monitor_score": monitor_score,
        "monitor_verdict": monitor_verdict,
        "evaluation_mode": "offline",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    out = vault_dir / f"step_{step_id:04d}_offline_dpo.json"
    # G26: atomic write — temp→rename so a reader never sees a partial file
    import os as _os_g26

    tmp = out.with_name(f"step_{step_id:04d}_offline_dpo.{_os_g26.getpid()}.tmp")
    tmp.write_text(json.dumps(pair, indent=2), encoding="utf-8")
    tmp.replace(out)
    log.info("  DPO pair written → %s (score=%.2f)", out.name, monitor_score)


# ── Core observation pass ─────────────────────────────────────────────────────


def run_observation_pass(
    model_assignments: dict | None = None,
    idle_vram_gb: float = _IDLE_VRAM_GB,
    idle_cpu_pct: float = _IDLE_CPU_PCT,
    max_steps_per_pass: int = 20,
) -> int:
    """
    Single observation pass: find pending offline steps, run Monitor on each.
    Returns number of steps processed.

    Called either once (CLI --run-once) or on each daemon poll interval.
    """
    from hive.api_client import load_role_assignments
    from hive.manifest import (
        find_offline_pending,
        load_manifest,
        save_manifest,
        wal_complete_offline,
    )

    if model_assignments is None:
        model_assignments = load_role_assignments()

    pending = find_offline_pending(_SESSIONS_DIR)
    if not pending:
        log.debug("No offline_pending steps found")
        return 0

    log.info("Offline observer: %d steps queued for evaluation", len(pending))

    if not is_gpu_idle(idle_vram_gb, idle_cpu_pct):
        log.info("GPU/CPU not idle — deferring offline observation")
        return 0

    processed = 0
    for session_id, step_id in pending[:max_steps_per_pass]:
        try:
            session = load_manifest(session_id)
        except Exception as e:
            log.warning("Could not load manifest for session %s: %s", session_id, e)
            continue

        # Find the step record
        step = next((s for s in session.steps if s.id == step_id), None)
        if step is None:
            log.warning("Step %d not found in session %s manifest — skipping", step_id, session_id)
            continue

        # Rebuild step_data dict for Monitor
        from dataclasses import asdict

        step_data = asdict(step)

        log.info("  Evaluating session=%s step=%d offline...", session_id[:8], step_id)
        # #22 Ephemeral worker: run Monitor in isolated subprocess to prevent
        # Python GC tensor reference leaks from accumulating across batches.
        score, verdict = _run_monitor_ephemeral(step_data, session.lang, model_assignments)

        # Write DPO pair
        _write_dpo_pair(session_id, step_id, step_data, score, verdict)

        # Determine result label
        result = "pass" if score >= 0.7 else "fail"

        # Update step record in manifest
        step.offline_observation_pending = False
        step.offline_observation_result = result
        save_manifest(session)

        # Rename WAL marker
        wal_complete_offline(session_id, step_id, result)

        log.info(
            "  Step %d: offline Monitor score=%.2f verdict=%s → %s",
            step_id,
            score,
            verdict[:60],
            result,
        )
        processed += 1

        # Re-check idle state between steps — a live session may have started
        if not is_gpu_idle(idle_vram_gb, idle_cpu_pct):
            log.info(
                "GPU/CPU became active — pausing offline observation after %d steps", processed
            )
            break

    return processed


# ── Daemon mode ───────────────────────────────────────────────────────────────


def run_daemon(
    interval_s: int = 300, idle_vram_gb: float = _IDLE_VRAM_GB, idle_cpu_pct: float = _IDLE_CPU_PCT
) -> None:
    """Poll for offline_pending steps on a fixed interval."""
    import signal

    print("[offline_observer] Determinex offline Monitor daemon")
    print(f"[offline_observer] Poll interval: {interval_s}s")
    print(f"[offline_observer] Idle threshold: VRAM < {idle_vram_gb}GB, CPU < {idle_cpu_pct}%")
    print(f"[offline_observer] Sessions dir: {_SESSIONS_DIR}")
    print("[offline_observer] Ctrl+C to stop\n")

    def _sig(sig, frame):
        print("\n[offline_observer] Stopped.")
        _LOCKFILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig)

    with ObserverLock():
        while True:
            try:
                n = run_observation_pass(idle_vram_gb=idle_vram_gb, idle_cpu_pct=idle_cpu_pct)
                if n > 0:
                    print(f"[offline_observer] Processed {n} steps")
            except Exception as e:
                log.error("Observation pass error (continuing): %s", e)
            time.sleep(interval_s)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser(description="Determinex offline Monitor observer")
    p.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    p.add_argument(
        "--interval", type=int, default=300, help="Daemon poll interval in seconds (default 300)"
    )
    p.add_argument(
        "--idle-vram",
        type=float,
        default=_IDLE_VRAM_GB,
        help=f"VRAM idle threshold GB (default {_IDLE_VRAM_GB})",
    )
    p.add_argument(
        "--idle-cpu",
        type=float,
        default=_IDLE_CPU_PCT,
        help=f"CPU idle threshold %% (default {_IDLE_CPU_PCT})",
    )
    p.add_argument(
        "--force", action="store_true", help="Skip idle check — run regardless of GPU state"
    )
    p.add_argument("--list-pending", action="store_true", help="List pending steps and exit")
    args = p.parse_args()

    if args.list_pending:
        from hive.manifest import find_offline_pending

        pending = find_offline_pending(_SESSIONS_DIR)
        if not pending:
            print("No steps pending offline observation.")
        else:
            print(f"{len(pending)} steps pending offline observation:")
            for sid, step_id in pending:
                print(f"  session={sid[:8]}... step={step_id}")
        sys.exit(0)

    if args.force:
        # Override idle check by temporarily setting impossible thresholds
        _IDLE_VRAM_GB_override = 9999.0
        _IDLE_CPU_PCT_override = 9999.0
    else:
        _IDLE_VRAM_GB_override = args.idle_vram
        _IDLE_CPU_PCT_override = args.idle_cpu

    if args.daemon:
        run_daemon(
            interval_s=args.interval,
            idle_vram_gb=_IDLE_VRAM_GB_override,
            idle_cpu_pct=_IDLE_CPU_PCT_override,
        )
    else:
        with ObserverLock():
            n = run_observation_pass(
                idle_vram_gb=_IDLE_VRAM_GB_override,
                idle_cpu_pct=_IDLE_CPU_PCT_override,
            )
        print(f"[offline_observer] Processed {n} steps.")
