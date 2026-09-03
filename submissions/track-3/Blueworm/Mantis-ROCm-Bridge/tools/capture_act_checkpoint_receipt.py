#!/usr/bin/env python3
"""Capture a fail-closed provenance receipt for one LeRobot ACT checkpoint.

The collector is deliberately read-only with respect to ``checkpoint_dir``.
It produces six sibling evidence files derived from ``--output-prefix``:

* ``.inventory.txt``
* ``.SHA256SUMS``
* ``.gpu.txt``
* ``.receipt.json``
* ``.status``
* ``_artifacts.SHA256SUMS``

Publication is transaction-like rather than globally atomic: every staged
file is committed with an atomic no-clobber hard-link operation.  If any
commit fails, files created by this invocation are rolled back after verifying
their inode identity.  No pre-existing or concurrently-created file is
overwritten or removed.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = 1
PRETRAINED_MODEL_REL = "pretrained_model/model.safetensors"
OPTIMIZER_STATE_REL = "training_state/optimizer_state.safetensors"
TRAINING_STEP_REL = "training_state/training_step.json"
REQUIRED_FILES = (
    PRETRAINED_MODEL_REL,
    OPTIMIZER_STATE_REL,
    TRAINING_STEP_REL,
)
GPU_FLAGS = (
    "--showpids",
    "--showuse",
    "--showmemuse",
    "--showtemp",
    "--showpower",
)
OUTPUT_SUFFIXES = (
    ".inventory.txt",
    ".SHA256SUMS",
    ".gpu.txt",
    ".receipt.json",
    ".status",
    "_artifacts.SHA256SUMS",
)
ERROR_PATTERN_SOURCES = (
    r"Traceback",
    r"CUDA out of memory",
    r"HIP out of memory",
    r"RuntimeError",
    r"loss:(?:nan|inf)\b",
    r"grdn:(?:nan|inf)\b",
)
ERROR_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in ERROR_PATTERN_SOURCES
)
CHUNK_BYTES = 1024 * 1024


class CheckpointReceiptError(RuntimeError):
    """A provenance invariant failed; no successful receipt may be published."""


@dataclass(frozen=True)
class FileSnapshot:
    """Identity and mutation-sensitive metadata for one regular file."""

    relative_path: str
    size: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class HashedFile:
    snapshot: FileSnapshot
    sha256: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_from_stat(relative_path: str, info: os.stat_result) -> FileSnapshot:
    return FileSnapshot(
        relative_path=relative_path,
        size=info.st_size,
        device=info.st_dev,
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def inventory_checkpoint(checkpoint_dir: Path) -> list[FileSnapshot]:
    """Return a deterministic regular-file inventory without following links."""

    base = checkpoint_dir.resolve()
    entries: list[FileSnapshot] = []

    def walk_error(error: OSError) -> None:
        raise CheckpointReceiptError(f"cannot inventory checkpoint: {error}")

    for root, directories, names in os.walk(
        base, topdown=True, followlinks=False, onerror=walk_error
    ):
        # Exclude directory symlinks explicitly and stabilize traversal.
        stable_directories = []
        for name in sorted(directories):
            path = Path(root) / name
            try:
                info = os.lstat(path)
            except OSError as exc:
                raise CheckpointReceiptError(
                    f"cannot inspect checkpoint directory entry {path}: {exc}"
                ) from exc
            if stat.S_ISDIR(info.st_mode):
                stable_directories.append(name)
        directories[:] = stable_directories

        for name in sorted(names):
            path = Path(root) / name
            try:
                info = os.lstat(path)
            except OSError as exc:
                raise CheckpointReceiptError(
                    f"cannot inspect checkpoint file {path}: {exc}"
                ) from exc
            if not stat.S_ISREG(info.st_mode):
                continue
            relative_path = path.relative_to(base).as_posix()
            entries.append(snapshot_from_stat(relative_path, info))

    entries.sort(key=lambda entry: entry.relative_path)
    return entries


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CheckpointReceiptError(f"cannot hash checkpoint file {path}: {exc}") from exc
    return digest.hexdigest()


def hash_inventory(
    checkpoint_dir: Path, inventory: Sequence[FileSnapshot]
) -> list[HashedFile]:
    """Hash files while detecting replacement or mutation during acquisition."""

    base = checkpoint_dir.resolve()
    hashed: list[HashedFile] = []
    for expected in inventory:
        path = base / expected.relative_path
        try:
            before_info = os.lstat(path)
        except OSError as exc:
            raise CheckpointReceiptError(
                f"checkpoint changed before hashing {expected.relative_path}: {exc}"
            ) from exc
        before = snapshot_from_stat(expected.relative_path, before_info)
        if before != expected or not stat.S_ISREG(before_info.st_mode):
            raise CheckpointReceiptError(
                f"checkpoint changed before hashing {expected.relative_path}"
            )
        digest = sha256_file(path)
        try:
            after_info = os.lstat(path)
        except OSError as exc:
            raise CheckpointReceiptError(
                f"checkpoint changed while hashing {expected.relative_path}: {exc}"
            ) from exc
        after = snapshot_from_stat(expected.relative_path, after_info)
        if after != expected or not stat.S_ISREG(after_info.st_mode):
            raise CheckpointReceiptError(
                f"checkpoint changed while hashing {expected.relative_path}"
            )
        hashed.append(HashedFile(expected, digest))

    if inventory_checkpoint(checkpoint_dir) != list(inventory):
        raise CheckpointReceiptError("checkpoint inventory changed during acquisition")
    return hashed


def required_snapshot(
    inventory: Sequence[FileSnapshot], relative_path: str
) -> FileSnapshot:
    for entry in inventory:
        if entry.relative_path == relative_path:
            if entry.size <= 0:
                raise CheckpointReceiptError(
                    f"required checkpoint file is empty: {relative_path}"
                )
            return entry
    raise CheckpointReceiptError(
        f"required checkpoint file missing or not regular: {relative_path}"
    )


def parse_training_step(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointReceiptError(
            f"cannot parse training step file {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict) or "step" not in payload:
        raise CheckpointReceiptError(
            f"training step file {path} has no integer step field"
        )
    step = payload["step"]
    if not isinstance(step, int) or isinstance(step, bool):
        raise CheckpointReceiptError(
            f"training step in {path} is not an integer: {step!r}"
        )
    return step


def scan_log_errors(text: str) -> int:
    return sum(len(pattern.findall(text)) for pattern in ERROR_PATTERNS)


def capture_gpu(
    rocm_smi: str, *, skip: bool, captured_at_utc: str
) -> tuple[dict[str, Any], str]:
    argv = [rocm_smi, *GPU_FLAGS]
    if skip:
        body = (
            "# rocm-smi checkpoint GPU capture\n"
            "# GPU CAPTURE SKIPPED (--skip-gpu)\n"
            f"# rocm_smi_path: {rocm_smi}\n"
            f"# captured_at_utc: {captured_at_utc}\n"
        )
        return (
            {
                "skipped": True,
                "rocm_smi_path": rocm_smi,
                "capture_argv": [],
                "returncode": None,
                "stdout_bytes": 0,
                "stderr_bytes": 0,
            },
            body,
        )

    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise CheckpointReceiptError(
            f"cannot execute rocm-smi {rocm_smi}: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise CheckpointReceiptError(
            f"rocm-smi exited with code {completed.returncode}; "
            f"stderr: {(completed.stderr or '').strip()}"
        )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    body = (
        "# rocm-smi checkpoint GPU capture\n"
        f"# command: {' '.join(argv)}\n"
        f"# returncode: {completed.returncode}\n"
        f"# captured_at_utc: {captured_at_utc}\n"
        f"{stdout}"
    )
    return (
        {
            "skipped": False,
            "rocm_smi_path": rocm_smi,
            "capture_argv": argv,
            "returncode": completed.returncode,
            "stdout_bytes": len(stdout.encode("utf-8")),
            "stderr_bytes": len(stderr.encode("utf-8")),
        },
        body,
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def checkpoint_manifest_sha256(hashed: Sequence[HashedFile]) -> str:
    body = "".join(
        f"{entry.snapshot.relative_path} {entry.snapshot.size} {entry.sha256}\n"
        for entry in hashed
    ).encode("utf-8")
    return sha256_bytes(body)


def output_paths(prefix: Path) -> dict[str, Path]:
    text = str(prefix)
    return {
        "inventory": Path(text + ".inventory.txt"),
        "sha256sums": Path(text + ".SHA256SUMS"),
        "gpu": Path(text + ".gpu.txt"),
        "receipt": Path(text + ".receipt.json"),
        "status": Path(text + ".status"),
        "artifacts_sha256sums": Path(text + "_artifacts.SHA256SUMS"),
    }


def ensure_outputs_outside_checkpoint(
    outputs: Iterable[Path], checkpoint_dir: Path
) -> None:
    checkpoint = checkpoint_dir.resolve()
    for output in outputs:
        try:
            output.resolve().relative_to(checkpoint)
        except ValueError:
            continue
        raise CheckpointReceiptError(
            f"refusing to write output inside read-only checkpoint dir: {output}"
        )


def make_stage_file(final: Path, content: bytes) -> Path:
    """Create one unique, invocation-owned sibling stage file."""

    final.parent.mkdir(parents=True, exist_ok=True)
    descriptor, stage_name = tempfile.mkstemp(
        dir=str(final.parent), prefix=f".{final.name}.stage."
    )
    stage = Path(stage_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            stage.unlink()
        raise
    return stage


def same_inode(left: Path, right: Path) -> bool:
    try:
        left_stat = os.lstat(left)
        right_stat = os.lstat(right)
    except OSError:
        return False
    return (left_stat.st_dev, left_stat.st_ino) == (
        right_stat.st_dev,
        right_stat.st_ino,
    )


def publish_no_clobber(pairs: Sequence[tuple[Path, bytes]]) -> None:
    """Transaction-like publication with per-file atomic no-clobber commit."""

    staged: list[tuple[Path, Path]] = []
    published: list[tuple[Path, Path]] = []
    try:
        for final, content in pairs:
            staged.append((make_stage_file(final, content), final))

        for stage, final in staged:
            try:
                os.link(stage, final, follow_symlinks=False)
            except FileExistsError as exc:
                raise CheckpointReceiptError(
                    f"refusing to overwrite concurrently-created output: {final}"
                ) from exc
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise CheckpointReceiptError(
                        f"refusing to overwrite concurrently-created output: {final}"
                    ) from exc
                raise CheckpointReceiptError(
                    f"cannot publish evidence output {final}: {exc}"
                ) from exc
            published.append((stage, final))
    except BaseException:
        # Remove only a final path that still names this invocation's inode.
        for stage, final in reversed(published):
            if same_inode(stage, final):
                with contextlib.suppress(OSError):
                    final.unlink()
        raise
    finally:
        # Staging paths are unique and owned by this invocation.
        for stage, _final in staged:
            with contextlib.suppress(OSError):
                stage.unlink()


def render_receipt_set(
    *,
    checkpoint_dir: Path,
    expected_step: int,
    recorded_step: int,
    hashed: Sequence[HashedFile],
    model_bytes: int,
    optimizer_bytes: int,
    training_log: Path,
    exact_error_match_count: int,
    gpu: dict[str, Any],
    gpu_body: str,
    outputs: dict[str, Path],
    captured_at_utc: str,
) -> list[tuple[Path, bytes]]:
    total_bytes = sum(entry.snapshot.size for entry in hashed)
    manifest = checkpoint_manifest_sha256(hashed)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": captured_at_utc,
        "checkpoint_dir": str(checkpoint_dir.resolve()),
        "expected_step": expected_step,
        "recorded_step": recorded_step,
        "step_match": recorded_step == expected_step,
        "file_count": len(hashed),
        "total_bytes": total_bytes,
        "model_bytes": model_bytes,
        "optimizer_bytes": optimizer_bytes,
        "checkpoint_manifest_sha256": manifest,
        "error_scan": {
            "training_log": str(training_log.resolve()),
            "case_insensitive": True,
            "patterns": list(ERROR_PATTERN_SOURCES),
            "exact_error_match_count": exact_error_match_count,
        },
        "exact_error_match_count": exact_error_match_count,
        "gpu": dict(gpu, output_path=str(outputs["gpu"])),
        "outputs": {name: str(path) for name, path in outputs.items()},
        "claim_boundary": {
            "provenance_only": True,
            "convergence_claimed": False,
            "inference_claimed": False,
            "closed_loop_claimed": False,
            "statement": (
                "This receipt establishes checkpoint provenance only. It makes "
                "no claim about convergence, policy quality, generalization, "
                "inference correctness, task success, robustness, performance, "
                "or closed-loop behavior."
            ),
        },
    }
    inventory = "".join(
        f"{entry.snapshot.relative_path}\t{entry.snapshot.size}\n"
        for entry in hashed
    ).encode("utf-8")
    sha256sums = "".join(
        f"{entry.sha256}  {entry.snapshot.relative_path}\n" for entry in hashed
    ).encode("utf-8")
    gpu_bytes = gpu_body.encode("utf-8")
    receipt_bytes = (
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    status = (
        "ACT_CHECKPOINT_RECEIPT_STATUS=PASS\n"
        f"checkpoint_dir={receipt['checkpoint_dir']}\n"
        f"expected_step={expected_step}\n"
        f"recorded_step={recorded_step}\n"
        "step_match=True\n"
        f"file_count={len(hashed)}\n"
        f"total_bytes={total_bytes}\n"
        f"model_bytes={model_bytes}\n"
        f"optimizer_bytes={optimizer_bytes}\n"
        f"checkpoint_manifest_sha256={manifest}\n"
        f"exact_error_match_count={exact_error_match_count}\n"
        f"gpu_skipped={gpu['skipped']}\n"
    ).encode("utf-8")
    primary = [
        (outputs["inventory"], inventory),
        (outputs["sha256sums"], sha256sums),
        (outputs["gpu"], gpu_bytes),
        (outputs["receipt"], receipt_bytes),
        (outputs["status"], status),
    ]
    artifact_manifest = "".join(
        f"{sha256_bytes(content)}  {path.name}\n"
        for path, content in sorted(primary, key=lambda item: item[0].name)
    ).encode("utf-8")
    return primary + [(outputs["artifacts_sha256sums"], artifact_manifest)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture a read-only ACT checkpoint provenance receipt."
    )
    parser.add_argument("checkpoint_dir", type=Path)
    parser.add_argument("--expected-step", type=int, required=True)
    parser.add_argument("--training-log", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--rocm-smi", default="rocm-smi")
    parser.add_argument("--skip-gpu", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    checkpoint_dir = args.checkpoint_dir
    if not checkpoint_dir.is_dir():
        print(
            f"error: checkpoint_dir is not a directory: {checkpoint_dir}",
            file=sys.stderr,
        )
        return 1

    outputs = output_paths(args.output_prefix)
    existing = [path for path in outputs.values() if path.exists()]
    if existing:
        parser.error(
            "refusing to overwrite existing output(s): "
            + ", ".join(str(path) for path in existing)
        )

    try:
        ensure_outputs_outside_checkpoint(outputs.values(), checkpoint_dir)
        inventory = inventory_checkpoint(checkpoint_dir)
        model = required_snapshot(inventory, PRETRAINED_MODEL_REL)
        optimizer = required_snapshot(inventory, OPTIMIZER_STATE_REL)
        required_snapshot(inventory, TRAINING_STEP_REL)
        recorded_step = parse_training_step(
            checkpoint_dir.resolve() / TRAINING_STEP_REL
        )
        if recorded_step != args.expected_step:
            raise CheckpointReceiptError(
                f"recorded step {recorded_step} != expected step {args.expected_step}"
            )
        hashed = hash_inventory(checkpoint_dir, inventory)
        try:
            log_text = args.training_log.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CheckpointReceiptError(
                f"cannot read training log {args.training_log}: {exc}"
            ) from exc
        error_count = scan_log_errors(log_text)
        captured_at = utc_now_iso()
        gpu, gpu_body = capture_gpu(
            args.rocm_smi, skip=args.skip_gpu, captured_at_utc=captured_at
        )
        pairs = render_receipt_set(
            checkpoint_dir=checkpoint_dir,
            expected_step=args.expected_step,
            recorded_step=recorded_step,
            hashed=hashed,
            model_bytes=model.size,
            optimizer_bytes=optimizer.size,
            training_log=args.training_log,
            exact_error_match_count=error_count,
            gpu=gpu,
            gpu_body=gpu_body,
            outputs=outputs,
            captured_at_utc=captured_at,
        )
        # Recheck the checkpoint immediately before publication.
        if inventory_checkpoint(checkpoint_dir) != inventory:
            raise CheckpointReceiptError(
                "checkpoint inventory changed before publication"
            )
        publish_no_clobber(pairs)
    except CheckpointReceiptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: evidence acquisition failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"captured checkpoint provenance: step {recorded_step}, "
        f"{len(hashed)} files, {sum(x.snapshot.size for x in hashed)} bytes, "
        f"{error_count} exact log error matches -> {outputs['receipt']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
