# Reproducible performance and exactness baseline

## Scope

These measurements verify the device-native implementation and provide a
repeatable baseline. They are not AMD performance claims: the local workstation
did not have an available ROCm device during development.

Since P01, every benchmark run also produces a versioned JSON **receipt** that
records the command, environment, source/input/output hashes, raw samples,
statistics, git state, and failures. AMD throughput evidence (P02) must be
collected as receipts on target hardware and appended below; historical local
numbers are retained for CPU/CUDA comparison and are explicitly not AMD claims.

Measurement date: 2026-08-02

- Host OS: Windows
- CPU: Intel Core i9-13900HX
- Local accelerator: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- PyTorch: 2.13.0+cu130
- CUDA runtime reported by PyTorch: 13.0
- `torch.version.hip`: `None`
- Input: 1254 x 1254 RGB, batch size 1
- Palette: 32 colors
- Explicit source pixel size: 1
- K-Means iteration limit: 20
- Protocol: one warm-up, five synchronized measured runs, median wall time

## Results

| Implementation | Device | Run times (seconds) | Median | Output |
|---|---|---:|---:|---:|
| Device-native PyTorch | CPU | 0.4417, 0.4287, 0.4305, 0.4325, 0.4377 | 0.4325 s | 1254 x 1254 |
| Device-native PyTorch | Local CUDA GPU | 0.0711, 0.0682, 0.0544, 0.0659, 0.0584 | 0.0659 s | 1254 x 1254 |
| Former NumPy implementation | CPU | historical single run | 46.24 s | 1095 x 923 |

The new local GPU run is 6.56 times faster than the new CPU run. The former
NumPy timing is retained as a migration reference only. It is not a strict
apples-to-apples benchmark because the serial walker drifted to a different
output grid, whereas an explicit pixel size of 1 now preserves 1254 x 1254.

## Benchmark receipts

`benchmarks/receipt.py` defines the versioned receipt format
(`"format": "spritefusion-benchmark-receipt"`, `"schema_version": 1`) and the
statistics contract. `benchmarks/benchmark_snapper.py` runs the pipeline and
emits a receipt. Everything below is the schema contract; do not fabricate
numbers into a receipt — a receipt is only valid if it came from a real run.

### What a receipt records

| Field | Meaning |
|---|---|
| `benchmark` | name, algorithm, and full `SnapConfig` |
| `timestamp_utc` | ISO-8601 UTC time the receipt was assembled |
| `command` | recorded command line; sanitized by default |
| `environment` | Python, PyTorch, `torch.version.hip`, CUDA availability, selected device, GPU name/memory/capability, working directory (redacted by default) |
| `sources` | SHA-256 of `pixel_snapper_core.py`, `pixel_snapper_node.py` (role `core`) and of the benchmark tooling (role `tooling`) |
| `inputs` | SHA-256 of the raw input tensor bytes, shape, dtype, source (`synthetic`/`file`) |
| `outputs` | SHA-256 of every output frame, shape, dtype |
| `timing` | warmup runs, measured runs, whether host-to-device transfer is included, sync-boundary flag, raw `samples_seconds`, statistics, peak GPU memory (when available) |
| `git` | HEAD commit, branch, dirty flag, and `git status --short` lines |
| `failures` | per-failure records (phase, run index, exception type, sanitized message and traceback) |
| `sanitized` | whether paths/user directories were scrubbed |
| `status` | `ok` or `error` (any failure record flips it to `error`) |

### Statistics contract

Raw samples are the per-run wall-clock times in seconds. Statistics come from
the Python standard library:

- median: `statistics.median`
- mean: `statistics.mean`
- min / max: builtins over raw samples
- spread: `statistics.pstdev`
- P90: nearest-rank 90th percentile (stable for very small sample counts)

Empty sample sets (for example a warm-up failure) record `null` for every
statistic.

### Timing convention

The default measured quantity is the full wall-clock time of one
`snap_images` call, **including any host-to-device transfer** of the input.
This preserves the pre-receipt behavior of `benchmark_snapper.py`. The device
is synchronized immediately before and after every warm-up and measured run,
so a GPU sample never absorbs work queued from a previous iteration. The
receipt records `timing.include_host_to_device` and
`timing.synchronize = {before_each_run, after_each_run}`.

`--exclude-host-to-device` opts into device-resident timing (the input is
moved to the device once before warm-up) for micro-benchmarks.

### Sanitization

Receipts are sanitized by default (`sanitized: true`): absolute paths outside
the repository collapse to their basename, paths inside the repository become
`<REPO_ROOT>/...`, and home directories become `<HOME>` / `<USERS_DIR>`.
`--no-sanitize` records absolute paths and the working directory verbatim.

### Failure records

A failure during warm-up aborts immediately with no samples. A failure during
a measured run aborts that run, keeps the samples collected so far, and
records the failure with `phase`, `run_index`, `exception_type`, and a
sanitized message/traceback. Any failure record makes the receipt
`status: "error"` and the CLI exits non-zero.

### Example receipt

> **Example only — synthetic values, NOT a measurement.** This document shows
> the schema shape. Real receipts are produced by `python -m
> benchmarks.benchmark_snapper`; never hand-write or embed measurements.

