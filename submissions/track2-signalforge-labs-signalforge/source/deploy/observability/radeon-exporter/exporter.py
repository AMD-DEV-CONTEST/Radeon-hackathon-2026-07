#!/usr/bin/env python3
"""Bounded Prometheus exporter for amd-smi or rocm-smi JSON output."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

COMMANDS = (
    ("amd-smi", "metric", "--json"),
    ("rocm-smi", "--showuse", "--showmeminfo", "vram", "--showtemp", "--showpower", "--json"),
)

METRICS = {
    "utilization": ("radeon_gpu_utilization_ratio", ("gpu_use", "gpu_util", "gpu_activity"), "ratio"),
    "vram_used": ("radeon_gpu_vram_used_bytes", ("vram_used", "vram_memory_used", "vram_used_memory_b"), "bytes"),
    "vram_total": ("radeon_gpu_vram_total_bytes", ("vram_total", "vram_memory_total", "vram_total_memory_b"), "bytes"),
    "temperature": ("radeon_gpu_temperature_celsius", ("temperature", "edge_temperature", "temperature_sensor_edge_c", "temp"), "number"),
    "power": ("radeon_gpu_power_watts", ("power", "average_socket_power", "current_socket_power", "average_graphics_package_power_w"), "number"),
}


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if not match:
            return None
        result = float(match.group(0))
    else:
        return None
    return result if math.isfinite(result) else None


def flatten(value: Any, prefix: str = "") -> dict[str, float]:
    output: dict[str, float] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = "_".join(part for part in (prefix, normalize_key(str(key))) if part)
            output.update(flatten(item, next_prefix))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            output.update(flatten(item, f"{prefix}_{index}"))
    else:
        parsed = number(value)
        if parsed is not None:
            output[prefix] = parsed
    return output


def gpu_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    nested = [value for key, value in payload.items() if "gpu" in normalize_key(str(key)) and isinstance(value, dict)]
    if nested:
        return nested
    return [payload]


def matching_value(flat: dict[str, float], aliases: tuple[str, ...]) -> float | None:
    for alias in aliases:
        normalized = normalize_key(alias)
        candidates = [value for key, value in flat.items() if key == normalized or key.endswith("_" + normalized)]
        if candidates:
            return candidates[0]
    return None


def normalize_metric(value: float, unit: str, key: str) -> float:
    if unit == "ratio" and value > 1:
        return value / 100
    if unit == "bytes" and "byte" not in key and value < 1024**3:
        return value * 1024 * 1024
    return value


def parse_metrics(payload: Any) -> list[tuple[str, int, float]]:
    result: list[tuple[str, int, float]] = []
    for index, record in enumerate(gpu_records(payload)):
        flat = flatten(record)
        for _, (metric_name, aliases, unit) in METRICS.items():
            value = matching_value(flat, aliases)
            if value is None:
                continue
            source_key = next((key for key in flat if any(key.endswith(normalize_key(alias)) for alias in aliases)), "")
            result.append((metric_name, index, normalize_metric(value, unit, source_key)))
    return result


def collect() -> tuple[bool, list[tuple[str, int, float]], str]:
    for command in COMMANDS:
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=5)
            return True, parse_metrics(json.loads(completed.stdout)), command[0]
        except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
            continue
    return False, [], "unavailable"


def render() -> str:
    healthy, metrics, collector = collect()
    lines = [
        "# HELP radeon_gpu_exporter_up Whether an AMD SMI collector returned valid JSON.",
        "# TYPE radeon_gpu_exporter_up gauge",
        f'radeon_gpu_exporter_up{{collector="{collector}"}} {1 if healthy else 0}',
    ]
    seen: set[str] = set()
    for metric_name, gpu, value in metrics:
        if metric_name not in seen:
            lines.extend((f"# HELP {metric_name} Bounded Radeon device metric.", f"# TYPE {metric_name} gauge"))
            seen.add(metric_name)
        lines.append(f'{metric_name}{{gpu="{gpu}"}} {value:g}')
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/metrics"):
            self.send_error(404)
            return
        payload = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_: Any) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer((os.getenv("RADEON_EXPORTER_HOST", "127.0.0.1"), int(os.getenv("RADEON_EXPORTER_PORT", "9400"))), Handler).serve_forever()
