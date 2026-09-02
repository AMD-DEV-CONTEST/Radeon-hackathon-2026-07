#!/usr/bin/env python3
"""Benchmark the frozen r5 deployed pipeline at fixed Radeon environment counts."""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import torch

SCAFFOLD_ROOT = Path(__file__).resolve().parents[1]
if str(SCAFFOLD_ROOT) not in sys.path:
    sys.path.insert(0, str(SCAFFOLD_ROOT))

from tools.build_radeon_formal_scaling_protocol import (
    AGGREGATE_FILENAME,
    BASELINE_FREE_VRAM_FRACTION_MIN,
    CONTEXT_FIT_STEPS,
    CONTEXT_SEED_BASE,
    CONTEXT_SEED_REPETITION_STRIDE,
    DROPOUT_START_STEP,
    ENV_COUNTS,
    FROZEN_STATUS,
    GENESIS_SEED,
    GLOBAL_GPU_LOCK_PATH,
    MAX_MEASURED_CV,
    MEASURED_RUNS,
    MIN_512_VS_32_SPEEDUP,
    PROJECTED_512_GROWTH_MULTIPLIER,
    PROJECTED_512_TOTAL_FRACTION_MAX,
    PROTOCOL_VERSION,
    R5_EVALUATOR,
    ROCM_SMI_SAMPLE_INTERVAL_S,
    SCALING_BUILDER,
    SCALING_SCRIPT,
    SERIAL_GPU_QUEUE_HELPER,
    STEPS,
    WARMUP_RUNS,
    canonical_json_bytes,
    canonical_sha256,
    load_strict_json,
    require_official_r5_protocol_sha256,
    require_sha256,
    sha256_file,
    sha256_source_tree,
    validate_source_r5,
    write_json_exclusive,
)
from tools.build_radeon_formal_scaling_protocol import (
    SCHEMA_VERSION as PROTOCOL_SCHEMA_VERSION,
)

AGGREGATE_SCHEMA_VERSION = "flightguard-radeon-formal-scaling-result-v1"
WORKER_SCHEMA_VERSION = "flightguard-radeon-formal-scaling-worker-v1"
WORKER_CHECK_NAMES = {
    "backend_is_amdgpu",
    "visible_gpu_count_is_one",
    "torch_hip_nonempty",
    "python_version_matches_r5",
    "numpy_version_matches_r5",
    "torch_version_matches_r5",
    "torch_hip_matches_r5",
    "genesis_version_matches_r5",
    "genesis_source_tree_matches_r5",
    "nominal_domain_has_no_scheduled_faults",
    "one_warmup_three_measured",
    "all_repetitions_exact_800_steps",
    "all_repetitions_exact_fixed_calls",
    "all_repetitions_finite",
    "all_repetitions_froze_context",
    "post_freeze_context_updates_zero",
    "all_repetitions_have_rocm_smi_samples",
    "all_rocm_smi_samples_parse_without_error",
    "fault_or_repair_result_selection_absent",
    "mission_outcomes_do_not_change_fixed_steps",
}
PREFLIGHT_SCHEMA_VERSION = "flightguard-radeon-formal-scaling-preflight-v1"


@dataclass(frozen=True)
class ScalingConfig:
    protocol_path: Path
    protocol_sha256: str
    source_protocol_path: Path
    source_protocol_sha256: str
    source_project_root: Path
    scaffold_project_root: Path
    genesis_source_root: Path
    output_root: Path
    aggregate_path: Path
    worker_paths: tuple[Path, ...]
    runtime: dict[str, Any]
    checkpoint: dict[str, Any]
    expected_environment: dict[str, Any]
    scaling_script_sha256: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-env-count", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-env-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def _resolve_absolute(value: Any, *, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return path.resolve()


def _validate_scaffold_files(
    protocol: dict[str, Any],
    *,
    scaffold_root: Path,
) -> dict[str, str]:
    scaffold = protocol.get("scaffold")
    if not isinstance(scaffold, dict):
        raise TypeError("protocol scaffold binding is missing")
    if (
        _resolve_absolute(
            scaffold.get("project_root"),
            name="scaffold.project_root",
        )
        != scaffold_root
    ):
        raise ValueError("scaffold project root differs from this executable")
    files = scaffold.get("implementation_files_sha256")
    if not isinstance(files, dict) or set(files) != {
        SCALING_BUILDER,
        SCALING_SCRIPT,
        SERIAL_GPU_QUEUE_HELPER,
    }:
        raise ValueError("scaffold implementation file set mismatch")
    verified: dict[str, str] = {}
    for relative_name, expected in sorted(files.items()):
        require_sha256(expected, name=f"scaffold {relative_name}")
        path = (scaffold_root / relative_name).resolve()
        if not path.is_relative_to(scaffold_root) or not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"scaffold implementation SHA256 mismatch: {relative_name}")
        verified[relative_name] = actual
    return verified


