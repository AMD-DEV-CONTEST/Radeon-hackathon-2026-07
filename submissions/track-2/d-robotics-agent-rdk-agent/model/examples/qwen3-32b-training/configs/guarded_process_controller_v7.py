#!/usr/bin/env python3
"""Monitor one fixed process and fail closed on CPU/GPU memory pressure."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_HOSTNAME = "u-7701-ae3eba8a"
EXPECTED_MACHINE_SHA256 = "7c225d1717bb5f671c4bf071b1df172abdc72a50a3ed53e24de9ab724d35ad54"
CPU_LIMIT = 48 * 1024**3
GPU_LIMIT = 44 * 1024**3
GPU_BASELINE_LIMIT = 1 * 1024**3
INTERVAL_SECONDS = 0.25
MAX_SAMPLE_START_GAP_SECONDS = 1.0
MAX_SAMPLE_DURATION_SECONDS = 0.5
EXPECTED_GPU_UNIQUE_ID = "0x1f135175d2ee4757"
EXPECTED_GPU_TOTAL_BYTES = 51_522_830_336
GPU_SYSFS_DEVICE = Path("/sys/class/drm/card3/device")
EXPECTED_GPU_SYSFS_DEVICE = Path(
    "/sys/devices/pci0000:40/0000:40:01.7/0000:41:00.0/0000:42:00.0/0000:43:00.0"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def machine_sha256() -> str:
    return hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def read_int(path: str) -> int:
    return int(Path(path).read_text().strip())


def read_events() -> dict[str, int]:
    return {
        key: int(value)
        for key, value in (
            line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines()
        )
    }


def read_memory_stat() -> dict[str, int]:
    return {
        key: int(value)
        for key, value in (
            line.split() for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines()
        )
    }


def reclaim_files(descriptors: list[int]) -> None:
    for descriptor in descriptors:
        os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)


def gpu_sample() -> dict[str, Any]:
    """Read the bound physical GPU directly from amdgpu sysfs."""

    started = time.monotonic()
    require(GPU_SYSFS_DEVICE.resolve(strict=True) == EXPECTED_GPU_SYSFS_DEVICE, "GPU sysfs path changed")
    unique_id = "0x" + (GPU_SYSFS_DEVICE / "unique_id").read_text().strip().lower()
    total_bytes = read_int(str(GPU_SYSFS_DEVICE / "mem_info_vram_total"))
    used_bytes = read_int(str(GPU_SYSFS_DEVICE / "mem_info_vram_used"))
    completed = time.monotonic()
    return {
        "gpu_unique_id": unique_id,
        "gpu_total_bytes": total_bytes,
        "gpu_used_bytes": used_bytes,
        "probe_seconds": completed - started,
        "probe_source": "amdgpu_sysfs",
        "probe_completed_monotonic": completed,
    }


def resource_sample(
    sample_number: int,
    phase: str,
    previous_sample_started: float | None,
    reclaim_descriptors: list[int],
) -> dict[str, Any]:
    sample_started = time.monotonic()
    reclaim_files(reclaim_descriptors)
    cpu = read_int("/sys/fs/cgroup/memory.current")
    memory_stat = read_memory_stat()
    events = read_events()
    gpu = gpu_sample()
    sample_completed = time.monotonic()
    return {
        "sample": sample_number,
        "phase": phase,
        "sample_started_monotonic": sample_started,
        "sample_completed_monotonic": sample_completed,
        "sample_start_gap_seconds": (
            None if previous_sample_started is None else sample_started - previous_sample_started
        ),
        "sample_duration_seconds": sample_completed - sample_started,
        "cpu_current_bytes": cpu,
        "cpu_anon_bytes": memory_stat.get("anon"),
        "cpu_file_bytes": memory_stat.get("file"),
        "memory_events": events,
        **gpu,
    }


def sample_quality_error(sample: dict[str, Any]) -> str | None:
    gap = sample["sample_start_gap_seconds"]
    if gap is not None and gap > MAX_SAMPLE_START_GAP_SECONDS:
        return f"sample start gap {gap:.6f}s exceeds {MAX_SAMPLE_START_GAP_SECONDS:.6f}s"
    duration = sample["sample_duration_seconds"]
    if duration > MAX_SAMPLE_DURATION_SECONDS:
        return f"sample duration {duration:.6f}s exceeds {MAX_SAMPLE_DURATION_SECONDS:.6f}s"
    return None


def validate_gpu_sample(sample: dict[str, Any]) -> None:
    require(sample["gpu_unique_id"] == EXPECTED_GPU_UNIQUE_ID, "GPU identity changed")
    require(sample["gpu_total_bytes"] == EXPECTED_GPU_TOTAL_BYTES, "GPU capacity changed")


def child_preexec() -> None:
    parent_before = os.getppid()
    os.setsid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        os._exit(126)
    if parent_before <= 1 or os.getppid() != parent_before:
        os._exit(126)


def send_pidfd(pidfd: int, sig: signal.Signals) -> None:
    require(hasattr(signal, "pidfd_send_signal"), "pidfd_send_signal unavailable")
    signal.pidfd_send_signal(pidfd, sig)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        require(not path.exists(), f"result already exists: {path}")
        os.link(temporary, path)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--reclaim-file", action="append", type=Path, default=[])
    parser.add_argument("--expected-exit-code", type=int, default=0)
    parser.add_argument("--expected-result-status", default="PASS")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    require(args.command, "gate command missing")
    return args


def main() -> None:
    args = parse_args()
    require(socket.gethostname() == EXPECTED_HOSTNAME, "hostname mismatch")
    require(machine_sha256() == EXPECTED_MACHINE_SHA256, "machine-id mismatch")
    require(hasattr(os, "pidfd_open"), "pidfd_open unavailable")
    require(hasattr(signal, "pidfd_send_signal"), "pidfd_send_signal unavailable")
    require(not args.run_dir.exists(), f"run directory exists: {args.run_dir}")
    args.run_dir.mkdir(parents=True, mode=0o755)
    require(hasattr(os, "posix_fadvise"), "posix_fadvise unavailable")
    reclaim_descriptors: list[int] = []
    for path in args.reclaim_file:
        require(path.is_file() and not path.is_symlink(), f"reclaim target invalid: {path}")
        require(path.stat().st_mode & 0o222 == 0, f"reclaim target writable: {path}")
        reclaim_descriptors.append(os.open(path, os.O_RDONLY | os.O_CLOEXEC))
    cpu_before_initial_reclaim = read_int("/sys/fs/cgroup/memory.current")
    reclaim_files(reclaim_descriptors)
    cpu_after_initial_reclaim = read_int("/sys/fs/cgroup/memory.current")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    events_before = read_events()
    gpu_before = gpu_sample()
    validate_gpu_sample(gpu_before)
    require(gpu_before["gpu_used_bytes"] < GPU_BASELINE_LIMIT, "GPU is not idle enough for an exclusive gate")
    require(read_int("/sys/fs/cgroup/memory.current") < CPU_LIMIT, "cgroup already above guard threshold")

    telemetry_path = args.run_dir / "telemetry.jsonl"
    log_path = args.run_dir / "gate.log"
    started_unix = time.time()
    started_monotonic = time.monotonic()
    breach: dict[str, Any] | None = None
    monitor_error: str | None = None
    maximum_cpu = 0
    maximum_gpu = 0
    maximum_sample_start_gap = 0.0
    maximum_sample_duration = 0.0
    samples = 0
    deadline = time.monotonic()
    previous_sample_started: float | None = None
    final_sample: dict[str, Any] | None = None
    postflight_error: str | None = None
    with log_path.open("xb", buffering=0) as log_handle, telemetry_path.open("x", encoding="utf-8") as telemetry:
        child_launch_started_monotonic = time.monotonic()
        previous_sample_started = child_launch_started_monotonic
        child = subprocess.Popen(
            args.command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            preexec_fn=child_preexec,
        )
        pidfd = os.pidfd_open(child.pid, 0)
        try:
            while child.poll() is None:
                deadline += INTERVAL_SECONDS
                try:
                    sample = resource_sample(
                        samples,
                        "running",
                        previous_sample_started,
                        reclaim_descriptors,
                    )
                    previous_sample_started = sample["sample_started_monotonic"]
                    validate_gpu_sample(sample)
                    maximum_cpu = max(maximum_cpu, sample["cpu_current_bytes"])
                    maximum_gpu = max(maximum_gpu, sample["gpu_used_bytes"])
                    maximum_sample_start_gap = max(
                        maximum_sample_start_gap,
                        sample["sample_start_gap_seconds"] or 0.0,
                    )
                    maximum_sample_duration = max(
                        maximum_sample_duration,
                        sample["sample_duration_seconds"],
                    )
                    telemetry.write(json.dumps(sample, sort_keys=True) + "\n")
                    telemetry.flush()
                    os.fsync(telemetry.fileno())
                    samples += 1
                    quality_error = sample_quality_error(sample)
                    if sample["cpu_current_bytes"] >= CPU_LIMIT:
                        breach = {"kind": "CPU_MEMORY", "sample": sample}
                    elif sample["gpu_used_bytes"] >= GPU_LIMIT:
                        breach = {"kind": "GPU_MEMORY", "sample": sample}
                    elif any(
                        sample["memory_events"].get(key, 0) > events_before.get(key, 0)
                        for key in ("max", "oom", "oom_kill", "oom_group_kill")
                    ):
                        breach = {"kind": "CGROUP_MEMORY_EVENT", "sample": sample}
                    if quality_error is not None:
                        monitor_error = f"SAMPLE_QUALITY: {quality_error}"
                except BaseException as error:
                    monitor_error = f"{type(error).__name__}: {error}"
                if breach is not None or monitor_error is not None:
                    send_pidfd(pidfd, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        send_pidfd(pidfd, signal.SIGKILL)
                    break
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
            exit_code = child.wait()
        finally:
            os.close(pidfd)
        try:
            final_sample = resource_sample(
                samples,
                "postflight",
                previous_sample_started,
                reclaim_descriptors,
            )
            previous_sample_started = final_sample["sample_started_monotonic"]
            validate_gpu_sample(final_sample)
            maximum_cpu = max(maximum_cpu, final_sample["cpu_current_bytes"])
            maximum_gpu = max(maximum_gpu, final_sample["gpu_used_bytes"])
            maximum_sample_start_gap = max(
                maximum_sample_start_gap,
                final_sample["sample_start_gap_seconds"] or 0.0,
            )
            maximum_sample_duration = max(
                maximum_sample_duration,
                final_sample["sample_duration_seconds"],
            )
            telemetry.write(json.dumps(final_sample, sort_keys=True) + "\n")
            telemetry.flush()
            os.fsync(telemetry.fileno())
            samples += 1
            quality_error = sample_quality_error(final_sample)
            if quality_error is not None:
                postflight_error = f"SAMPLE_QUALITY: {quality_error}"
        except BaseException as error:
            postflight_error = f"{type(error).__name__}: {error}"
        if postflight_error is not None and monitor_error is None:
            monitor_error = f"POSTFLIGHT: {postflight_error}"
        try:
            telemetry.flush()
            os.fsync(telemetry.fileno())
        except BaseException as error:
            if monitor_error is None:
                monitor_error = f"TELEMETRY_FINALIZE: {type(error).__name__}: {error}"
    os.chmod(log_path, 0o444)
    os.chmod(telemetry_path, 0o444)
    for descriptor in reclaim_descriptors:
        os.close(descriptor)

    gate_result_path = args.run_dir / "gate-result.json"
    gate_result: dict[str, Any] | None = None
    gate_result_error: str | None = None
    if gate_result_path.exists() or gate_result_path.is_symlink():
        try:
            require(gate_result_path.is_file() and not gate_result_path.is_symlink(), "gate result is invalid")
            parsed_gate_result = json.loads(gate_result_path.read_text())
            require(isinstance(parsed_gate_result, dict), "gate result is not an object")
            gate_result = parsed_gate_result
        except BaseException as error:
            gate_result_error = f"{type(error).__name__}: {error}"
            if monitor_error is None:
                monitor_error = f"GATE_RESULT: {gate_result_error}"
    reported_gpu_peak = None
    if gate_result is not None:
        try:
            for section in ("gpu_memory", "gpu_after"):
                value = gate_result.get(section, {}).get("max_reserved")
                if value is not None:
                    reported_gpu_peak = max(int(value), reported_gpu_peak or 0)
        except BaseException as error:
            gate_result_error = f"{type(error).__name__}: {error}"
            if monitor_error is None:
                monitor_error = f"GATE_RESULT_GPU_PEAK: {gate_result_error}"
    events_after = final_sample["memory_events"] if final_sample is not None else None
    final_gpu = (
        {
            key: final_sample[key]
            for key in (
                "gpu_unique_id",
                "gpu_total_bytes",
                "gpu_used_bytes",
                "probe_seconds",
                "probe_source",
                "probe_completed_monotonic",
            )
        }
        if final_sample is not None
        else None
    )
    cpu_after = final_sample["cpu_current_bytes"] if final_sample is not None else None
    identity_ok = (
        socket.gethostname() == EXPECTED_HOSTNAME
        and machine_sha256() == EXPECTED_MACHINE_SHA256
        and Path("/proc/sys/kernel/random/boot_id").read_text().strip() == boot_id
        and final_sample is not None
        and final_sample["gpu_unique_id"] == EXPECTED_GPU_UNIQUE_ID
        and final_sample["gpu_total_bytes"] == EXPECTED_GPU_TOTAL_BYTES
    )
    post_exit_event_delta = (
        {
            key: events_after.get(key, 0) - events_before.get(key, 0)
            for key in ("max", "oom", "oom_kill", "oom_group_kill")
        }
        if events_after is not None
        else None
    )
    if breach is None and final_sample is not None and final_sample["cpu_current_bytes"] >= CPU_LIMIT:
        breach = {"kind": "POST_EXIT_CPU_MEMORY", "sample": final_sample}
    if breach is None and final_sample is not None and final_sample["gpu_used_bytes"] >= GPU_LIMIT:
        breach = {"kind": "POST_EXIT_GPU_MEMORY", "sample": final_sample}
    if breach is None and post_exit_event_delta is not None and any(value > 0 for value in post_exit_event_delta.values()):
        breach = {"kind": "POST_EXIT_CGROUP_EVENT", "delta": post_exit_event_delta}
    if breach is None and reported_gpu_peak is not None and reported_gpu_peak >= GPU_LIMIT:
        breach = {"kind": "GATE_REPORTED_GPU_PEAK", "bytes": reported_gpu_peak}
    telemetry_lines = sum(1 for _ in telemetry_path.open("r", encoding="utf-8"))
    if telemetry_lines != samples and monitor_error is None:
        monitor_error = f"TELEMETRY_INVENTORY: lines={telemetry_lines} samples={samples}"
    telemetry_evidence = {
        "path": str(telemetry_path),
        "bytes": telemetry_path.stat().st_size,
        "lines": telemetry_lines,
        "sha256": sha256_file(telemetry_path),
    }
    if breach is not None:
        status = "RESOURCE_BREACH"
    elif monitor_error is not None:
        status = "MONITOR_ERROR"
    elif not identity_ok:
        status = "INFRASTRUCTURE_ABORTED"
    elif (
        exit_code == args.expected_exit_code
        and gate_result is not None
        and gate_result.get("status") == args.expected_result_status
    ):
        status = "PASS"
    else:
        status = "FAIL"
    result = {
        "schema_version": "guarded_gate_controller.v7",
        "status": status,
        "command": args.command,
        "hostname": socket.gethostname(),
        "machine_sha256": machine_sha256(),
        "boot_id": boot_id,
        "controller_pid": os.getpid(),
        "gate_pid": child.pid,
        "gate_exit_code": exit_code,
        "expected_exit_code": args.expected_exit_code,
        "expected_result_status": args.expected_result_status,
        "started_unix": started_unix,
        "child_launch_started_monotonic": child_launch_started_monotonic,
        "elapsed_seconds": time.monotonic() - started_monotonic,
        "cpu_limit_bytes": CPU_LIMIT,
        "gpu_limit_bytes": GPU_LIMIT,
        "gpu_baseline_limit_bytes": GPU_BASELINE_LIMIT,
        "sampling_interval_seconds": INTERVAL_SECONDS,
        "max_sample_start_gap_limit_seconds": MAX_SAMPLE_START_GAP_SECONDS,
        "max_sample_duration_limit_seconds": MAX_SAMPLE_DURATION_SECONDS,
        "maximum_sample_start_gap_seconds": maximum_sample_start_gap,
        "maximum_sample_duration_seconds": maximum_sample_duration,
        "samples": samples,
        "maximum_cpu_current_bytes": maximum_cpu,
        "maximum_gpu_used_bytes": maximum_gpu,
        "gate_reported_gpu_peak_bytes": reported_gpu_peak,
        "cpu_before_initial_reclaim_bytes": cpu_before_initial_reclaim,
        "cpu_after_initial_reclaim_bytes": cpu_after_initial_reclaim,
        "cpu_after_bytes": cpu_after,
        "events_before": events_before,
        "events_after": events_after,
        "post_exit_event_delta": post_exit_event_delta,
        "gpu_before": gpu_before,
        "gpu_after": final_gpu,
        "breach": breach,
        "monitor_error": monitor_error,
        "postflight_error": postflight_error,
        "identity_ok": identity_ok,
        "gate_result": gate_result,
        "gate_result_error": gate_result_error,
        "telemetry": telemetry_evidence,
        "containment": {
            "pidfd": True,
            "parent_death_signal": True,
            "new_session": True,
            "dedicated_cgroup_leaf": False,
            "scoped_posix_fadvise_dontneed": [str(path) for path in args.reclaim_file],
            "reason": "container cgroup2 mount is read-only",
            "sampling_boundary": (
                "direct bound amdgpu sysfs and cgroup sampling targeted every 250ms; "
                "any observed start gap above 1.0s or sample duration above 0.5s is non-PASS; "
                "gate-reported torch max_reserved is supplemental"
            ),
        },
    }
    result_path = args.run_dir / "controller-result.json"
    atomic_json(result_path, result)
    directory = os.open(args.run_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    print(json.dumps({"status": status, "result": str(result_path)}, sort_keys=True), flush=True)
    raise SystemExit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
