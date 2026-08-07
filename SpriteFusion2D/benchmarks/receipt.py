"""Versioned JSON benchmark receipts for SpriteFusion 2D.

A *receipt* is the auditable, machine-readable record of one benchmark run:

* schema version and benchmark identity;
* environment snapshot (Python, PyTorch, HIP/ROCm, GPU, device);
* SHA-256 fingerprints of the core sources, the input, and every output;
* raw per-run samples plus standard-library statistics;
* git state of the working tree that produced the run;
* failure records with sanitized tracebacks.

Receipts are sanitized by default: absolute paths outside the repository and
user directories are replaced with placeholders so a receipt can be shared
without leaking a contributor's home directory or machine layout.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

RECEIPT_FORMAT = "spritefusion-benchmark-receipt"
RECEIPT_SCHEMA_VERSION = 1

_HOME_PLACEHOLDER = "<HOME>"
_REPO_ROOT_PLACEHOLDER = "<REPO_ROOT>"
_USERS_DIR_PLACEHOLDER = "<USERS_DIR>"
_CHUNK_SIZE = 1024 * 1024

_REQUIRED_KEYS = (
    "format",
    "schema_version",
    "benchmark",
    "timestamp_utc",
    "command",
    "environment",
    "sources",
    "inputs",
    "outputs",
    "timing",
    "failures",
    "git",
    "sanitized",
    "status",
)
_TIMING_KEYS = (
    "warmup_runs",
    "runs",
    "include_host_to_device",
    "synchronize",
    "samples_seconds",
    "stats",
    "peak_memory_bytes",
)


class ReceiptError(ValueError):
    """Raised when a receipt cannot be built or validated."""


@dataclass(frozen=True, slots=True)
class SampleStats:
    """Summary statistics over raw benchmark samples."""

    median_seconds: float | None
    mean_seconds: float | None
    min_seconds: float | None
    max_seconds: float | None
    pstdev_seconds: float | None
    p90_seconds: float | None

    def to_dict(self) -> dict[str, float | None]:
        return {
            "median_seconds": self.median_seconds,
            "mean_seconds": self.mean_seconds,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "pstdev_seconds": self.pstdev_seconds,
            "p90_seconds": self.p90_seconds,
        }


def compute_sample_stats(samples_seconds: Sequence[float]) -> SampleStats:
    """Compute statistics over raw samples using the standard library.

    The median is :func:`statistics.median`; the mean is
    :func:`statistics.mean`; spread is :func:`statistics.pstdev`.  P90 is the
    nearest-rank 90th percentile so the definition stays stable for very small
    sample counts.  An empty sample list produces ``None`` in every field.
    """

    values = [float(sample) for sample in samples_seconds]
    if not values:
        return SampleStats(None, None, None, None, None, None)
    return SampleStats(
        median_seconds=statistics.median(values),
        mean_seconds=statistics.mean(values),
        min_seconds=min(values),
        max_seconds=max(values),
        pstdev_seconds=statistics.pstdev(values),
        p90_seconds=_nearest_rank_percentile(values, 0.90),
    )


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of raw bytes."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Return the lowercase hex SHA-256 of a file's contents."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tensor_fingerprint(tensor: Any) -> dict[str, Any]:
    """Return a deterministic content fingerprint for one tensor.

    The tensor is detached, moved to CPU, made contiguous, and hashed as raw
    bytes so the fingerprint depends only on values and shape, not on the
    execution device.
    """

    import torch

    raw = tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
    return {
        "sha256": sha256_bytes(raw),
        "shape": list(tensor.shape),
        "dtype": str(tensor.dtype),
    }


def hash_source_files(
    repo_root: str | os.PathLike[str],
    relative_paths: Sequence[str],
) -> list[dict[str, Any]]:
    """Hash repository files relative to ``repo_root``.

    A missing file is recorded with ``"missing": True`` and ``sha256: None``
    instead of raising, so a receipt still documents the intended sources.
    """

    root = Path(repo_root)
    entries: list[dict[str, Any]] = []
    for relative in relative_paths:
        path = root / relative
        if path.is_file():
            entries.append({"path": relative, "sha256": sha256_file(path)})
        else:
            entries.append({"path": relative, "sha256": None, "missing": True})
    return entries


@dataclass(frozen=True, slots=True)
class GitState:
    """Snapshot of the git repository that produced a benchmark run."""

    available: bool
    commit_sha: str | None
    branch: str | None
    dirty: bool | None
    status: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "dirty": self.dirty,
            "status": list(self.status),
        }


def git_repo_state(repo_root: str | os.PathLike[str] | None = None) -> GitState:
    """Read the git state of ``repo_root`` (or the current directory).

    Every git invocation failure is treated as "git unavailable" so receipt
    generation still works outside a git checkout or when git is missing.
    """

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - deliberate read-only git query
            args,
            cwd=str(repo_root) if repo_root else None,
            capture_output=True,
            text=True,
            check=False,
            errors="replace",
        )

    try:
        head = run("git", "rev-parse", "HEAD")
        branch_result = run("git", "branch", "--show-current")
        status_result = run("git", "status", "--short")
    except OSError:
        return GitState(False, None, None, None, ())
    if head.returncode != 0:
        return GitState(False, None, None, None, ())
    branch = branch_result.stdout.strip() or None
    if status_result.returncode != 0:
        return GitState(
            available=True,
            commit_sha=head.stdout.strip(),
            branch=branch,
            dirty=None,
            status=(),
        )
    status_lines = tuple(line for line in status_result.stdout.splitlines() if line)
    return GitState(
        available=True,
        commit_sha=head.stdout.strip(),
        branch=branch,
        dirty=bool(status_lines),
        status=status_lines,
    )


def _default_home() -> str:
    return str(Path.home())


def _normcase(value: str) -> str:
    return os.path.normcase(value).rstrip("\\/")


def _is_rooted_path(value: str) -> bool:
    """Whether ``value`` is drive-absolute or root-relative (``\\opt\\...``)."""

    return os.path.isabs(value) or value.startswith(("/", "\\"))


def sanitize_text(
    text: str,
    *,
    repo_root: str | os.PathLike[str] | None = None,
    home: str | None = None,
) -> str:
    """Replace repository roots and user directories with placeholders."""

    result = str(text)
    if repo_root is not None:
        root_value = str(repo_root)
        result = result.replace(root_value, _REPO_ROOT_PLACEHOLDER)
        result = result.replace(_normcase(root_value), _REPO_ROOT_PLACEHOLDER)
    home_path = home if home is not None else _default_home()
    if home_path:
        result = result.replace(home_path, _HOME_PLACEHOLDER)
        result = result.replace(_normcase(home_path), _HOME_PLACEHOLDER)
    result = re.sub(
        r"(?i)([A-Za-z]:[\\/]Users[\\/][^\\/\"'<>\\s]+)",
        _USERS_DIR_PLACEHOLDER,
        result,
    )
    result = re.sub(
        r"(?i)(/[hH]ome/[^/\"'<>\\s]+)",
        _USERS_DIR_PLACEHOLDER,
        result,
    )
    return result


def sanitize_command(
    argv: Sequence[str],
    *,
    repo_root: str | os.PathLike[str] | None = None,
    home: str | None = None,
) -> tuple[str, ...]:
    """Scrub absolute paths from a recorded command line.

    Absolute paths inside the repository become ``<REPO_ROOT>/...``; absolute
    paths outside it collapse to their basename (so ``--input
    C:\\Users\\alice\\source.png`` records as ``--input source.png``).
    """

    home_path = home if home is not None else _default_home()
    root = _normcase(str(repo_root)) if repo_root is not None else ""
    scrubbed: list[str] = []
    for argument in argv:
        if _is_rooted_path(argument):
            normalized = _normcase(argument)
            if root and (normalized == root or normalized.startswith(root + os.sep)):
                relative = os.path.relpath(argument, str(repo_root)).replace(
                    os.sep, "/"
                )
                scrubbed.append(f"{_REPO_ROOT_PLACEHOLDER}/{relative}")
            else:
                scrubbed.append(os.path.basename(argument.rstrip("\\/")))
        else:
            scrubbed.append(argument)
    result: list[str] = []
    for argument in scrubbed:
        normalized = _normcase(argument)
        if home_path and (
            normalized == _normcase(home_path)
            or normalized.startswith(_normcase(home_path) + os.sep)
        ):
            argument = _HOME_PLACEHOLDER + argument[len(home_path) :]
        result.append(argument)
    return tuple(result)


def format_failure(
    exception: BaseException,
    *,
    repo_root: str | os.PathLike[str] | None = None,
    home: str | None = None,
    sanitize: bool = True,
    include_traceback: bool = True,
) -> dict[str, Any]:
    """Record one benchmark failure.

    The traceback is included so a receipt is actionable, and it is scrubbed
    through :func:`sanitize_text` when sanitization is enabled (the default).
    """

    message = str(exception) or exception.__class__.__name__
    record: dict[str, Any] = {
        "exception_type": exception.__class__.__name__,
        "message": (
            sanitize_text(message, repo_root=repo_root, home=home)
            if sanitize
            else message
        ),
    }
    if include_traceback:
        import traceback

        text = "".join(
            traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
        )
        record["traceback"] = (
            sanitize_text(text, repo_root=repo_root, home=home) if sanitize else text
        )
    return record


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_receipt(
    *,
    benchmark: str | Mapping[str, Any],
    command: Sequence[str],
    environment: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    inputs: Sequence[Mapping[str, Any]],
    outputs: Sequence[Mapping[str, Any]],
    timing: Mapping[str, Any],
    failures: Sequence[Mapping[str, Any]] = (),
    git: Mapping[str, Any],
    sanitized: bool,
    notes: str | None = None,
    timestamp_utc: str | None = None,
    schema_version: int = RECEIPT_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Assemble one versioned receipt document."""

    benchmark_section = (
        {"name": benchmark} if isinstance(benchmark, str) else dict(benchmark)
    )
    receipt: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "schema_version": schema_version,
        "benchmark": benchmark_section,
        "timestamp_utc": timestamp_utc or _utc_now(),
        "command": list(command),
        "environment": dict(environment),
        "sources": [dict(entry) for entry in sources],
        "inputs": [dict(entry) for entry in inputs],
        "outputs": [dict(entry) for entry in outputs],
        "timing": dict(timing),
        "failures": [dict(entry) for entry in failures],
        "git": dict(git),
        "sanitized": bool(sanitized),
        "status": "error" if failures else "ok",
    }
    if notes is not None:
        receipt["notes"] = str(notes)
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    """Raise :class:`ReceiptError` when a receipt document is malformed."""

    missing = [key for key in _REQUIRED_KEYS if key not in receipt]
    if missing:
        raise ReceiptError(
            f"receipt missing required keys: {', '.join(sorted(missing))}"
        )
    if receipt["format"] != RECEIPT_FORMAT:
        raise ReceiptError(f"unexpected receipt format: {receipt['format']!r}")
    if receipt["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise ReceiptError(
            "unsupported receipt schema_version: "
            f"{receipt['schema_version']!r} (expected {RECEIPT_SCHEMA_VERSION})"
        )
    if receipt["status"] not in ("ok", "error"):
        raise ReceiptError(f"invalid receipt status: {receipt['status']!r}")
    if (
        not isinstance(receipt.get("benchmark"), Mapping)
        or "name" not in receipt["benchmark"]
    ):
        raise ReceiptError("receipt benchmark section must contain a name")
    missing_timing = [
        key for key in _TIMING_KEYS if key not in receipt.get("timing", {})
    ]
    if missing_timing:
        raise ReceiptError(
            f"receipt timing missing required keys: {', '.join(sorted(missing_timing))}"
        )


def receipt_dumps(receipt: Mapping[str, Any]) -> str:
    """Serialize a receipt to stable, sorted, indented JSON text."""

    return json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_receipt(receipt: Mapping[str, Any], path: str | os.PathLike[str]) -> None:
    """Write a receipt to ``path``, creating parent directories as needed."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(receipt_dumps(receipt), encoding="utf-8")
