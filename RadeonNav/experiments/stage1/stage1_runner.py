#!/usr/bin/env python3
"""Run the fixed Stage-1 UniLab experiments and save auditable JSON artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
UNILAB = ROOT / "UniLab"
DEFAULT_RESULTS = ROOT / "experiment-results" / "stage1"
GOLDEN_FIXTURE = ROOT / "refine-logs" / "golden-contract-fixture-v1.yaml"
PLANNER_FIXTURE = ROOT / "refine-logs" / "planner-config-v1.yaml"
EXPECTED_GOLDEN_SHA256 = (
    "de660f3aac0211eefaeb8e1ecbca11ab9995ae78e8f1948f5cc42d53ab78cc83"
)
EXPECTED_PLANNER_SHA256 = (
    "9372361aafd240278df8a7c37f162a6f419351377560c3aaed1a6eb2ac344842"
)
EXPECTED_CPP_SHA256 = "2206659a6a23886446dcfc05d86888d6cdc9b8a4e31f44cbbc4e2d17ba3d6ead"
GPU_BUDGET_HOURS = 4.0
FIXED_SEED = 1
ENV_SMOKE_NUM_ENVS = 8
ENV_SMOKE_WARMUP_STEPS = 2
ENV_SMOKE_NUM_STEPS = 10
ENV_SMOKE_TIMEOUT_SEC = 600
ALLOWED_RUN_IDS = {f"S1-R{index:03d}" for index in range(11)} | {"S1-M3"}


@dataclass(frozen=True)
class TrainSpec:
    run_id: str
    num_envs: int
    iterations: int
    require_rocm: bool
    timeout_sec: int
    warmup_iterations: int = 0


TRAIN_SPECS = {
    "S1-R004": TrainSpec("S1-R004", 8, 1, False, 1800),
    "S1-R005": TrainSpec("S1-R005", 128, 10, True, 900),
    "S1-R006": TrainSpec("S1-R006", 512, 40, True, 2700, 10),
    "S1-R007": TrainSpec("S1-R007", 1024, 40, True, 2700, 10),
    "S1-R008": TrainSpec("S1-R008", 2048, 40, True, 2700, 10),
    "S1-R009": TrainSpec("S1-R009", 0, 100, True, 3600),
    "S1-R010": TrainSpec("S1-R010", 0, 10, True, 1800),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(temporary, path)


def _new_attempt(results_root: Path, run_id: str) -> Path:
    if run_id not in ALLOWED_RUN_IDS:
        raise ValueError(f"unsupported run id: {run_id}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    attempt = results_root / run_id / f"attempt_{timestamp}_{os.getpid()}"
    attempt.mkdir(parents=True, exist_ok=False)
    return attempt


def _latest_result(results_root: Path, run_id: str) -> dict[str, Any] | None:
    paths = list((results_root / run_id).glob("attempt_*/result.json"))
    if not paths:
        return None
    path = max(paths, key=lambda candidate: candidate.stat().st_mtime_ns)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["_result_path"] = str(path)
    return payload


def _command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", "/tmp/unilab-uv-cache")
    env.setdefault("XDG_CACHE_HOME", "/tmp/unilab-cache")
    env.setdefault("MPLCONFIGDIR", "/tmp/unilab-matplotlib")
    return env


def _telemetry_candidates() -> list[list[str]]:
    candidates: list[list[str]] = []
    if shutil.which("amd-smi"):
        candidates.extend([["amd-smi", "metric"], ["amd-smi", "metric", "--json"]])
    if shutil.which("rocm-smi"):
        candidates.append(
            ["rocm-smi", "--showuse", "--showmemuse", "--showpower", "--json"]
        )
    return candidates


def _telemetry_worker(path: Path, stop: threading.Event, interval_sec: float) -> None:
    selected: list[str] | None = None
    for command in _telemetry_candidates():
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=10
            )
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0:
            selected = command
            break
    with path.open("a", encoding="utf-8") as stream:
        if selected is None:
            stream.write(
                json.dumps(
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "status": "unavailable",
                    }
                )
                + "\n"
            )
            return
        while not stop.is_set():
            try:
                result = subprocess.run(
                    selected,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=max(10, int(interval_sec * 2)),
                )
            except subprocess.TimeoutExpired:
                stream.write(
                    json.dumps(
                        {
                            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            "command": selected,
                            "status": "timeout",
                        }
                    )
                    + "\n"
                )
                stream.flush()
                continue
            parsed: Any = None
            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
            stream.write(
                json.dumps(
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "command": selected,
                        "returncode": result.returncode,
                        "parsed": parsed,
                        "stdout": None if parsed is not None else result.stdout,
                        "stderr": result.stderr,
                    }
                )
                + "\n"
            )
            stream.flush()
            stop.wait(interval_sec)


def _numeric_values(value: Any, key_pattern: re.Pattern[str]) -> list[float]:
    found: list[float] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key_pattern.search(str(key)):
                if isinstance(child, (int, float)):
                    found.append(float(child))
                elif isinstance(child, str):
                    match = re.search(r"-?\d+(?:\.\d+)?", child)
                    if match:
                        found.append(float(match.group()))
            found.extend(_numeric_values(child, key_pattern))
    elif isinstance(value, list):
        for child in value:
            found.extend(_numeric_values(child, key_pattern))
    return found


def _telemetry_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"samples": 0}
    samples = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    utilization: list[float] = []
    vram_percent: list[float] = []
    power_w: list[float] = []
    for sample in samples:
        parsed = sample.get("parsed")
        if parsed is not None:
            utilization.extend(
                _numeric_values(parsed, re.compile(r"(gfx.*activity|gpu.*util)", re.I))
            )
            vram_percent.extend(
                _numeric_values(
                    parsed,
                    re.compile(
                        r"(vram.*(%|percent)|memory.*(%|percent)|gpu memory allocated)",
                        re.I,
                    ),
                )
            )
            power_w.extend(
                _numeric_values(parsed, re.compile(r"(socket.*power|power)", re.I))
            )
        else:
            text = sample.get("stdout") or ""
            utilization.extend(
                float(value)
                for value in re.findall(
                    r"(?:GFX_ACTIVITY|GPU(?:_|\s)UTIL(?:IZATION)?)[^0-9]*(\d+(?:\.\d+)?)",
                    text,
                    re.I,
                )
            )
            power_w.extend(
                float(value)
                for value in re.findall(
                    r"(?:SOCKET_POWER|AVERAGE_POWER|POWER)[^0-9]*(\d+(?:\.\d+)?)",
                    text,
                    re.I,
                )
            )
            used = re.findall(
                r"USED_(?:VISIBLE_)?VRAM[^0-9]*(\d+(?:\.\d+)?)", text, re.I
            )
            total = re.findall(
                r"TOTAL_(?:VISIBLE_)?VRAM[^0-9]*(\d+(?:\.\d+)?)", text, re.I
            )
            if used and total and float(total[0]) > 0:
                vram_percent.append(100.0 * float(used[0]) / float(total[0]))

    def percentile95(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[math.ceil(0.95 * len(ordered)) - 1]

    return {
        "samples": len(samples),
        "gpu_utilization_mean": statistics.fmean(utilization) if utilization else None,
        "gpu_utilization_p50": statistics.median(utilization) if utilization else None,
        "gpu_utilization_p95": percentile95(utilization),
        "vram_percent_peak": max(vram_percent) if vram_percent else None,
        "power_w_mean": statistics.fmean(power_w) if power_w else None,
        "power_w_peak": max(power_w) if power_w else None,
    }


def _run(
    command: list[str],
    *,
    attempt: Path,
    timeout_sec: int,
    telemetry: bool = False,
) -> tuple[int, float, dict[str, Any]]:
    log_path = attempt / "run.log"
    telemetry_path = attempt / "gpu_metrics.jsonl"
    stop = threading.Event()
    thread: threading.Thread | None = None
    if telemetry:
        thread = threading.Thread(
            target=_telemetry_worker,
            args=(telemetry_path, stop, 5.0),
            daemon=True,
        )
        thread.start()

    started = time.monotonic()
    try:
        with log_path.open("x", encoding="utf-8") as log:
            log.write("$ " + " ".join(command) + "\n")
            log.flush()
            try:
                process = subprocess.Popen(
                    command,
                    cwd=UNILAB,
                    env=_command_env(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                returncode = process.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                log.write(f"\nTIMEOUT after {timeout_sec} seconds\n")
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                except ProcessLookupError:
                    pass
                returncode = 124
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=15)
    return returncode, time.monotonic() - started, _telemetry_summary(telemetry_path)


def _git_snapshot(path: Path) -> dict[str, Any]:
    def read(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args], cwd=path, capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None

    status = read("status", "--porcelain=v1")
    return {
        "commit": read("rev-parse", "HEAD"),
        "branch": read("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status),
        "status": status.splitlines() if status else [],
    }


def _torch_probe() -> dict[str, Any]:
    import torch

    available = bool(torch.cuda.is_available())
    names = (
        [
            torch.cuda.get_device_name(index)
            for index in range(torch.cuda.device_count())
        ]
        if available
        else []
    )
    return {
        "version": torch.__version__,
        "hip": torch.version.hip,
        "cuda_api_available": available,
        "device_count": torch.cuda.device_count() if available else 0,
        "device_names": names,
    }


def _rocm_ready(torch_info: dict[str, Any]) -> bool:
    names = " ".join(torch_info["device_names"]).lower()
    return bool(
        torch_info["hip"]
        and torch_info["cuda_api_available"]
        and torch_info["device_count"] > 0
        and Path("/dev/kfd").exists()
        and "w7900" in names
    )


def _gpu_hours_used(results_root: Path) -> float:
    total = 0.0
    for run_id in (f"S1-R{index:03d}" for index in range(5, 11)):
        for result_path in (results_root / run_id).glob("attempt_*/result.json"):
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            value = payload.get("gpu_hours")
            if isinstance(value, (int, float)):
                total += float(value)
    return total


def command_probe(args: argparse.Namespace) -> int:
    run_id = "S1-R001" if args.require_rocm else "S1-R000"
    attempt = _new_attempt(args.results_root, run_id)
    torch_info = _torch_probe()
    ready = _rocm_ready(torch_info)
    payload = {
        "run_id": run_id,
        "status": "PASSED" if (ready or not args.require_rocm) else "BLOCKED_ENV",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "tools": {
            name: shutil.which(name)
            for name in ("uv", "amd-smi", "rocm-smi", "rocminfo")
        },
        "devices": {
            "dev_kfd": Path("/dev/kfd").exists(),
            "render_nodes": (
                sorted(str(path) for path in Path("/dev/dri").glob("render*"))
                if Path("/dev/dri").exists()
                else []
            ),
        },
        "torch": torch_info,
        "rocm_w7900_ready": ready,
        "git": {"root": _git_snapshot(ROOT), "unilab": _git_snapshot(UNILAB)},
        "hashes": {
            "golden_fixture": _sha256(GOLDEN_FIXTURE),
            "planner_fixture": _sha256(PLANNER_FIXTURE),
            "cpp_checkpoint": _sha256(
                ROOT / "CPP/go2_rl_gym/deploy/pre_train/go2/go2_moe_cts_137k_0.6739.pt"
            ),
        },
    }
    _write_json(attempt / "result.json", payload)
    print(f"{payload['status']}: {attempt / 'result.json'}")
    return 0 if payload["status"] == "PASSED" else 2


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a YAML mapping")
    return payload


def command_contract(args: argparse.Namespace) -> int:
    attempt = _new_attempt(args.results_root, "S1-R002")
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        golden = _load_yaml(GOLDEN_FIXTURE)
        planner = _load_yaml(PLANNER_FIXTURE)
        observations = golden["expected_observation"]
        targets = golden["target_test"]["expected_target_canonical_rad"]
        checks = {
            "golden_hash": _sha256(GOLDEN_FIXTURE) == EXPECTED_GOLDEN_SHA256,
            "planner_hash": _sha256(PLANNER_FIXTURE) == EXPECTED_PLANNER_SHA256,
            "cpp_checkpoint_hash": _sha256(
                ROOT / "CPP/go2_rl_gym/deploy/pre_train/go2/go2_moe_cts_137k_0.6739.pt"
            )
            == EXPECTED_CPP_SHA256,
            "cpp_observation_dim": len(observations["cpp_moe"]) == 45,
            "unilab_observation_dim": len(observations["unilab_rough"]) == 45,
            "cpp_target_dim": len(targets["cpp_moe"]) == 12,
            "unilab_target_dim": len(targets["unilab_rough"]) == 12,
            "planner_resolution": planner["occupancy"]["resolution_m"] == 0.10,
            "planner_timeout": planner["command"]["timeout_s"] == 0.25,
        }
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    passed = bool(checks) and all(checks.values()) and not errors
    _write_json(
        attempt / "result.json",
        {
            "run_id": "S1-R002",
            "status": "PASSED" if passed else "FAILED",
            "checks": checks,
            "errors": errors,
        },
    )
    print(f"{'PASSED' if passed else 'FAILED'}: {attempt / 'result.json'}")
    return 0 if passed else 1


def _find_record(value: Any, required_key: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if required_key in value:
            return value
        for child in value.values():
            found = _find_record(child, required_key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_record(child, required_key)
            if found is not None:
                return found
    return None


def command_env_smoke(args: argparse.Namespace) -> int:
    attempt = _new_attempt(args.results_root, "S1-R003")
    benchmark_json = attempt / "env_step.json"
    command = [
        "uv",
        "run",
        "--no-sync",
        "benchmark/benchmark_env_step.py",
        "task=go2_joystick_rough/mujoco",
        f"num_envs={ENV_SMOKE_NUM_ENVS}",
        f"num_steps={ENV_SMOKE_NUM_STEPS}",
        f"warmup_steps={ENV_SMOKE_WARMUP_STEPS}",
        f"seed={FIXED_SEED}",
        f"out_json={benchmark_json}",
        "skip_plots=true",
    ]
    returncode, duration, _ = _run(
        command, attempt=attempt, timeout_sec=ENV_SMOKE_TIMEOUT_SEC
    )
    benchmark_payload = (
        json.loads(benchmark_json.read_text(encoding="utf-8"))
        if benchmark_json.exists()
        else None
    )
    record = _find_record(benchmark_payload, "actor_observation_dim")
    throughput = (
        record.get("plot_data", {}).get("throughput_env_steps_per_s")
        if record
        else None
    )
    checks = {
        "returncode": returncode == 0,
        "result_exists": benchmark_json.exists(),
        "throughput_positive": isinstance(throughput, (int, float)) and throughput > 0,
        "actor_observation_dim_45": bool(
            record and record["actor_observation_dim"] == 45
        ),
        "action_dim_12": bool(record and record["action_dim"] == 12),
        "finite_observation": bool(record and record["finite_observation"]),
        "seed_1": bool(record and record["seed"] == FIXED_SEED),
    }
    passed = all(checks.values())
    _write_json(
        attempt / "result.json",
        {
            "run_id": "S1-R003",
            "status": "PASSED" if passed else "FAILED",
            "command": command,
            "returncode": returncode,
            "duration_sec": duration,
            "checks": checks,
            "benchmark_record": record,
            "benchmark_json": str(benchmark_json),
            "log": str(attempt / "run.log"),
        },
    )
    print(f"{'PASSED' if passed else 'FAILED'}: {attempt / 'result.json'}")
    return 0 if passed else 1


def _validate_checkpoint(path: Path) -> tuple[bool, str | None]:
    import torch

    try:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        tensors: list[Any] = []

        def collect(value: Any) -> None:
            if isinstance(value, torch.Tensor):
                tensors.append(value)
            elif isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    collect(child)

        collect(payload)
        if not tensors:
            return False, "checkpoint contains no tensors"
        if not all(bool(torch.isfinite(tensor).all()) for tensor in tensors):
            return False, "checkpoint contains NaN/Inf"
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _training_artifacts(
    log_root: Path,
) -> tuple[Path | None, Path | None, Path | None, dict[str, Any], list[str]]:
    errors: list[str] = []
    task_root = log_root / "Go2JoystickRough"
    run_dirs = sorted(path for path in task_root.glob("*") if path.is_dir())
    if len(run_dirs) != 1:
        errors.append(f"expected one run directory, found {len(run_dirs)}")
        return None, None, None, {}, errors
    run_dir = run_dirs[0]
    config_path = run_dir / "run_config.json"
    summary_path = run_dir / "run_summary.json"
    if not config_path.is_file():
        errors.append("missing run_config.json")
    if not summary_path.is_file():
        errors.append("missing run_summary.json")
        return run_dir, config_path, None, {}, errors
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    raw_checkpoint = summary.get("last_checkpoint")
    checkpoint = Path(raw_checkpoint).resolve() if raw_checkpoint else None
    if checkpoint is None or not checkpoint.is_file():
        errors.append("summary last_checkpoint is missing")
    elif not checkpoint.is_relative_to(run_dir.resolve()):
        errors.append("summary checkpoint escapes its run directory")
    return run_dir, config_path, checkpoint, summary, errors


def _training_fps(log_path: Path, warmup_iterations: int) -> dict[str, Any]:
    values = [
        float(value)
        for value in re.findall(
            r"Steps per second:\s*(\d+(?:\.\d+)?)",
            log_path.read_text(encoding="utf-8", errors="replace"),
        )
    ]
    measured = values[warmup_iterations:]
    return {
        "all_samples": values,
        "warmup_iterations": warmup_iterations,
        "measured_samples": measured,
        "measured_mean": statistics.fmean(measured) if measured else None,
        "measured_p50": statistics.median(measured) if measured else None,
    }


def _checkpoint_iterations(run_dir: Path | None) -> list[int]:
    if run_dir is None:
        return []
    return sorted(
        {
            int(match.group(1))
            for path in run_dir.glob("model_*.pt")
            if (match := re.fullmatch(r"model_(\d+)\.pt", path.name))
        }
    )


def _tensorboard_axes(run_dir: Path | None) -> tuple[dict[str, Any], list[str]]:
    if run_dir is None:
        return {}, ["TensorBoard run directory is unavailable"]
    try:
        from tensorboard.backend.event_processing.event_accumulator import (
            EventAccumulator,
        )

        accumulator = EventAccumulator(str(run_dir), size_guidance={"scalars": 0})
        accumulator.Reload()
        available = set(accumulator.Tags().get("scalars", []))
        axes: dict[str, Any] = {}
        for tag in (
            "Perf/total_fps",
            "Train/mean_reward/time",
            "Train/mean_episode_length/time",
        ):
            if tag not in available:
                continue
            steps = [int(event.step) for event in accumulator.Scalars(tag)]
            if steps:
                axes[tag] = {
                    "count": len(steps),
                    "first_step": steps[0],
                    "last_step": steps[-1],
                    "monotonic": all(
                        current >= previous
                        for previous, current in zip(steps, steps[1:])
                    ),
                }
        errors = [] if "Perf/total_fps" in axes else ["missing Perf/total_fps"]
        errors.extend(
            f"non-monotonic TensorBoard axis: {tag}"
            for tag, axis in axes.items()
            if not axis["monotonic"]
        )
        return axes, errors
    except Exception as exc:
        return {}, [f"TensorBoard parse failed: {type(exc).__name__}: {exc}"]


def _check_checkpoint_sequence(
    run_id: str,
    checkpoint_iterations: list[int],
    summary: dict[str, Any],
    prior_result: dict[str, Any] | None,
) -> list[str]:
    if run_id not in {"S1-R009", "S1-R010"}:
        return []
    errors: list[str] = []
    completed = summary.get("completed_iterations")
    if not checkpoint_iterations:
        return ["no numbered checkpoints found"]
    if any(
        current - previous != 1
        for previous, current in zip(checkpoint_iterations, checkpoint_iterations[1:])
    ):
        errors.append("checkpoint interval is not continuous at save_interval=1")
    if checkpoint_iterations[-1] != completed:
        errors.append("final checkpoint iteration differs from run summary")
    expected_first = 0
    if prior_result is not None:
        expected_first = prior_result.get("summary", {}).get("completed_iterations")
    if checkpoint_iterations[0] != expected_first:
        errors.append(
            f"first checkpoint iteration is {checkpoint_iterations[0]}, "
            f"expected {expected_first}"
        )
    return errors


def _training_command(
    spec: TrainSpec,
    *,
    log_root: Path,
    resume_from: Path | None,
) -> list[str]:
    command = [
        "uv",
        "run",
        "--no-sync",
        "train",
        "--algo",
        "ppo",
        "--task",
        "go2_joystick_rough",
        "--sim",
        "mujoco",
        f"algo.num_envs={spec.num_envs}",
        f"algo.max_iterations={spec.iterations}",
        "algo.save_interval=1",
        f"algo.seed={FIXED_SEED}",
        "algo.algorithm.enable_compile=false",
        "training.no_play=true",
        "training.logger=tensorboard",
        f"training.log_root={log_root}",
    ]
    if resume_from is not None:
        command.append(f"algo.load_run={resume_from}")
    return command


def _run_training(
    args: argparse.Namespace,
    spec: TrainSpec,
    *,
    resume_from: Path | None = None,
    prior_result: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    attempt = _new_attempt(args.results_root, spec.run_id)
    torch_info = _torch_probe()
    if spec.require_rocm and not _rocm_ready(torch_info):
        payload = {
            "run_id": spec.run_id,
            "status": "BLOCKED_ENV",
            "reason": "ROCm PyTorch, /dev/kfd, and an AMD W7900 are required",
            "torch": torch_info,
        }
        _write_json(attempt / "result.json", payload)
        print(f"BLOCKED_ENV: {attempt / 'result.json'}")
        return 2, payload
    if spec.require_rocm and not _telemetry_candidates():
        payload = {
            "run_id": spec.run_id,
            "status": "BLOCKED_ENV",
            "reason": "amd-smi or rocm-smi is required for GPU accounting",
            "torch": torch_info,
        }
        _write_json(attempt / "result.json", payload)
        print(f"BLOCKED_ENV: {attempt / 'result.json'}")
        return 2, payload

    used_hours = _gpu_hours_used(args.results_root)
    remaining_sec = max(0, int((GPU_BUDGET_HOURS - used_hours) * 3600))
    if spec.require_rocm and remaining_sec <= 0:
        payload = {
            "run_id": spec.run_id,
            "status": "BLOCKED_BUDGET",
            "gpu_hours_used": used_hours,
            "gpu_hour_limit": GPU_BUDGET_HOURS,
        }
        _write_json(attempt / "result.json", payload)
        print(f"BLOCKED_BUDGET: {attempt / 'result.json'}")
        return 2, payload

    timeout_sec = (
        min(spec.timeout_sec, remaining_sec) if spec.require_rocm else spec.timeout_sec
    )
    log_root = attempt / "unilab-runs"
    command = _training_command(spec, log_root=log_root, resume_from=resume_from)
    returncode, duration, telemetry = _run(
        command,
        attempt=attempt,
        timeout_sec=timeout_sec,
        telemetry=spec.require_rocm,
    )
    run_dir, config_path, checkpoint, summary, errors = _training_artifacts(log_root)
    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path is not None and config_path.is_file()
        else {}
    )
    checkpoint_valid = False
    checkpoint_error: str | None = None
    if checkpoint is not None and checkpoint.is_file():
        checkpoint_valid, checkpoint_error = _validate_checkpoint(checkpoint)
        if checkpoint_error:
            errors.append(checkpoint_error)

    fps = _training_fps(attempt / "run.log", spec.warmup_iterations)
    if len(fps["all_samples"]) != spec.iterations:
        errors.append(
            f"found {len(fps['all_samples'])} FPS samples, expected {spec.iterations}"
        )
    steps_per_sec = fps["measured_mean"]
    tensorboard_axes, tensorboard_errors = _tensorboard_axes(run_dir)
    errors.extend(tensorboard_errors)
    checkpoint_iterations = _checkpoint_iterations(run_dir)
    errors.extend(
        _check_checkpoint_sequence(
            spec.run_id, checkpoint_iterations, summary, prior_result
        )
    )

    total_steps = summary.get("total_env_steps")
    expected_device = config.get("run", {}).get("device")
    if spec.require_rocm and expected_device != "cuda":
        errors.append(f"run_config device is {expected_device!r}, expected 'cuda'")
    if spec.require_rocm:
        missing_telemetry = [
            key
            for key in (
                "gpu_utilization_mean",
                "vram_percent_peak",
                "power_w_mean",
            )
            if telemetry.get(key) is None
        ]
        if telemetry.get("samples", 0) < 1 or missing_telemetry:
            errors.append(
                "missing required GPU telemetry: "
                + ", ".join(missing_telemetry or ["samples"])
            )
    if prior_result is not None:
        prior_steps = prior_result.get("summary", {}).get("total_env_steps")
        if not isinstance(total_steps, (int, float)) or not isinstance(
            prior_steps, (int, float)
        ):
            errors.append("resume total steps are unavailable")
        elif total_steps <= prior_steps:
            errors.append("resume total steps did not increase")
        prior_iteration = prior_result.get("summary", {}).get("completed_iterations")
        current_iteration = summary.get("completed_iterations")
        if not isinstance(prior_iteration, int) or not isinstance(
            current_iteration, int
        ):
            errors.append("resume iteration values are unavailable")
        elif current_iteration <= prior_iteration:
            errors.append("resume iteration did not increase")
        prior_axes = prior_result.get("tensorboard_axes", {})
        for tag, prior_axis in prior_axes.items():
            current_axis = tensorboard_axes.get(tag)
            if current_axis is None:
                errors.append(f"resume TensorBoard tag disappeared: {tag}")
            elif current_axis["first_step"] < prior_axis["last_step"]:
                errors.append(f"resume TensorBoard axis reset: {tag}")

    passed = (
        returncode == 0
        and summary.get("status") == "completed"
        and checkpoint_valid
        and not errors
    )
    payload = {
        "run_id": spec.run_id,
        "status": "PASSED" if passed else "FAILED",
        "command": command,
        "returncode": returncode,
        "duration_sec": duration,
        "gpu_hours": duration / 3600 if spec.require_rocm else 0.0,
        "seed": FIXED_SEED,
        "num_envs": spec.num_envs,
        "iterations": spec.iterations,
        "warmup_iterations": spec.warmup_iterations,
        "require_rocm": spec.require_rocm,
        "torch": torch_info,
        "run_dir": str(run_dir) if run_dir else None,
        "run_config_path": str(config_path) if config_path else None,
        "checkpoint_path": str(checkpoint) if checkpoint else None,
        "checkpoint_sha256": (
            _sha256(checkpoint)
            if checkpoint is not None and checkpoint.is_file()
            else None
        ),
        "checkpoint_valid": checkpoint_valid,
        "checkpoint_iterations": checkpoint_iterations,
        "steps_per_sec": steps_per_sec,
        "fps": fps,
        "tensorboard_axes": tensorboard_axes,
        "telemetry": telemetry,
        "summary": summary,
        "errors": errors,
        "log": str(attempt / "run.log"),
    }
    _write_json(attempt / "result.json", payload)
    print(f"{payload['status']}: {attempt / 'result.json'}")
    return (0 if passed else 1), payload


def command_microtrain(args: argparse.Namespace) -> int:
    return _run_training(args, TRAIN_SPECS[args.run_id])[0]


def command_throughput_scan(args: argparse.Namespace) -> int:
    results: list[dict[str, Any]] = []
    for run_id in ("S1-R006", "S1-R007", "S1-R008"):
        code, payload = _run_training(args, TRAIN_SPECS[run_id])
        if code != 0:
            return code
        results.append(payload)
    selected = _select_throughput_result(results)
    if selected is None:
        return 1
    attempt = _new_attempt(args.results_root, "S1-M3")
    _write_json(
        attempt / "result.json",
        {
            "status": "PASSED",
            "selected_run_id": selected["run_id"],
            "selected_num_envs": selected["num_envs"],
            "selection_rule": "max stable steps/s; prefer smaller num_envs when gain <5%",
            "candidates": [
                {
                    "run_id": result["run_id"],
                    "num_envs": result["num_envs"],
                    "steps_per_sec": result["steps_per_sec"],
                    "telemetry": result["telemetry"],
                }
                for result in results
            ],
        },
    )
    print(f"PASSED: selected {selected['num_envs']} envs")
    return 0


def _select_throughput_result(
    results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    eligible = [
        result
        for result in results
        if result["status"] == "PASSED"
        and result["steps_per_sec"]
        and (
            result["telemetry"].get("vram_percent_peak") is None
            or result["telemetry"]["vram_percent_peak"] <= 90
        )
    ]
    if not eligible:
        return None
    ranked = sorted(eligible, key=lambda result: result["steps_per_sec"], reverse=True)
    selected = ranked[0]
    if len(ranked) > 1:
        gain = selected["steps_per_sec"] / ranked[1]["steps_per_sec"] - 1
        if gain < 0.05:
            selected = min(ranked[:2], key=lambda result: result["num_envs"])
    return selected


def command_stability(args: argparse.Namespace) -> int:
    selection = _latest_result(args.results_root, "S1-M3")
    if selection is None or selection.get("status") != "PASSED":
        print("BLOCKED_DEP: no passed S1-M3 selection")
        return 2
    spec = TrainSpec(
        "S1-R009",
        int(selection["selected_num_envs"]),
        TRAIN_SPECS["S1-R009"].iterations,
        True,
        TRAIN_SPECS["S1-R009"].timeout_sec,
    )
    return _run_training(args, spec)[0]


def command_resume(args: argparse.Namespace) -> int:
    prior = _latest_result(args.results_root, "S1-R009")
    if prior is None or prior.get("status") != "PASSED" or not prior.get("run_dir"):
        print("BLOCKED_DEP: no passed S1-R009 run")
        return 2
    spec = TrainSpec(
        "S1-R010",
        int(prior["num_envs"]),
        TRAIN_SPECS["S1-R010"].iterations,
        True,
        TRAIN_SPECS["S1-R010"].timeout_sec,
    )
    return _run_training(
        args, spec, resume_from=Path(prior["run_dir"]), prior_result=prior
    )[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--require-rocm", action="store_true")
    probe.set_defaults(handler=command_probe)

    contract = subparsers.add_parser("contract")
    contract.set_defaults(handler=command_contract)

    env_smoke = subparsers.add_parser("env-smoke")
    env_smoke.set_defaults(handler=command_env_smoke)

    microtrain = subparsers.add_parser("microtrain")
    microtrain.add_argument(
        "--run-id", choices=("S1-R004", "S1-R005"), default="S1-R004"
    )
    microtrain.set_defaults(handler=command_microtrain)

    scan = subparsers.add_parser("throughput-scan")
    scan.set_defaults(handler=command_throughput_scan)

    stability = subparsers.add_parser("stability")
    stability.set_defaults(handler=command_stability)

    resume = subparsers.add_parser("resume")
    resume.set_defaults(handler=command_resume)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.results_root = args.results_root.resolve()
    if not args.results_root.is_relative_to(ROOT):
        raise SystemExit(f"--results-root must stay inside {ROOT}")
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
