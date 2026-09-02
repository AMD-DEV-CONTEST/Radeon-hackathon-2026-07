"""Measure one command with timestamped Radeon/ROCm telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import time


ROCM_SMI_COMMAND = [
    "rocm-smi",
    "--showuse",
    "--showmemuse",
    "--showmeminfo",
    "vram",
    "--showpower",
    "--json",
]


def _number(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return None


def parse_rocm_sample(payload: dict, elapsed_s: float) -> dict:
    """Normalize the first card reported by rocm-smi."""
    cards = [value for key, value in payload.items() if key.startswith("card")]
    if not cards:
        raise ValueError("rocm-smi JSON did not contain a card")
    card = cards[0]
    return {
        "elapsed_s": elapsed_s,
        "gpu_use_percent": _number(card.get("GPU use (%)")),
        "vram_allocated_percent": _number(
            card.get("GPU Memory Allocated (VRAM%)")
        ),
        "vram_used_bytes": _number(card.get("VRAM Total Used Memory (B)")),
        "vram_total_bytes": _number(card.get("VRAM Total Memory (B)")),
        "power_watts": _number(card.get("Average Graphics Package Power (W)")),
        "memory_activity_percent": _number(
            card.get("GPU Memory Read/Write Activity (%)")
        ),
    }


def _summarize(values: list[float | None]) -> dict | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return {
        "mean": statistics.fmean(numeric),
        "peak": max(numeric),
        "minimum": min(numeric),
    }


def summarize_samples(samples: list[dict]) -> dict:
    return {
        "sample_count": len(samples),
        "gpu_use_percent": _summarize(
            [sample["gpu_use_percent"] for sample in samples]
        ),
        "vram_allocated_percent": _summarize(
            [sample["vram_allocated_percent"] for sample in samples]
        ),
        "vram_used_bytes": _summarize(
            [sample["vram_used_bytes"] for sample in samples]
        ),
        "vram_total_bytes": (
            samples[-1]["vram_total_bytes"] if samples else None
        ),
        "power_watts": _summarize(
            [sample["power_watts"] for sample in samples]
        ),
        "memory_activity_percent": _summarize(
            [sample["memory_activity_percent"] for sample in samples]
        ),
    }


def _read_sample(elapsed_s: float) -> dict:
    completed = subprocess.run(
        ROCM_SMI_COMMAND,
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_rocm_sample(json.loads(completed.stdout), elapsed_s)


def measure_command(
    *,
    command: list[str],
    output_json: Path,
    log_path: Path,
    sample_interval_s: float,
    result_json: Path | None,
) -> dict:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    sample_errors = []
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        while process.poll() is None:
            elapsed = time.monotonic() - started
            try:
                samples.append(_read_sample(elapsed))
            except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
                sample_errors.append(
                    {"elapsed_s": elapsed, "error": f"{type(error).__name__}: {error}"}
                )
            time.sleep(sample_interval_s)
        returncode = process.wait()
    wall_time_s = time.monotonic() - started
    result = {
        "schema_version": 1,
        "command": command,
        "returncode": returncode,
        "wall_time_s": wall_time_s,
        "sample_interval_s": sample_interval_s,
        "summary": summarize_samples(samples),
        "samples": samples,
        "sample_errors": sample_errors,
        "command_log": str(log_path),
    }
    if result_json is not None and result_json.is_file():
        pipeline = json.loads(result_json.read_text(encoding="utf-8"))
        trials = pipeline.get("trials")
        if isinstance(trials, list):
            steps = sum(
                int(trial.get("recorded_control_steps", 0))
                for trial in trials
            )
            frames = sum(
                int(trial.get("recorded_video_frames", 0))
                for trial in trials
            )
            transport_success = (
                pipeline.get("successful_trials")
                == pipeline.get("attempted_trials")
            )
        else:
            steps = pipeline.get("recorded_control_steps")
            frames = pipeline.get("recorded_video_frames")
            transport_success = pipeline.get("transport_success")
        result["pipeline_result"] = {
            "path": str(result_json),
            "transport_success": transport_success,
            "recorded_control_steps": steps,
            "recorded_video_frames": frames,
            "control_steps_per_wall_second": (
                float(steps) / wall_time_s if steps is not None else None
            ),
        }
    output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one command while sampling Radeon telemetry with rocm-smi"
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--result-json", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    if args.sample_interval <= 0:
        parser.error("--sample-interval must be positive")
    result = measure_command(
        command=command,
        output_json=args.output_json,
        log_path=args.log,
        sample_interval_s=args.sample_interval,
        result_json=args.result_json,
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(result["returncode"])


if __name__ == "__main__":
    main()
