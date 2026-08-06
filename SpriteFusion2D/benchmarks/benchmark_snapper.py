"""Device-native Pixel Snapper benchmark with auditable JSON receipts.

The measured quantity is the full wall-clock time of one :func:`snap_images`
call, including any host-to-device transfer of the input, with a device
synchronization on both sides of every timed run.  This preserves the
project's original timing convention.  ``--exclude-host-to-device`` opts into
device-resident timing for micro-benchmarks.

Every run produces a versioned JSON receipt (``benchmarks.receipt``) that
records raw samples, standard-library statistics, input/output/core source
hashes, git state, failure records, and sanitized command lines by default.
"""

from __future__ import annotations

import argparse
import platform
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import torch
from PIL import Image

from pixel_snapper_core import SnapConfig, runtime_description, snap_images

if __package__ in (None, ""):
    # Direct script execution (python benchmarks/benchmark_snapper.py) does
    # not put the repository root on sys.path; add it so the sibling receipt
    # module and the flat pixel_snapper_core module resolve like -m mode.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.receipt import (  # noqa: E402
    build_receipt,
    compute_sample_stats,
    format_failure,
    git_repo_state,
    hash_source_files,
    receipt_dumps,
    sanitize_command,
    tensor_fingerprint,
    validate_receipt,
    write_receipt,
)

CORE_SOURCE_FILES = ("pixel_snapper_core.py", "pixel_snapper_node.py")
TOOLING_SOURCE_FILES = ("benchmarks/receipt.py", "benchmarks/benchmark_snapper.py")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the device-native Pixel Snapper pipeline and "
        "write a versioned JSON receipt."
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--algorithm",
        choices=("optimized", "legacy_exact"),
        default="optimized",
    )
    parser.add_argument("--colors", type=int, default=32)
    parser.add_argument("--pixel-size", type=float, default=6.0)
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument(
        "--warmup",
        type=_non_negative_int,
        default=1,
        help="warm-up runs executed before measurement (default: 1)",
    )
    parser.add_argument(
        "--runs",
        type=_positive_int,
        default=3,
        help="measured runs recorded as raw samples (default: 3)",
    )
    parser.add_argument("--synthetic-size", type=int, default=1024)
    parser.add_argument(
        "--receipt",
        type=Path,
        help="write the JSON receipt to this file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the JSON receipt to stdout",
    )
    parser.add_argument(
        "--no-sanitize",
        action="store_true",
        help="record absolute paths and the working directory verbatim",
    )
    parser.add_argument(
        "--exclude-host-to-device",
        action="store_true",
        help="move the input to the device before timing (default timing "
        "includes host-to-device transfer)",
    )
    return parser.parse_args(argv)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def load_input(path: Path | None, synthetic_size: int) -> torch.Tensor:
    if path is None:
        generator = torch.Generator().manual_seed(2026)
        return torch.rand((1, synthetic_size, synthetic_size, 3), generator=generator)

    with Image.open(path) as source:
        rgb = source.convert("RGB")
        storage = torch.frombuffer(bytearray(rgb.tobytes()), dtype=torch.uint8)
        image = storage.reshape(rgb.height, rgb.width, 3)
    return image.to(torch.float32).div_(255.0).unsqueeze(0)


def synchronize(device: torch.device) -> None:
    """Block until all queued work on ``device`` completes (no-op on CPU)."""

    if device.type == "cuda":
        torch.cuda.synchronize(device)


def reset_peak_memory(device: torch.device) -> None:
    if device.type == "cuda":
        try:
            torch.cuda.reset_peak_memory_stats(device)
        except Exception:
            pass


def read_peak_memory(device: torch.device) -> int | None:
    if device.type == "cuda":
        try:
            return int(torch.cuda.max_memory_allocated(device))
        except Exception:
            return None
    return None


def save_output(path: Path, image: torch.Tensor) -> None:
    pixels = image[0].mul(255).round().to(torch.uint8).cpu().numpy()
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode="RGB").save(path)