```json
{
  "benchmark": {
    "algorithm": "optimized",
    "config": {"k_colors": 4, "pixel_size_override": 1.0, "algorithm": "optimized"},
    "name": "snapper"
  },
  "command": ["python.exe", "-m", "benchmarks.benchmark_snapper", "--device", "cpu", "--synthetic-size", "8"],
  "environment": {
    "cuda_available": false,
    "device": {"requested": "cpu", "selected": "cpu", "type": "cpu"},
    "gpu": null,
    "hip": null,
    "python": "3.12.3",
    "torch": "2.9.1+cpu",
    "working_dir": null
  },
  "failures": [],
  "format": "spritefusion-benchmark-receipt",
  "git": {"available": true, "branch": "agent/real-backend", "commit_sha": "cfcfd54abd6c0bc3401b39444597e1ab3a0d009d", "dirty": true, "status": [" M benchmarks/benchmark_snapper.py"]},
  "inputs": [{"dtype": "torch.float32", "path": null, "role": "image", "sha256": "1b17702aef86ff15896eedb6a17233f42501153a66f11878c93e35d918f1e720", "shape": [1, 8, 8, 3], "source": "synthetic"}],
  "notes": "EXAMPLE ONLY - synthetic values, not a measurement.",
  "outputs": [{"dtype": "torch.float32", "role": "frame_0", "sha256": "cf50c7d40c657ccc9d2b0f71d0e2a32a81e8441e438c480969d1d58d38db7a6d", "shape": [1, 8, 8, 3]}],
  "sanitized": true,
  "schema_version": 1,
  "sources": [
    {"path": "pixel_snapper_core.py", "role": "core", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {"path": "pixel_snapper_node.py", "role": "core", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {"path": "benchmarks/receipt.py", "role": "tooling", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {"path": "benchmarks/benchmark_snapper.py", "role": "tooling", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
  ],
  "status": "ok",
  "timestamp_utc": "2026-08-06T00:00:00+00:00",
  "timing": {
    "include_host_to_device": true,
    "peak_memory_bytes": null,
    "runs": 3,
    "samples_seconds": [0.0100, 0.0110, 0.0105],
    "stats": {
      "max_seconds": 0.011,
      "mean_seconds": 0.0105,
      "median_seconds": 0.0105,
      "min_seconds": 0.01,
      "p90_seconds": 0.011,
      "pstdev_seconds": 0.000408248290463863
    },
    "synchronize": {"after_each_run": true, "before_each_run": true},
    "warmup_runs": 1
  }
}
```

The source hashes in the example are placeholder values and the samples are
fabricated for illustration.

## Reproduction

From the repository root:

```bash
# Human summary + JSON receipt on stdout
python -m benchmarks.benchmark_snapper \
  --input source.png \
  --device cpu \
  --colors 32 \
  --pixel-size 1 \
  --iterations 20 \
  --warmup 1 \
  --runs 5 \
  --json

# Write the receipt to a file for an audit trail
python -m benchmarks.benchmark_snapper \
  --input source.png \
  --device cpu \
  --colors 32 \
  --pixel-size 1 \
  --iterations 20 \
  --warmup 1 \
  --runs 5 \
  --receipt benchmarks/receipts/cpu-1254.json

python -m benchmarks.benchmark_snapper \
  --input source.png \
  --device cuda \
  --colors 32 \
  --pixel-size 1 \
  --iterations 20 \
  --warmup 1 \
  --runs 5 \
  --receipt benchmarks/receipts/gpu-1254.json
```

On a PyTorch ROCm build, the last command targets the AMD GPU because PyTorch
represents HIP devices with the `cuda` device type. Device timing includes the
host-to-device transfer by default; pass `--exclude-host-to-device` for
device-resident timing only. `--no-sanitize` disables path scrubbing.

## Legacy-exact 12-image matrix

Measurement date: 2026-08-03. Twelve independently generated source images
were normalized to 512 x 512 RGB. The canonical version 0.4 NumPy implementation
produced the golden PNGs. `legacy_exact` then ran three synchronized GPU trials
per image through the same public `snap_images` interface.

| Source | Exact GPU median | Old / exact speed-up | Pixel difference |
|---:|---:|---:|---:|
| 01 | 0.4420 s | 8.57x | 0 |
| 02 | 0.4341 s | 8.28x | 0 |
| 03 | 0.4264 s | 7.93x | 0 |
| 04 | 0.4243 s | 7.91x | 0 |
| 05 | 0.4453 s | 7.44x | 0 |
| 06 | 0.4467 s | 7.61x | 0 |
| 07 | 0.4084 s | 8.28x | 0 |
| 08 | 0.4274 s | 7.89x | 0 |
| 09 | 0.4414 s | 8.58x | 0 |
| 10 | 0.4448 s | 9.18x | 0 |
| 11 | 0.4462 s | 9.45x | 0 |
| 12 | 0.4488 s | 8.88x | 0 |

All 12 output shapes and every RGB channel matched the golden files. The median
runtime across images was 0.4417 seconds and the median old-to-exact speed-up
was 8.28x. These timings used the local NVIDIA accelerator, so they prove the
hybrid algorithm and exactness contract, not AMD throughput.

The golden-output test suite also loads the old source directly from Git. This
prevents an implementation from passing merely because two newly written paths
share the same bug.

## AMD acceptance matrix

The ROCm implementation is complete at the source level; these measurements
remain to be collected on target hardware:

| Check | Required evidence | Status |
|---|---|---|
| Runtime identity | PyTorch version, non-null `torch.version.hip`, GPU name | Pending hardware |
| Device residency | ROCm unit test passes and output device is `cuda`/HIP | Pending hardware |
| Correctness | Exact-palette CPU/ROCm comparison passes | Pending hardware |
| Legacy exactness | Old-commit oracle produces zero differing channels | Pending hardware |
| 1x throughput | Five synchronized runs of the command above | Pending hardware |
| 6x throughput | Same input with `--pixel-size 6` | Pending hardware |
| Kernel profile | rocprof trace without image-wide host copies | Pending hardware |

AMD results should be appended as real receipts rather than replacing this
baseline so CPU, CUDA, and ROCm behavior remain independently auditable.

## Verification

```bash
python -m unittest tests.test_benchmark_receipt
python -m unittest discover -s tests
ruff format --check .
ruff check --select I .
```