"""Append-only ROCm GPU telemetry collected with ``rocm-smi``.

The collector deliberately treats unavailable and malformed values as missing.
It never substitutes zero for a metric that ``rocm-smi`` did not report.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import signal
import statistics
import subprocess
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any, Protocol


METRIC_NAMES = (
    "gpu_use_percent",
    "vram_used_bytes",
    "vram_total_bytes",
    "vram_used_percent",
    "memory_activity_percent",
    "power_watts",
    "temperature_celsius",
    "sclk_mhz",
    "mclk_mhz",
)

_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_DEVICE_NAME = re.compile(
    r"^(?:card|gpu|device)(?:[-_ ]?\d+|\[\d+\])$",
    re.IGNORECASE,
)
_MISSING_VALUES = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "nan",
    "none",
    "not available",
    "not supported",
    "unsupported",
    "unknown",
}


class Runner(Protocol):
    """Callable used to inject a fake ``rocm-smi`` in tests."""

    def __call__(self, command: Sequence[str]) -> Any: ...


@dataclass(frozen=True)
class ParsedRocmSmi:
    """Normalized result of parsing one structured ``rocm-smi`` response."""

    output_format: str | None
    devices: list[dict[str, Any]]
    errors: list[str]


@dataclass(frozen=True)
class _CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None = None


def build_rocm_smi_command(
    executable: str = "rocm-smi",
    *,
    output_format: str = "json",
) -> tuple[str, ...]:
    """Build the structured query used for each sample."""

    if output_format not in {"json", "csv"}:
        raise ValueError("output_format must be 'json' or 'csv'")
    return (
        executable,
        "--showuse",
        "--showmemuse",
        "--showmeminfo",
        "vram",
        "--showpower",
        "--showtemp",
        "--showclocks",
        f"--{output_format}",
    )


def _normalized_label(label: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", str(label).lower()).split())


def _metric_for_label(label: str) -> str | None:
    normalized = _normalized_label(label)
    words = set(normalized.split())

    if "sclk" in words or "system clock" in normalized or "graphics clock" in normalized:
        return "sclk_mhz"
    if "mclk" in words or "memory clock" in normalized:
        return "mclk_mhz"
    if "temperature" in normalized or re.search(r"\btemp\b", normalized):
        return "temperature_celsius"
    if "power" in words:
        if {"cap", "limit", "maximum"} & words or "max power" in normalized:
            return None
        return "power_watts"

    is_percent = "%" in normalized or "percent" in words or "percentage" in words
    if "vram" in normalized:
        if {"used", "use", "usage", "allocated"} & words:
            return "vram_used_percent" if is_percent else "vram_used_bytes"
        if "total" in words:
            return "vram_total_bytes"

    memory_activity_phrases = (
        "memory activity",
        "mem activity",
        "memory busy",
        "mem busy",
        "memory controller utilization",
        "memory controller use",
    )
    if any(phrase in normalized for phrase in memory_activity_phrases):
        return "memory_activity_percent"

    if "memory" in words and {"allocated", "used", "usage"} & words:
        if is_percent:
            return "vram_used_percent"

    if "gpu" in words and not ({"memory", "vram"} & words):
        if {"use", "usage", "utilization", "activity", "busy"} & words:
            return "gpu_use_percent"
    return None


def _flatten_mapping(
    mapping: Mapping[object, Any],
    *,
    prefix: str = "",
) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in mapping.items():
        label = f"{prefix} {key}".strip()
        if isinstance(value, Mapping):
            flattened.update(_flatten_mapping(value, prefix=label))
        else:
            flattened[label] = value
    return flattened


def _looks_like_metric_mapping(mapping: Mapping[object, Any]) -> bool:
    return any(_metric_for_label(label) is not None for label in _flatten_mapping(mapping))


def _device_from_fields(fields: Mapping[str, Any], fallback: str) -> str:
    for label, value in fields.items():
        normalized = _normalized_label(label)
        if normalized in {"device", "device id", "card", "gpu", "gpu id"}:
            text = str(value).strip()
            if text:
                return text
    return fallback


def _extract_json_rows(
    value: Any,
    *,
    device_hint: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(value, list):
        rows: list[tuple[str, dict[str, Any]]] = []
        for index, item in enumerate(value):
            hint = device_hint or f"gpu{index}"
            rows.extend(_extract_json_rows(item, device_hint=hint))
        return rows
    if not isinstance(value, Mapping):
        return []

    device_children = [
        (str(key).strip(), item)
        for key, item in value.items()
        if _DEVICE_NAME.fullmatch(str(key).strip()) and isinstance(item, (Mapping, list))
    ]
    if device_children:
        rows: list[tuple[str, dict[str, Any]]] = []
        for device, item in device_children:
            rows.extend(_extract_json_rows(item, device_hint=device))
        return rows

    if _looks_like_metric_mapping(value):
        raw = {str(key): item for key, item in value.items()}
        fallback = device_hint or "gpu0"
        return [(_device_from_fields(_flatten_mapping(raw), fallback), raw)]

    rows = []
    for key, item in value.items():
        if not isinstance(item, (Mapping, list)):
            continue
        key_text = str(key).strip()
        hint = key_text if _DEVICE_NAME.fullmatch(key_text) else device_hint
        rows.extend(_extract_json_rows(item, device_hint=hint))
    return rows


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in _MISSING_VALUES)


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric metric")
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        match = _NUMBER.search(value.replace(",", ""))
        if match is None:
            raise ValueError(f"no number in {value!r}")
        result = float(match.group())
    else:
        raise ValueError(f"unsupported value type {type(value).__name__}")
    if not math.isfinite(result):
        raise ValueError(f"non-finite value {value!r}")
    return result


def _unit_text(label: str, value: Any) -> str:
    return f"{label} {value}".lower().replace("µ", "u")


def _convert_metric(metric: str, label: str, value: Any) -> float:
    result = _number(value)
    unit_text = _unit_text(label, value)

    if metric in {"vram_used_bytes", "vram_total_bytes"}:
        units = (
            ("tib", 1024.0**4),
            ("gib", 1024.0**3),
            ("mib", 1024.0**2),
            ("kib", 1024.0),
            ("tb", 1000.0**4),
            ("gb", 1000.0**3),
            ("mb", 1000.0**2),
            ("kb", 1000.0),
        )
        for unit, multiplier in units:
            if re.search(rf"(?<![a-z]){unit}\b", unit_text):
                return result * multiplier
        return result

    if metric in {"sclk_mhz", "mclk_mhz"}:
        if re.search(r"(?<![a-z])ghz\b", unit_text):
            return result * 1000.0
        if re.search(r"(?<![a-z])khz\b", unit_text):
            return result / 1000.0
        if re.search(r"(?<![a-z])hz\b", unit_text):
            return result / 1_000_000.0
        return result

    if metric == "power_watts":
        if re.search(r"(?<![a-z])mw\b", unit_text):
            return result / 1000.0
        if re.search(r"(?<![a-z])kw\b", unit_text):
            return result * 1000.0
        return result

    if metric == "temperature_celsius" and re.search(
        r"(?<![a-z])f(?:ahrenheit)?\b",
        unit_text,
    ):
        return (result - 32.0) * (5.0 / 9.0)
    return result


def _normalize_device(
    device: str,
    raw: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    metrics: dict[str, float | None] = dict.fromkeys(METRIC_NAMES)
    flattened = _flatten_mapping(raw)
    for label, value in flattened.items():
        metric = _metric_for_label(label)
        if metric is None or _is_missing(value):
            continue
        try:
            converted = _convert_metric(metric, label, value)
        except ValueError as exc:
            errors.append(f"{device}: cannot parse {label!r}={value!r}: {exc}")
            continue
        current = metrics[metric]
        if current is None:
            metrics[metric] = converted
        elif metric == "temperature_celsius":
            metrics[metric] = max(current, converted)

    used = metrics["vram_used_bytes"]
    total = metrics["vram_total_bytes"]
    if metrics["vram_used_percent"] is None and used is not None and total is not None:
        if total > 0:
            metrics["vram_used_percent"] = used * 100.0 / total
        else:
            errors.append(f"{device}: cannot derive VRAM percentage from non-positive total")

    return {
        "device": device,
        "metrics": metrics,
        "raw": _json_safe(dict(raw)),
    }


def _parse_json(text: str) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        return [], f"JSON decode failed: {exc}"
    rows = _extract_json_rows(payload)
    if not rows:
        return [], "JSON contained no recognizable GPU metric records"
    return rows, None


def _parse_csv(text: str) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
    lines = [line for line in text.splitlines() if line.strip()]
    header_index: int | None = None
    for index, line in enumerate(lines):
        if "," not in line:
            continue
        labels = next(csv.reader([line]))
        if any(
            _normalized_label(label) in {"device", "card", "gpu", "gpu id"}
            or _metric_for_label(label) is not None
            for label in labels
        ):
            header_index = index
            break
    if header_index is None:
        return [], "CSV header containing GPU metrics was not found"

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    rows: list[tuple[str, dict[str, Any]]] = []
    for index, row in enumerate(reader):
        raw = {
            str(key).strip(): value.strip() if isinstance(value, str) else value
            for key, value in row.items()
            if key is not None
        }
        if not any(value not in {None, ""} for value in raw.values()):
            continue
        rows.append((_device_from_fields(raw, f"gpu{index}"), raw))
    if not rows:
        return [], "CSV contained a header but no GPU metric records"
    return rows, None


def parse_rocm_smi_output(
    output: str,
    *,
    format_hint: str | None = None,
) -> ParsedRocmSmi:
    """Parse ROCm SMI JSON or CSV while retaining all malformed-field errors."""

    if format_hint not in {None, "json", "csv"}:
        raise ValueError("format_hint must be None, 'json', or 'csv'")
    text = output.strip()
    if not text:
        return ParsedRocmSmi(None, [], ["rocm-smi produced empty stdout"])

    attempts = (
        [format_hint, "csv" if format_hint == "json" else "json"]
        if format_hint is not None
        else (["json", "csv"] if text.startswith(("{", "[")) else ["csv", "json"])
    )
    parse_errors: list[str] = []
    rows: list[tuple[str, dict[str, Any]]] = []
    parsed_format: str | None = None
    for candidate in attempts:
        if candidate == "json":
            rows, error = _parse_json(text)
        else:
            rows, error = _parse_csv(text)
        if rows:
            parsed_format = candidate
            break
        if error is not None:
            parse_errors.append(error)

    if not rows:
        return ParsedRocmSmi(None, [], parse_errors)

    field_errors: list[str] = []
    devices = [_normalize_device(device, raw, field_errors) for device, raw in rows]
    return ParsedRocmSmi(parsed_format, devices, parse_errors + field_errors)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _coerce_runner_result(result: Any) -> _CommandResult:
    if isinstance(result, Mapping):
        returncode = result.get("returncode")
        stdout = result.get("stdout")
        stderr = result.get("stderr")
    else:
        returncode = getattr(result, "returncode", None)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
    if returncode is not None:
        returncode = int(returncode)
    return _CommandResult(returncode, _text(stdout), _text(stderr))


def _send_process_signal(process: subprocess.Popen[str], signum: int) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signum)
    except (AttributeError, PermissionError, ProcessLookupError):
        try:
            process.send_signal(signum)
        except ProcessLookupError:
            pass


def _terminate_and_collect(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float,
) -> tuple[str, str]:
    _send_process_signal(process, signal.SIGTERM)
    try:
        return process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        _send_process_signal(process, signal.SIGKILL)
        return process.communicate()


class RocmTelemetry:
    """Periodic ``rocm-smi`` sampler writing one durable JSON object per line."""

    def __init__(
        self,
        output: str | Path,
        *,
        job: str,
        stage: str,
        interval: float = 1.0,
        command: Sequence[str] | None = None,
        output_format: str = "json",
        runner: Runner | None = None,
        command_timeout: float = 10.0,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if command_timeout <= 0:
            raise ValueError("command_timeout must be positive")
        if not job:
            raise ValueError("job must not be empty")
        if not stage:
            raise ValueError("stage must not be empty")
        if command is not None and not command:
            raise ValueError("command must not be empty")

        self.output = Path(output)
        self.job = job
        self.interval = float(interval)
        self.command_timeout = float(command_timeout)
        self.command = tuple(command or build_rocm_smi_command(output_format=output_format))
        self.output_format = output_format
        self.runner = runner

        self._stage = stage
        self._stage_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_process: subprocess.Popen[str] | None = None
        self._thread_error: BaseException | None = None
        self._closed = False

    @property
    def stage(self) -> str:
        with self._stage_lock:
            return self._stage

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def set_stage(self, stage: str) -> None:
        if not stage:
            raise ValueError("stage must not be empty")
        with self._stage_lock:
            self._stage = stage

    def start(self) -> RocmTelemetry:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("telemetry collector is closed")
            if self._thread is not None:
                return self
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self._thread = threading.Thread(
                target=self._run_loop,
                name="rocm-telemetry",
                daemon=True,
            )
            self._thread.start()
        return self

    def _execute_default(self) -> _CommandResult:
        try:
            process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            return _CommandResult(None, "", "", f"{type(exc).__name__}: {exc}")

        with self._process_lock:
            self._active_process = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=self.command_timeout)
                return _CommandResult(process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                stdout, stderr = _terminate_and_collect(process, grace_seconds=0.5)
                return _CommandResult(
                    process.returncode,
                    stdout,
                    stderr,
                    f"rocm-smi timed out after {self.command_timeout:g} seconds",
                )
        finally:
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None

    def _execute(self) -> _CommandResult:
        if self.runner is None:
            return self._execute_default()
        try:
            return _coerce_runner_result(self.runner(self.command))
        except BaseException as exc:
            return _CommandResult(None, "", "", f"{type(exc).__name__}: {exc}")

    def sample_once(self) -> dict[str, Any]:
        with self._state_lock:
            if self._closed and threading.current_thread() is not self._thread:
                raise RuntimeError("telemetry collector is closed")

        wall_time_ns = time.time_ns()
        monotonic_ns = time.monotonic_ns()
        result = self._execute()
        duration_ns = time.monotonic_ns() - monotonic_ns

        errors: list[str] = []
        if result.error is not None:
            errors.append(result.error)
        if result.returncode not in {None, 0}:
            errors.append(f"rocm-smi exited with status {result.returncode}")

        if result.stdout:
            parsed = parse_rocm_smi_output(result.stdout, format_hint=self.output_format)
            errors.extend(parsed.errors)
        else:
            parsed = ParsedRocmSmi(None, [], [])
            if result.error is None:
                errors.append("rocm-smi produced empty stdout")

        record = {
            "schema_version": 1,
            "kind": "rocm_smi_sample",
            "wall_time_ns": wall_time_ns,
            "wall_time_utc": datetime.fromtimestamp(wall_time_ns / 1e9, UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "monotonic_ns": monotonic_ns,
            "duration_ns": duration_ns,
            "job": self.job,
            "stage": self.stage,
            "command": list(self.command),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "parse_format": parsed.output_format,
            "parse_errors": errors,
            "devices": parsed.devices,
        }
        encoded = json.dumps(_json_safe(record), sort_keys=True, allow_nan=False)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.output.open("a", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
        return record

    def _run_loop(self) -> None:
        next_sample = time.monotonic()
        try:
            while not self._stop_event.is_set():
                self.sample_once()
                next_sample += self.interval
                delay = next_sample - time.monotonic()
                if delay <= 0:
                    next_sample = time.monotonic()
                    continue
                if self._stop_event.wait(delay):
                    return
        except BaseException as exc:
            self._thread_error = exc
            self._stop_event.set()

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        self._stop_event.set()
        with self._process_lock:
            process = self._active_process
        if process is not None:
            _send_process_signal(process, signal.SIGTERM)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.command_timeout + 2.0)
            if thread.is_alive():
                raise RuntimeError("telemetry collector did not stop")
        if self._thread_error is not None:
            raise RuntimeError("telemetry collector failed") from self._thread_error

    stop = close

    def __enter__(self) -> RocmTelemetry:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool:
        try:
            self.close()
        except BaseException:
            if exc_type is None:
                raise
        return False


ROCmTelemetry = RocmTelemetry


def _metric_statistics(values: list[float]) -> dict[str, int | float | None]:
    if not values:
        return {
            "samples": 0,
            "mean": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "samples": len(ordered),
        "mean": statistics.fmean(ordered),
        "p50": statistics.median(ordered),
        "p95": ordered[p95_index],
        "max": ordered[-1],
    }


def _read_records(
    source: str | Path | Iterable[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    if not isinstance(source, (str, Path)):
        return list(source), []
    records: list[Mapping[str, Any]] = []
    errors: list[str] = []
    with Path(source).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: {exc}")
                continue
            if not isinstance(record, Mapping):
                errors.append(f"line {line_number}: JSON value is not an object")
                continue
            records.append(record)
    return records, errors


def summarize_rocm_telemetry(
    source: str | Path | Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize all finite per-device metrics in telemetry records."""

    records, summary_errors = _read_records(source)
    values: dict[str, list[float]] = {name: [] for name in METRIC_NAMES}
    devices: set[str] = set()
    device_samples = 0
    parse_error_count = 0

    for record in records:
        record_errors = record.get("parse_errors")
        if isinstance(record_errors, list):
            parse_error_count += len(record_errors)
        raw_devices = record.get("devices", [])
        if not isinstance(raw_devices, list):
            continue
        for device in raw_devices:
            if not isinstance(device, Mapping):
                continue
            device_samples += 1
            if device.get("device") is not None:
                devices.add(str(device["device"]))
            metrics = device.get("metrics", device)
            if not isinstance(metrics, Mapping):
                continue
            for name in METRIC_NAMES:
                value = metrics.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                numeric = float(value)
                if math.isfinite(numeric):
                    values[name].append(numeric)

    metrics = {name: _metric_statistics(metric_values) for name, metric_values in values.items()}
    return {
        "records": len(records),
        "device_samples": device_samples,
        "devices": sorted(devices),
        "parse_error_count": parse_error_count,
        "summary_errors": summary_errors,
        "metrics": metrics,
        "peak_vram_used_bytes": metrics["vram_used_bytes"]["max"],
        "average_power_watts": metrics["power_watts"]["mean"],
        "peak_power_watts": metrics["power_watts"]["max"],
        "maximum_temperature_celsius": metrics["temperature_celsius"]["max"],
    }