def make_measured_call(
    image: torch.Tensor,
    config: SnapConfig,
    *,
    device: torch.device,
    include_host_to_device: bool,
) -> tuple[Callable[[], list[torch.Tensor]], dict[str, Any]]:
    """Return the timed call plus a shared state dict with the last output.

    With ``include_host_to_device`` (the default) the CPU input is handed to
    ``snap_images`` unchanged, so the wall-clock sample covers the transfer.
    Otherwise the input is moved to the device once before timing.
    """

    state: dict[str, Any] = {"last_output": None}
    if include_host_to_device:
        input_for_call = image
    else:
        input_for_call = image.to(device)

    def call() -> list[torch.Tensor]:
        frames = snap_images(input_for_call, config, device=device)
        state["last_output"] = frames
        return frames

    return call, state


def measure_benchmark(
    fn: Callable[[], list[torch.Tensor]],
    *,
    warmup_runs: int,
    runs: int,
    device: torch.device,
    clock: Callable[[], float] = perf_counter,
    sync: Callable[[], None] | None = None,
    repo_root: Path | None = None,
    sanitize: bool = True,
) -> tuple[list[float], list[Mapping[str, Any]], int | None]:
    """Run warm-up and measured runs with synchronization boundaries.

    ``sync`` is invoked immediately before and after every warm-up and
    measured run, so GPU samples never include work still queued from a
    previous iteration.  A failure aborts the phase it occurred in, records a
    failure record, and leaves partial samples in the receipt.
    """

    sync_call = sync if sync is not None else (lambda: synchronize(device))
    reset_peak_memory(device)
    failures: list[Mapping[str, Any]] = []

    for _warmup_index in range(warmup_runs):
        sync_call()
        try:
            fn()
        except Exception as exception:  # noqa: BLE001 - recorded, not swallowed
            sync_call()
            failures.append(
                {
                    **format_failure(
                        exception,
                        repo_root=repo_root,
                        sanitize=sanitize,
                    ),
                    "run_index": _warmup_index,
                    "phase": "warmup",
                }
            )
            return [], failures, read_peak_memory(device)
        sync_call()

    samples: list[float] = []
    for run_index in range(runs):
        sync_call()
        started = clock()
        try:
            fn()
        except Exception as exception:  # noqa: BLE001 - recorded, not swallowed
            sync_call()
            failures.append(
                {
                    **format_failure(
                        exception,
                        repo_root=repo_root,
                        sanitize=sanitize,
                    ),
                    "run_index": run_index,
                    "phase": "measure",
                }
            )
            break
        elapsed = clock() - started
        sync_call()
        samples.append(elapsed)

    return samples, failures, read_peak_memory(device)


def environment_snapshot(
    *,
    requested_device: torch.device | None,
    selected_device: torch.device,
    sanitized: bool,
    working_dir: Path,
) -> dict[str, Any]:
    gpu: dict[str, Any] | None = None
    if selected_device.type == "cuda" and torch.cuda.is_available():
        try:
            properties = torch.cuda.get_device_properties(selected_device)
            gpu = {
                "name": torch.cuda.get_device_name(selected_device),
                "memory_total_bytes": int(properties.total_memory),
                "capability": f"{properties.major}.{properties.minor}",
            }
        except Exception:
            gpu = {"name": "unavailable"}
    return {
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda if torch.cuda.is_available() else None,
        "device": {
            "requested": "auto" if requested_device is None else str(requested_device),
            "selected": str(selected_device),
            "type": selected_device.type,
        },
        "gpu": gpu,
        "working_dir": None if sanitized else str(working_dir),
    }


