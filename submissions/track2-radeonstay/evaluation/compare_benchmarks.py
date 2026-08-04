#!/usr/bin/env python3
"""Compare two quality-gated RadeonStay benchmark reports and assess acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3
OFFICIAL_SUITE_VERSION = "30-case-p0-v3"
OFFICIAL_SUITE_SHA256 = "60fae4be0bd7a16ee9b2e7963bb3afccbf319c2ed64cd3ba43acfc912bfd3d1b"
OFFICIAL_CASE_IDS = tuple(f"KQ-{index:03d}" for index in range(1, 9))
OFFICIAL_CONCURRENCY = (1, 2, 4)
MIN_OFFICIAL_REPETITIONS = 3
MIN_OFFICIAL_WARMUP = 2
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
GPU_BACKEND_RE = re.compile(
    r"^\s*ggml_(?:cuda|hip)_init\s*:.*\b(?:ROCm|HIP)\b.*$",
    re.I | re.M,
)
GPU_OFFLOAD_RE = re.compile(
    r"^\s*(?:llm_)?load_tensors\s*:\s*offloaded\s+"
    r"([1-9][0-9]*)/([1-9][0-9]*)\s+layers?\s+to\s+GPU\b.*$",
    re.I | re.M,
)
MONITOR_SAMPLE_RE = re.compile(
    r"sample=([1-9][0-9]*) run_id=(\S+) collected_at_utc=(\S+)"
)
GPU_INDEX_RE = re.compile(r"GPU\[([0-9]+)\]", re.I)
GPU_UNIQUE_ID_RE = re.compile(
    r"^\s*GPU\[([0-9]+)\]\s*:\s*Unique ID\s*:\s*(0x[0-9a-f]+)\s*$",
    re.I,
)
DEVICE_IDENTITY_BEGIN = "device_identity_begin"
DEVICE_IDENTITY_END = "device_identity_end"
DEVICE_UNIQUE_ID_MARKER = "unique id"
GPU_USE_MARKERS = ("gpu use (%)", "gpu utilization (%)", "gpu utilization")
VRAM_USED_MARKERS = (
    "vram total used memory",
    "vram used memory",
    "vram used",
)
BINDING_FILE_NAMES = {
    "retrieval_file": "retrieval.json",
    "quality_file": "agent-quality.json",
    "benchmark_file": "agent-benchmark.json",
    "monitor_file": "rocm-monitor.log",
    "server_log": "llama-server.log",
}
BINDING_HASH_FIELDS = {
    "retrieval_file": "retrieval_sha256",
    "quality_file": "quality_sha256",
    "benchmark_file": "benchmark_sha256",
    "monitor_file": "monitor_sha256",
    "server_log": "server_log_sha256",
}
BINDING_REQUIRED_FIELDS = {
    "schema_version",
    "run_id",
    "created_at_utc",
    "binding_status",
    "commit",
    "project_tree",
    "source_tree_sha256",
    "hardware_identity_algorithm",
    "hardware_identity_sha256",
    *BINDING_FILE_NAMES,
    *BINDING_HASH_FIELDS.values(),
    "model_file",
    "model_sha256",
    "llama_server",
    "llama_server_sha256",
}
BUNDLE_CHECKSUM_FILES = {
    "manifest.txt",
    "system.txt",
    "rocminfo.txt",
    "rocm-smi.txt",
    "rocm-version.txt",
    "git.txt",
    *BINDING_FILE_NAMES.values(),
    "binding-manifest.txt",
}
TOKEN_RATE_FIELDS = (
    "effective_output_tokens_per_second_p50",
    "effective_output_tokens_per_second_p95",
)
CORE_METRIC_NAMES = (
    "latency_p50_ms",
    "latency_p95_ms",
    "successful_throughput_requests_per_second",
    *TOKEN_RATE_FIELDS,
)
OPTIONAL_METRIC_GROUPS = (
    (
        "server_decode_rate_sample_count",
        (
            "server_decode_tokens_per_second_p50",
            "server_decode_tokens_per_second_p95",
        ),
        False,
    ),
    ("ttft_sample_count", ("ttft_ms_p50", "ttft_ms_p95"), True),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare baseline and optimized schema-v3 benchmark evidence. "
            "A quality-preserving, regression-free material core improvement "
            "is accepted as the optimized winner."
        )
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--optimized", type=Path, required=True)
    parser.add_argument("--baseline-binding", type=Path, required=True)
    parser.add_argument("--optimized-binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--material-threshold-percent",
        type=float,
        default=5.0,
        help="Minimum directional change considered material (default: 5.0)",
    )
    parser.add_argument(
        "--require-accepted",
        action="store_true",
        help="Return a non-zero exit status after writing the report when not accepted",
    )
    return parser.parse_args(argv)


def require_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return number


def validate_request_configuration(
    payload: dict[str, Any], label: str
) -> dict[str, Any]:
    configuration = payload.get("request_configuration")
    if not isinstance(configuration, dict):
        raise ValueError(f"{label} report is missing request_configuration")
    for field in ("thinking_enabled", "schema_constrained"):
        value = configuration.get(field)
        if type(value) is not bool:
            raise ValueError(
                f"{label}.request_configuration.{field} must be a boolean"
            )
    return dict(configuration)


def validate_request_configuration_evidence(
    payload: dict[str, Any], label: str
) -> dict[str, Any]:
    configuration = validate_request_configuration(payload, label)
    evidence = payload.get("request_configuration_evidence")
    if not isinstance(evidence, dict) or evidence.get("trace_verified") is not True:
        raise ValueError(f"{label} report has no verified request-configuration trace")
    require_integer(
        evidence.get("model_call_count"),
        f"{label}.request_configuration_evidence.model_call_count",
        minimum=1,
    )
    for field in ("thinking_enabled", "schema_constrained"):
        if type(evidence.get(field)) is not bool:
            raise ValueError(
                f"{label}.request_configuration_evidence.{field} must be a boolean"
            )
        if evidence[field] != configuration[field]:
            raise ValueError(
                f"{label} request-configuration evidence does not match {field}"
            )
    response_formats = evidence.get("response_formats")
    if not isinstance(response_formats, list) or not all(
        isinstance(item, str) and item for item in response_formats
    ):
        raise ValueError(f"{label} report has invalid response-format evidence")
    if configuration["schema_constrained"] and response_formats != ["json_schema"]:
        raise ValueError(f"{label} report does not prove schema-constrained requests")
    return dict(evidence)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_binding(path: Path, label: str) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} binding manifest does not exist: {resolved}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        resolved.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not raw_line or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        if not key or key in values:
            raise ValueError(f"Invalid or duplicate key in {label} binding at line {line_number}")
        values[key] = value
    if values.get("schema_version") != "3" or values.get("binding_status") != "complete":
        raise ValueError(f"{label} binding manifest must be schema 3 and complete")
    missing = sorted(BINDING_REQUIRED_FIELDS - set(values))
    if missing:
        raise ValueError(f"{label} binding manifest is missing fields: {missing}")
    hash_fields = {
        "source_tree_sha256",
        "hardware_identity_sha256",
        *BINDING_HASH_FIELDS.values(),
        "model_sha256",
        "llama_server_sha256",
    }
    for field in hash_fields:
        if not SHA256_RE.fullmatch(values[field]):
            raise ValueError(f"{label} binding has an invalid {field}")
    if not re.fullmatch(r"[0-9a-f]{40,64}", values["commit"]):
        raise ValueError(f"{label} binding has an invalid commit")
    if not re.fullmatch(r"[0-9a-f]{40,64}", values["project_tree"]):
        raise ValueError(f"{label} binding has an invalid project_tree")
    for field, expected_name in BINDING_FILE_NAMES.items():
        if values[field] != expected_name:
            raise ValueError(f"{label} binding has an unexpected {field}")
    if (
        values["hardware_identity_algorithm"]
        != "stable-system-v1+rocminfo+rocm-version"
    ):
        raise ValueError(f"{label} binding has an unsupported hardware identity algorithm")
    return values


def load_checksum_manifest(path: Path, label: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = raw_line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Invalid {label} SHA256SUMS line {line_number}")
        checksum, raw_name = parts
        name = raw_name.lstrip("*")
        if not SHA256_RE.fullmatch(checksum) or name in checksums:
            raise ValueError(f"Invalid {label} SHA256SUMS line {line_number}")
        if Path(name).name != name:
            raise ValueError(f"Unsafe path in {label} SHA256SUMS line {line_number}")
        checksums[name] = checksum
    missing = sorted(BUNDLE_CHECKSUM_FILES - set(checksums))
    if missing:
        raise ValueError(f"{label} SHA256SUMS is missing files: {missing}")
    return checksums


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def stable_system_sha256(path: Path) -> str:
    dynamic_prefixes = (b"CPU MHz:", b"CPU(s) scaling MHz:")
    digest = hashlib.sha256()
    for line in path.read_bytes().splitlines(keepends=True):
        if line.lstrip().startswith(dynamic_prefixes):
            continue
        digest.update(line)
    return digest.hexdigest()


def _reported_metric_values(text: str, markers: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for raw_line in text.splitlines():
        folded = raw_line.casefold()
        if not any(marker in folded for marker in markers):
            continue
        value_text = raw_line.rsplit(":", 1)[-1] if ":" in raw_line else raw_line
        matches = NUMBER_RE.findall(value_text)
        if matches:
            values.append(float(matches[-1]))
    return values


def _parse_utc_instant(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is missing")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid timestamp") from exc
    if instant.tzinfo is None:
        raise ValueError(f"{field} must include a UTC offset")
    return instant


def _monitor_sample_summaries(monitor_text: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in monitor_text.splitlines():
        if raw_line.startswith("sample="):
            match = MONITOR_SAMPLE_RE.fullmatch(raw_line)
            if match is None:
                raise ValueError("monitor contains a malformed sample header")
            if current is not None:
                samples.append(current)
            collected_at = _parse_utc_instant(
                match.group(3),
                "monitor sample timestamp",
            )
            current = {
                "sequence": int(match.group(1)),
                "run_id": match.group(2),
                "collected_at": collected_at,
                "lines": [],
            }
        elif current is not None:
            current["lines"].append(raw_line)
    if current is not None:
        samples.append(current)

    for sample in samples:
        sample_lines = sample.pop("lines")
        sample_text = "\n".join(sample_lines)
        gpu_use = _reported_metric_values(sample_text, GPU_USE_MARKERS)
        vram_used = _reported_metric_values(sample_text, VRAM_USED_MARKERS)
        device_metrics: dict[int, dict[str, list[float]]] = {}
        for raw_line in sample_lines:
            index_match = GPU_INDEX_RE.search(raw_line)
            if index_match is None:
                continue
            gpu_index = int(index_match.group(1))
            values = device_metrics.setdefault(gpu_index, {"gpu_use": [], "vram_used": []})
            folded = raw_line.casefold()
            if any(marker in folded for marker in GPU_USE_MARKERS):
                values["gpu_use"].extend(_reported_metric_values(raw_line, GPU_USE_MARKERS))
            if any(marker in folded for marker in VRAM_USED_MARKERS):
                values["vram_used"].extend(
                    _reported_metric_values(raw_line, VRAM_USED_MARKERS)
                )
        active_gpu_indices = sorted(
            gpu_index
            for gpu_index, values in device_metrics.items()
            if max(values["gpu_use"], default=0.0) > 0
            and max(values["vram_used"], default=0.0) > 0
        )
        sample["peak_gpu_use_percent"] = max(gpu_use, default=0.0)
        sample["peak_vram_used_reported"] = max(vram_used, default=0.0)
        sample["active_gpu_indices"] = active_gpu_indices
    return samples


def _monitor_device_unique_ids(monitor_text: str) -> tuple[dict[int, str], set[int]]:
    identities: dict[int, str] = {}
    invalid_indices: set[int] = set()
    inside_identity = False
    saw_begin = False
    saw_end = False
    for raw_line in monitor_text.splitlines():
        if raw_line == DEVICE_IDENTITY_BEGIN:
            if saw_begin or inside_identity:
                raise ValueError("monitor contains duplicate device identity blocks")
            saw_begin = True
            inside_identity = True
            continue
        if raw_line == DEVICE_IDENTITY_END:
            if not inside_identity or saw_end:
                raise ValueError("monitor contains a malformed device identity block")
            saw_end = True
            inside_identity = False
            continue
        if not inside_identity or DEVICE_UNIQUE_ID_MARKER not in raw_line.casefold():
            continue
        index_match = GPU_INDEX_RE.search(raw_line)
        # rocm-smi prints a decorative "Unique ID" section heading without a
        # device index before the per-GPU rows.
        if index_match is None:
            continue
        identity_match = GPU_UNIQUE_ID_RE.fullmatch(raw_line)
        if identity_match is None:
            invalid_index = int(index_match.group(1))
            invalid_indices.add(invalid_index)
            identities.pop(invalid_index, None)
            continue
        gpu_index = int(identity_match.group(1))
        unique_id = identity_match.group(2).casefold()
        if int(unique_id, 16) == 0:
            invalid_indices.add(gpu_index)
            identities.pop(gpu_index, None)
            continue
        if gpu_index in invalid_indices:
            continue
        if gpu_index in identities and identities[gpu_index] != unique_id:
            invalid_indices.add(gpu_index)
            identities.pop(gpu_index, None)
            continue
        identities[gpu_index] = unique_id
    if inside_identity or saw_begin != saw_end:
        raise ValueError("monitor contains an incomplete device identity block")
    if len(set(identities.values())) != len(identities):
        raise ValueError("monitor maps multiple GPU indices to one unique ID")
    return identities, invalid_indices


def runtime_gpu_summary(
    server_path: Path,
    monitor_path: Path,
    label: str,
    *,
    required_windows: dict[str, tuple[datetime, datetime]] | None = None,
    expected_run_id: str | None = None,
    expected_sample_count: int | None = None,
    maximum_sample_gap_seconds: float | None = None,
    coverage_window: tuple[datetime, datetime] | None = None,
    declared_monitor_window: tuple[datetime, datetime] | None = None,
    require_device_identity: bool = False,
) -> dict[str, Any]:
    server_text = server_path.read_text(encoding="utf-8", errors="replace")
    monitor_text = monitor_path.read_text(encoding="utf-8", errors="replace")
    if GPU_BACKEND_RE.search(server_text) is None:
        raise ValueError(f"{label} server log has no ROCm/HIP Radeon backend marker")

    positive_offload = any(
        0 < int(match.group(1)) <= int(match.group(2))
        for match in GPU_OFFLOAD_RE.finditer(server_text)
    )
    if not positive_offload:
        raise ValueError(f"{label} server log does not prove any model layer was GPU-offloaded")

    gpu_use = _reported_metric_values(monitor_text, GPU_USE_MARKERS)
    vram_used = _reported_metric_values(monitor_text, VRAM_USED_MARKERS)
    if not gpu_use or max(gpu_use) <= 0:
        raise ValueError(f"{label} monitor has no positive Radeon GPU-use observation")
    if not vram_used or max(vram_used) <= 0:
        raise ValueError(f"{label} monitor has no positive VRAM-use observation")
    samples = _monitor_sample_summaries(monitor_text)
    device_unique_ids, invalid_device_identity_indices = _monitor_device_unique_ids(
        monitor_text
    )
    if require_device_identity and not required_windows and not device_unique_ids:
        raise ValueError(f"{label} monitor has no Radeon GPU unique-ID evidence")
    if any(
        value is not None
        for value in (
            expected_run_id,
            expected_sample_count,
            maximum_sample_gap_seconds,
            coverage_window,
            declared_monitor_window,
        )
    ) and not samples:
        raise ValueError(f"{label} monitor has no timestamped telemetry samples")
    if samples:
        sequences = [sample["sequence"] for sample in samples]
        if sequences != list(range(1, len(samples) + 1)):
            raise ValueError(f"{label} monitor sample sequence is not contiguous")
        if expected_run_id is not None and any(
            sample["run_id"] != expected_run_id for sample in samples
        ):
            raise ValueError(f"{label} monitor sample has the wrong run-id")
        if expected_sample_count is not None and len(samples) != expected_sample_count:
            raise ValueError(f"{label} monitor sample count is inconsistent")
        sample_times = [sample["collected_at"] for sample in samples]
        for previous, current in zip(sample_times[:-1], sample_times[1:], strict=True):
            if current < previous:
                raise ValueError(f"{label} monitor sample timestamps are not monotonic")
            if (
                maximum_sample_gap_seconds is not None
                and (current - previous).total_seconds() > maximum_sample_gap_seconds
            ):
                raise ValueError(f"{label} monitor contains an excessive sampling gap")
        first_sample_at = sample_times[0]
        last_sample_at = sample_times[-1]
        if declared_monitor_window is not None and not (
            declared_monitor_window[0]
            <= first_sample_at
            <= last_sample_at
            <= declared_monitor_window[1]
        ):
            raise ValueError(f"{label} samples exceed the declared monitor window")
        if coverage_window is not None and not (
            first_sample_at <= coverage_window[0]
            and coverage_window[1] <= last_sample_at
        ):
            raise ValueError(f"{label} monitor samples do not cover evaluation windows")
    window_hits: dict[str, int] = {}
    window_gpu_indices: dict[str, set[int]] = {}
    window_sample_sequences: dict[str, set[int]] = {}
    window_gpu_sample_sequences: dict[str, dict[int, set[int]]] = {}
    common_window_gpu_indices: set[int] = set()
    if required_windows:
        if not samples:
            raise ValueError(f"{label} monitor has no timestamped telemetry samples")
        for window_name, (window_start, window_end) in required_windows.items():
            if window_start >= window_end:
                raise ValueError(f"{label} {window_name} window must have positive duration")
            active_sequences = {
                sample["sequence"]
                for sample in samples
                if window_start <= sample["collected_at"] <= window_end
                and bool(sample["active_gpu_indices"])
            }
            if not active_sequences:
                raise ValueError(
                    f"{label} monitor has no active GPU/VRAM sample in {window_name} window"
                )
            window_hits[window_name] = len(active_sequences)
            window_sample_sequences[window_name] = active_sequences
            gpu_sequences: dict[int, set[int]] = {}
            for sample in samples:
                if not window_start <= sample["collected_at"] <= window_end:
                    continue
                for gpu_index in sample["active_gpu_indices"]:
                    gpu_sequences.setdefault(gpu_index, set()).add(sample["sequence"])
            window_gpu_sample_sequences[window_name] = gpu_sequences
            window_gpu_indices[window_name] = set(gpu_sequences)
        common_window_gpu_indices = set.intersection(*window_gpu_indices.values())
        if not common_window_gpu_indices:
            raise ValueError(
                f"{label} evaluation windows do not share an active GPU index"
            )
        window_names = list(window_gpu_sample_sequences)
        independently_observed_gpu_indices: set[int] = set()
        for gpu_index in common_window_gpu_indices:
            independently_observed = True
            for index, left_name in enumerate(window_names):
                left_sequences = window_gpu_sample_sequences[left_name][gpu_index]
                for right_name in window_names[index + 1 :]:
                    right_sequences = window_gpu_sample_sequences[right_name][gpu_index]
                    if not (left_sequences - right_sequences) or not (
                        right_sequences - left_sequences
                    ):
                        independently_observed = False
                        break
                if not independently_observed:
                    break
            if independently_observed:
                independently_observed_gpu_indices.add(gpu_index)
        common_window_gpu_indices = independently_observed_gpu_indices
        if not common_window_gpu_indices:
            raise ValueError(
                f"{label} evaluation windows require distinct active telemetry "
                "samples on one shared GPU"
            )
    missing_identity_indices = sorted(
        gpu_index
        for gpu_index in common_window_gpu_indices
        if gpu_index not in device_unique_ids
    )
    if require_device_identity and missing_identity_indices:
        invalid_active_indices = sorted(
            set(missing_identity_indices) & invalid_device_identity_indices
        )
        if invalid_active_indices:
            raise ValueError(
                f"{label} active GPU indices have invalid Radeon GPU unique ID "
                f"evidence: {invalid_active_indices}"
            )
        raise ValueError(
            f"{label} active GPU indices lack unique-ID evidence: "
            f"{missing_identity_indices}"
        )
    common_window_gpu_unique_ids = sorted(
        {
            device_unique_ids[gpu_index]
            for gpu_index in common_window_gpu_indices
            if gpu_index in device_unique_ids
        }
    )
    return {
        "gpu_use_observations": len(gpu_use),
        "peak_gpu_use_percent": round(max(gpu_use), 3),
        "vram_use_observations": len(vram_used),
        "peak_vram_used_reported": round(max(vram_used), 3),
        "model_layer_offload_observed": True,
        "rocm_or_hip_backend_observed": True,
        "active_gpu_indices": sorted(
            {
                gpu_index
                for sample in samples
                for gpu_index in sample["active_gpu_indices"]
            }
        ),
        "active_window_sample_counts": window_hits,
        "active_window_gpu_indices": {
            window_name: sorted(indices)
            for window_name, indices in window_gpu_indices.items()
        },
        "active_window_sample_sequences": {
            window_name: sorted(sequences)
            for window_name, sequences in window_sample_sequences.items()
        },
        "active_window_gpu_sample_sequences": {
            window_name: {
                str(gpu_index): sorted(sequences)
                for gpu_index, sequences in sorted(gpu_sequences.items())
            }
            for window_name, gpu_sequences in window_gpu_sample_sequences.items()
        },
        "common_active_gpu_indices": sorted(common_window_gpu_indices),
        "device_unique_ids": {
            str(gpu_index): unique_id
            for gpu_index, unique_id in sorted(device_unique_ids.items())
        },
        "invalid_device_identity_indices": sorted(invalid_device_identity_indices),
        "common_active_gpu_unique_ids": common_window_gpu_unique_ids,
        "first_sample_at_utc": (
            samples[0]["collected_at"].isoformat() if samples else None
        ),
        "last_sample_at_utc": (
            samples[-1]["collected_at"].isoformat() if samples else None
        ),
    }


def load_key_value_evidence(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        if key and key not in values:
            values[key] = value
    return values


def load_server_configuration(path: Path) -> dict[str, str]:
    configuration: dict[str, str] = {}
    allowed = {"ctx", "parallel", "batch", "ubatch", "flash_attn"}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not (raw_line.startswith("ctx=") or raw_line.startswith("batch=")):
            continue
        for item in raw_line.split():
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            if key in allowed:
                configuration[key] = value
    if set(configuration) != allowed:
        raise ValueError(f"Server evidence is missing launch settings: {sorted(allowed)}")
    return configuration


def validate_bundle(
    binding_path: Path, binding: dict[str, str], label: str
) -> dict[str, Any]:
    resolved_binding = binding_path.expanduser().resolve()
    bundle_dir = resolved_binding.parent
    if resolved_binding != bundle_dir / "binding-manifest.txt":
        raise ValueError(f"{label} binding must be the bundle binding-manifest.txt")
    checksum_path = bundle_dir / "SHA256SUMS.txt"
    if not checksum_path.is_file():
        raise FileNotFoundError(f"{label} bundle is missing SHA256SUMS.txt")
    checksums = load_checksum_manifest(checksum_path, label)
    for name in BUNDLE_CHECKSUM_FILES:
        artifact = bundle_dir / name
        if not artifact.is_file():
            raise FileNotFoundError(f"{label} bundle is missing {name}")
        actual = file_sha256(artifact)
        if checksums.get(name) != actual:
            raise ValueError(f"{label} bundle checksum mismatch: {name}")

    for file_field, hash_field in BINDING_HASH_FIELDS.items():
        artifact = bundle_dir / binding[file_field]
        if file_sha256(artifact) != binding[hash_field]:
            raise ValueError(f"{label} binding hash mismatch: {hash_field}")

    identity_payload = "".join(
        f"{digest}\n"
        for digest in (
            stable_system_sha256(bundle_dir / "system.txt"),
            file_sha256(bundle_dir / "rocminfo.txt"),
            file_sha256(bundle_dir / "rocm-version.txt"),
        )
    ).encode("ascii")
    identity_hash = hashlib.sha256(identity_payload).hexdigest()
    if identity_hash != binding["hardware_identity_sha256"]:
        raise ValueError(f"{label} hardware identity hash does not match raw files")

    retrieval = load_json_object(bundle_dir / binding["retrieval_file"], f"{label} retrieval")
    quality = load_json_object(bundle_dir / binding["quality_file"], f"{label} quality")
    benchmark = load_json_object(bundle_dir / binding["benchmark_file"], f"{label} benchmark")
    if any(
        report.get("run_id") != binding["run_id"]
        for report in (retrieval, quality, benchmark)
    ):
        raise ValueError(f"{label} bundle reports do not share the bound run-id")
    if retrieval.get("quality_gate", {}).get("passed") is not True:
        raise ValueError(f"{label} retrieval gate did not pass")
    if quality.get("passed") is not True:
        raise ValueError(f"{label} Agent quality gate did not pass")
    if not (
        retrieval.get("suite_version")
        == quality.get("suite_version")
        == benchmark.get("suite_version")
        == OFFICIAL_SUITE_VERSION
    ):
        raise ValueError(f"{label} retrieval, quality and benchmark suite versions differ")
    if not (
        retrieval.get("suite_sha256")
        == quality.get("suite_sha256")
        == benchmark.get("suite_sha256")
        == OFFICIAL_SUITE_SHA256
    ):
        raise ValueError(
            f"{label} retrieval, quality and benchmark must use the official suite hash"
        )
    if not (
        retrieval.get("policy_corpus_sha256")
        == quality.get("policy_corpus_sha256")
        == benchmark.get("policy_corpus_sha256")
    ) or not SHA256_RE.fullmatch(
        str(retrieval.get("policy_corpus_sha256", ""))
    ):
        raise ValueError(f"{label} policy corpus hashes differ or are invalid")
    quality_request_configuration = validate_request_configuration(
        quality, f"{label} quality"
    )
    benchmark_request_configuration = validate_request_configuration(
        benchmark, f"{label} benchmark"
    )
    if quality_request_configuration != benchmark_request_configuration:
        raise ValueError(
            f"{label} quality and benchmark request configurations differ"
        )
    validate_request_configuration_evidence(quality, f"{label} quality")
    validate_request_configuration_evidence(benchmark, f"{label} benchmark")
    expected_provenance = {
        "commit": binding["commit"],
        "project_tree": binding["project_tree"],
        "source_tree_sha256": binding["source_tree_sha256"],
    }
    for report_name, report in (
        ("retrieval", retrieval),
        ("quality", quality),
        ("benchmark", benchmark),
    ):
        provenance = report.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError(f"{label} {report_name} provenance is missing")
        for field, expected_value in expected_provenance.items():
            if provenance.get(field) != expected_value:
                raise ValueError(f"{label} {report_name} provenance mismatch: {field}")
    if benchmark.get("quality_report", {}).get("sha256") != binding["quality_sha256"]:
        raise ValueError(f"{label} benchmark is not bound to the bundled quality report")
    if benchmark.get("quality_report", {}).get("total_score") != quality.get(
        "metrics", {}
    ).get("total_score"):
        raise ValueError(f"{label} benchmark quality score does not match raw quality evidence")
    for report_name, report in (("quality", quality), ("benchmark", benchmark)):
        artifacts = report.get("artifacts") or {}
        if artifacts.get("model_file_sha256") != binding["model_sha256"]:
            raise ValueError(f"{label} {report_name} model hash mismatch")
        if artifacts.get("llama_server_sha256") != binding["llama_server_sha256"]:
            raise ValueError(f"{label} {report_name} llama-server hash mismatch")

    monitor = load_key_value_evidence(bundle_dir / binding["monitor_file"])
    server = load_key_value_evidence(bundle_dir / binding["server_log"])
    if (
        monitor.get("run_id") != binding["run_id"]
        or monitor.get("status") != "complete"
        or monitor.get("schema_version") != "1"
    ):
        raise ValueError(f"{label} monitor evidence is incomplete")
    if (
        server.get("evidence_run_id") != binding["run_id"]
        or server.get("evidence_log_status") != "complete"
        or server.get("llama_server_exit_code") not in {"0", "143"}
    ):
        raise ValueError(f"{label} server evidence is incomplete")
    if server.get("model_sha256_at_start") != binding["model_sha256"]:
        raise ValueError(f"{label} server startup model hash mismatch")
    if server.get("llama_server_sha256_at_start") != binding["llama_server_sha256"]:
        raise ValueError(f"{label} server startup binary hash mismatch")
    try:
        monitor_interval = float(monitor["interval_seconds"])
        completed_samples = int(monitor["completed_samples"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} monitor has invalid sample metadata") from exc
    if not math.isfinite(monitor_interval) or not 0 < monitor_interval <= 5:
        raise ValueError(f"{label} monitor interval must be at most 5 seconds")
    if completed_samples < 2:
        raise ValueError(f"{label} monitor must contain at least two samples")
    retrieval_window = (
        _parse_utc_instant(retrieval.get("started_at_utc"), f"{label} retrieval start"),
        _parse_utc_instant(retrieval.get("completed_at_utc"), f"{label} retrieval end"),
    )
    quality_window = (
        _parse_utc_instant(quality.get("started_at_utc"), f"{label} quality start"),
        _parse_utc_instant(quality.get("completed_at_utc"), f"{label} quality end"),
    )
    benchmark_window = (
        _parse_utc_instant(benchmark.get("started_at_utc"), f"{label} benchmark start"),
        _parse_utc_instant(benchmark.get("completed_at_utc"), f"{label} benchmark end"),
    )
    server_window = (
        _parse_utc_instant(server.get("server_started_at_utc"), f"{label} server start"),
        _parse_utc_instant(server.get("server_completed_at_utc"), f"{label} server end"),
    )
    monitor_window = (
        _parse_utc_instant(monitor.get("started_at_utc"), f"{label} monitor start"),
        _parse_utc_instant(monitor.get("completed_at_utc"), f"{label} monitor end"),
    )
    if not (
        server_window[0]
        <= retrieval_window[0]
        <= retrieval_window[1]
        <= quality_window[0]
        <= quality_window[1]
        <= benchmark_window[0]
        <= benchmark_window[1]
        <= server_window[1]
    ):
        raise ValueError(f"{label} server does not cover ordered evaluation windows")
    quality_model = quality.get("model")
    if not isinstance(quality_model, dict):
        raise ValueError(f"{label} quality report has invalid model metadata")
    expected_model_alias = quality_model.get("name")
    expected_model_base_url = quality_model.get("base_url")
    if not isinstance(expected_model_alias, str) or not expected_model_alias:
        raise ValueError(f"{label} quality report has no model alias")
    if not isinstance(expected_model_base_url, str) or not expected_model_base_url:
        raise ValueError(f"{label} quality report has no model endpoint")
    if not (
        server.get("model_alias")
        == benchmark.get("model_name")
        == expected_model_alias
    ):
        raise ValueError(f"{label} server and evaluation model aliases differ")
    if not (
        server.get("model_base_url")
        == benchmark.get("model_base_url")
        == expected_model_base_url
    ):
        raise ValueError(f"{label} server and evaluation model endpoints differ")
    return runtime_gpu_summary(
        bundle_dir / binding["server_log"],
        bundle_dir / binding["monitor_file"],
        label,
        required_windows={
            "agent_quality": quality_window,
            "agent_benchmark": benchmark_window,
        },
        expected_run_id=binding["run_id"],
        expected_sample_count=completed_samples,
        maximum_sample_gap_seconds=max(5.0, monitor_interval * 3.0),
        coverage_window=(retrieval_window[0], benchmark_window[1]),
        declared_monitor_window=monitor_window,
        require_device_identity=True,
    )


def validate_binding(
    report: dict[str, Any],
    report_path: Path,
    binding_path: Path,
    binding: dict[str, str],
    label: str,
) -> dict[str, Any]:
    runtime_summary = validate_bundle(binding_path, binding, label)
    expected = {
        "run_id": report["run_id"],
        "benchmark_sha256": file_sha256(report_path),
        "quality_sha256": str(report["quality_report"].get("sha256")),
        "model_sha256": str(report["artifacts"].get("model_file_sha256")),
        "llama_server_sha256": str(report["artifacts"].get("llama_server_sha256")),
        "commit": str(report["provenance"].get("commit")),
        "project_tree": str(report["provenance"].get("project_tree")),
        "source_tree_sha256": str(report["provenance"].get("source_tree_sha256")),
    }
    for field, value in expected.items():
        if binding.get(field) != value:
            raise ValueError(f"{label} binding mismatch: {field}")
    bundled_report = report_path.parent / binding["benchmark_file"]
    if report_path.expanduser().resolve() != bundled_report.resolve():
        raise ValueError(f"{label} benchmark must be read from its complete evidence bundle")
    return runtime_summary


def require_integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 3)


def require_close(actual: Any, expected: float, field: str, *, tolerance: float) -> None:
    number = require_number(actual, field)
    if not math.isclose(number, expected, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(f"{field} is inconsistent with raw request evidence")


def validate_official_report(payload: dict[str, Any], label: str) -> None:
    if payload.get("suite_version") != OFFICIAL_SUITE_VERSION:
        raise ValueError(f"{label} report has an unexpected suite version")
    if payload.get("suite_sha256") != OFFICIAL_SUITE_SHA256:
        raise ValueError(f"{label} report is not bound to the official suite")
    if tuple(payload.get("case_ids") or ()) != OFFICIAL_CASE_IDS:
        raise ValueError(f"{label} report has unexpected knowledge case IDs")
    request_configuration = validate_request_configuration(payload, label)
    validate_request_configuration_evidence(payload, label)
    if request_configuration["schema_constrained"] is not True:
        raise ValueError(f"{label} report must use schema-constrained model requests")

    configuration = payload["configuration"]
    repetitions = require_integer(
        configuration.get("repetitions"),
        f"{label}.configuration.repetitions",
        minimum=MIN_OFFICIAL_REPETITIONS,
    )
    require_integer(
        configuration.get("warmup"),
        f"{label}.configuration.warmup",
        minimum=MIN_OFFICIAL_WARMUP,
    )
    if tuple(configuration.get("concurrency") or ()) != OFFICIAL_CONCURRENCY:
        raise ValueError(f"{label} report must contain concurrency 1,2,4")
    if configuration.get("min_success_rate") != 1.0:
        raise ValueError(f"{label} report must require 100% request success")
    citation_threshold = require_number(
        configuration.get("min_citation_hit_rate"),
        f"{label}.configuration.min_citation_hit_rate",
    )
    if citation_threshold < 0.95 or citation_threshold > 1.0:
        raise ValueError(f"{label} report must require citation hit rate >= 0.95")

    expected_case_ids = list(OFFICIAL_CASE_IDS) * repetitions
    if payload.get("request_case_ids") != expected_case_ids:
        raise ValueError(f"{label} request_case_ids do not match repetitions")
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or len(raw_runs) != len(OFFICIAL_CONCURRENCY):
        raise ValueError(f"{label} report must contain exactly three concurrency runs")
    if tuple(run.get("concurrency") for run in raw_runs if isinstance(run, dict)) != (
        OFFICIAL_CONCURRENCY
    ):
        raise ValueError(f"{label} raw run order must be concurrency 1,2,4")

    request_ids: set[str] = set()
    for run in raw_runs:
        concurrency = run["concurrency"]
        requests = run.get("requests")
        if not isinstance(requests, list) or len(requests) != len(expected_case_ids):
            raise ValueError(f"{label} concurrency {concurrency} has an invalid workload size")
        if [row.get("case_id") for row in requests if isinstance(row, dict)] != expected_case_ids:
            raise ValueError(f"{label} concurrency {concurrency} workload order is invalid")

        successful: list[dict[str, Any]] = []
        latencies: list[float] = []
        model_calls: list[dict[str, Any]] = []
        citation_hits = 0
        for index, row in enumerate(requests):
            if not isinstance(row, dict) or type(row.get("ok")) is not bool:
                raise ValueError(f"{label} concurrency {concurrency} request {index} is invalid")
            request_id = row.get("request_id")
            if not isinstance(request_id, str) or not request_id or request_id in request_ids:
                raise ValueError(f"{label} contains a missing or duplicate request_id")
            request_ids.add(request_id)
            wall_ms = require_number(
                row.get("wall_ms"),
                f"{label}.c{concurrency}.requests[{index}].wall_ms",
            )
            if not row["ok"]:
                continue
            if type(row.get("citation_hit")) is not bool:
                raise ValueError(f"{label} request {request_id} has invalid citation_hit")
            backend = row.get("model_backend")
            if (
                not isinstance(backend, str)
                or "llama.cpp-rocm" not in backend
                or "deterministic-development" in backend
            ):
                raise ValueError(f"{label} request {request_id} did not use the ROCm model path")
            calls = row.get("model_calls")
            if not isinstance(calls, list) or not calls:
                raise ValueError(f"{label} request {request_id} has no model-call evidence")
            if not all(isinstance(call, dict) for call in calls):
                raise ValueError(f"{label} request {request_id} has invalid model-call evidence")
            if any(
                call.get("thinking_enabled")
                != request_configuration["thinking_enabled"]
                for call in calls
            ):
                raise ValueError(
                    f"{label} request {request_id} has inconsistent thinking configuration"
                )
            if any(
                type(call.get("schema_constrained")) is not bool
                or call["schema_constrained"]
                != request_configuration["schema_constrained"]
                for call in calls
            ):
                raise ValueError(
                    f"{label} request {request_id} has inconsistent schema configuration"
                )
            if request_configuration["schema_constrained"] and any(
                call.get("response_format") != "json_schema" for call in calls
            ):
                raise ValueError(
                    f"{label} request {request_id} was not schema constrained"
                )
            successful.append(row)
            latencies.append(wall_ms)
            citation_hits += int(row["citation_hit"])
            model_calls.extend(calls)

        summary = run.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing summary")
        successful_count = len(successful)
        success_rate = successful_count / len(requests)
        citation_rate = citation_hits / successful_count if successful_count else 0.0
        if summary.get("requests") != len(requests):
            raise ValueError(f"{label} concurrency {concurrency} request count mismatch")
        if summary.get("successful") != successful_count:
            raise ValueError(f"{label} concurrency {concurrency} success count mismatch")
        require_close(
            summary.get("success_rate"),
            round(success_rate, 6),
            f"{label}.c{concurrency}.success_rate",
            tolerance=1e-6,
        )
        require_close(
            summary.get("citation_hit_rate"),
            round(citation_rate, 6),
            f"{label}.c{concurrency}.citation_hit_rate",
            tolerance=1e-6,
        )
        latency = summary.get("latency_ms")
        if not isinstance(latency, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing latency_ms")
        for field, expected in (
            ("p50", percentile(latencies, 0.50)),
            ("p95", percentile(latencies, 0.95)),
            ("min", round(min(latencies), 3) if latencies else 0.0),
            ("max", round(max(latencies), 3) if latencies else 0.0),
        ):
            require_close(
                latency.get(field),
                expected,
                f"{label}.c{concurrency}.latency_ms.{field}",
                tolerance=1e-3,
            )

        successful_calls = [call for call in model_calls if call.get("ok") is True]
        failed_calls = [call for call in model_calls if call.get("ok") is not True]
        effective_rates = [
            require_number(
                call.get("effective_output_tokens_per_second"),
                f"{label}.c{concurrency}.model_call.effective_rate",
            )
            for call in successful_calls
        ]
        server_decode_rates = [
            require_number(
                call["server_decode_tokens_per_second"],
                f"{label}.c{concurrency}.model_call.server_decode_rate",
            )
            for call in successful_calls
            if call.get("server_decode_tokens_per_second") is not None
        ]
        ttft_values = [
            require_number(
                call["ttft_ms"],
                f"{label}.c{concurrency}.model_call.ttft_ms",
            )
            for call in successful_calls
            if call.get("ttft_ms") is not None
        ]
        if any(rate <= 0 for rate in effective_rates):
            raise ValueError(f"{label} concurrency {concurrency} has a non-positive token rate")
        model_metrics = summary.get("model_call_metrics")
        if not isinstance(model_metrics, dict):
            raise ValueError(f"{label} concurrency {concurrency} has no model_call_metrics")
        expected_counts = {
            "calls": len(model_calls),
            "successful_calls": len(successful_calls),
            "failed_calls": len(failed_calls),
            "effective_rate_sample_count": len(effective_rates),
        }
        for field, expected in expected_counts.items():
            if model_metrics.get(field) != expected:
                raise ValueError(f"{label} concurrency {concurrency} {field} mismatch")
        require_close(
            model_metrics.get("effective_rate_coverage"),
            1.0 if successful_calls else 0.0,
            f"{label}.c{concurrency}.effective_rate_coverage",
            tolerance=1e-6,
        )
        for field, expected in (
            ("effective_output_tokens_per_second_p50", percentile(effective_rates, 0.50)),
            ("effective_output_tokens_per_second_p95", percentile(effective_rates, 0.95)),
        ):
            require_close(
                model_metrics.get(field),
                expected,
                f"{label}.c{concurrency}.{field}",
                tolerance=1e-3,
            )
        for count_field, coverage_field, values, metric_fields in (
            (
                "server_decode_rate_sample_count",
                "server_decode_rate_coverage",
                server_decode_rates,
                (
                    "server_decode_tokens_per_second_p50",
                    "server_decode_tokens_per_second_p95",
                ),
            ),
            (
                "ttft_sample_count",
                "ttft_coverage",
                ttft_values,
                ("ttft_ms_p50", "ttft_ms_p95"),
            ),
        ):
            if model_metrics.get(count_field) != len(values):
                raise ValueError(f"{label} concurrency {concurrency} {count_field} mismatch")
            expected_coverage = (
                round(len(values) / len(successful_calls), 6)
                if successful_calls
                else 0.0
            )
            require_close(
                model_metrics.get(coverage_field),
                expected_coverage,
                f"{label}.c{concurrency}.{coverage_field}",
                tolerance=1e-6,
            )
            expected_values = (
                (percentile(values, 0.50), percentile(values, 0.95))
                if values
                else (None, None)
            )
            for metric_field, expected in zip(
                metric_fields, expected_values, strict=True
            ):
                observed = model_metrics.get(metric_field)
                if expected is None:
                    if observed is not None:
                        raise ValueError(
                            f"{label} concurrency {concurrency} has {metric_field} without samples"
                        )
                else:
                    require_close(
                        observed,
                        expected,
                        f"{label}.c{concurrency}.{metric_field}",
                        tolerance=1e-3,
                    )

        wall_seconds = require_number(
            summary.get("wall_seconds"), f"{label}.c{concurrency}.wall_seconds"
        )
        if wall_seconds <= 0:
            raise ValueError(f"{label} concurrency {concurrency} has invalid wall_seconds")
        require_close(
            summary.get("offered_throughput_requests_per_second"),
            round(len(requests) / wall_seconds, 6),
            f"{label}.c{concurrency}.offered_throughput",
            tolerance=1e-6,
        )
        require_close(
            summary.get("successful_throughput_requests_per_second"),
            round(successful_count / wall_seconds, 6),
            f"{label}.c{concurrency}.successful_throughput",
            tolerance=1e-6,
        )
        if success_rate < 1.0 or citation_rate < citation_threshold or failed_calls:
            raise ValueError(f"{label} concurrency {concurrency} fails the official quality gate")

    quality_gate = payload["quality_gate"]
    if quality_gate.get("failures") != []:
        raise ValueError(f"{label} report claims pass but contains gate failures")
    expected_thresholds = {
        "min_success_rate": configuration["min_success_rate"],
        "min_citation_hit_rate": configuration["min_citation_hit_rate"],
    }
    if quality_gate.get("thresholds") != expected_thresholds:
        raise ValueError(f"{label} quality thresholds do not match configuration")


def load_report(path: Path, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {label} report: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} report must contain one JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{label} report must use schema_version {SCHEMA_VERSION}")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{label} report is missing run_id")
    quality_gate = payload.get("quality_gate")
    if not isinstance(quality_gate, dict) or quality_gate.get("passed") is not True:
        raise ValueError(f"{label} report quality_gate must be passed")
    if not isinstance(payload.get("model_name"), str) or not payload["model_name"]:
        raise ValueError(f"{label} report is missing model_name")
    if not isinstance(payload.get("cases_path"), str) or not payload["cases_path"]:
        raise ValueError(f"{label} report is missing cases_path")
    if not isinstance(payload.get("suite_sha256"), str) or not payload["suite_sha256"]:
        raise ValueError(f"{label} report is missing suite_sha256")
    if not SHA256_RE.fullmatch(str(payload.get("policy_corpus_sha256", ""))):
        raise ValueError(f"{label} report has an invalid policy_corpus_sha256")
    if not isinstance(payload.get("case_ids"), list) or not payload["case_ids"]:
        raise ValueError(f"{label} report is missing case_ids")
    if not isinstance(payload.get("request_case_ids"), list) or not payload["request_case_ids"]:
        raise ValueError(f"{label} report is missing request_case_ids")
    validate_request_configuration(payload, label)
    for field in ("configuration", "provenance", "artifacts", "quality_report"):
        if not isinstance(payload.get(field), dict):
            raise ValueError(f"{label} report is missing {field}")
    if payload["quality_report"].get("passed") is not True:
        raise ValueError(f"{label} report is not bound to a passing quality report")
    validate_official_report(payload, label)
    return payload


def indexed_runs(report: dict[str, Any], label: str) -> dict[int, dict[str, Any]]:
    raw_runs = report.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError(f"{label} report must contain at least one run")
    result: dict[int, dict[str, Any]] = {}
    for index, run in enumerate(raw_runs):
        if not isinstance(run, dict):
            raise ValueError(f"{label} runs[{index}] must be an object")
        concurrency = run.get("concurrency")
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError(f"{label} runs[{index}].concurrency must be a positive integer")
        if concurrency in result:
            raise ValueError(f"{label} report repeats concurrency {concurrency}")
        summary = run.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing summary")
        latency = summary.get("latency_ms")
        if not isinstance(latency, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing latency_ms")
        require_number(latency.get("p50"), f"{label}.c{concurrency}.latency_ms.p50")
        require_number(latency.get("p95"), f"{label}.c{concurrency}.latency_ms.p95")
        require_number(
            summary.get("successful_throughput_requests_per_second"),
            f"{label}.c{concurrency}.successful_throughput_requests_per_second",
        )
        result[concurrency] = run
    return result


def token_rates(
    run: dict[str, Any],
    label: str,
    concurrency: int,
) -> dict[str, float]:
    summary = run["summary"]
    model_call_metrics = summary.get("model_call_metrics")
    if not isinstance(model_call_metrics, dict):
        raise ValueError(
            f"{label} concurrency {concurrency} model_call_metrics must be an object"
        )
    sample_count = model_call_metrics.get("effective_rate_sample_count")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
        raise ValueError(
            f"{label} concurrency {concurrency} has no effective token-rate samples"
        )
    present = [field for field in TOKEN_RATE_FIELDS if field in model_call_metrics]
    if len(present) != len(TOKEN_RATE_FIELDS):
        missing = sorted(set(TOKEN_RATE_FIELDS) - set(present))
        raise ValueError(
            f"{label} concurrency {concurrency} is missing token-rate fields: {missing}"
        )
    return {
        field: require_number(
            model_call_metrics[field],
            f"{label}.c{concurrency}.model_call_metrics.{field}",
        )
        for field in TOKEN_RATE_FIELDS
    }


def optional_metrics(
    run: dict[str, Any],
    label: str,
    concurrency: int,
    count_field: str,
    fields: tuple[str, ...],
) -> dict[str, float] | None:
    model_metrics = run["summary"].get("model_call_metrics")
    if not isinstance(model_metrics, dict):
        raise ValueError(f"{label} concurrency {concurrency} has no model_call_metrics")
    sample_count = model_metrics.get(count_field)
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 0:
        raise ValueError(f"{label} concurrency {concurrency} has invalid {count_field}")
    if sample_count == 0:
        if any(model_metrics.get(field) is not None for field in fields):
            raise ValueError(f"{label} concurrency {concurrency} has metrics without samples")
        return None
    return {
        field: require_number(
            model_metrics.get(field),
            f"{label}.c{concurrency}.model_call_metrics.{field}",
        )
        for field in fields
    }


def compare_metric(
    baseline: float,
    optimized: float,
    *,
    lower_is_better: bool,
    material_threshold_percent: float,
) -> dict[str, Any]:
    absolute_delta = optimized - baseline
    if baseline == 0:
        improvement_percent: float | None = None
    elif lower_is_better:
        improvement_percent = ((baseline - optimized) / baseline) * 100
    else:
        improvement_percent = ((optimized - baseline) / baseline) * 100
    rounded_improvement = (
        round(improvement_percent, 3) if improvement_percent is not None else None
    )
    return {
        "baseline": round(baseline, 6),
        "optimized": round(optimized, 6),
        "absolute_delta_optimized_minus_baseline": round(absolute_delta, 6),
        "improvement_percent": rounded_improvement,
        "direction": "lower_is_better" if lower_is_better else "higher_is_better",
        "material_improvement": bool(
            improvement_percent is not None
            and improvement_percent >= material_threshold_percent
        ),
        "material_regression": bool(
            improvement_percent is not None
            and improvement_percent <= -material_threshold_percent
        ),
    }


def validate_pair(
    baseline: dict[str, Any],
    optimized: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    if baseline["run_id"] == optimized["run_id"]:
        raise ValueError("Baseline and optimized reports must use different run_id values")
    if baseline["model_name"] != optimized["model_name"]:
        raise ValueError("Baseline and optimized reports must use the same model_name")
    if baseline.get("model_base_url") != optimized.get("model_base_url"):
        raise ValueError("Baseline and optimized reports must use the same model endpoint")
    if baseline["policy_corpus_sha256"] != optimized["policy_corpus_sha256"]:
        raise ValueError("Baseline and optimized reports must use the same policy corpus")
    for field in ("commit", "project_tree", "source_tree_sha256"):
        if baseline["provenance"].get(field) != optimized["provenance"].get(field):
            raise ValueError(f"Baseline and optimized provenance must match {field}")
    for field in (
        "suite_version",
        "suite_sha256",
        "case_ids",
        "request_case_ids",
        "configuration",
    ):
        if baseline[field] != optimized[field]:
            raise ValueError(f"Baseline and optimized reports must match {field}")
    baseline_request_configuration = validate_request_configuration(
        baseline, "baseline"
    )
    optimized_request_configuration = validate_request_configuration(
        optimized, "optimized"
    )
    baseline_bound_configuration = {
        key: value
        for key, value in baseline_request_configuration.items()
        if key != "thinking_enabled"
    }
    optimized_bound_configuration = {
        key: value
        for key, value in optimized_request_configuration.items()
        if key != "thinking_enabled"
    }
    if baseline_bound_configuration != optimized_bound_configuration:
        raise ValueError(
            "Baseline and optimized request configurations may differ only in "
            "thinking_enabled"
        )
    for field in ("model_file_sha256", "llama_server_sha256"):
        if baseline["artifacts"].get(field) != optimized["artifacts"].get(field):
            raise ValueError(f"Baseline and optimized artifacts must match {field}")
    for report, label in ((baseline, "baseline"), (optimized, "optimized")):
        require_number(
            report["quality_report"].get("total_score"),
            f"{label}.quality_report.total_score",
        )
    baseline_thresholds = baseline["quality_gate"].get("thresholds")
    optimized_thresholds = optimized["quality_gate"].get("thresholds")
    if baseline_thresholds != optimized_thresholds:
        raise ValueError("Baseline and optimized reports must use the same quality thresholds")
    baseline_runs = indexed_runs(baseline, "baseline")
    optimized_runs = indexed_runs(optimized, "optimized")
    if set(baseline_runs) != set(optimized_runs):
        raise ValueError("Baseline and optimized reports must contain the same concurrency levels")
    for concurrency in baseline_runs:
        baseline_requests = baseline_runs[concurrency].get("requests")
        optimized_requests = optimized_runs[concurrency].get("requests")
        if not isinstance(baseline_requests, list) or not isinstance(optimized_requests, list):
            raise ValueError(f"Concurrency {concurrency} is missing raw request rows")
        baseline_case_ids = [row.get("case_id") for row in baseline_requests]
        optimized_case_ids = [row.get("case_id") for row in optimized_requests]
        if baseline_case_ids != optimized_case_ids:
            raise ValueError(f"Concurrency {concurrency} request workloads do not match")
        baseline_summary = baseline_runs[concurrency]["summary"]
        optimized_summary = optimized_runs[concurrency]["summary"]
        baseline_model_metrics = baseline_summary["model_call_metrics"]
        optimized_model_metrics = optimized_summary["model_call_metrics"]
        for metric in ("success_rate", "citation_hit_rate"):
            require_number(
                baseline_summary.get(metric), f"baseline.c{concurrency}.{metric}"
            )
            require_number(
                optimized_summary.get(metric), f"optimized.c{concurrency}.{metric}"
            )
        for count_field in (
            "successful_calls",
            "effective_rate_sample_count",
            "server_decode_rate_sample_count",
            "ttft_sample_count",
        ):
            if baseline_model_metrics.get(count_field) != optimized_model_metrics.get(
                count_field
            ):
                raise ValueError(
                    f"Baseline and optimized {count_field} differ at concurrency {concurrency}"
                )
    return baseline_runs, optimized_runs


def build_comparison(
    baseline: dict[str, Any],
    optimized: dict[str, Any],
    *,
    material_threshold_percent: float,
) -> dict[str, Any]:
    baseline_runs, optimized_runs = validate_pair(baseline, optimized)
    comparisons: list[dict[str, Any]] = []
    materially_improved: list[str] = []
    materially_improved_core: list[str] = []
    materially_regressed: list[str] = []
    materially_regressed_core: list[str] = []
    quality_regressions: list[dict[str, Any]] = []
    optional_timing_complete = {"server_decode": True, "ttft": True}
    baseline_quality_score = require_number(
        baseline["quality_report"].get("total_score"),
        "baseline.quality_report.total_score",
    )
    optimized_quality_score = require_number(
        optimized["quality_report"].get("total_score"),
        "optimized.quality_report.total_score",
    )
    if optimized_quality_score < baseline_quality_score:
        quality_regressions.append(
            {
                "metric": "quality_report.total_score",
                "baseline": baseline_quality_score,
                "optimized": optimized_quality_score,
            }
        )

    for concurrency in sorted(baseline_runs):
        baseline_run = baseline_runs[concurrency]
        optimized_run = optimized_runs[concurrency]
        baseline_summary = baseline_run["summary"]
        optimized_summary = optimized_run["summary"]
        for quality_metric in ("success_rate", "citation_hit_rate"):
            baseline_quality_value = require_number(
                baseline_summary.get(quality_metric),
                f"baseline.c{concurrency}.{quality_metric}",
            )
            optimized_quality_value = require_number(
                optimized_summary.get(quality_metric),
                f"optimized.c{concurrency}.{quality_metric}",
            )
            if optimized_quality_value < baseline_quality_value:
                quality_regressions.append(
                    {
                        "metric": f"c{concurrency}.{quality_metric}",
                        "baseline": baseline_quality_value,
                        "optimized": optimized_quality_value,
                    }
                )
        metrics = {
            "latency_p50_ms": compare_metric(
                require_number(
                    baseline_summary["latency_ms"]["p50"],
                    f"baseline.c{concurrency}.latency_ms.p50",
                ),
                require_number(
                    optimized_summary["latency_ms"]["p50"],
                    f"optimized.c{concurrency}.latency_ms.p50",
                ),
                lower_is_better=True,
                material_threshold_percent=material_threshold_percent,
            ),
            "latency_p95_ms": compare_metric(
                require_number(
                    baseline_summary["latency_ms"]["p95"],
                    f"baseline.c{concurrency}.latency_ms.p95",
                ),
                require_number(
                    optimized_summary["latency_ms"]["p95"],
                    f"optimized.c{concurrency}.latency_ms.p95",
                ),
                lower_is_better=True,
                material_threshold_percent=material_threshold_percent,
            ),
            "successful_throughput_requests_per_second": compare_metric(
                require_number(
                    baseline_summary["successful_throughput_requests_per_second"],
                    f"baseline.c{concurrency}.successful_throughput",
                ),
                require_number(
                    optimized_summary["successful_throughput_requests_per_second"],
                    f"optimized.c{concurrency}.successful_throughput",
                ),
                lower_is_better=False,
                material_threshold_percent=material_threshold_percent,
            ),
        }
        baseline_tokens = token_rates(baseline_run, "baseline", concurrency)
        optimized_tokens = token_rates(optimized_run, "optimized", concurrency)
        for field in TOKEN_RATE_FIELDS:
            metrics[field] = compare_metric(
                baseline_tokens[field],
                optimized_tokens[field],
                lower_is_better=False,
                material_threshold_percent=material_threshold_percent,
            )
        for count_field, fields, lower_is_better in OPTIONAL_METRIC_GROUPS:
            baseline_optional = optional_metrics(
                baseline_run,
                "baseline",
                concurrency,
                count_field,
                fields,
            )
            optimized_optional = optional_metrics(
                optimized_run,
                "optimized",
                concurrency,
                count_field,
                fields,
            )
            if (baseline_optional is None) != (optimized_optional is None):
                raise ValueError(
                    f"Optional timing evidence differs at concurrency {concurrency}: "
                    f"{count_field}"
                )
            for field in fields:
                if baseline_optional is None:
                    group_name = (
                        "server_decode"
                        if count_field == "server_decode_rate_sample_count"
                        else "ttft"
                    )
                    optional_timing_complete[group_name] = False
                    metrics[field] = {
                        "status": "unavailable",
                        "reason": "pinned local model response did not expose this timing",
                    }
                else:
                    assert optimized_optional is not None
                    metrics[field] = compare_metric(
                        baseline_optional[field],
                        optimized_optional[field],
                        lower_is_better=lower_is_better,
                        material_threshold_percent=material_threshold_percent,
                    )

        for metric_name, result in metrics.items():
            if result.get("material_improvement"):
                qualified_name = f"c{concurrency}.{metric_name}"
                materially_improved.append(qualified_name)
                if metric_name in CORE_METRIC_NAMES:
                    materially_improved_core.append(qualified_name)
            if result.get("material_regression"):
                qualified_name = f"c{concurrency}.{metric_name}"
                materially_regressed.append(qualified_name)
                if metric_name in CORE_METRIC_NAMES:
                    materially_regressed_core.append(qualified_name)
        comparisons.append({"concurrency": concurrency, "metrics": metrics})

    core_evidence_complete = True
    full_timing_evidence_complete = all(optional_timing_complete.values())
    core_material_improvement_observed = bool(materially_improved_core)
    quality_not_regressed = not quality_regressions
    accepted = bool(
        core_evidence_complete
        and core_material_improvement_observed
        and not materially_regressed_core
        and quality_not_regressed
    )
    rejection_reasons: list[str] = []
    if not core_material_improvement_observed:
        rejection_reasons.append("no_core_metric_met_material_threshold")
    if materially_regressed_core:
        rejection_reasons.append("core_material_regression_observed")
    if not quality_not_regressed:
        rejection_reasons.append("quality_regression_observed")

    return {
        "schema_version": 1,
        "comparison": "radeonstay-baseline-vs-optimized",
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "baseline": {
            "run_id": baseline["run_id"],
            "model_name": baseline["model_name"],
            "cases_path": baseline["cases_path"],
            "suite_sha256": baseline["suite_sha256"],
            "source_tree_sha256": baseline["provenance"].get("source_tree_sha256"),
            "quality_report_sha256": baseline["quality_report"].get("sha256"),
        },
        "optimized": {
            "run_id": optimized["run_id"],
            "model_name": optimized["model_name"],
            "cases_path": optimized["cases_path"],
            "suite_sha256": optimized["suite_sha256"],
            "source_tree_sha256": optimized["provenance"].get("source_tree_sha256"),
            "quality_report_sha256": optimized["quality_report"].get("sha256"),
        },
        "matched_artifacts": {
            "policy_corpus_sha256": baseline["policy_corpus_sha256"],
            "model_file_sha256": baseline["artifacts"].get("model_file_sha256"),
            "llama_server_sha256": baseline["artifacts"].get("llama_server_sha256"),
        },
        "request_configuration": {
            "baseline": dict(baseline["request_configuration"]),
            "optimized": dict(optimized["request_configuration"]),
            "allowed_difference": ["thinking_enabled"],
        },
        "quality_thresholds": baseline["quality_gate"].get("thresholds"),
        "material_threshold_percent": material_threshold_percent,
        "comparisons": comparisons,
        "assessment": {
            "status": "accepted" if accepted else "not_accepted",
            "accepted": accepted,
            "optimization_winner": "optimized" if accepted else "not_accepted",
            "acceptance_criteria": {
                "minimum_core_improvement_percent": material_threshold_percent,
                "at_least_one_core_metric_improved": (
                    core_material_improvement_observed
                ),
                "no_material_core_metric_regression": not materially_regressed_core,
                "quality_not_regressed": quality_not_regressed,
            },
            "rejection_reasons": rejection_reasons,
            "core_evidence_complete": core_evidence_complete,
            "full_timing_evidence_complete": full_timing_evidence_complete,
            "optional_timing_evidence": optional_timing_complete,
            "missing_effective_token_rate_concurrency": [],
            "materially_improved_metrics": materially_improved,
            "materially_improved_core_metrics": materially_improved_core,
            "materially_regressed_metrics": materially_regressed,
            "materially_regressed_core_metrics": materially_regressed_core,
            "material_improvement_observed": core_material_improvement_observed,
            "quality_regressions": quality_regressions,
            "note": (
                "Acceptance requires a material core improvement, no material core "
                "metric regression, and no quality regression across bound evidence."
            ),
        },
    }


def comparison_exit_code(report: dict[str, Any], *, require_accepted: bool) -> int:
    accepted = report.get("assessment", {}).get("accepted")
    if type(accepted) is not bool:
        raise ValueError("Comparison report is missing assessment.accepted")
    return 1 if require_accepted and not accepted else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    threshold = require_number(
        args.material_threshold_percent,
        "material-threshold-percent",
    )
    if threshold <= 0 or threshold > 100:
        raise ValueError("material-threshold-percent must be greater than 0 and at most 100")
    baseline_path = args.baseline.expanduser().resolve()
    optimized_path = args.optimized.expanduser().resolve()
    baseline_binding_path = args.baseline_binding.expanduser().resolve()
    optimized_binding_path = args.optimized_binding.expanduser().resolve()
    if baseline_path == optimized_path:
        raise ValueError("Baseline and optimized paths must be different")
    output_path = args.output.expanduser().resolve()
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"Output parent does not exist: {output_path.parent}")

    baseline = load_report(baseline_path, "baseline")
    optimized = load_report(optimized_path, "optimized")
    baseline_binding = load_binding(baseline_binding_path, "baseline")
    optimized_binding = load_binding(optimized_binding_path, "optimized")
    baseline_runtime_summary = validate_binding(
        baseline,
        baseline_path,
        baseline_binding_path,
        baseline_binding,
        "baseline",
    )
    optimized_runtime_summary = validate_binding(
        optimized,
        optimized_path,
        optimized_binding_path,
        optimized_binding,
        "optimized",
    )
    if (
        baseline_binding.get("hardware_identity_sha256")
        != optimized_binding.get("hardware_identity_sha256")
    ):
        raise ValueError("Baseline and optimized evidence must use the same hardware identity")
    if (
        baseline_runtime_summary.get("common_active_gpu_indices")
        != optimized_runtime_summary.get("common_active_gpu_indices")
    ):
        raise ValueError("Baseline and optimized evidence must use the same active GPU indices")
    if (
        baseline_runtime_summary.get("common_active_gpu_unique_ids")
        != optimized_runtime_summary.get("common_active_gpu_unique_ids")
    ):
        raise ValueError("Baseline and optimized evidence must use the same physical GPUs")
    baseline_server_configuration = load_server_configuration(
        baseline_binding_path.parent / baseline_binding["server_log"]
    )
    optimized_server_configuration = load_server_configuration(
        optimized_binding_path.parent / optimized_binding["server_log"]
    )
    if baseline_server_configuration["ctx"] != optimized_server_configuration["ctx"]:
        raise ValueError("Baseline and optimized evidence must use the same context size")
    report = build_comparison(
        baseline,
        optimized,
        material_threshold_percent=threshold,
    )
    report["evidence_binding"] = {
        "baseline_manifest": str(baseline_binding_path),
        "optimized_manifest": str(optimized_binding_path),
        "hardware_identity_sha256": baseline_binding.get("hardware_identity_sha256"),
        "baseline_server_configuration": baseline_server_configuration,
        "optimized_server_configuration": optimized_server_configuration,
        "baseline_runtime_gpu_evidence": baseline_runtime_summary,
        "optimized_runtime_gpu_evidence": optimized_runtime_summary,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "assessment": report["assessment"]["status"],
                "accepted": report["assessment"]["accepted"],
                "optimization_winner": report["assessment"]["optimization_winner"],
            }
        )
    )
    return comparison_exit_code(report, require_accepted=args.require_accepted)


if __name__ == "__main__":
    raise SystemExit(main())