def validate_scaling_protocol(
    *,
    protocol_path: Path,
    source_sha256_policy: Callable[[str], None] = require_official_r5_protocol_sha256,
) -> ScalingConfig:
    resolved_protocol_path = protocol_path.expanduser().resolve()
    if not resolved_protocol_path.is_file():
        raise FileNotFoundError(resolved_protocol_path)
    protocol = load_strict_json(resolved_protocol_path)
    if protocol.get("schema_version") != PROTOCOL_SCHEMA_VERSION:
        raise ValueError("scaling protocol schema mismatch")
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("scaling protocol version mismatch")
    if protocol.get("status") != FROZEN_STATUS or protocol.get("simulation_only") is not True:
        raise ValueError("scaling protocol is not frozen and simulation-only")

    source = protocol.get("source_r5")
    if not isinstance(source, dict):
        raise TypeError("source r5 binding is missing")
    source_record = source.get("protocol")
    if not isinstance(source_record, dict):
        raise TypeError("source r5 protocol record is missing")
    source_protocol_path = _resolve_absolute(
        source_record.get("path"),
        name="source_r5.protocol.path",
    )
    source_protocol_sha256 = require_sha256(
        source_record.get("sha256"),
        name="source_r5.protocol.sha256",
    )
    source_sha256_policy(source_protocol_sha256)
    if (
        not source_protocol_path.is_file()
        or sha256_file(source_protocol_path) != source_protocol_sha256
    ):
        raise ValueError("source r5 protocol file or SHA256 mismatch")
    source_project_root = _resolve_absolute(
        source.get("project_root"),
        name="source_r5.project_root",
    )
    if not source_project_root.is_dir():
        raise FileNotFoundError(source_project_root)
    genesis = protocol.get("genesis")
    if not isinstance(genesis, dict) or not isinstance(genesis.get("source_tree"), dict):
        raise TypeError("Genesis source-tree binding is missing")
    genesis_record = genesis["source_tree"]
    genesis_source_root = _resolve_absolute(
        genesis_record.get("root"),
        name="genesis.source_tree.root",
    )
    if not genesis_source_root.is_dir():
        raise FileNotFoundError(genesis_source_root)

    source_payload = load_strict_json(source_protocol_path)
    validated_source = validate_source_r5(
        source_protocol=source_payload,
        source_protocol_path=source_protocol_path,
        source_project_root=source_project_root,
        genesis_source_root=genesis_source_root,
    )
    if source.get("implementation_files_sha256") != validated_source["implementation_files"]:
        raise ValueError("source r5 implementation binding mismatch")
    if source.get("runtime") != validated_source["runtime"]:
        raise ValueError("source r5 runtime binding mismatch")
    if source.get("runtime_canonical_sha256") != canonical_sha256(validated_source["runtime"]):
        raise ValueError("source r5 runtime canonical SHA256 mismatch")
    if source.get("checkpoint") != validated_source["checkpoint"]:
        raise ValueError("source r5 checkpoint binding mismatch")
    if {
        "root": str(genesis_source_root),
        **sha256_source_tree(genesis_source_root),
    } != genesis_record:
        raise ValueError("Genesis source-tree record mismatch")

    scaffold_root = Path(__file__).resolve().parents[1]
    scaffold_files = _validate_scaffold_files(protocol, scaffold_root=scaffold_root)
    scaling_script_sha256 = scaffold_files[SCALING_SCRIPT]
    if sha256_file(Path(__file__).resolve()) != scaling_script_sha256:
        raise ValueError("running scaling script differs from frozen leaf")

    fixed = protocol.get("fixed_workload")
    execution = protocol.get("execution_contract")
    if not isinstance(fixed, dict) or not isinstance(execution, dict):
        raise TypeError("fixed workload or execution contract is missing")
    exact_workload = {
        "env_counts": list(ENV_COUNTS),
        "warmup_runs_per_env_count": WARMUP_RUNS,
        "measured_runs_per_env_count": MEASURED_RUNS,
        "steps_per_run": STEPS,
        "dropout_start_step": DROPOUT_START_STEP,
        "context_fit_steps": CONTEXT_FIT_STEPS,
        "genesis_seed": GENESIS_SEED,
        "context_seed_base": CONTEXT_SEED_BASE,
        "context_seed_repetition_stride": CONTEXT_SEED_REPETITION_STRIDE,
    }
    for field, expected in exact_workload.items():
        if fixed.get(field) != expected:
            raise ValueError(f"fixed workload mismatch: {field}")
    expected_measured = {str(count): count * STEPS * MEASURED_RUNS for count in ENV_COUNTS}
    expected_all = {
        str(count): count * STEPS * (WARMUP_RUNS + MEASURED_RUNS) for count in ENV_COUNTS
    }
    if (
        fixed.get("measured_transitions_by_env_count") != expected_measured
        or fixed.get("all_transitions_by_env_count") != expected_all
        or fixed.get("total_measured_transitions") != sum(expected_measured.values())
        or fixed.get("total_including_warmup_transitions") != sum(expected_all.values())
    ):
        raise ValueError("fixed transition budget mismatch")
    required_execution = {
        "one_fresh_subprocess_per_env_count": True,
        "subprocess_order": list(ENV_COUNTS),
        "strictly_serial": True,
        "exactly_one_visible_radeon": True,
        "hip_visible_devices": "0",
        "rocr_visible_devices": "0",
        "cuda_visible_devices": "0",
        "automatic_retry": False,
        "rocm_smi_sample_interval_s": ROCM_SMI_SAMPLE_INTERVAL_S,
        "minimum_valid_rocm_smi_samples_per_run": 1,
    }
    for field, expected in required_execution.items():
        if execution.get(field) != expected:
            raise ValueError(f"execution contract mismatch: {field}")
    expected_lock = {
        "path": str(GLOBAL_GPU_LOCK_PATH),
        "mode": "fcntl.flock(LOCK_EX|LOCK_NB)",
        "held_for_entire_parent_run": True,
        "lock_owner_exact_process_evidence_required": True,
    }
    if execution.get("global_gpu_lock") != expected_lock:
        raise ValueError("global GPU lock contract mismatch")
    expected_preflight = {
        "before_worker_series": True,
        "before_each_worker": True,
        "require_zero_live_gpu_processes": True,
        "freeze_card_product_unique_id_and_total_vram": True,
        "minimum_free_vram_fraction": BASELINE_FREE_VRAM_FRACTION_MIN,
        "process_evidence_sources": ["rocm-smi --showpids --json", "KFD procfs"],
    }
    if execution.get("preflight") != expected_preflight:
        raise ValueError("GPU preflight contract mismatch")
    expected_512_gate = {
        "baseline_env_count": 256,
        "projected_bytes_formula": (
            "baseline_used_bytes + 2.25 * max(0, "
            "peak_used_bytes_at_256 - baseline_used_bytes), where "
            "peak_used_bytes_at_256 is the maximum of rocm-smi/global "
            "memory evidence and global_memory_before + max(0, "
            "torch_peak_reserved - torch_reserved_before)"
        ),
        "growth_multiplier": PROJECTED_512_GROWTH_MULTIPLIER,
        "maximum_projected_total_vram_fraction": PROJECTED_512_TOTAL_FRACTION_MAX,
        "require_current_free_bytes_at_least_projected_increment": True,
        "failure_action": "FAIL_INELIGIBLE_BEFORE_512_WORKER_BUILD",
    }
    if execution.get("env_512_headroom_gate") != expected_512_gate:
        raise ValueError("512-environment headroom contract mismatch")
    if fixed.get("fault_activation") != "disabled":
        raise ValueError("scaling workload must disable fault activation")
    if fixed.get("fault_or_repair_outcome_selection") != "forbidden":
        raise ValueError("scaling workload permits outcome selection")
    if fixed.get("mission_outcomes_used_to_change_workload") is not False:
        raise ValueError("mission outcomes may not change the fixed workload")
    reported = protocol.get("reported_metrics")
    if not isinstance(reported, dict):
        raise TypeError("reported metrics contract is missing")
    if reported.get("performance_acceptance_threshold") != {
        "maximum_cv_each_env_count": MAX_MEASURED_CV,
        "minimum_512_vs_32_speedup": MIN_512_VS_32_SPEEDUP,
    }:
        raise ValueError("performance acceptance contract mismatch")

    output = protocol.get("output_contract")
    if not isinstance(output, dict):
        raise TypeError("output contract is missing")
    output_root = _resolve_absolute(output.get("output_root"), name="output root")
    aggregate_path = _resolve_absolute(output.get("aggregate"), name="aggregate output")
    if aggregate_path != output_root / AGGREGATE_FILENAME:
        raise ValueError("aggregate output path mismatch")
    workers = output.get("workers")
    if not isinstance(workers, dict) or set(workers) != {str(count) for count in ENV_COUNTS}:
        raise ValueError("worker output slots mismatch")
    worker_paths = tuple(
        _resolve_absolute(workers[str(count)], name=f"worker output {count}")
        for count in ENV_COUNTS
    )
    expected_worker_paths = tuple(
        output_root / "workers" / f"envs-{count}.json" for count in ENV_COUNTS
    )
    if worker_paths != expected_worker_paths:
        raise ValueError("worker output path layout mismatch")
    if output.get("exclusive_create") is not True or output.get("automatic_retry") is not False:
        raise ValueError("output exclusivity contract mismatch")
    expected_environment = protocol.get("expected_execution_environment")
    if expected_environment != validated_source["execution_environment"]:
        raise ValueError("expected execution environment binding mismatch")

    return ScalingConfig(
        protocol_path=resolved_protocol_path,
        protocol_sha256=sha256_file(resolved_protocol_path),
        source_protocol_path=source_protocol_path,
        source_protocol_sha256=source_protocol_sha256,
        source_project_root=source_project_root,
        scaffold_project_root=scaffold_root,
        genesis_source_root=genesis_source_root,
        output_root=output_root,
        aggregate_path=aggregate_path,
        worker_paths=worker_paths,
        runtime=validated_source["runtime"],
        checkpoint=validated_source["checkpoint"],
        expected_environment=validated_source["execution_environment"],
        scaling_script_sha256=scaling_script_sha256,
    )


def _parse_number(value: Any, *, name: str, integer: bool = False) -> float | int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    if isinstance(value, int):
        number = float(value)
    elif isinstance(value, float):
        number = value
    elif isinstance(value, str):
        stripped = value.strip()
        if integer:
            match = re.fullmatch(r"([+]?[0-9]+)(?:\s*(?:B|bytes?))?", stripped, re.IGNORECASE)
        else:
            match = re.fullmatch(
                r"([-+]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))(?:\s*%)?",
                stripped,
            )
        if match is None:
            raise ValueError(f"{name} has trailing garbage or an invalid numeric value")
        number = float(match.group(1))
    else:
        raise TypeError(f"{name} must be numeric")
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if integer:
        if not number.is_integer():
            raise ValueError(f"{name} must be an integer number of bytes")
        return int(number)
    return float(number)


def _normalized_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _metric_kind(label: str) -> str | None:
    if label in {"gpu use", "gpu use percent"}:
        return "gpu_use_percent"
    if (
        ("vram" in label or "gpu memory" in label)
        and ("allocated" in label or "use" in label)
        and "byte" not in label
        and "memory b" not in label
    ):
        return "vram_use_percent"
    if "vram" in label and "used" in label and ("memory" in label or "byte" in label):
        return "vram_used_bytes"
    if (
        "vram" in label
        and "total" in label
        and "used" not in label
        and ("memory" in label or "byte" in label)
    ):
        return "vram_total_bytes"
    return None