summary = summarize_rocm_telemetry


def _wait_for_child(
    process: subprocess.Popen[Any],
    *,
    termination_state: dict[str, float | int | None],
) -> int:
    while True:
        returncode = process.poll()
        if returncode is not None:
            return int(returncode)
        deadline = termination_state["deadline"]
        if isinstance(deadline, float) and time.monotonic() >= deadline:
            _send_process_signal(process, signal.SIGKILL)
            termination_state["deadline"] = None
        time.sleep(0.05)


def _stop_child(process: subprocess.Popen[Any], grace_seconds: float) -> None:
    if process.poll() is not None:
        return
    _send_process_signal(process, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        _send_process_signal(process, signal.SIGKILL)
        process.wait()


def run_with_rocm_telemetry(
    command: Sequence[str],
    *,
    output: str | Path,
    job: str,
    stage: str,
    interval: float = 1.0,
    telemetry_command: Sequence[str] | None = None,
    output_format: str = "json",
    runner: Runner | None = None,
    command_timeout: float = 10.0,
    termination_grace: float = 5.0,
) -> int:
    """Run a child process with telemetry and forward SIGINT/SIGTERM safely."""

    if not command:
        raise ValueError("command must not be empty")
    if termination_grace <= 0:
        raise ValueError("termination_grace must be positive")

    collector = RocmTelemetry(
        output,
        job=job,
        stage=stage,
        interval=interval,
        command=telemetry_command,
        output_format=output_format,
        runner=runner,
        command_timeout=command_timeout,
    )
    process: subprocess.Popen[Any] | None = None
    previous_handlers: dict[int, Any] = {}
    termination_state: dict[str, float | int | None] = {
        "signal": None,
        "deadline": None,
    }

    def forward_signal(signum: int, _frame: FrameType | None) -> None:
        termination_state["signal"] = signum
        termination_state["deadline"] = time.monotonic() + termination_grace
        if process is not None:
            _send_process_signal(process, signum)

    with collector:
        try:
            process = subprocess.Popen(tuple(command), start_new_session=True)
            if threading.current_thread() is threading.main_thread():
                for signum in (signal.SIGINT, signal.SIGTERM):
                    previous_handlers[signum] = signal.getsignal(signum)
                    signal.signal(signum, forward_signal)
            return _wait_for_child(process, termination_state=termination_state)
        finally:
            if process is not None:
                _stop_child(process, termination_grace)
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