def run_benchmark(args: argparse.Namespace, argv: Sequence[str] = ()) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parent.parent
    sanitized = not args.no_sanitize

    requested_device = None if args.device == "auto" else torch.device(args.device)
    selected_device = (
        requested_device
        if requested_device is not None
        else torch.device("cuda" if torch.cuda.is_available() else "cpu")
    )
    include_host_to_device = not args.exclude_host_to_device

    image = load_input(args.input, args.synthetic_size)
    config = SnapConfig(
        algorithm=args.algorithm,
        k_colors=args.colors,
        pixel_size_override=args.pixel_size,
        max_kmeans_iterations=args.iterations,
    )
    measured_call, state = make_measured_call(
        image,
        config,
        device=selected_device,
        include_host_to_device=include_host_to_device,
    )

    samples, failures, peak_memory = measure_benchmark(
        measured_call,
        warmup_runs=args.warmup,
        runs=args.runs,
        device=selected_device,
        repo_root=repo_root,
        sanitize=sanitized,
    )

    frames = state["last_output"] or []
    input_entry: dict[str, Any] = {
        "role": "image",
        "source": "synthetic" if args.input is None else "file",
        "path": None,
    }
    if args.input is not None:
        input_entry["path"] = (
            Path(args.input).name if sanitized else str(Path(args.input).resolve())
        )
    input_entry.update(tensor_fingerprint(image))

    output_entries = [
        {
            "role": f"frame_{index}",
            **tensor_fingerprint(frame),
        }
        for index, frame in enumerate(frames)
    ]

    sources = [
        {"role": "core", **entry}
        for entry in hash_source_files(repo_root, CORE_SOURCE_FILES)
    ] + [
        {"role": "tooling", **entry}
        for entry in hash_source_files(repo_root, TOOLING_SOURCE_FILES)
    ]

    timing = {
        "warmup_runs": args.warmup,
        "runs": args.runs,
        "include_host_to_device": include_host_to_device,
        "synchronize": {"before_each_run": True, "after_each_run": True},
        "samples_seconds": samples,
        "stats": compute_sample_stats(samples).to_dict(),
        "peak_memory_bytes": peak_memory,
    }

    command = tuple(
        sanitize_command(
            [sys.executable, "-m", "benchmarks.benchmark_snapper", *argv],
            repo_root=repo_root,
        )
        if sanitized
        else [sys.executable, "-m", "benchmarks.benchmark_snapper", *argv]
    )

    receipt = build_receipt(
        benchmark={
            "name": "snapper",
            "algorithm": args.algorithm,
            "config": asdict(config),
        },
        command=command,
        environment=environment_snapshot(
            requested_device=requested_device,
            selected_device=selected_device,
            sanitized=sanitized,
            working_dir=Path.cwd(),
        ),
        sources=sources,
        inputs=[input_entry],
        outputs=output_entries,
        timing=timing,
        failures=failures,
        git=git_repo_state(repo_root).to_dict(),
        sanitized=sanitized,
    )
    validate_receipt(receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.argv = list(sys.argv[1:] if argv is None else argv)
    receipt = run_benchmark(args, argv=args.argv)

    samples = receipt["timing"]["samples_seconds"]
    stats = receipt["timing"]["stats"]
    frames = receipt["outputs"]
    selected_device = torch.device(receipt["environment"]["device"]["selected"])

    print(f"runtime: {runtime_description(selected_device)}")
    print(f"algorithm: {receipt['benchmark']['algorithm']}")
    print(f"input: {tuple(receipt['inputs'][0]['shape'])}")
    print(f"output: {[tuple(frame['shape']) for frame in frames]}")
    print(f"seconds: {', '.join(f'{value:.4f}' for value in samples)}")
    median = stats["median_seconds"]
    print(
        f"median_seconds: {median:.4f}" if median is not None else "median_seconds: n/a"
    )
    print(f"warmup_runs: {receipt['timing']['warmup_runs']}")
    print(f"runs: {receipt['timing']['runs']}")
    print(f"status: {receipt['status']}")

    if args.json:
        print(receipt_dumps(receipt), end="")
    if args.receipt is not None:
        write_receipt(receipt, args.receipt)
        print(f"receipt: {args.receipt}")
    return 0 if receipt["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