def _strict_json_object(stdout: str, *, name: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"{name} contains non-finite JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"{name} contains duplicate JSON key: {key}")
            output[key] = value
        return output

    payload = json.loads(
        stdout,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(payload, dict):
        raise TypeError(f"{name} JSON root must be an object")
    return payload


def parse_rocm_smi_json(stdout: str) -> dict[str, Any]:
    payload = _strict_json_object(stdout, name="rocm-smi")
    cards = [
        (key, value)
        for key, value in payload.items()
        if isinstance(key, str) and key.lower().startswith("card") and isinstance(value, dict)
    ]
    if len(cards) != 1:
        raise ValueError("rocm-smi must expose exactly one card")
    card_name, card = cards[0]
    if card_name != "card0":
        raise ValueError("rocm-smi single visible Radeon must be card0")
    matches: dict[str, list[tuple[str, Any]]] = {
        "gpu_use_percent": [],
        "vram_use_percent": [],
        "vram_used_bytes": [],
        "vram_total_bytes": [],
    }
    for key, value in card.items():
        kind = _metric_kind(_normalized_label(str(key)))
        if kind is not None:
            matches[kind].append((str(key), value))
    for kind, entries in matches.items():
        if len(entries) != 1:
            raise ValueError(
                f"rocm-smi semantic metric {kind} must occur exactly once; "
                f"found aliases {[key for key, _value in entries]}"
            )
    gpu_use = _parse_number(
        matches["gpu_use_percent"][0][1],
        name="gpu use percent",
    )
    vram_percent = _parse_number(
        matches["vram_use_percent"][0][1],
        name="VRAM use percent",
    )
    vram_used = _parse_number(
        matches["vram_used_bytes"][0][1],
        name="VRAM used bytes",
        integer=True,
    )
    vram_total = _parse_number(
        matches["vram_total_bytes"][0][1],
        name="VRAM total bytes",
        integer=True,
    )
    if not (0.0 <= gpu_use <= 100.0 and 0.0 <= vram_percent <= 100.0):
        raise ValueError("rocm-smi utilization percent lies outside [0, 100]")
    if vram_used < 0 or vram_total <= 0 or vram_used > vram_total:
        raise ValueError("rocm-smi VRAM byte values are invalid")
    return {
        "card": card_name,
        "gpu_use_percent": gpu_use,
        "vram_use_percent": vram_percent,
        "vram_used_bytes": vram_used,
        "vram_total_bytes": vram_total,
    }


def validate_gpu_sample(
    sample: Any,
    *,
    previous_offset_s: float | None = None,
    expected_total_bytes: int | None = None,
) -> float:
    if not isinstance(sample, dict) or set(sample) != {
        "card",
        "gpu_use_percent",
        "vram_use_percent",
        "vram_used_bytes",
        "vram_total_bytes",
        "monotonic_offset_s",
    }:
        raise ValueError("GPU sample field set mismatch")
    if sample["card"] != "card0":
        raise ValueError("GPU sample card must be card0")
    for name in ("gpu_use_percent", "vram_use_percent"):
        value = sample[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"GPU sample {name} must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 100.0:
            raise ValueError(f"GPU sample {name} lies outside [0, 100]")
    used = sample["vram_used_bytes"]
    total = sample["vram_total_bytes"]
    if type(used) is not int or type(total) is not int:
        raise TypeError("GPU sample VRAM bytes must be integers")
    if used < 0 or total <= 0 or used > total:
        raise ValueError("GPU sample VRAM bytes are invalid")
    if expected_total_bytes is not None and total != expected_total_bytes:
        raise ValueError("GPU sample total VRAM changed from frozen identity")
    offset = sample["monotonic_offset_s"]
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        raise TypeError("GPU sample monotonic offset must be numeric")
    offset_s = float(offset)
    if not math.isfinite(offset_s) or offset_s < 0.0:
        raise ValueError("GPU sample monotonic offset must be finite and nonnegative")
    if previous_offset_s is not None and offset_s < previous_offset_s:
        raise ValueError("GPU sample monotonic offsets decreased")
    return offset_s


def gpu_sample_summary(
    samples: list[dict[str, Any]],
    *,
    validate_offsets: bool = True,
    expected_total_bytes: int | None = None,
) -> dict[str, Any]:
    if not samples:
        raise ValueError("at least one GPU sample is required")
    previous_offset: float | None = None
    for sample in samples:
        previous_offset = validate_gpu_sample(
            sample,
            previous_offset_s=previous_offset if validate_offsets else None,
            expected_total_bytes=expected_total_bytes,
        )
    gpu_use = [float(sample["gpu_use_percent"]) for sample in samples]
    vram_use = [float(sample["vram_use_percent"]) for sample in samples]
    vram_used = [int(sample["vram_used_bytes"]) for sample in samples]
    for values, name in ((gpu_use, "GPU use"), (vram_use, "VRAM use")):
        if not all(math.isfinite(value) and 0.0 <= value <= 100.0 for value in values):
            raise ValueError(f"{name} samples are invalid")
    return {
        "sample_count": len(samples),
        "gpu_use_percent_min": min(gpu_use),
        "gpu_use_percent_mean": statistics.fmean(gpu_use),
        "gpu_use_percent_max": max(gpu_use),
        "vram_use_percent_min": min(vram_use),
        "vram_use_percent_mean": statistics.fmean(vram_use),
        "vram_use_percent_max": max(vram_use),
        "vram_used_bytes_max": max(vram_used),
    }


class RocmSmiSampler:
    """Collect parsed single-card rocm-smi samples on a background thread."""

    def __init__(self, executable: Path, *, interval_s: float) -> None:
        if not math.isfinite(interval_s) or interval_s <= 0.0:
            raise ValueError("sampling interval must be finite and positive")
        self.executable = executable.resolve()
        self.interval_s = interval_s
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_ns: int | None = None

    def _sample_once(self) -> None:
        try:
            run = subprocess.run(
                [
                    str(self.executable),
                    "--showuse",
                    "--showmemuse",
                    "--showmeminfo",
                    "vram",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=max(5.0, self.interval_s * 10.0),
            )
            if run.returncode:
                raise RuntimeError(f"rocm-smi rc={run.returncode}: {run.stderr.strip()}")
            sample = parse_rocm_smi_json(run.stdout)
            if self._started_ns is None:
                raise RuntimeError("sampler start time is unavailable")
            sample["monotonic_offset_s"] = (
                time.monotonic_ns() - self._started_ns
            ) / 1_000_000_000.0
            self.samples.append(sample)
        except (
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            TypeError,
            ValueError,
        ) as error:
            self.errors.append(f"{type(error).__name__}: {error}")

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._sample_once()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("rocm-smi sampler may only be started once")
        self._started_ns = time.monotonic_ns()
        self._sample_once()
        self._thread = threading.Thread(
            target=self._loop,
            name="flightguard-rocm-smi-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        if self._thread is None:
            raise RuntimeError("rocm-smi sampler was not started")
        self._stop.set()
        self._thread.join(timeout=max(5.0, self.interval_s * 10.0))
        if self._thread.is_alive():
            self.errors.append("RuntimeError: rocm-smi sampler thread did not stop")
        self._sample_once()
        summary = gpu_sample_summary(self.samples) if self.samples else None
        return {
            "sample_interval_s": self.interval_s,
            "sample_count": len(self.samples),
            "samples": self.samples,
            "samples_canonical_sha256": canonical_sha256(self.samples),
            "errors": self.errors,
            "summary": summary,
        }


class GlobalGpuLockBusyError(RuntimeError):
    """Raised when the exact shared Radeon lock is already held."""


@contextmanager
def hold_global_gpu_lock(path: Path) -> Iterator[dict[str, Any]]:
    """Hold one nonblocking flock and expose exact owner evidence."""

    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(resolved, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GlobalGpuLockBusyError(f"global Radeon lock is busy: {resolved}") from error
        cmdline_path = Path("/proc") / str(os.getpid()) / "cmdline"
        cmdline = (
            cmdline_path.read_bytes().replace(b"\0", b" ").strip().decode("utf-8", "replace")
            if cmdline_path.is_file()
            else " ".join(sys.argv)
        )
        proc_stat = Path("/proc") / str(os.getpid()) / "stat"
        start_time_ticks: int | None = None
        if proc_stat.is_file():
            fields = proc_stat.read_text(encoding="utf-8").split()
            if len(fields) >= 22:
                start_time_ticks = int(fields[21])
        evidence = {
            "path": str(resolved),
            "pid": os.getpid(),
            "process_start_time_ticks": start_time_ticks,
            "cmdline": cmdline,
            "acquired_monotonic_ns": time.monotonic_ns(),
        }
        serialized = (
            json.dumps(evidence, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.write(descriptor, serialized)
        os.fsync(descriptor)
        yield evidence
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _identity_metric(card: dict[str, Any], aliases: set[str], *, name: str) -> str:
    matches = [value for key, value in card.items() if _normalized_label(str(key)) in aliases]
    if len(matches) != 1:
        raise ValueError(f"rocm-smi {name} must occur exactly once")
    value = matches[0]
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TypeError(f"rocm-smi {name} has an invalid type")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"rocm-smi {name} is empty")
    return normalized


def _preferred_identity_metric(
    card: dict[str, Any],
    aliases: tuple[str, ...],
    *,
    name: str,
) -> str:
    for alias in aliases:
        matches = [
            value
            for key, value in card.items()
            if _normalized_label(str(key)) == alias
        ]
        if len(matches) > 1:
            raise ValueError(f"rocm-smi {name} alias {alias!r} must occur at most once")
        if matches:
            return _identity_metric(card, {alias}, name=name)
    raise ValueError(f"rocm-smi {name} is missing")


def capture_gpu_preflight() -> dict[str, Any]:
    """Capture idle/process/identity evidence without constructing a Genesis scene."""

    from tools.serial_gpu_queue import gpu_snapshot

    rocm_smi_name = shutil.which("rocm-smi")
    if rocm_smi_name is None:
        raise FileNotFoundError("rocm-smi")
    rocm_smi = Path(rocm_smi_name).resolve()
    command = [
        str(rocm_smi),
        "--showuse",
        "--showmemuse",
        "--showmeminfo",
        "vram",
        "--showproductname",
        "--showuniqueid",
        "--json",
    ]
    run = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=15.0,
    )
    if run.returncode:
        raise RuntimeError(f"rocm-smi preflight rc={run.returncode}: {run.stderr.strip()}")
    payload = _strict_json_object(run.stdout, name="rocm-smi preflight")
    card = payload.get("card0")
    if not isinstance(card, dict):
        raise TypeError("rocm-smi preflight must expose exact card0 object")
    sample = parse_rocm_smi_json(run.stdout)
    sample["monotonic_offset_s"] = 0.0
    product_name = _preferred_identity_metric(
        card,
        ("product name", "card series", "card model"),
        name="product name",
    )
    unique_id = _identity_metric(card, {"unique id"}, name="unique ID")
    snapshot = gpu_snapshot()
    total_bytes = sample["vram_total_bytes"]
    used_bytes = sample["vram_used_bytes"]
    free_bytes = total_bytes - used_bytes
    process_evidence = {
        "kfd_proc_status": snapshot["kfd_proc_status"],
        "live_gpu_processes": snapshot["live_gpu_processes"],
        "stale_gpu_processes": snapshot["stale_gpu_processes"],
        "snapshot_gpu_use_percent": snapshot["gpu_use_percent"],
        "snapshot_vram_use_percent": snapshot["vram_use_percent"],
        "snapshot_vram_used_bytes": snapshot["vram_used_bytes"],
    }
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "gpu_identity": {
            "card": "card0",
            "product_name": product_name,
            "unique_id": unique_id,
            "total_vram_bytes": total_bytes,
        },
        "baseline": {
            "sample": sample,
            "used_vram_bytes": used_bytes,
            "free_vram_bytes": free_bytes,
            "free_vram_fraction": free_bytes / total_bytes,
        },
        "process_evidence": process_evidence,
        "process_evidence_canonical_sha256": canonical_sha256(process_evidence),
        "rocm_smi": {
            "path": str(rocm_smi),
            "sha256": sha256_file(rocm_smi),
            "command": command,
            "stdout_sha256": canonical_sha256(payload),
            "stderr": run.stderr.strip(),
        },
    }


def validate_gpu_preflight(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or record.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise ValueError("GPU preflight schema mismatch")
    identity = record.get("gpu_identity")
    baseline = record.get("baseline")
    processes = record.get("process_evidence")
    if not all(isinstance(value, dict) for value in (identity, baseline, processes)):
        raise TypeError("GPU preflight sections are missing")
    if identity.get("card") != "card0":
        raise ValueError("GPU preflight card must be card0")
    for field in ("product_name", "unique_id"):
        if not isinstance(identity.get(field), str) or not identity[field]:
            raise ValueError(f"GPU preflight identity {field} is missing")
    total = identity.get("total_vram_bytes")
    used = baseline.get("used_vram_bytes")
    free = baseline.get("free_vram_bytes")
    if type(total) is not int or total <= 0:
        raise ValueError("GPU preflight total VRAM is invalid")
    if type(used) is not int or type(free) is not int or used < 0 or free < 0:
        raise ValueError("GPU preflight VRAM headroom is invalid")
    if used + free != total:
        raise ValueError("GPU preflight VRAM headroom arithmetic mismatch")
    fraction = baseline.get("free_vram_fraction")
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not math.isfinite(float(fraction))
        or not math.isclose(float(fraction), free / total, rel_tol=0.0, abs_tol=1.0e-15)
    ):
        raise ValueError("GPU preflight free VRAM fraction mismatch")
    if float(fraction) < BASELINE_FREE_VRAM_FRACTION_MIN:
        raise ValueError("GPU preflight has less than 90% free VRAM")
    sample = baseline.get("sample")
    validate_gpu_sample(sample, expected_total_bytes=total)
    if sample["vram_used_bytes"] != used:
        raise ValueError("GPU preflight sample/headroom mismatch")
    if processes.get("live_gpu_processes") != []:
        raise ValueError("GPU preflight found conflicting live compute processes")
    if processes.get("kfd_proc_status") not in {"absent", "enumerated"}:
        raise ValueError("GPU preflight KFD process evidence status is invalid")
    for field in ("snapshot_gpu_use_percent", "snapshot_vram_use_percent"):
        value = processes.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 100.0
        ):
            raise ValueError(f"GPU preflight process snapshot {field} is invalid")
    snapshot_used = processes.get("snapshot_vram_used_bytes")
    if type(snapshot_used) is not int or not 0 <= snapshot_used <= total:
        raise ValueError("GPU preflight process snapshot VRAM bytes are invalid")
    stale = processes.get("stale_gpu_processes")
    if not isinstance(stale, list):
        raise TypeError("GPU preflight stale process evidence is missing")
    for item in stale:
        if (
            not isinstance(item, dict)
            or type(item.get("pid")) is not int
            or item["pid"] <= 0
            or not isinstance(item.get("sources"), list)
        ):
            raise ValueError("GPU preflight stale process record is invalid")
    if record.get("process_evidence_canonical_sha256") != canonical_sha256(processes):
        raise ValueError("GPU preflight process evidence SHA256 mismatch")
    rocm_smi = record.get("rocm_smi")
    if not isinstance(rocm_smi, dict):
        raise TypeError("GPU preflight rocm-smi binding is missing")
    require_sha256(rocm_smi.get("sha256"), name="preflight rocm-smi")
    require_sha256(rocm_smi.get("stdout_sha256"), name="preflight rocm-smi stdout")
    return record


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) != MEASURED_RUNS:
        raise ValueError("CV requires exactly three measured runs")
    if not all(math.isfinite(value) and value > 0.0 for value in values):
        raise ValueError("throughput values must be finite and positive")
    return statistics.stdev(values) / statistics.fmean(values)


def _load_r5_module(config: ScalingConfig) -> Any:
    source_paths = [
        str(config.genesis_source_root),
        str(config.source_project_root / "src"),
        str(config.source_project_root),
    ]
    for source_path in reversed(source_paths):
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
    evaluator_path = (config.source_project_root / R5_EVALUATOR).resolve()
    name = "_flightguard_frozen_r5_scaling_evaluator"
    spec = importlib.util.spec_from_file_location(name, evaluator_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load frozen r5 evaluator: {evaluator_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != evaluator_path:
        raise RuntimeError("loaded r5 evaluator path mismatch")
    return module


def _make_context(*, env_count: int, device: torch.device, runtime: dict[str, Any]) -> Any:
    from flightguard.online_context import FrozenAffineDelayConfig, FrozenAffineDelayContext

    return FrozenAffineDelayContext(
        env_count,
        device=device,
        dtype=torch.float32,
        config=FrozenAffineDelayConfig(
            max_delay_steps=int(runtime["context_max_delay_steps"]),
            ridge=float(runtime["context_ridge"]),
            gamma_min=-float(runtime["context_gamma_limit"]),
            gamma_max=float(runtime["context_gamma_limit"]),
            bias_abs_max_mps2=float(runtime["context_bias_limit_mps2"]),
            min_fit_samples=int(runtime["context_min_fit_samples"]),
            min_score_samples=int(runtime["context_min_score_samples"]),
            min_excitation=float(runtime["context_min_excitation"]),
            delay_score_tolerance=float(runtime["context_delay_score_tolerance"]),
            min_score_improvement_absolute=float(runtime["context_min_score_improvement_absolute"]),
            min_score_improvement_relative=float(runtime["context_min_score_improvement_relative"]),
            score_residual_quantile=float(runtime["context_score_residual_quantile"]),
            max_score_samples=(
                int(runtime["dropout_start_step"]) - int(runtime["context_fit_steps"])
            ),
        ),
    )


def _make_controller(runtime: dict[str, Any]) -> Any:
    from flightguard.controller import BatchedWaypointController, controller_config_for_profile

    config = controller_config_for_profile(runtime["controller_profile"])
    config = replace(
        config,
        max_upward_vertical_acceleration=float(runtime["max_upward_vertical_acceleration_mps2"]),
        max_downward_vertical_acceleration=float(
            runtime["max_downward_vertical_acceleration_mps2"]
        ),
    )
    return BatchedWaypointController(config)


def _memory_info() -> dict[str, int]:
    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    return {
        "free_bytes": int(free_bytes),
        "total_bytes": int(total_bytes),
        "used_bytes": int(total_bytes - free_bytes),
    }


def _run_repetition(
    *,
    env: Any,
    model: torch.nn.Module,
    context: Any,
    controller: Any,
    runtime: dict[str, Any],
    r5: Any,
    rocm_smi: Path,
    kind: str,
    repetition_index: int,
) -> dict[str, Any]:
    from flightguard.gate_math import gate_crossing, gate_lookthrough_target
    from flightguard.imu import perturb_imu

    if kind not in {"warmup", "measured"}:
        raise ValueError("repetition kind is invalid")
    env_count = env.num_envs
    device = env.device
    all_envs = torch.arange(env_count, device=device)
    with torch.inference_mode():
        env.reset(all_envs)
        context.reset()
    steps = int(runtime["steps"])
    dropout_start = int(runtime["dropout_start_step"])
    fit_steps = int(runtime["context_fit_steps"])
    context_seeds = [
        CONTEXT_SEED_BASE + CONTEXT_SEED_REPETITION_STRIDE * repetition_index + env_index
        for env_index in range(env_count)
    ]
    attitude_noise, angular_velocity_noise = r5.context_noise(
        context_seeds,
        steps=steps,
        attitude_std_rad=math.radians(float(runtime["attitude_noise_std_deg"])),
        angular_velocity_std_rad_s=float(runtime["angular_velocity_noise_std_rad_s"]),
    )
    attitude_bias = torch.tensor(
        runtime["attitude_bias_deg"],
        device=device,
        dtype=torch.float32,
    ) * (math.pi / 180.0)
    angular_velocity_bias = torch.tensor(
        runtime["angular_velocity_bias_rad_s"],
        device=device,
        dtype=torch.float32,
    )

    estimated_position = env.drone.get_pos().clone()
    estimated_velocity = env.drone.get_vel().clone()
    control_gate_index = torch.zeros(env_count, dtype=torch.long, device=device)
    finite = torch.ones((), dtype=torch.bool, device=device)
    reset_count = 0
    call_counts = {
        "perturb_imu": 0,
        "controller": 0,
        "context_push_issued": 0,
        "context_observe_transition": 0,
        "context_predict_acceleration": 0,
        "environment_step": 0,
    }
    torch.cuda.reset_peak_memory_stats(0)
    memory_before = _memory_info()
    torch_reserved_before_bytes = int(torch.cuda.memory_reserved(0))
    torch.cuda.synchronize()
    sampler = RocmSmiSampler(
        rocm_smi,
        interval_s=ROCM_SMI_SAMPLE_INTERVAL_S,
    )
    sampler.start()
    started = time.perf_counter()
    with torch.inference_mode():
        for step in range(steps):
            if step == fit_steps:
                context.begin_scoring()
            if step == dropout_start:
                context.freeze()

            position = env.drone.get_pos()
            quaternion = env.drone.get_quat()
            velocity = env.drone.get_vel()
            angular_velocity = env.drone.get_ang()
            if step < dropout_start:
                estimated_position = position
                estimated_velocity = velocity

            measured_quaternion, measured_angular_velocity = perturb_imu(
                quaternion,
                angular_velocity,
                attitude_noise[step].to(device=device) + attitude_bias,
                angular_velocity_noise[step].to(device=device) + angular_velocity_bias,
            )
            call_counts["perturb_imu"] += 1
            gate_center, target_yaw = r5.indexed_gate(
                env.gates,
                env.gate_yaws,
                control_gate_index,
            )
            controller_target = gate_lookthrough_target(
                gate_center,
                target_yaw,
                float(runtime["gate_lookthrough_m"]),
            )
            action = controller(
                estimated_position,
                measured_quaternion,
                estimated_velocity,
                measured_angular_velocity,
                controller_target,
            )
            call_counts["controller"] += 1
            context.push_issued(action)
            call_counts["context_push_issued"] += 1

            if step >= dropout_start:
                learned_acceleration = context.predict_acceleration(
                    model,
                    estimated_velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                )
                call_counts["context_predict_acceleration"] += 1
                proposed_position = (
                    estimated_position
                    + estimated_velocity * env.dt
                    + 0.5 * learned_acceleration * env.dt * env.dt
                )
                proposed_velocity = estimated_velocity + learned_acceleration * env.dt
            else:
                proposed_position = position
                proposed_velocity = velocity

            result = env.step(action)
            call_counts["environment_step"] += 1
            next_position = env.drone.get_pos()
            next_velocity = env.drone.get_vel()
            if step < dropout_start:
                context.observe_transition(
                    model,
                    velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                    next_velocity,
                    dt=env.dt,
                    phase=("fit" if step < fit_steps else "score"),
                    mask=torch.ones(env_count, dtype=torch.bool, device=device),
                )
                call_counts["context_observe_transition"] += 1
                proposed_position = next_position
                proposed_velocity = next_velocity

            crossing = gate_crossing(
                estimated_position,
                proposed_position,
                gate_center,
                target_yaw,
                half_width=0.6,
                half_height=0.5,
                proxy_radius=0.08,
            )
            control_gate_index += crossing.passed.long()
            estimated_position = proposed_position
            estimated_velocity = proposed_velocity
            finite &= torch.stack(
                [
                    torch.isfinite(values).all()
                    for values in (
                        next_position,
                        next_velocity,
                        measured_quaternion,
                        measured_angular_velocity,
                        estimated_position,
                        estimated_velocity,
                        action,
                        env.last_applied_action,
                    )
                ]
            ).all()

            done_idx = torch.nonzero(result.done, as_tuple=False).reshape(-1)
            if done_idx.numel():
                reset_count += int(done_idx.numel())
                env.reset(done_idx)
                control_gate_index[done_idx] = 0
                estimated_position[done_idx] = env.drone.get_pos()[done_idx]
                estimated_velocity[done_idx] = env.drone.get_vel()[done_idx]
                if step < dropout_start:
                    context.reset(done_idx)

    torch.cuda.synchronize()
    elapsed_s = time.perf_counter() - started
    gpu_monitor = sampler.stop()
    memory_after = _memory_info()
    transitions = env_count * steps
    expected_calls = {
        "perturb_imu": steps,
        "controller": steps,
        "context_push_issued": steps,
        "context_observe_transition": dropout_start,
        "context_predict_acceleration": steps - dropout_start,
        "environment_step": steps,
    }
    return {
        "kind": kind,
        "repetition_index": repetition_index,
        "steps": steps,
        "transitions": transitions,
        "elapsed_s": elapsed_s,
        "transitions_per_s": transitions / elapsed_s,
        "context_seed_first": context_seeds[0],
        "context_seed_last": context_seeds[-1],
        "all_tracked_tensors_finite": bool(finite.item()),
        "terminal_reset_count": reset_count,
        "call_counts": call_counts,
        "expected_call_counts": expected_calls,
        "context_frozen": bool(context.frozen.item()),
        "context_selected_valid_count": int(context.selected_valid.sum().item()),
        "context_post_freeze_update_attempts": int(context.post_freeze_update_attempts.item()),
        "torch_memory_before": memory_before,
        "torch_memory_after": memory_after,
        "torch_reserved_before_bytes": torch_reserved_before_bytes,
        "torch_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(0)),
        "torch_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(0)),
        "gpu_monitor": gpu_monitor,
    }


def _device_identity(
    *,
    gs: Any,
    rocm_smi: Path,
    config: ScalingConfig,
) -> dict[str, Any]:
    import numpy as np

    version = subprocess.run(
        [str(rocm_smi), "--version"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10.0,
    )
    if version.returncode:
        raise RuntimeError(f"rocm-smi --version failed: {version.stderr.strip()}")
    properties = torch.cuda.get_device_properties(0)
    return {
        "backend": str(gs.backend),
        "device": str(gs.device),
        "visible_gpu_count": torch.cuda.device_count(),
        "gpu": {
            "name": torch.cuda.get_device_name(0),
            "total_memory_bytes": int(properties.total_memory),
            "multi_processor_count": int(properties.multi_processor_count),
            "major": int(properties.major),
            "minor": int(properties.minor),
        },
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "torch_version": torch.__version__,
        "torch_hip": torch.version.hip,
        "genesis_version": str(gs.__version__),
        "genesis_module": str(Path(gs.__file__).resolve()),
        "genesis_source_tree": {
            "root": str(config.genesis_source_root),
            **sha256_source_tree(config.genesis_source_root),
        },
        "rocm_smi": {
            "path": str(rocm_smi),
            "sha256": sha256_file(rocm_smi),
            "version_stdout": version.stdout.strip(),
            "version_stderr": version.stderr.strip(),
        },
    }


def run_worker(
    *,
    protocol_path: Path,
    env_count: int,
    env_index: int,
    worker_output: Path,
) -> dict[str, Any]:
    config = validate_scaling_protocol(protocol_path=protocol_path)
    if env_index < 0 or env_index >= len(ENV_COUNTS) or ENV_COUNTS[env_index] != env_count:
        raise ValueError("worker environment index/count binding mismatch")
    if worker_output.expanduser().resolve() != config.worker_paths[env_index]:
        raise ValueError("worker output differs from its exclusive frozen slot")

    r5 = _load_r5_module(config)
    import genesis as gs

    genesis_module_root = Path(gs.__file__).resolve().parents[1]
    if genesis_module_root != config.genesis_source_root:
        raise RuntimeError("imported Genesis tree differs from frozen source root")
    gs.init(
        backend=gs.amdgpu,
        precision="32",
        seed=GENESIS_SEED,
        performance_mode=False,
        logging_level="warning",
    )
    visible_gpu_count = torch.cuda.device_count()
    if (
        gs.backend != gs.amdgpu
        or not torch.cuda.is_available()
        or visible_gpu_count != 1
        or not torch.version.hip
    ):
        raise RuntimeError("exactly one Radeon/ROCm GPU is required")
    rocm_smi_name = shutil.which("rocm-smi")
    if rocm_smi_name is None:
        raise FileNotFoundError("rocm-smi")
    rocm_smi = Path(rocm_smi_name).resolve()

    from flightguard.domain_randomization import DomainParameters
    from flightguard.genesis_env import FlightGuardGenesisEnv

    runtime = config.runtime
    domain_parameters = DomainParameters(
        mass_scale=torch.ones(env_count),
        thrust_scale=torch.ones(env_count),
        wind_acceleration_mps2=torch.zeros((env_count, 3)),
        action_delay_steps=torch.zeros(env_count, dtype=torch.long),
        stratum=torch.full((env_count,), -1, dtype=torch.long),
        profile="off",
        seed=GENESIS_SEED,
    )
    env = FlightGuardGenesisEnv(
        env_count,
        domain_parameters=domain_parameters,
        delay_history_max_steps=int(runtime["delay_history_max_steps"]),
    )
    if env.dt != float(runtime["dt_s"]):
        raise ValueError("Genesis environment dt differs from frozen r5")
    if env.has_scheduled_faults:
        raise RuntimeError("fixed scaling workload unexpectedly has scheduled faults")
    model = r5.load_model(Path(config.checkpoint["path"]), gs.device)
    context = _make_context(env_count=env_count, device=gs.device, runtime=runtime)
    controller = _make_controller(runtime)
    gate_seeds = [CONTEXT_SEED_BASE + env_id for env_id in range(env_count)]
    env.gates += r5.context_gate_offsets(
        gate_seeds,
        y_jitter_m=float(runtime["gate_y_jitter_m"]),
        z_jitter_m=float(runtime["gate_z_jitter_m"]),
    ).to(device=gs.device)[:, None, :]

    repetitions = []
    total_runs = WARMUP_RUNS + MEASURED_RUNS
    for repetition_index in range(total_runs):
        repetitions.append(
            _run_repetition(
                env=env,
                model=model,
                context=context,
                controller=controller,
                runtime=runtime,
                r5=r5,
                rocm_smi=rocm_smi,
                kind=("warmup" if repetition_index < WARMUP_RUNS else "measured"),
                repetition_index=repetition_index,
            )
        )
    identity = _device_identity(gs=gs, rocm_smi=rocm_smi, config=config)
    expected = config.expected_environment
    checks = {
        "backend_is_amdgpu": gs.backend == gs.amdgpu,
        "visible_gpu_count_is_one": visible_gpu_count == 1,
        "torch_hip_nonempty": bool(torch.version.hip),
        "python_version_matches_r5": identity["python_version"] == expected["python_version"],
        "numpy_version_matches_r5": identity["numpy_version"] == expected["numpy_version"],
        "torch_version_matches_r5": identity["torch_version"] == expected["torch_version"],
        "torch_hip_matches_r5": identity["torch_hip"] == expected["torch_hip"],
        "genesis_version_matches_r5": (identity["genesis_version"] == expected["genesis_version"]),
        "genesis_source_tree_matches_r5": (
            identity["genesis_source_tree"]["sha256"]
            == load_strict_json(config.protocol_path)["genesis"]["source_tree"]["sha256"]
        ),
        "nominal_domain_has_no_scheduled_faults": not env.has_scheduled_faults,
        "one_warmup_three_measured": (
            [record["kind"] for record in repetitions]
            == ["warmup", "measured", "measured", "measured"]
        ),
        "all_repetitions_exact_800_steps": all(record["steps"] == STEPS for record in repetitions),
        "all_repetitions_exact_fixed_calls": all(
            record["call_counts"] == record["expected_call_counts"] for record in repetitions
        ),
        "all_repetitions_finite": all(
            record["all_tracked_tensors_finite"] for record in repetitions
        ),
        "all_repetitions_froze_context": all(record["context_frozen"] for record in repetitions),
        "post_freeze_context_updates_zero": all(
            record["context_post_freeze_update_attempts"] == 0 for record in repetitions
        ),
        "all_repetitions_have_rocm_smi_samples": all(
            record["gpu_monitor"]["sample_count"] >= 1 for record in repetitions
        ),
        "all_rocm_smi_samples_parse_without_error": all(
            not record["gpu_monitor"]["errors"] for record in repetitions
        ),
        "fault_or_repair_result_selection_absent": True,
        "mission_outcomes_do_not_change_fixed_steps": True,
    }
    return {
        "schema_version": WORKER_SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "simulation_only": True,
        "binding": {
            "protocol": {
                "path": str(config.protocol_path),
                "sha256": config.protocol_sha256,
            },
            "source_r5_protocol_sha256": config.source_protocol_sha256,
            "source_r5_evaluator_sha256": load_strict_json(config.protocol_path)["source_r5"][
                "implementation_files_sha256"
            ][R5_EVALUATOR],
            "source_r5_runtime_canonical_sha256": canonical_sha256(config.runtime),
            "checkpoint": config.checkpoint,
            "genesis_source_tree_sha256": load_strict_json(config.protocol_path)["genesis"][
                "source_tree"
            ]["sha256"],
            "scaling_script_sha256": config.scaling_script_sha256,
            "worker_output": str(worker_output.expanduser().resolve()),
        },
        "workload": {
            "env_count": env_count,
            "env_index": env_index,
            "steps_per_run": STEPS,
            "warmup_runs": WARMUP_RUNS,
            "measured_runs": MEASURED_RUNS,
            "genesis_seed": GENESIS_SEED,
            "fault_activation": "disabled",
            "result_selection": "forbidden",
        },
        "identity": identity,
        "runtime_race_asset": {
            "path": str(env.drone_urdf),
            "sha256": sha256_file(env.drone_urdf),
        },
        "controller": asdict(controller.config),
        "checks": checks,
        "repetitions": repetitions,
    }


def _validate_gpu_monitor(monitor: Any, *, expected_total_bytes: int) -> None:
    if not isinstance(monitor, dict):
        raise TypeError("worker GPU monitor is missing")
    samples = monitor.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("worker GPU samples are missing")
    if monitor.get("sample_count") != len(samples):
        raise ValueError("worker GPU sample count mismatch")
    if monitor.get("samples_canonical_sha256") != canonical_sha256(samples):
        raise ValueError("worker GPU sample SHA256 mismatch")
    if monitor.get("errors") != []:
        raise ValueError("worker GPU monitor reported errors")
    recomputed_summary = gpu_sample_summary(
        samples,
        validate_offsets=True,
        expected_total_bytes=expected_total_bytes,
    )
    if monitor.get("summary") != recomputed_summary:
        raise ValueError("worker GPU sample summary mismatch")


def validate_worker_record(
    record: dict[str, Any],
    *,
    config: ScalingConfig,
    env_index: int,
) -> None:
    env_count = ENV_COUNTS[env_index]
    if (
        record.get("schema_version") != WORKER_SCHEMA_VERSION
        or record.get("status") != "PASS"
        or record.get("simulation_only") is not True
    ):
        raise ValueError("worker status/schema mismatch")
    binding = record.get("binding")
    workload = record.get("workload")
    identity = record.get("identity")
    checks = record.get("checks")
    repetitions = record.get("repetitions")
    if not all(
        isinstance(value, dict) for value in (binding, workload, identity, checks)
    ) or not isinstance(repetitions, list):
        raise TypeError("worker record sections are missing")
    protocol_binding = binding.get("protocol")
    if protocol_binding != {
        "path": str(config.protocol_path),
        "sha256": config.protocol_sha256,
    }:
        raise ValueError("worker protocol binding mismatch")
    protocol = load_strict_json(config.protocol_path)
    expected_binding = {
        "source_r5_protocol_sha256": config.source_protocol_sha256,
        "source_r5_evaluator_sha256": protocol["source_r5"]["implementation_files_sha256"][
            R5_EVALUATOR
        ],
        "source_r5_runtime_canonical_sha256": canonical_sha256(config.runtime),
        "checkpoint": config.checkpoint,
        "genesis_source_tree_sha256": protocol["genesis"]["source_tree"]["sha256"],
        "scaling_script_sha256": config.scaling_script_sha256,
        "worker_output": str(config.worker_paths[env_index]),
    }
    for field, expected in expected_binding.items():
        if binding.get(field) != expected:
            raise ValueError(f"worker binding mismatch: {field}")
    if workload != {
        "env_count": env_count,
        "env_index": env_index,
        "steps_per_run": STEPS,
        "warmup_runs": WARMUP_RUNS,
        "measured_runs": MEASURED_RUNS,
        "genesis_seed": GENESIS_SEED,
        "fault_activation": "disabled",
        "result_selection": "forbidden",
    }:
        raise ValueError("worker workload mismatch")
    if identity.get("visible_gpu_count") != 1 or not identity.get("torch_hip"):
        raise ValueError("worker did not use exactly one ROCm GPU")
    gpu_identity = identity.get("gpu")
    if not isinstance(gpu_identity, dict):
        raise TypeError("worker GPU identity is missing")
    total_vram_bytes = gpu_identity.get("total_memory_bytes")
    if type(total_vram_bytes) is not int or total_vram_bytes <= 0:
        raise ValueError("worker GPU total VRAM identity is invalid")
    if set(checks) != WORKER_CHECK_NAMES or any(value is not True for value in checks.values()):
        raise ValueError("worker integrity check failed")
    expected_identity = config.expected_environment
    for identity_field, expected_field in (
        ("python_version", "python_version"),
        ("numpy_version", "numpy_version"),
        ("torch_version", "torch_version"),
        ("torch_hip", "torch_hip"),
        ("genesis_version", "genesis_version"),
    ):
        if identity.get(identity_field) != expected_identity[expected_field]:
            raise ValueError(f"worker identity mismatch: {identity_field}")
    expected_genesis_sha256 = load_strict_json(config.protocol_path)["genesis"]["source_tree"][
        "sha256"
    ]
    if (
        not isinstance(identity.get("genesis_source_tree"), dict)
        or identity["genesis_source_tree"].get("sha256") != expected_genesis_sha256
    ):
        raise ValueError("worker Genesis source-tree identity mismatch")
    race_asset = record.get("runtime_race_asset")
    if not isinstance(race_asset, dict) or set(race_asset) != {"path", "sha256"}:
        raise ValueError("worker runtime race asset binding is missing")
    race_asset_path = _resolve_absolute(
        race_asset["path"],
        name="worker runtime race asset",
    )
    if not race_asset_path.is_file() or sha256_file(race_asset_path) != race_asset["sha256"]:
        raise ValueError("worker runtime race asset file or SHA256 mismatch")
    if len(repetitions) != WARMUP_RUNS + MEASURED_RUNS:
        raise ValueError("worker repetition count mismatch")
    expected_kinds = ["warmup", "measured", "measured", "measured"]
    for repetition_index, (repetition, expected_kind) in enumerate(
        zip(repetitions, expected_kinds, strict=True)
    ):
        if not isinstance(repetition, dict):
            raise TypeError("worker repetition must be an object")
        if (
            repetition.get("kind") != expected_kind
            or repetition.get("repetition_index") != repetition_index
            or repetition.get("steps") != STEPS
            or repetition.get("transitions") != env_count * STEPS
        ):
            raise ValueError("worker fixed repetition mismatch")
        elapsed = float(repetition.get("elapsed_s"))
        throughput = float(repetition.get("transitions_per_s"))
        if (
            not math.isfinite(elapsed)
            or elapsed <= 0.0
            or not math.isfinite(throughput)
            or throughput <= 0.0
            or not math.isclose(
                throughput,
                (env_count * STEPS) / elapsed,
                rel_tol=1.0e-12,
                abs_tol=0.0,
            )
        ):
            raise ValueError("worker throughput arithmetic mismatch")
        if repetition.get("call_counts") != repetition.get("expected_call_counts"):
            raise ValueError("worker deployed-pipeline call count mismatch")
        expected_calls = {
            "perturb_imu": STEPS,
            "controller": STEPS,
            "context_push_issued": STEPS,
            "context_observe_transition": DROPOUT_START_STEP,
            "context_predict_acceleration": STEPS - DROPOUT_START_STEP,
            "environment_step": STEPS,
        }
        if repetition.get("call_counts") != expected_calls:
            raise ValueError("worker deployed-pipeline call contract mismatch")
        if (
            repetition.get("context_seed_first")
            != CONTEXT_SEED_BASE + CONTEXT_SEED_REPETITION_STRIDE * repetition_index
            or repetition.get("context_seed_last")
            != CONTEXT_SEED_BASE + CONTEXT_SEED_REPETITION_STRIDE * repetition_index + env_count - 1
        ):
            raise ValueError("worker nested context-seed prefix mismatch")
        if repetition.get("all_tracked_tensors_finite") is not True:
            raise ValueError("worker repetition has non-finite state")
        if repetition.get("context_frozen") is not True:
            raise ValueError("worker context did not freeze")
        if repetition.get("context_post_freeze_update_attempts") != 0:
            raise ValueError("worker context changed after freeze")
        for memory_snapshot_field in ("torch_memory_before", "torch_memory_after"):
            memory_snapshot = repetition.get(memory_snapshot_field)
            if not isinstance(memory_snapshot, dict) or set(memory_snapshot) != {
                "free_bytes",
                "total_bytes",
                "used_bytes",
            }:
                raise ValueError(f"worker invalid memory field: {memory_snapshot_field}")
            free_bytes = memory_snapshot["free_bytes"]
            snapshot_total = memory_snapshot["total_bytes"]
            used_bytes = memory_snapshot["used_bytes"]
            if (
                type(free_bytes) is not int
                or type(snapshot_total) is not int
                or type(used_bytes) is not int
                or free_bytes < 0
                or snapshot_total != total_vram_bytes
                or used_bytes < 0
                or free_bytes + used_bytes != snapshot_total
            ):
                raise ValueError(f"worker invalid memory field: {memory_snapshot_field}")
        torch_reserved_before = repetition.get("torch_reserved_before_bytes")
        torch_peak_allocated = repetition.get("torch_peak_allocated_bytes")
        torch_peak_reserved = repetition.get("torch_peak_reserved_bytes")
        if not all(
            type(value) is int
            for value in (
                torch_reserved_before,
                torch_peak_allocated,
                torch_peak_reserved,
            )
        ):
            raise ValueError("worker Torch memory evidence must contain integer byte counts")
        if not (0 <= torch_peak_allocated <= torch_peak_reserved <= total_vram_bytes):
            raise ValueError(
                "worker Torch peak memory must satisfy 0 <= allocated <= reserved <= total VRAM"
            )
        if not (
            0 <= torch_reserved_before <= torch_peak_reserved
            and torch_reserved_before <= repetition["torch_memory_before"]["used_bytes"]
        ):
            raise ValueError(
                "worker Torch reserved-before memory must not exceed the "
                "reserved peak or global memory-before usage"
            )
        _validate_gpu_monitor(
            repetition.get("gpu_monitor"),
            expected_total_bytes=total_vram_bytes,
        )


def summarize_scaling(
    worker_records: list[dict[str, Any]],
    *,
    config: ScalingConfig,
) -> dict[str, Any]:
    if len(worker_records) != len(ENV_COUNTS):
        raise ValueError("scaling summary requires all five workers")
    for env_index, record in enumerate(worker_records):
        validate_worker_record(record, config=config, env_index=env_index)
    identities = [record["identity"] for record in worker_records]
    identity_consistent = all(
        canonical_json_bytes(identity) == canonical_json_bytes(identities[0])
        for identity in identities[1:]
    )
    if not identity_consistent:
        raise ValueError("GPU/runtime identity changed across serial workers")

    summaries = []
    for env_count, record in zip(ENV_COUNTS, worker_records, strict=True):
        measured = [
            repetition for repetition in record["repetitions"] if repetition["kind"] == "measured"
        ]
        throughputs = [float(repetition["transitions_per_s"]) for repetition in measured]
        samples = [
            sample for repetition in measured for sample in repetition["gpu_monitor"]["samples"]
        ]
        monitor_summary = gpu_sample_summary(
            samples,
            validate_offsets=False,
            expected_total_bytes=int(record["identity"]["gpu"]["total_memory_bytes"]),
        )
        summaries.append(
            {
                "env_count": env_count,
                "measured_transitions_per_s": throughputs,
                "mean_transitions_per_s": statistics.fmean(throughputs),
                "coefficient_of_variation": coefficient_of_variation(throughputs),
                "measured_gpu_monitor": monitor_summary,
                "maximum_torch_peak_allocated_bytes": max(
                    int(repetition["torch_peak_allocated_bytes"]) for repetition in measured
                ),
                "maximum_torch_peak_reserved_bytes": max(
                    int(repetition["torch_peak_reserved_bytes"]) for repetition in measured
                ),
                "measured_transitions": env_count * STEPS * MEASURED_RUNS,
            }
        )
    baseline = float(summaries[0]["mean_transitions_per_s"])
    for summary in summaries:
        speedup = float(summary["mean_transitions_per_s"]) / baseline
        env_ratio = int(summary["env_count"]) / ENV_COUNTS[0]
        summary["speedup_vs_32_envs"] = speedup
        summary["parallel_efficiency_vs_32_envs"] = speedup / env_ratio
    cv_checks = {
        str(summary["env_count"]): (float(summary["coefficient_of_variation"]) <= MAX_MEASURED_CV)
        for summary in summaries
    }
    achieved_speedup = float(summaries[-1]["speedup_vs_32_envs"])
    performance_achieved = all(cv_checks.values()) and achieved_speedup >= MIN_512_VS_32_SPEEDUP
    return {
        "status": "PASS",
        "pass_semantics": (
            "evidence-integrity PASS only; preregistered performance thresholds "
            "are reported separately and never redefine PASS"
        ),
        "identity_consistent_across_fresh_serial_workers": identity_consistent,
        "env_summaries": summaries,
        "total_measured_transitions": sum(
            int(summary["measured_transitions"]) for summary in summaries
        ),
        "metric_definitions": {
            "speedup": "mean throughput at N envs / mean throughput at 32 envs",
            "parallel_efficiency": "speedup / (N / 32)",
            "coefficient_of_variation": (
                "sample standard deviation / arithmetic mean over 3 measured runs"
            ),
        },
        "performance_acceptance": {
            "preregistered": True,
            "thresholds": {
                "maximum_cv_each_env_count": MAX_MEASURED_CV,
                "minimum_512_vs_32_speedup": MIN_512_VS_32_SPEEDUP,
            },
            "checks": {
                "cv_each_env_count": cv_checks,
                "speedup_512_vs_32": {
                    "observed": achieved_speedup,
                    "achieved": achieved_speedup >= MIN_512_VS_32_SPEEDUP,
                },
            },
            "achieved": performance_achieved,
        },
    }


def build_prelaunch_gate(
    *,
    frozen_preflight: dict[str, Any],
    current_preflight: dict[str, Any],
    env_count: int,
    completed_worker_records: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_gpu_preflight(frozen_preflight)
    validate_gpu_preflight(current_preflight)
    if current_preflight["gpu_identity"] != frozen_preflight["gpu_identity"]:
        raise ValueError("GPU identity or total VRAM changed after preflight freeze")
    gate: dict[str, Any] = {
        "env_count": env_count,
        "identity_matches_frozen_preflight": True,
        "zero_live_gpu_processes": True,
        "free_vram_fraction": current_preflight["baseline"]["free_vram_fraction"],
        "minimum_free_vram_fraction": BASELINE_FREE_VRAM_FRACTION_MIN,
        "eligible": True,
    }
    if env_count != 512:
        return gate
    if not completed_worker_records or completed_worker_records[-1]["workload"]["env_count"] != 256:
        raise ValueError("512 headroom gate requires a validated 256-env worker")
    baseline_used = int(frozen_preflight["baseline"]["used_vram_bytes"])
    total = int(frozen_preflight["gpu_identity"]["total_vram_bytes"])
    observed_global_peak_candidates = [
        int(sample["vram_used_bytes"])
        for repetition in completed_worker_records[-1]["repetitions"]
        for sample in repetition["gpu_monitor"]["samples"]
    ]
    observed_global_peak_candidates.extend(
        int(repetition[memory_field]["used_bytes"])
        for repetition in completed_worker_records[-1]["repetitions"]
        for memory_field in ("torch_memory_before", "torch_memory_after")
    )
    torch_delta_adjusted_peak_candidates = [
        int(repetition["torch_memory_before"]["used_bytes"])
        + max(
            0,
            int(repetition["torch_peak_reserved_bytes"])
            - int(repetition["torch_reserved_before_bytes"]),
        )
        for repetition in completed_worker_records[-1]["repetitions"]
    ]
    observed_global_peak_256 = max(observed_global_peak_candidates)
    torch_delta_adjusted_peak_256 = max(torch_delta_adjusted_peak_candidates)
    peak_used_256 = max(
        observed_global_peak_256,
        torch_delta_adjusted_peak_256,
    )
    projected = baseline_used + math.ceil(
        PROJECTED_512_GROWTH_MULTIPLIER * max(0, peak_used_256 - baseline_used)
    )
    maximum_projected = math.floor(PROJECTED_512_TOTAL_FRACTION_MAX * total)
    projected_increment = projected - baseline_used
    current_free = int(current_preflight["baseline"]["free_vram_bytes"])
    projection_within_limit = projected <= maximum_projected
    current_headroom_sufficient = current_free >= projected_increment
    gate["env_512_projection"] = {
        "baseline_used_bytes": baseline_used,
        "peak_used_bytes_at_256": peak_used_256,
        "observed_global_peak_used_bytes_at_256": observed_global_peak_256,
        "torch_delta_adjusted_peak_used_bytes_at_256": (torch_delta_adjusted_peak_256),
        "growth_multiplier": PROJECTED_512_GROWTH_MULTIPLIER,
        "projected_512_bytes": projected,
        "maximum_projected_bytes": maximum_projected,
        "projected_increment_bytes": projected_increment,
        "current_free_bytes": current_free,
        "projection_within_85_percent_total": projection_within_limit,
        "current_free_covers_projected_increment": current_headroom_sufficient,
    }
    gate["eligible"] = projection_within_limit and current_headroom_sufficient
    return gate


def _failure_payload(
    *,
    config: ScalingConfig,
    completed_workers: list[dict[str, Any]],
    env_count: int | None,
    reason: str,
    returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
    lock_evidence: dict[str, Any] | None = None,
    frozen_preflight: dict[str, Any] | None = None,
    prelaunch_gates: list[dict[str, Any]] | None = None,
    ineligible: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "status": "FAIL_INELIGIBLE" if ineligible else "FAIL",
        "simulation_only": True,
        "protocol": {
            "path": str(config.protocol_path),
            "sha256": config.protocol_sha256,
        },
        "execution_contract": {
            "strictly_serial": True,
            "automatic_retry": False,
            "completed_worker_count": len(completed_workers),
            "global_gpu_lock": lock_evidence,
        },
        "frozen_gpu_preflight": frozen_preflight,
        "prelaunch_gates": [] if prelaunch_gates is None else prelaunch_gates,
        "completed_workers": completed_workers,
        "failure": {
            "env_count": env_count,
            "reason": reason,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    }


def run_parent(
    *,
    protocol_path: Path,
    output_path: Path,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    source_sha256_policy: Callable[[str], None] = require_official_r5_protocol_sha256,
    lock_context_factory: Callable[[Path], Any] = hold_global_gpu_lock,
    preflight_provider: Callable[[], dict[str, Any]] = capture_gpu_preflight,
) -> int:
    with lock_context_factory(GLOBAL_GPU_LOCK_PATH) as lock_evidence:
        if not isinstance(lock_evidence, dict):
            raise TypeError("global GPU lock did not return owner evidence")
        if lock_evidence.get("path") != str(GLOBAL_GPU_LOCK_PATH):
            raise ValueError("global GPU lock evidence path mismatch")
        return _run_parent_locked(
            protocol_path=protocol_path,
            output_path=output_path,
            run_command=run_command,
            source_sha256_policy=source_sha256_policy,
            preflight_provider=preflight_provider,
            lock_evidence=lock_evidence,
        )


def _run_parent_locked(
    *,
    protocol_path: Path,
    output_path: Path,
    run_command: Callable[..., subprocess.CompletedProcess[str]],
    source_sha256_policy: Callable[[str], None],
    preflight_provider: Callable[[], dict[str, Any]],
    lock_evidence: dict[str, Any],
) -> int:
    config = validate_scaling_protocol(
        protocol_path=protocol_path,
        source_sha256_policy=source_sha256_policy,
    )
    resolved_output = output_path.expanduser().resolve()
    if resolved_output != config.aggregate_path:
        raise ValueError("aggregate output differs from its frozen slot")
    if config.output_root.exists():
        raise FileExistsError("scaling output root already exists; refusing overwrite/retry")
    if resolved_output.exists() or any(path.exists() for path in config.worker_paths):
        raise FileExistsError("registered scaling output already exists")

    worker_records: list[dict[str, Any]] = []
    worker_artifacts: list[dict[str, Any]] = []
    prelaunch_gates: list[dict[str, Any]] = []
    config.output_root.mkdir(parents=True, exist_ok=False)
    try:
        frozen_preflight = validate_gpu_preflight(preflight_provider())
    except Exception as error:  # noqa: BLE001 - persist exact preflight failure
        payload = _failure_payload(
            config=config,
            completed_workers=worker_artifacts,
            env_count=None,
            reason=f"{type(error).__name__}: {error}",
            lock_evidence=lock_evidence,
        )
        write_json_exclusive(resolved_output, payload)
        return 2
    script_path = Path(__file__).resolve()
    for env_index, env_count in enumerate(ENV_COUNTS):
        try:
            current = validate_scaling_protocol(
                protocol_path=config.protocol_path,
                source_sha256_policy=source_sha256_policy,
            )
            if current != config:
                raise RuntimeError("frozen binding changed before worker launch")
            current_preflight = (
                frozen_preflight if env_index == 0 else validate_gpu_preflight(preflight_provider())
            )
            gate = build_prelaunch_gate(
                frozen_preflight=frozen_preflight,
                current_preflight=current_preflight,
                env_count=env_count,
                completed_worker_records=worker_records,
            )
            prelaunch_gates.append(gate)
            if gate["eligible"] is not True:
                payload = _failure_payload(
                    config=config,
                    completed_workers=worker_artifacts,
                    env_count=env_count,
                    reason="512-environment VRAM projection gate is ineligible",
                    lock_evidence=lock_evidence,
                    frozen_preflight=frozen_preflight,
                    prelaunch_gates=prelaunch_gates,
                    ineligible=True,
                )
                write_json_exclusive(resolved_output, payload)
                return 2
            command = [
                sys.executable,
                str(script_path),
                "--protocol",
                str(config.protocol_path),
                "--worker-env-count",
                str(env_count),
                "--worker-env-index",
                str(env_index),
                "--worker-output",
                str(config.worker_paths[env_index]),
            ]
            environment = os.environ.copy()
            environment.update(
                {
                    "HIP_VISIBLE_DEVICES": "0",
                    "ROCR_VISIBLE_DEVICES": "0",
                    "CUDA_VISIBLE_DEVICES": "0",
                }
            )
            started_at_unix_s = time.time()
            run = run_command(
                command,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            finished_at_unix_s = time.time()
            after_worker = validate_scaling_protocol(
                protocol_path=config.protocol_path,
                source_sha256_policy=source_sha256_policy,
            )
            if after_worker != config:
                raise RuntimeError("frozen binding changed during worker execution")
            if run.returncode:
                payload = _failure_payload(
                    config=config,
                    completed_workers=worker_artifacts,
                    env_count=env_count,
                    reason="worker subprocess failed",
                    returncode=run.returncode,
                    stdout=run.stdout,
                    stderr=run.stderr,
                    lock_evidence=lock_evidence,
                    frozen_preflight=frozen_preflight,
                    prelaunch_gates=prelaunch_gates,
                )
                write_json_exclusive(resolved_output, payload)
                return run.returncode
            worker_path = config.worker_paths[env_index]
            if not worker_path.is_file():
                raise FileNotFoundError(f"worker output is missing: {worker_path}")
            record = load_strict_json(worker_path)
            validate_worker_record(record, config=config, env_index=env_index)
            worker_sha256 = sha256_file(worker_path)
            worker_records.append(record)
            worker_artifacts.append(
                {
                    "env_count": env_count,
                    "path": str(worker_path),
                    "sha256": worker_sha256,
                    "started_at_unix_s": started_at_unix_s,
                    "finished_at_unix_s": finished_at_unix_s,
                    "subprocess_elapsed_s": finished_at_unix_s - started_at_unix_s,
                }
            )
            print(
                json.dumps(
                    {
                        "event": "radeon_formal_scaling_worker_complete",
                        "env_count": env_count,
                        "output_sha256": worker_sha256,
                    },
                    allow_nan=False,
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as error:  # noqa: BLE001 - persist exact worker failure evidence
            payload = _failure_payload(
                config=config,
                completed_workers=worker_artifacts,
                env_count=env_count,
                reason=f"{type(error).__name__}: {error}",
                lock_evidence=lock_evidence,
                frozen_preflight=frozen_preflight,
                prelaunch_gates=prelaunch_gates,
                ineligible=env_count == 512,
            )
            write_json_exclusive(resolved_output, payload)
            return 2

    try:
        final_binding = validate_scaling_protocol(
            protocol_path=config.protocol_path,
            source_sha256_policy=source_sha256_policy,
        )
        if final_binding != config:
            raise RuntimeError("frozen binding changed before aggregation")
        summary = summarize_scaling(worker_records, config=config)
    except Exception as error:  # noqa: BLE001 - persist exact summary failure evidence
        payload = _failure_payload(
            config=config,
            completed_workers=worker_artifacts,
            env_count=None,
            reason=f"{type(error).__name__}: {error}",
            lock_evidence=lock_evidence,
            frozen_preflight=frozen_preflight,
            prelaunch_gates=prelaunch_gates,
        )
        write_json_exclusive(resolved_output, payload)
        return 2
    payload = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "status": "PASS",
        "simulation_only": True,
        "claim_boundary": load_strict_json(config.protocol_path)["claim_boundary"],
        "protocol": {
            "path": str(config.protocol_path),
            "sha256": config.protocol_sha256,
            "version": PROTOCOL_VERSION,
        },
        "source_r5": {
            "protocol_sha256": config.source_protocol_sha256,
            "runtime_canonical_sha256": canonical_sha256(config.runtime),
            "checkpoint": config.checkpoint,
        },
        "execution_contract": {
            "one_radeon_gpu": True,
            "fresh_subprocess_per_env_count": True,
            "strictly_serial": True,
            "subprocess_order": list(ENV_COUNTS),
            "automatic_retry": False,
            "output_overwrite": False,
            "global_gpu_lock": lock_evidence,
        },
        "frozen_gpu_preflight": frozen_preflight,
        "prelaunch_gates": prelaunch_gates,
        "worker_artifacts": worker_artifacts,
        "scaling": summary,
    }
    write_json_exclusive(resolved_output, payload)
    print(
        json.dumps(
            {
                "event": "radeon_formal_scaling_complete",
                "status": "PASS",
                "output": str(resolved_output),
                "sha256": sha256_file(resolved_output),
            },
            allow_nan=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def main() -> None:
    args = parse_args()
    protocol_path = args.protocol.expanduser().resolve()
    worker_fields = (
        args.worker_env_count,
        args.worker_env_index,
        args.worker_output,
    )
    worker_mode = any(value is not None for value in worker_fields)
    if worker_mode:
        if any(value is None for value in worker_fields) or args.output is not None:
            raise ValueError(
                "worker mode requires env count, env index, and worker output; "
                "it forbids aggregate output"
            )
        worker_output = args.worker_output.expanduser().resolve()
        payload = run_worker(
            protocol_path=protocol_path,
            env_count=args.worker_env_count,
            env_index=args.worker_env_index,
            worker_output=worker_output,
        )
        write_json_exclusive(worker_output, payload)
        print(
            json.dumps(
                {
                    "event": "radeon_formal_scaling_worker_final",
                    "status": payload["status"],
                    "env_count": args.worker_env_count,
                    "output": str(worker_output),
                    "sha256": sha256_file(worker_output),
                },
                allow_nan=False,
                sort_keys=True,
            ),
            flush=True,
        )
        if payload["status"] != "PASS":
            raise SystemExit(2)
        return
    if args.output is None:
        raise ValueError("parent mode requires --output")
    raise SystemExit(
        run_parent(
            protocol_path=protocol_path,
            output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
