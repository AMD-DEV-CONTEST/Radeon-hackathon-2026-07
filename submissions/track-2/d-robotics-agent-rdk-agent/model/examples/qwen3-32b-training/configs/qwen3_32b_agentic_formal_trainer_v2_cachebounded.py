#!/usr/bin/env python3
"""Fail-closed one-epoch Qwen3-32B agentic QLoRA trainer.

This is deliberately a small, manual, single-process trainer.  It consumes the
frozen semantic-boundary loss-window plan, performs token-weighted accumulation
over exactly 119 optimizer steps, validates at the frozen boundaries, and
publishes immutable checkpoints.  Each training micro-window releases only the
allocator cache after backward has completed and all temporary GPU references
have been dropped.  Phase 1 must stop after checkpoint 10.  Phase 2 is allowed
to resume only that exact checkpoint in a fresh process.

The script intentionally has no generic "latest checkpoint" or hyperparameter
CLI.  Changing the objective, schedule, optimizer, or checkpoint contract
requires a new reviewed script and therefore a new script hash.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import math
import os
import random
import re
import socket
import stat
import struct
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable


EXPECTED_HOSTNAME = "u-7701-ae3eba8a"
EXPECTED_MACHINE_SHA256 = "7c225d1717bb5f671c4bf071b1df172abdc72a50a3ed53e24de9ab724d35ad54"
EXPECTED_MODEL_VERIFICATION_SHA256 = "5f8b675142ee4d2e6a968e756c1da6546f59dcfd34ed997ef23d95211feb7b0d"
EXPECTED_ORIGINAL_PLAN_SHA256 = "39d6ae20fcb566d6544049e2ea263c5bc64fe8ecd349c71b4a8ec58721134f25"
EXPECTED_LOSS_PLAN_SHA256 = "7ef449cb41f37f5d32d4562c336aba4e3cb8f01b506850a93d34bccef6260afb"
EXPECTED_COMMON_SHA256 = "d0159dd2ab96961ea116dc4264833a65a98d63421a21c798aa70dcc8bfcb9f7f"
EXPECTED_SPLIT_SHA256 = {
    "train": "707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58",
    "validation": "d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f",
}
EXPECTED_MODEL_REVISION = "7f721e74a6a8cc9ee352f7e49303a2c1705f9083"
EXPECTED_TEMPLATE_SHA256 = "96fd16d36fb085260f9eb1e717b2c4e6e8b9e75a5e6504f66c8d6b128d82784d"
EXPECTED_CONFIG_SHA256 = "918fe2d123e79abf8ed4688278cc7d9c6c54d25fbea35e5f0870985f4d663000"
EXPECTED_INDEX_SHA256 = "2771f7e67bacc73ceb4ee0dfe6027d49fc9a4390d17eda517a4f7f48923d6a61"

EXPECTED_PYTHON_PREFIX = "3.12.3"
EXPECTED_TORCH = "2.9.1+rocm7.2.0.git7e1940d4"
EXPECTED_TORCH_HIP = "7.2.26015-fc0010cf6a"
EXPECTED_TRANSFORMERS = "5.5.0"
EXPECTED_PEFT = "0.19.1"
EXPECTED_BITSANDBYTES = "0.50.0"
EXPECTED_TOKENIZER_LENGTH = 151_669
EXPECTED_LINEAR4BIT = 448
EXPECTED_RMSNORM = 257
EXPECTED_LORA_MODULES = 448
EXPECTED_TRAINABLE_TENSORS = 896
EXPECTED_TRAINABLE_ELEMENTS = 67_108_864

SEED = 20260803
MAX_RENDER_TOKENS = 32_768
MAX_WINDOW_TOKENS = 8_192
OPTIMIZER_STEPS = 119
VALIDATION_STEPS = (0, 30, 60, 90, 119)
BEST_CANDIDATE_STEPS = (30, 60, 90, 119)
CHECKPOINT_STEPS = tuple(range(10, 120, 10)) + (119,)
PHASE1_STOP_STEP = 10
PHASE1_RESTART_EXIT_CODE = 75

EXPECTED_TRAIN_ROWS = 946
EXPECTED_TRAIN_MICRO_WINDOWS = 948
EXPECTED_TRAIN_TOKENS = 534_734
EXPECTED_TRAIN_CURATED_ROWS = 262
EXPECTED_TRAIN_PROMOTED_ROWS = 684
EXPECTED_TRAIN_CURATED_TOKENS = 100_078
EXPECTED_TRAIN_PROMOTED_TOKENS = 434_656
EXPECTED_TRAIN_SYSTEMLESS_WINDOWS = 23
EXPECTED_TRAIN_SYSTEMLESS_TOKENS = 24_521
EXPECTED_TRAIN_LONG_ROWS = 23

EXPECTED_VALIDATION_ROWS = 116
EXPECTED_VALIDATION_WINDOWS = 116
EXPECTED_VALIDATION_TOKENS = 66_181
EXPECTED_VALIDATION_CURATED_ROWS = 32
EXPECTED_VALIDATION_PROMOTED_ROWS = 84
EXPECTED_VALIDATION_CURATED_TOKENS = 14_608
EXPECTED_VALIDATION_PROMOTED_TOKENS = 51_573
EXPECTED_VALIDATION_SYSTEMLESS_WINDOWS = 4
EXPECTED_VALIDATION_SYSTEMLESS_TOKENS = 4_295
EXPECTED_VALIDATION_LONG_ROWS = 4
EXPECTED_VALIDATION_LONG_WINDOWS = 4
EXPECTED_VALIDATION_LONG_TOKENS = 4_295

EXPECTED_STEP10_MICROS = 79
EXPECTED_STEP10_UNIQUE_TASKS = 79
EXPECTED_STEP10_TOKENS = 45_025
EXPECTED_STEP10_CURATED_MICROS = 22
EXPECTED_STEP10_CURATED_TOKENS = 8_396
EXPECTED_STEP10_PROMOTED_MICROS = 57
EXPECTED_STEP10_PROMOTED_TOKENS = 36_629
EXPECTED_STEP10_WINDOW_IDS_SHA256 = "56fdf2ec59cefc53b249260af67cb290dab4dff70e4981f21becfa4173c89dc6"
EXPECTED_STEP10_TASK_IDS_SHA256 = "83a85cc431ea3d00b4b41376c9dd4bcd9f3f62c3916a0e1fbdc4ca20dee8a0b5"
EXPECTED_FINAL_WINDOW_IDS_SHA256 = "f1516c99a606dd2b29b958e9cf86e017f9945ecfd969ba17340c101e4f67f5c1"

LORA_TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
LEARNING_RATE = 1.0e-4
ADAM_BETAS = (0.9, 0.999)
ADAM_EPS = 1.0e-8
WEIGHT_DECAY = 0.0
MAX_GRAD_NORM = 1.0
LR_SCHEDULE = "constant_1e-4.v1"
PER_MICRO_ALLOCATOR_CACHE_RELEASE = {
    "enabled": True,
    "scope": "every training micro-window",
    "placement": "after backward, CPU loss capture, metric update, and temporary GPU reference release",
    "sequence": ["torch.cuda.synchronize(0)", "gc.collect()", "torch.cuda.empty_cache()"],
}

RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_i64(values: Iterable[int]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(struct.pack("<q", int(value)))
    return digest.hexdigest()


def machine_sha256() -> str:
    return sha256_bytes(Path("/etc/machine-id").read_bytes())


def process_instance() -> dict[str, Any]:
    fields = Path("/proc/self/stat").read_text().split()
    require(len(fields) > 21, "cannot read process start time")
    return {
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "pid": os.getpid(),
        "start_ticks": int(fields[21]),
    }


def exact_process_is_alive(instance: dict[str, Any]) -> bool:
    if instance.get("boot_id") != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        return False
    pid = instance.get("pid")
    start_ticks = instance.get("start_ticks")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(start_ticks, int):
        return False
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
    except FileNotFoundError:
        return False
    require(len(fields) > 21, "cannot inspect prior process start time")
    return int(fields[21]) == start_ticks


def require_no_gradients(trainable: list[tuple[str, Any]], context: str) -> None:
    residual = [name for name, parameter in trainable if parameter.grad is not None]
    require(not residual, f"{context}: residual gradients: {residual[:8]}")


def gpu_memory_evidence(runtime: dict[str, Any]) -> dict[str, int]:
    torch = runtime["torch"]
    torch.cuda.synchronize(0)
    return {
        "allocated": int(torch.cuda.memory_allocated(0)),
        "reserved": int(torch.cuda.memory_reserved(0)),
        "max_allocated": int(torch.cuda.max_memory_allocated(0)),
        "max_reserved": int(torch.cuda.max_memory_reserved(0)),
    }


def release_per_micro_allocator_cache(torch: Any) -> None:
    """Release cached allocator blocks without touching gradients or RNG state."""

    torch.cuda.synchronize(0)
    gc.collect()
    torch.cuda.empty_cache()


def json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without permitting replacement."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    require(renameat2 is not None, "renameat2 is unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(destination))


def reclaim_tree_page_cache(root: Path) -> dict[str, int]:
    """Drop only this tree's clean file pages after durability checks."""

    require(hasattr(os, "posix_fadvise"), "posix_fadvise unavailable")
    require(hasattr(os, "POSIX_FADV_DONTNEED"), "POSIX_FADV_DONTNEED unavailable")
    files = 0
    bytes_total = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        require(not path.is_symlink(), f"cache-reclaim symlink: {path}")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(descriptor)
        files += 1
        bytes_total += path.stat().st_size
    return {"files": files, "bytes": bytes_total}


def write_new_bytes(path: Path, payload: bytes, mode: int = 0o444) -> None:
    require(path.parent.is_dir(), f"output parent missing: {path.parent}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_json_create(path: Path, payload: Any) -> None:
    require(not path.exists(), f"atomic output exists: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    write_new_bytes(temporary, json_bytes(payload))
    try:
        os.link(temporary, path)
        temporary.unlink()
        fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def torch_save_new(torch: Any, value: Any, path: Path) -> None:
    require(not path.exists(), f"torch output exists: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    require(not temporary.exists(), f"torch partial exists: {temporary}")
    try:
        torch.save(value, temporary)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(temporary, 0o444)
        os.link(temporary, path)
        temporary.unlink()
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def inventory_files(root: Path, excluded: set[str] | None = None) -> dict[str, dict[str, Any]]:
    excluded = excluded or set()
    inventory: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = str(path.relative_to(root))
        if relative in excluded:
            continue
        require(not path.is_symlink(), f"inventory symlink: {path}")
        inventory[relative] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return inventory


def fsync_tree(root: Path) -> None:
    directories: set[Path] = {root}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), f"checkpoint symlink: {path}")
        if path.is_file():
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            directories.add(path.parent)
        elif path.is_dir():
            directories.add(path)
        else:
            raise RuntimeError(f"checkpoint contains non-file entry: {path}")
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)


def read_bound_file(path: Path, expected_sha256: str, *, writable_ok: bool = False) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"bound file invalid: {path}")
    if not writable_ok:
        require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"bound file writable: {path}")
    payload = path.read_bytes()
    require(sha256_bytes(payload) == expected_sha256, f"bound file hash drift: {path}")
    return payload


def read_json_bound(path: Path, expected_sha256: str) -> dict[str, Any]:
    payload = json.loads(read_bound_file(path, expected_sha256))
    require(isinstance(payload, dict), f"bound JSON is not an object: {path}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("phase1", "phase2"), required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-verification", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--original-plan", type=Path, required=True)
    parser.add_argument("--loss-plan", type=Path, required=True)
    parser.add_argument("--common-script", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    if args.phase == "phase1":
        require(args.resume is None, "phase1 forbids --resume")
    else:
        require(args.resume is not None, "phase2 requires --resume")
    require(args.run_dir.is_absolute(), "--run-dir must be absolute")
    require(args.result.is_absolute(), "--result must be absolute")
    require(args.model.is_absolute(), "--model must be absolute")
    require(args.data_dir.is_absolute(), "--data-dir must be absolute")
    require(args.original_plan.is_absolute(), "--original-plan must be absolute")
    require(args.loss_plan.is_absolute(), "--loss-plan must be absolute")
    require(args.common_script.is_absolute(), "--common-script must be absolute")
    require(args.model_verification.is_absolute(), "--model-verification must be absolute")
    if args.resume is not None:
        require(args.resume.is_absolute(), "--resume must be absolute")
    return args


def verify_static_environment(args: argparse.Namespace) -> dict[str, Any]:
    require(socket.gethostname() == EXPECTED_HOSTNAME, "hostname mismatch")
    require(machine_sha256() == EXPECTED_MACHINE_SHA256, "machine-id mismatch")
    require(sys.version.startswith(EXPECTED_PYTHON_PREFIX), f"Python version drift: {sys.version}")
    trainer_path = Path(__file__).resolve()
    require(trainer_path.is_file() and not Path(__file__).is_symlink(), "trainer script invalid")
    require(stat.S_IMODE(trainer_path.stat().st_mode) & 0o222 == 0, "trainer script writable")
    trainer_sha256 = sha256_file(trainer_path)

    original_plan_bytes = read_bound_file(args.original_plan, EXPECTED_ORIGINAL_PLAN_SHA256)
    loss_plan_bytes = read_bound_file(args.loss_plan, EXPECTED_LOSS_PLAN_SHA256)
    read_bound_file(args.common_script, EXPECTED_COMMON_SHA256)
    train_bytes = read_bound_file(args.data_dir / "train.jsonl", EXPECTED_SPLIT_SHA256["train"])
    validation_bytes = read_bound_file(
        args.data_dir / "validation.jsonl", EXPECTED_SPLIT_SHA256["validation"]
    )

    verification = read_json_bound(args.model_verification, EXPECTED_MODEL_VERIFICATION_SHA256)
    require(verification.get("status") == "PASS", "model verification status is not PASS")
    require(verification.get("model_path") == str(args.model), "verified model path drift")
    require(verification.get("revision") == EXPECTED_MODEL_REVISION, "verified model revision drift")
    expected_inventory = verification.get("file_sha256")
    require(isinstance(expected_inventory, dict) and len(expected_inventory) == 16, "model inventory drift")
    require(args.model.is_dir() and not args.model.is_symlink(), "model directory invalid")
    require(stat.S_IMODE(args.model.stat().st_mode) & 0o222 == 0, "model directory writable")
    entries = list(args.model.iterdir())
    require(all(path.is_file() and not path.is_symlink() for path in entries), "model has non-file entry")
    require({path.name for path in entries} == set(expected_inventory), "model filename inventory drift")
    fresh_model_sha256: dict[str, str] = {}
    for name in sorted(expected_inventory):
        path = args.model / name
        require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"model file writable: {name}")
        actual = sha256_file(path)
        require(actual == expected_inventory[name], f"model file hash drift: {name}")
        fresh_model_sha256[name] = actual
    require(fresh_model_sha256.get("chat_template.jinja") == EXPECTED_TEMPLATE_SHA256, "template hash drift")
    require(fresh_model_sha256.get("config.json") == EXPECTED_CONFIG_SHA256, "config hash drift")
    require(fresh_model_sha256.get("model.safetensors.index.json") == EXPECTED_INDEX_SHA256, "index hash drift")

    original_plan = json.loads(original_plan_bytes)
    loss_plan = json.loads(loss_plan_bytes)
    require(original_plan.get("schema_version") == "qwen3_32b_agentic_train_plan.v1", "original plan schema drift")
    require(
        loss_plan.get("schema_version") == "qwen3_32b_agentic_loss_window_plan.v1",
        "loss plan schema drift",
    )
    require(loss_plan.get("algorithm") == "semantic_boundary_loss_windows.v1", "loss-window algorithm drift")
    source = loss_plan.get("source", {})
    require(source.get("original_plan_sha256") == EXPECTED_ORIGINAL_PLAN_SHA256, "loss plan base binding drift")
    require(source.get("common_script_sha256") == EXPECTED_COMMON_SHA256, "loss plan common binding drift")
    require(
        source.get("split_sha256", {}).get("train") == EXPECTED_SPLIT_SHA256["train"],
        "loss plan train binding drift",
    )
    require(
        source.get("split_sha256", {}).get("validation") == EXPECTED_SPLIT_SHA256["validation"],
        "loss plan validation binding drift",
    )
    contract = loss_plan.get("execution_contract", {})
    require(contract.get("max_window_tokens") == MAX_WINDOW_TOKENS, "max loss-window length drift")
    require(contract.get("assistant_labels_covered_exactly_once") is True, "label coverage contract drift")
    require(contract.get("context_assistant_labels_masked") is True, "context-mask contract drift")
    require(contract.get("causal_predecessor_required") is True, "causal predecessor contract drift")
    require(
        contract.get("position_ids") == "absolute source offsets arange(source_start, source_end)",
        "position-id contract drift",
    )
    require(contract.get("padding") is False and contract.get("packing") is False, "packing/padding drift")

    raw_lines = {
        "train": train_bytes.splitlines(),
        "validation": validation_bytes.splitlines(),
    }
    require(len(raw_lines["train"]) == EXPECTED_TRAIN_ROWS, "train row count drift")
    require(len(raw_lines["validation"]) == EXPECTED_VALIDATION_ROWS, "validation row count drift")
    return {
        "trainer_path": str(trainer_path),
        "trainer_sha256": trainer_sha256,
        "original_plan": original_plan,
        "original_plan_bytes": original_plan_bytes,
        "loss_plan": loss_plan,
        "loss_plan_bytes": loss_plan_bytes,
        "raw_lines": raw_lines,
        "fresh_model_sha256": fresh_model_sha256,
        "verification": verification,
        "process": process_instance(),
    }


def digest_ordered_strings(values: Iterable[str]) -> str:
    materialized = list(values)
    require(bool(materialized), "cannot digest an empty ordered sequence")
    require(all("\n" not in value for value in materialized), "newline in ordered digest value")
    return sha256_bytes("\n".join(materialized).encode("utf-8"))


def validate_original_plan(original_plan: dict[str, Any]) -> None:
    require(original_plan.get("algorithm") == "capacity_constrained_lpt.v1", "original algorithm drift")
    model = original_plan.get("model", {})
    require(model.get("revision") == EXPECTED_MODEL_REVISION, "original model revision drift")
    require(model.get("tokenizer_length") == EXPECTED_TOKENIZER_LENGTH, "original tokenizer length drift")
    require(
        model.get("critical_file_sha256", {}).get("chat_template.jinja") == EXPECTED_TEMPLATE_SHA256,
        "original template binding drift",
    )
    require(
        model.get("critical_file_sha256", {}).get("model.safetensors.index.json") == EXPECTED_INDEX_SHA256,
        "original model-index binding drift",
    )
    render = original_plan.get("render_contract", {})
    require(render.get("assistant_only") is True, "original assistant-only contract drift")
    require(render.get("max_sequence_length") == MAX_RENDER_TOKENS, "original render length drift")
    require(render.get("causal_shift") == "logits[:-1] against labels[1:]", "original causal shift drift")
    require(render.get("packing") is False and render.get("padding") is False, "original packing drift")
    dataset = original_plan.get("dataset", {})
    require(dataset.get("rows") == EXPECTED_TRAIN_ROWS, "original train row count drift")
    require(
        dataset.get("shifted_supervised_tokens", {}).get("total") == EXPECTED_TRAIN_TOKENS,
        "original supervised-token total drift",
    )


def validate_loss_plan(static: dict[str, Any]) -> dict[str, Any]:
    """Validate every consumed plan edge before importing the GPU runtime."""

    validate_original_plan(static["original_plan"])
    plan = static["loss_plan"]
    source = plan["source"]
    require(source.get("split_rows", {}).get("train") == EXPECTED_TRAIN_ROWS, "source train rows drift")
    require(
        source.get("split_rows", {}).get("validation") == EXPECTED_VALIDATION_ROWS,
        "source validation rows drift",
    )
    require(plan.get("seed") == SEED, "loss-plan seed drift")
    require(plan.get("model", {}).get("tokenizer_length") == EXPECTED_TOKENIZER_LENGTH, "plan tokenizer drift")
    require(
        plan.get("model", {}).get("critical_file_sha256", {}).get("chat_template.jinja")
        == EXPECTED_TEMPLATE_SHA256,
        "loss-plan template drift",
    )

    expected_split = {
        "train": {
            "rows": EXPECTED_TRAIN_ROWS,
            "windows": EXPECTED_TRAIN_MICRO_WINDOWS,
            "tokens": EXPECTED_TRAIN_TOKENS,
            "curated_rows": EXPECTED_TRAIN_CURATED_ROWS,
            "promoted_rows": EXPECTED_TRAIN_PROMOTED_ROWS,
            "curated_tokens": EXPECTED_TRAIN_CURATED_TOKENS,
            "promoted_tokens": EXPECTED_TRAIN_PROMOTED_TOKENS,
            "systemless_windows": EXPECTED_TRAIN_SYSTEMLESS_WINDOWS,
            "systemless_tokens": EXPECTED_TRAIN_SYSTEMLESS_TOKENS,
            "long_rows": EXPECTED_TRAIN_LONG_ROWS,
        },
        "validation": {
            "rows": EXPECTED_VALIDATION_ROWS,
            "windows": EXPECTED_VALIDATION_WINDOWS,
            "tokens": EXPECTED_VALIDATION_TOKENS,
            "curated_rows": EXPECTED_VALIDATION_CURATED_ROWS,
            "promoted_rows": EXPECTED_VALIDATION_PROMOTED_ROWS,
            "curated_tokens": EXPECTED_VALIDATION_CURATED_TOKENS,
            "promoted_tokens": EXPECTED_VALIDATION_PROMOTED_TOKENS,
            "systemless_windows": EXPECTED_VALIDATION_SYSTEMLESS_WINDOWS,
            "systemless_tokens": EXPECTED_VALIDATION_SYSTEMLESS_TOKENS,
            "long_rows": EXPECTED_VALIDATION_LONG_ROWS,
        },
    }
    rows_by_task: dict[str, dict[str, dict[str, Any]]] = {}
    windows_by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for split in ("train", "validation"):
        split_plan = plan.get("splits", {}).get(split, {})
        expected = expected_split[split]
        require(split_plan.get("rows") == expected["rows"], f"{split}: plan row count drift")
        require(split_plan.get("windows") == expected["windows"], f"{split}: plan window count drift")
        require(split_plan.get("curated_rows") == expected["curated_rows"], f"{split}: curated rows drift")
        require(split_plan.get("promoted_rows") == expected["promoted_rows"], f"{split}: promoted rows drift")
        require(
            split_plan.get("shifted_supervised_tokens", {}).get("total") == expected["tokens"],
            f"{split}: plan token total drift",
        )
        require(
            split_plan.get("systemless_windows") == expected["systemless_windows"],
            f"{split}: plan systemless-window count drift",
        )
        require(
            split_plan.get("systemless_shifted_supervised_tokens") == expected["systemless_tokens"],
            f"{split}: plan systemless-token count drift",
        )
        require(split_plan.get("long_rows") == expected["long_rows"], f"{split}: plan long-row count drift")
        row_plans = split_plan.get("row_plans")
        require(isinstance(row_plans, list) and len(row_plans) == expected["rows"], f"{split}: row plans drift")
        task_index: dict[str, dict[str, Any]] = {}
        window_index: dict[str, dict[str, Any]] = {}
        curated_tokens = 0
        promoted_tokens = 0
        systemless_tokens = 0
        systemless_windows = 0
        long_rows = 0
        for line_number, (raw, row_plan) in enumerate(zip(static["raw_lines"][split], row_plans, strict=True), 1):
            require(isinstance(row_plan, dict), f"{split}:{line_number}: row plan is not an object")
            require(row_plan.get("line_number") == line_number, f"{split}:{line_number}: line number drift")
            require(sha256_bytes(raw) == row_plan.get("line_sha256"), f"{split}:{line_number}: line hash drift")
            row = json.loads(raw)
            task_id = row.get("task_id")
            require(isinstance(task_id, str) and task_id, f"{split}:{line_number}: task id missing")
            require(task_id == row_plan.get("task_id"), f"{split}:{line_number}: task binding drift")
            require(task_id not in task_index, f"{split}: duplicate task id {task_id}")
            require(row.get("schema_version") == "rdk_sft_sample.v1", f"{task_id}: schema drift")
            require(row.get("profile") == "agentic" and row.get("split") == split, f"{task_id}: profile/split drift")
            metadata = row.get("metadata")
            require(isinstance(metadata, dict), f"{task_id}: metadata missing")
            promoted = bool(metadata.get("promoted_from_needs_review", False))
            require(promoted == row_plan.get("promoted"), f"{task_id}: promotion binding drift")
            spans = row_plan.get("assistant_spans")
            windows = row_plan.get("windows")
            require(isinstance(spans, list) and spans, f"{task_id}: assistant spans missing")
            require(isinstance(windows, list) and windows, f"{task_id}: windows missing")
            require(row_plan.get("assistant_turns") == len(spans), f"{task_id}: assistant-turn count drift")
            require(row_plan.get("full_input_tokens", 0) <= MAX_RENDER_TOKENS, f"{task_id}: full render too long")
            require(row_plan.get("longer_than_window") == (row_plan["full_input_tokens"] > MAX_WINDOW_TOKENS), f"{task_id}: long flag drift")
            long_rows += int(row_plan["longer_than_window"])
            covered_span_indices: list[int] = []
            row_tokens = 0
            for part_index, window in enumerate(windows):
                require(isinstance(window, dict), f"{task_id}#{part_index}: window is not an object")
                window_id = f"{task_id}#{part_index}"
                require(window.get("window_id") == window_id, f"{task_id}#{part_index}: window id drift")
                require(window_id not in window_index, f"{split}: duplicate window id {window_id}")
                require(window.get("part_index") == part_index, f"{window_id}: part index drift")
                require(window.get("part_count") == len(windows), f"{window_id}: part count drift")
                source_start = window.get("source_start")
                source_end = window.get("source_end")
                require(
                    isinstance(source_start, int)
                    and isinstance(source_end, int)
                    and 0 <= source_start < source_end <= row_plan["full_input_tokens"],
                    f"{window_id}: invalid source slice",
                )
                require(source_end - source_start == window.get("input_tokens") <= MAX_WINDOW_TOKENS, f"{window_id}: input length drift")
                require(window.get("original_input_tokens") == row_plan["full_input_tokens"], f"{window_id}: original length drift")
                require(window.get("position_id_start") == source_start, f"{window_id}: position start drift")
                require(window.get("position_id_end_exclusive") == source_end, f"{window_id}: position end drift")
                require(window.get("position_ids_mode") == "absolute_source_offsets", f"{window_id}: position mode drift")
                indices = window.get("assigned_assistant_span_indices")
                ranges = window.get("assigned_source_label_spans")
                require(isinstance(indices, list) and indices, f"{window_id}: assigned spans missing")
                require(isinstance(ranges, list) and len(ranges) == len(indices), f"{window_id}: assigned ranges drift")
                assigned_tokens = 0
                for span_index, span_range in zip(indices, ranges, strict=True):
                    require(isinstance(span_index, int) and 0 <= span_index < len(spans), f"{window_id}: span index invalid")
                    require(span_range == spans[span_index], f"{window_id}: source span binding drift")
                    span_start, span_end = map(int, span_range)
                    require(source_start <= span_start - 1 and span_end <= source_end, f"{window_id}: causal span boundary drift")
                    assigned_tokens += span_end - span_start
                require(assigned_tokens == window.get("shifted_supervised_tokens") > 0, f"{window_id}: token count drift")
                require(all(isinstance(window.get(key), str) and len(window[key]) == 64 for key in ("input_ids_sha256", "labels_sha256", "position_ids_sha256")), f"{window_id}: digest missing")
                covered_span_indices.extend(indices)
                row_tokens += assigned_tokens
                if source_start > 0:
                    systemless_windows += 1
                    systemless_tokens += assigned_tokens
                window_index[window_id] = {"row_plan": row_plan, "window": window}
            require(sorted(covered_span_indices) == list(range(len(spans))), f"{task_id}: assistant span coverage drift")
            require(row_tokens == row_plan.get("shifted_supervised_tokens"), f"{task_id}: row token total drift")
            require(
                row_plan.get("system_context_in_all_windows") == all(window["source_start"] == 0 for window in windows),
                f"{task_id}: system-context flag drift",
            )
            if promoted:
                promoted_tokens += row_tokens
            else:
                curated_tokens += row_tokens
            task_index[task_id] = row_plan
        require(len(window_index) == expected["windows"], f"{split}: window index size drift")
        require(curated_tokens == expected["curated_tokens"], f"{split}: curated token total drift")
        require(promoted_tokens == expected["promoted_tokens"], f"{split}: promoted token total drift")
        require(systemless_windows == expected["systemless_windows"], f"{split}: derived systemless count drift")
        require(systemless_tokens == expected["systemless_tokens"], f"{split}: derived systemless tokens drift")
        require(long_rows == expected["long_rows"], f"{split}: derived long-row count drift")
        rows_by_task[split] = task_index
        windows_by_id[split] = window_index

    require(not set(rows_by_task["train"]) & set(rows_by_task["validation"]), "train/validation task leakage")
    schedule = plan.get("schedule", {})
    require(schedule.get("algorithm") == "capacity_constrained_lpt_micro_windows.v1", "schedule algorithm drift")
    require(schedule.get("optimizer_steps") == OPTIMIZER_STEPS, "optimizer-step count drift")
    require(schedule.get("seven_micro_window_steps") == 4, "seven-window step count drift")
    require(schedule.get("eight_micro_window_steps") == 115, "eight-window step count drift")
    require(schedule.get("micro_window_loss_reduction") == "sum", "micro loss reduction drift")
    require(
        schedule.get("optimizer_window_normalization") == "optimizer_window_shifted_supervised_tokens",
        "optimizer normalization drift",
    )
    require(
        schedule.get("token_weighting")
        == "sum_cross_entropy_per_micro_window_divided_by_optimizer_step_supervised_tokens",
        "token weighting drift",
    )
    steps = schedule.get("steps")
    require(isinstance(steps, list) and len(steps) == OPTIMIZER_STEPS, "schedule steps drift")
    ordered_windows: list[str] = []
    ordered_tasks: list[str] = []
    scheduled_tokens = 0
    capacities: list[int] = []
    construction_bins: set[int] = set()
    for optimizer_step, step_plan in enumerate(steps, 1):
        require(step_plan.get("optimizer_step") == optimizer_step, f"step {optimizer_step}: ordinal drift")
        capacity = step_plan.get("capacity")
        micros = step_plan.get("micro_windows")
        require(capacity in (7, 8) and isinstance(micros, list) and len(micros) == capacity, f"step {optimizer_step}: capacity drift")
        require(step_plan.get("construction_bin") not in construction_bins, f"step {optimizer_step}: duplicate construction bin")
        construction_bins.add(step_plan["construction_bin"])
        capacities.append(capacity)
        step_tokens = 0
        step_input_tokens = 0
        curated_micros = 0
        for micro in micros:
            window_id = micro.get("window_id")
            require(window_id in windows_by_id["train"], f"step {optimizer_step}: unknown window {window_id}")
            binding = windows_by_id["train"][window_id]
            row_plan = binding["row_plan"]
            window = binding["window"]
            expected_fields = {
                "task_id": row_plan["task_id"],
                "line_number": row_plan["line_number"],
                "line_sha256": row_plan["line_sha256"],
                "part_index": window["part_index"],
                "promoted": row_plan["promoted"],
                "input_tokens": window["input_tokens"],
                "shifted_supervised_tokens": window["shifted_supervised_tokens"],
                "input_ids_sha256": window["input_ids_sha256"],
                "labels_sha256": window["labels_sha256"],
            }
            require(all(micro.get(key) == value for key, value in expected_fields.items()), f"{window_id}: schedule binding drift")
            ordered_windows.append(window_id)
            ordered_tasks.append(row_plan["task_id"])
            step_tokens += window["shifted_supervised_tokens"]
            step_input_tokens += window["input_tokens"]
            curated_micros += not row_plan["promoted"]
        require(step_tokens == step_plan.get("shifted_supervised_tokens"), f"step {optimizer_step}: token total drift")
        require(step_input_tokens == step_plan.get("input_tokens"), f"step {optimizer_step}: input total drift")
        require(curated_micros == step_plan.get("curated_micro_windows"), f"step {optimizer_step}: curated count drift")
        require(capacity - curated_micros == step_plan.get("promoted_micro_windows"), f"step {optimizer_step}: promoted count drift")
        scheduled_tokens += step_tokens
    require(construction_bins == set(range(OPTIMIZER_STEPS)), "construction-bin inventory drift")
    require(capacities.count(7) == 4 and capacities.count(8) == 115, "schedule capacity inventory drift")
    require(len(ordered_windows) == len(set(ordered_windows)) == EXPECTED_TRAIN_MICRO_WINDOWS, "schedule window coverage drift")
    require(set(ordered_windows) == set(windows_by_id["train"]), "schedule does not cover train windows exactly once")
    require(scheduled_tokens == EXPECTED_TRAIN_TOKENS, "schedule supervised-token total drift")
    require(digest_ordered_strings(ordered_windows) == EXPECTED_FINAL_WINDOW_IDS_SHA256, "final window order digest drift")

    first10_micros = [micro for step in steps[:10] for micro in step["micro_windows"]]
    first10_windows = [micro["window_id"] for micro in first10_micros]
    first10_tasks = [micro["task_id"] for micro in first10_micros]
    first10_curated = [micro for micro in first10_micros if not micro["promoted"]]
    first10_promoted = [micro for micro in first10_micros if micro["promoted"]]
    require(len(first10_micros) == EXPECTED_STEP10_MICROS, "step10 micro count drift")
    require(len(set(first10_tasks)) == EXPECTED_STEP10_UNIQUE_TASKS, "step10 unique-task count drift")
    require(sum(micro["shifted_supervised_tokens"] for micro in first10_micros) == EXPECTED_STEP10_TOKENS, "step10 token total drift")
    require(len(first10_curated) == EXPECTED_STEP10_CURATED_MICROS, "step10 curated micro count drift")
    require(sum(micro["shifted_supervised_tokens"] for micro in first10_curated) == EXPECTED_STEP10_CURATED_TOKENS, "step10 curated token drift")
    require(len(first10_promoted) == EXPECTED_STEP10_PROMOTED_MICROS, "step10 promoted micro count drift")
    require(sum(micro["shifted_supervised_tokens"] for micro in first10_promoted) == EXPECTED_STEP10_PROMOTED_TOKENS, "step10 promoted token drift")
    require(digest_ordered_strings(first10_windows) == EXPECTED_STEP10_WINDOW_IDS_SHA256, "step10 window order drift")
    require(digest_ordered_strings(first10_tasks) == EXPECTED_STEP10_TASK_IDS_SHA256, "step10 task order drift")
    return {
        "rows_by_task": rows_by_task,
        "windows_by_id": windows_by_id,
        "schedule_steps": steps,
        "ordered_train_windows": ordered_windows,
        "ordered_train_tasks": ordered_tasks,
    }


def materialize_window(
    static: dict[str, Any],
    plan_state: dict[str, Any],
    common: Any,
    tokenizer: Any,
    split: str,
    window_id: str,
) -> dict[str, Any]:
    binding = plan_state["windows_by_id"][split].get(window_id)
    require(binding is not None, f"{split}: unbound window {window_id}")
    row_plan = binding["row_plan"]
    window = binding["window"]
    raw = static["raw_lines"][split][row_plan["line_number"] - 1]
    require(sha256_bytes(raw) == row_plan["line_sha256"], f"{window_id}: source line changed")
    row = json.loads(raw)
    require(row.get("task_id") == row_plan["task_id"], f"{window_id}: task id changed")
    promoted = bool(row["metadata"].get("promoted_from_needs_review", False))
    require(promoted == row_plan["promoted"], f"{window_id}: promotion status changed")
    rendered = common.render_agentic_sample(tokenizer, row, max_sequence_length=MAX_RENDER_TOKENS)
    full_input_ids = list(map(int, rendered.input_ids))
    full_labels = list(map(int, rendered.labels))
    require(len(full_input_ids) == row_plan["full_input_tokens"], f"{window_id}: full token length drift")
    require(sha256_i64(full_input_ids) == row_plan["full_input_ids_sha256"], f"{window_id}: full input digest drift")
    require(sha256_i64(full_labels) == row_plan["full_labels_sha256"], f"{window_id}: full label digest drift")
    require([list(span) for span in rendered.assistant_spans] == row_plan["assistant_spans"], f"{window_id}: assistant spans drift")
    require(rendered.shifted_supervised_tokens == row_plan["shifted_supervised_tokens"], f"{window_id}: full label count drift")
    source_start = window["source_start"]
    source_end = window["source_end"]
    input_ids = full_input_ids[source_start:source_end]
    labels = [-100] * len(input_ids)
    for span_start, span_end in window["assigned_source_label_spans"]:
        require(source_start <= span_start - 1 and span_end <= source_end, f"{window_id}: assigned span outside window")
        require(all(value != -100 for value in full_labels[span_start:span_end]), f"{window_id}: source assistant label masked")
        labels[span_start - source_start : span_end - source_start] = full_labels[span_start:span_end]
    position_ids = list(range(source_start, source_end))
    require(labels[0] == -100, f"{window_id}: local first token supervised")
    require(len(input_ids) == window["input_tokens"] <= MAX_WINDOW_TOKENS, f"{window_id}: local input length drift")
    require(sum(value != -100 for value in labels[1:]) == window["shifted_supervised_tokens"], f"{window_id}: local token count drift")
    require(sha256_i64(input_ids) == window["input_ids_sha256"], f"{window_id}: local input digest drift")
    require(sha256_i64(labels) == window["labels_sha256"], f"{window_id}: local labels digest drift")
    require(sha256_i64(position_ids) == window["position_ids_sha256"], f"{window_id}: absolute position digest drift")
    return {
        "task_id": row_plan["task_id"],
        "window_id": window_id,
        "promoted": promoted,
        "systemless": source_start > 0,
        "long_row": bool(row_plan["longer_than_window"]),
        "input_ids": input_ids,
        "labels": labels,
        "position_ids": position_ids,
        "shifted_supervised_tokens": window["shifted_supervised_tokens"],
    }


def load_runtime(args: argparse.Namespace) -> dict[str, Any]:
    require(args.common_script.name == "qwen3_agentic_common.py", "common script filename drift")
    sys.path.insert(0, str(args.common_script.parent))
    import bitsandbytes as bnb
    import peft
    import qwen3_agentic_common as common
    import torch
    import torch.nn.functional as functional
    import transformers
    from peft import LoraConfig, PeftConfig, get_peft_model, get_peft_model_state_dict
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file as load_safetensors_file
    from transformers import AutoModelForCausalLM, AutoTokenizer

    require(Path(common.__file__).resolve() == args.common_script.resolve(), "imported common module path drift")
    require(torch.__version__ == EXPECTED_TORCH, f"torch version drift: {torch.__version__}")
    require(torch.version.hip == EXPECTED_TORCH_HIP, f"torch HIP version drift: {torch.version.hip}")
    require(transformers.__version__ == EXPECTED_TRANSFORMERS, f"transformers version drift: {transformers.__version__}")
    require(peft.__version__ == EXPECTED_PEFT, f"peft version drift: {peft.__version__}")
    require(bnb.__version__ == EXPECTED_BITSANDBYTES, f"bitsandbytes version drift: {bnb.__version__}")
    require(torch.cuda.is_available(), "HIP device unavailable")
    require(torch.cuda.device_count() == 1, "formal trainer requires exactly one visible GPU")
    torch.cuda.set_device(0)
    return {
        "torch": torch,
        "functional": functional,
        "bnb": bnb,
        "peft": peft,
        "transformers": transformers,
        "common": common,
        "LoraConfig": LoraConfig,
        "PeftConfig": PeftConfig,
        "get_peft_model": get_peft_model,
        "get_peft_model_state_dict": get_peft_model_state_dict,
        "set_peft_model_state_dict": set_peft_model_state_dict,
        "load_safetensors_file": load_safetensors_file,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "versions": {
            "python": sys.version,
            "torch": torch.__version__,
            "torch_hip": torch.version.hip,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
            "bitsandbytes": bnb.__version__,
        },
    }


def seed_runtime(runtime: dict[str, Any]) -> None:
    torch = runtime["torch"]
    random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(0)


def load_tokenizer(runtime: dict[str, Any], args: argparse.Namespace) -> Any:
    tokenizer = runtime["AutoTokenizer"].from_pretrained(
        args.model,
        local_files_only=True,
        trust_remote_code=False,
    )
    require(len(tokenizer) == EXPECTED_TOKENIZER_LENGTH, "tokenizer length drift")
    require(tokenizer.chat_template == (args.model / "chat_template.jinja").read_text(), "active template drift")
    return tokenizer


def validate_lora_config(config: Any) -> None:
    require(config.r == 8, "LoRA rank drift")
    require(config.lora_alpha == 16, "LoRA alpha drift")
    require(float(config.lora_dropout) == 0.0, "LoRA dropout drift")
    require(config.bias == "none", "LoRA bias drift")
    require(set(config.target_modules) == set(LORA_TARGETS), "LoRA targets drift")
    require(config.inference_mode is False, "LoRA config is inference-only")
    require(getattr(config, "use_rslora", False) is False, "RS-LoRA drift")


def trainable_signature(trainable: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "shape": list(parameter.shape),
            "dtype": str(parameter.dtype),
            "device": str(parameter.device),
        }
        for name, parameter in trainable
    ]


def adapter_state_digest(runtime: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    torch = runtime["torch"]
    digest = hashlib.sha256()
    elements = 0
    for name in sorted(state):
        source = state[name].detach()
        require(source.dtype == torch.float32, f"adapter state dtype drift: {name}={source.dtype}")
        require(torch.isfinite(source).all().item(), f"nonfinite adapter tensor: {name}")
        tensor = source.contiguous().cpu()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tuple(tensor.shape)).encode("ascii") + b"\0")
        digest.update(tensor.numpy().tobytes(order="C"))
        elements += tensor.numel()
    require(len(state) == EXPECTED_TRAINABLE_TENSORS, "adapter tensor inventory drift")
    require(elements == EXPECTED_TRAINABLE_ELEMENTS, "adapter element inventory drift")
    return {"sha256": digest.hexdigest(), "tensors": len(state), "elements": elements}


def adapter_digest(runtime: dict[str, Any], model: Any) -> dict[str, Any]:
    state = runtime["get_peft_model_state_dict"](model, adapter_name="default")
    return adapter_state_digest(runtime, state)


def build_model(
    runtime: dict[str, Any],
    args: argparse.Namespace,
    adapter_checkpoint: Path | None = None,
) -> tuple[Any, list[tuple[str, Any]], dict[str, Any]]:
    torch = runtime["torch"]
    bnb = runtime["bnb"]
    load_started = time.time()
    model = runtime["AutoModelForCausalLM"].from_pretrained(
        args.model,
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
        device_map={"": 0},
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    linear4 = {name: module for name, module in model.named_modules() if isinstance(module, bnb.nn.Linear4bit)}
    require(len(linear4) == EXPECTED_LINEAR4BIT, f"Linear4bit inventory drift: {len(linear4)}")
    require(not [name for name, parameter in model.named_parameters() if parameter.device.type == "meta"], "meta base parameter")
    require(not [name for name, parameter in model.named_parameters() if parameter.device.type == "cpu"], "CPU base parameter")
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    norm_count = 0
    for module in model.modules():
        if module.__class__.__name__.endswith("RMSNorm"):
            module.to(torch.float32)
            norm_count += 1
    require(norm_count == EXPECTED_RMSNORM, f"RMSNorm inventory drift: {norm_count}")
    model.config.use_cache = False
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})

    if adapter_checkpoint is None:
        config = runtime["LoraConfig"](
            r=8,
            lora_alpha=16,
            lora_dropout=0.0,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=list(LORA_TARGETS),
            inference_mode=False,
            use_rslora=False,
        )
    else:
        config = runtime["PeftConfig"].from_pretrained(adapter_checkpoint, local_files_only=True)
        config.inference_mode = False
    validate_lora_config(config)
    model = runtime["get_peft_model"](
        model,
        config,
        autocast_adapter_dtype=False,
        low_cpu_mem_usage=False,
    )
    for _, parameter in model.named_parameters():
        if parameter.requires_grad and parameter.dtype != torch.float32:
            parameter.data = parameter.data.to(torch.float32)
    if adapter_checkpoint is not None:
        adapter_path = adapter_checkpoint / "adapter_model.safetensors"
        require(adapter_path.is_file() and not adapter_path.is_symlink(), "checkpoint adapter file missing")
        adapter_state = runtime["load_safetensors_file"](str(adapter_path), device="cpu")
        result = runtime["set_peft_model_state_dict"](
            model,
            adapter_state,
            adapter_name="default",
            ignore_mismatched_sizes=False,
            low_cpu_mem_usage=False,
        )
        missing_adapter = [key for key in result.missing_keys if "lora_" in key]
        require(not missing_adapter, f"missing adapter keys: {missing_adapter[:8]}")
        require(not result.unexpected_keys, f"unexpected adapter keys: {result.unexpected_keys[:8]}")
        del adapter_state

    lora_modules = {
        name: module
        for name, module in model.named_modules()
        if hasattr(module, "lora_A") and "default" in module.lora_A
    }
    require(len(lora_modules) == EXPECTED_LORA_MODULES, f"LoRA module inventory drift: {len(lora_modules)}")
    trainable = [(name, parameter) for name, parameter in model.named_parameters() if parameter.requires_grad]
    require(len(trainable) == EXPECTED_TRAINABLE_TENSORS, f"trainable tensor inventory drift: {len(trainable)}")
    require(
        all("lora_A.default.weight" in name or "lora_B.default.weight" in name for name, _ in trainable),
        "non-LoRA trainable parameter",
    )
    require(all(parameter.dtype == torch.float32 for _, parameter in trainable), "trainable parameter is not FP32")
    require(sum(parameter.numel() for _, parameter in trainable) == EXPECTED_TRAINABLE_ELEMENTS, "trainable element count drift")
    require(
        EXPECTED_TRAINABLE_ELEMENTS
        == sum(8 * (module.in_features + module.out_features) for module in lora_modules.values()),
        "LoRA shape-derived element count drift",
    )
    if adapter_checkpoint is None:
        b_parameters = [parameter for name, parameter in trainable if "lora_B.default.weight" in name]
        require(len(b_parameters) == EXPECTED_LORA_MODULES, "LoRA-B inventory drift")
        require(all(torch.count_nonzero(parameter).item() == 0 for parameter in b_parameters), "LoRA-B initialization drift")
    model.train()
    return model, trainable, {
        "load_seconds": time.time() - load_started,
        "linear4bit_modules": len(linear4),
        "rmsnorm_fp32_modules": norm_count,
        "lora_modules": len(lora_modules),
        "trainable_signature": trainable_signature(trainable),
    }


def make_optimizer(runtime: dict[str, Any], trainable: list[tuple[str, Any]]) -> Any:
    torch = runtime["torch"]
    optimizer = torch.optim.AdamW(
        [parameter for _, parameter in trainable],
        lr=LEARNING_RATE,
        betas=ADAM_BETAS,
        eps=ADAM_EPS,
        weight_decay=WEIGHT_DECAY,
        foreach=False,
        fused=False,
    )
    require(len(optimizer.param_groups) == 1, "optimizer param-group count drift")
    actual_parameters = optimizer.param_groups[0]["params"]
    expected_parameters = [parameter for _, parameter in trainable]
    require(
        len(actual_parameters) == len(expected_parameters)
        and all(actual is expected for actual, expected in zip(actual_parameters, expected_parameters, strict=True)),
        "optimizer parameter order drift",
    )
    return optimizer


def optimizer_evidence(
    runtime: dict[str, Any],
    optimizer: Any,
    trainable: list[tuple[str, Any]],
    expected_step: int,
) -> dict[str, Any]:
    torch = runtime["torch"]
    group = optimizer.param_groups[0]
    require(group["lr"] == LEARNING_RATE, "optimizer learning-rate drift")
    require(tuple(group["betas"]) == ADAM_BETAS, "optimizer beta drift")
    require(group["eps"] == ADAM_EPS, "optimizer epsilon drift")
    require(group["weight_decay"] == WEIGHT_DECAY, "optimizer weight-decay drift")
    require(group.get("foreach") is False and group.get("fused") is False, "optimizer kernel mode drift")
    if expected_step == 0:
        require(not optimizer.state, "fresh optimizer unexpectedly has state")
        return {
            "sha256": sha256_bytes(b"empty-adamw-state.v1"),
            "state_count": 0,
            "step": 0,
            "exp_avg_elements": 0,
            "exp_avg_sq_elements": 0,
        }
    require(len(optimizer.state) == EXPECTED_TRAINABLE_TENSORS, "optimizer state count drift")
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "lr": group["lr"],
                "betas": list(group["betas"]),
                "eps": group["eps"],
                "weight_decay": group["weight_decay"],
                "foreach": group.get("foreach"),
                "fused": group.get("fused"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    exp_avg_elements = 0
    exp_avg_sq_elements = 0
    observed_steps: set[int] = set()
    for parameter_name, parameter in trainable:
        require(parameter in optimizer.state, f"optimizer state missing: {parameter_name}")
        state = optimizer.state[parameter]
        require(set(state) == {"step", "exp_avg", "exp_avg_sq"}, f"optimizer state fields drift: {parameter_name}")
        digest.update(parameter_name.encode("utf-8") + b"\0")
        for state_name in ("exp_avg", "exp_avg_sq", "step"):
            value = state[state_name]
            require(torch.is_tensor(value), f"optimizer state is not a tensor: {parameter_name}:{state_name}")
            require(torch.isfinite(value).all().item(), f"nonfinite optimizer state: {parameter_name}:{state_name}")
            if state_name in ("exp_avg", "exp_avg_sq"):
                require(value.dtype == torch.float32, f"optimizer moment dtype drift: {parameter_name}:{state_name}")
                require(tuple(value.shape) == tuple(parameter.shape), f"optimizer moment shape drift: {parameter_name}:{state_name}")
                if state_name == "exp_avg":
                    exp_avg_elements += value.numel()
                else:
                    exp_avg_sq_elements += value.numel()
            else:
                observed_steps.add(int(value.item()))
            tensor = value.detach().contiguous().cpu()
            digest.update(state_name.encode("ascii") + b"\0")
            digest.update(str(tensor.dtype).encode("ascii") + b"\0")
            digest.update(str(tuple(tensor.shape)).encode("ascii") + b"\0")
            digest.update(tensor.numpy().tobytes(order="C"))
    require(observed_steps == {expected_step}, f"optimizer step drift: {observed_steps}")
    require(exp_avg_elements == EXPECTED_TRAINABLE_ELEMENTS, "optimizer first-moment size drift")
    require(exp_avg_sq_elements == EXPECTED_TRAINABLE_ELEMENTS, "optimizer second-moment size drift")
    return {
        "sha256": digest.hexdigest(),
        "state_count": len(optimizer.state),
        "step": expected_step,
        "exp_avg_elements": exp_avg_elements,
        "exp_avg_sq_elements": exp_avg_sq_elements,
    }


def capture_rng(runtime: dict[str, Any]) -> dict[str, Any]:
    torch = runtime["torch"]
    return {
        "python_random_state": random.getstate(),
        "torch_cpu_rng_state": torch.get_rng_state().clone(),
        "torch_cuda_rng_state_all": [state.clone() for state in torch.cuda.get_rng_state_all()],
    }


def rng_digest(runtime: dict[str, Any], payload: dict[str, Any]) -> str:
    torch = runtime["torch"]
    digest = hashlib.sha256(repr(payload["python_random_state"]).encode("ascii"))
    cpu = payload["torch_cpu_rng_state"].detach().contiguous().cpu()
    require(cpu.dtype == torch.uint8, "CPU RNG state dtype drift")
    digest.update(cpu.numpy().tobytes(order="C"))
    cuda_states = payload["torch_cuda_rng_state_all"]
    require(len(cuda_states) == 1, "GPU RNG state count drift")
    for state in cuda_states:
        value = state.detach().contiguous().cpu()
        require(value.dtype == torch.uint8, "GPU RNG state dtype drift")
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def restore_rng_last(runtime: dict[str, Any], payload: dict[str, Any]) -> None:
    torch = runtime["torch"]
    random.setstate(payload["python_random_state"])
    torch.set_rng_state(payload["torch_cpu_rng_state"])
    torch.cuda.set_rng_state_all(payload["torch_cuda_rng_state_all"])
    current = capture_rng(runtime)
    require(random.getstate() == payload["python_random_state"], "Python RNG restore drift")
    require(torch.equal(current["torch_cpu_rng_state"], payload["torch_cpu_rng_state"]), "CPU RNG restore drift")
    require(
        all(
            torch.equal(actual.cpu(), expected.cpu())
            for actual, expected in zip(
                current["torch_cuda_rng_state_all"], payload["torch_cuda_rng_state_all"], strict=True
            )
        ),
        "GPU RNG restore drift",
    )


def forward_loss_sum(
    runtime: dict[str, Any],
    model: Any,
    materialized: dict[str, Any],
    *,
    backward_denominator: int | None,
) -> tuple[float, int]:
    torch = runtime["torch"]
    functional = runtime["functional"]
    input_ids = torch.tensor([materialized["input_ids"]], dtype=torch.long, device="cuda:0")
    labels = torch.tensor([materialized["labels"]], dtype=torch.long, device="cuda:0")
    position_ids = torch.tensor([materialized["position_ids"]], dtype=torch.long, device="cuda:0")
    attention_mask = torch.ones_like(input_ids)
    supervised_mask = labels[0, 1:] != -100
    logit_positions = torch.arange(input_ids.shape[1] - 1, device="cuda:0")[supervised_mask]
    targets = labels[0, 1:][supervised_mask]
    expected_tokens = materialized["shifted_supervised_tokens"]
    require(logit_positions.numel() == expected_tokens > 0, f"{materialized['window_id']}: selective position drift")
    require(targets.numel() == expected_tokens, f"{materialized['window_id']}: target count drift")
    require(targets.min().item() >= 0 and targets.max().item() < model.config.vocab_size, "target token out of range")
    with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        outputs = model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            use_cache=False,
            logits_to_keep=logit_positions,
        )
    require(
        tuple(outputs.logits.shape) == (1, expected_tokens, int(model.config.vocab_size)),
        f"{materialized['window_id']}: selective logits shape drift",
    )
    loss_sum = functional.cross_entropy(outputs.logits[0].float(), targets, reduction="sum")
    require(torch.isfinite(loss_sum).item(), f"{materialized['window_id']}: nonfinite loss")
    loss_value = float(loss_sum.detach().cpu())
    if backward_denominator is not None:
        require(isinstance(backward_denominator, int) and backward_denominator > 0, "invalid backward denominator")
        (loss_sum / backward_denominator).backward()
    del outputs, loss_sum, input_ids, labels, position_ids, attention_mask, supervised_mask, logit_positions, targets
    return loss_value, expected_tokens


def empty_loss_buckets() -> dict[str, dict[str, Any]]:
    return {
        name: {"cross_entropy_sum": 0.0, "shifted_supervised_tokens": 0, "micro_windows": 0, "tasks": set()}
        for name in ("all", "curated", "promoted", "systemless", "long", "promoted_long")
    }


def add_loss_bucket(
    buckets: dict[str, dict[str, Any]],
    materialized: dict[str, Any],
    loss_sum: float,
) -> None:
    names = ["all", "promoted" if materialized["promoted"] else "curated"]
    if materialized["systemless"]:
        names.append("systemless")
    if materialized["long_row"]:
        names.append("long")
        if materialized["promoted"]:
            names.append("promoted_long")
    for name in names:
        bucket = buckets[name]
        bucket["cross_entropy_sum"] += loss_sum
        bucket["shifted_supervised_tokens"] += materialized["shifted_supervised_tokens"]
        bucket["micro_windows"] += 1
        bucket["tasks"].add(materialized["task_id"])


def finalize_loss_buckets(buckets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, bucket in buckets.items():
        tokens = int(bucket["shifted_supervised_tokens"])
        loss = float(bucket["cross_entropy_sum"]) / tokens if tokens else None
        result[name] = {
            "cross_entropy_sum": float(bucket["cross_entropy_sum"]),
            "shifted_supervised_tokens": tokens,
            "micro_windows": int(bucket["micro_windows"]),
            "unique_tasks": len(bucket["tasks"]),
            "mean_cross_entropy": loss,
            "perplexity": (math.exp(loss) if loss < 709.0 else float("inf")) if loss is not None else None,
        }
    return result


def train_optimizer_step(
    runtime: dict[str, Any],
    static: dict[str, Any],
    plan_state: dict[str, Any],
    tokenizer: Any,
    model: Any,
    optimizer: Any,
    trainable: list[tuple[str, Any]],
    optimizer_step: int,
) -> dict[str, Any]:
    torch = runtime["torch"]
    common = runtime["common"]
    step_plan = plan_state["schedule_steps"][optimizer_step - 1]
    require(step_plan["optimizer_step"] == optimizer_step, "selected optimizer step drift")
    denominator = int(step_plan["shifted_supervised_tokens"])
    require_no_gradients(trainable, f"optimizer step {optimizer_step} entry")
    optimizer.zero_grad(set_to_none=True)
    buckets = empty_loss_buckets()
    window_ids: list[str] = []
    task_ids: list[str] = []
    cache_releases = 0
    started = time.time()
    for micro in step_plan["micro_windows"]:
        materialized = materialize_window(
            static,
            plan_state,
            common,
            tokenizer,
            "train",
            micro["window_id"],
        )
        require(materialized["shifted_supervised_tokens"] == micro["shifted_supervised_tokens"], "micro token binding drift")
        loss_sum, token_count = forward_loss_sum(
            runtime,
            model,
            materialized,
            backward_denominator=denominator,
        )
        require(token_count == micro["shifted_supervised_tokens"], "backward token count drift")
        add_loss_bucket(buckets, materialized, loss_sum)
        window_ids.append(materialized["window_id"])
        task_ids.append(materialized["task_id"])
        del materialized
        release_per_micro_allocator_cache(torch)
        cache_releases += 1
    require(buckets["all"]["shifted_supervised_tokens"] == denominator, "optimizer denominator coverage drift")
    require(cache_releases == len(step_plan["micro_windows"]), "per-micro allocator-cache release count drift")
    missing_gradients: list[str] = []
    nonfinite_gradients: list[str] = []
    nonzero_gradients = 0
    for name, parameter in trainable:
        if parameter.grad is None:
            missing_gradients.append(name)
        else:
            if not torch.isfinite(parameter.grad).all().item():
                nonfinite_gradients.append(name)
            nonzero_gradients += int(torch.count_nonzero(parameter.grad).item() > 0)
    require(not missing_gradients, f"step {optimizer_step}: missing gradients: {missing_gradients[:8]}")
    require(not nonfinite_gradients, f"step {optimizer_step}: nonfinite gradients: {nonfinite_gradients[:8]}")
    require(nonzero_gradients > 0, f"step {optimizer_step}: all gradients zero")
    grad_norm = torch.nn.utils.clip_grad_norm_(
        [parameter for _, parameter in trainable],
        max_norm=MAX_GRAD_NORM,
        error_if_nonfinite=True,
        foreach=False,
    )
    grad_norm_value = float(grad_norm.detach().cpu())
    require(math.isfinite(grad_norm_value), f"step {optimizer_step}: nonfinite gradient norm")
    optimizer.step()
    torch.cuda.synchronize(0)
    optimizer.zero_grad(set_to_none=True)
    require_no_gradients(trainable, f"optimizer step {optimizer_step} exit")
    metrics = finalize_loss_buckets(buckets)
    require(metrics["all"]["shifted_supervised_tokens"] == denominator, "step metric denominator drift")
    require(window_ids == [micro["window_id"] for micro in step_plan["micro_windows"]], "executed window order drift")
    gc.collect()
    torch.cuda.empty_cache()
    return {
        "optimizer_step": optimizer_step,
        "window_ids": window_ids,
        "task_ids": task_ids,
        "micro_windows": len(window_ids),
        "shifted_supervised_tokens": denominator,
        "metrics": metrics,
        "gradient_norm_before_clip": grad_norm_value,
        "nonzero_gradient_tensors": nonzero_gradients,
        "per_micro_allocator_cache_release": {
            "executions": cache_releases,
            "expected_executions": len(step_plan["micro_windows"]),
        },
        "learning_rate": optimizer.param_groups[0]["lr"],
        "elapsed_seconds": time.time() - started,
    }


def validate_progress(
    history: list[dict[str, Any]],
    plan_state: dict[str, Any],
    completed_step: int,
) -> dict[str, Any]:
    require(len(history) == completed_step, "training history length drift")
    ordered_windows: list[str] = []
    ordered_tasks: list[str] = []
    total_tokens = 0
    curated_micros = 0
    curated_tokens = 0
    promoted_micros = 0
    promoted_tokens = 0
    cache_releases = 0
    for optimizer_step, record in enumerate(history, 1):
        plan = plan_state["schedule_steps"][optimizer_step - 1]
        expected_windows = [micro["window_id"] for micro in plan["micro_windows"]]
        expected_tasks = [micro["task_id"] for micro in plan["micro_windows"]]
        require(record.get("optimizer_step") == optimizer_step, f"history step {optimizer_step}: ordinal drift")
        require(record.get("window_ids") == expected_windows, f"history step {optimizer_step}: window order drift")
        require(record.get("task_ids") == expected_tasks, f"history step {optimizer_step}: task order drift")
        require(record.get("shifted_supervised_tokens") == plan["shifted_supervised_tokens"], f"history step {optimizer_step}: token drift")
        expected_releases = len(plan["micro_windows"])
        require(
            record.get("per_micro_allocator_cache_release")
            == {"executions": expected_releases, "expected_executions": expected_releases},
            f"history step {optimizer_step}: per-micro allocator-cache release drift",
        )
        ordered_windows.extend(expected_windows)
        ordered_tasks.extend(expected_tasks)
        total_tokens += plan["shifted_supervised_tokens"]
        cache_releases += expected_releases
        for micro in plan["micro_windows"]:
            if micro["promoted"]:
                promoted_micros += 1
                promoted_tokens += micro["shifted_supervised_tokens"]
            else:
                curated_micros += 1
                curated_tokens += micro["shifted_supervised_tokens"]
    evidence = {
        "completed_optimizer_step": completed_step,
        "next_optimizer_step": completed_step + 1,
        "micro_windows": len(ordered_windows),
        "unique_tasks": len(set(ordered_tasks)),
        "shifted_supervised_tokens": total_tokens,
        "curated_micro_windows": curated_micros,
        "curated_shifted_supervised_tokens": curated_tokens,
        "promoted_micro_windows": promoted_micros,
        "promoted_shifted_supervised_tokens": promoted_tokens,
        "per_micro_allocator_cache_release_executions": cache_releases,
        "ordered_window_ids_sha256": digest_ordered_strings(ordered_windows),
        "ordered_task_ids_sha256": digest_ordered_strings(ordered_tasks),
    }
    if completed_step == PHASE1_STOP_STEP:
        require(evidence["micro_windows"] == EXPECTED_STEP10_MICROS, "step10 progress micro count drift")
        require(evidence["unique_tasks"] == EXPECTED_STEP10_UNIQUE_TASKS, "step10 progress task count drift")
        require(evidence["shifted_supervised_tokens"] == EXPECTED_STEP10_TOKENS, "step10 progress token drift")
        require(evidence["curated_micro_windows"] == EXPECTED_STEP10_CURATED_MICROS, "step10 progress curated count drift")
        require(evidence["curated_shifted_supervised_tokens"] == EXPECTED_STEP10_CURATED_TOKENS, "step10 progress curated tokens drift")
        require(evidence["promoted_micro_windows"] == EXPECTED_STEP10_PROMOTED_MICROS, "step10 progress promoted count drift")
        require(evidence["promoted_shifted_supervised_tokens"] == EXPECTED_STEP10_PROMOTED_TOKENS, "step10 progress promoted tokens drift")
        require(evidence["ordered_window_ids_sha256"] == EXPECTED_STEP10_WINDOW_IDS_SHA256, "step10 progress order drift")
        require(evidence["ordered_task_ids_sha256"] == EXPECTED_STEP10_TASK_IDS_SHA256, "step10 progress task order drift")
    if completed_step == OPTIMIZER_STEPS:
        require(evidence["micro_windows"] == EXPECTED_TRAIN_MICRO_WINDOWS, "final progress micro count drift")
        require(evidence["unique_tasks"] == EXPECTED_TRAIN_ROWS, "final progress task count drift")
        require(evidence["shifted_supervised_tokens"] == EXPECTED_TRAIN_TOKENS, "final progress token drift")
        require(evidence["ordered_window_ids_sha256"] == EXPECTED_FINAL_WINDOW_IDS_SHA256, "final progress order drift")
    return evidence


def select_best_validation(validations: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [item for item in validations if item["optimizer_step"] in BEST_CANDIDATE_STEPS]
    if not candidates:
        return None
    best = min(candidates, key=lambda item: (item["metrics"]["all"]["mean_cross_entropy"], item["optimizer_step"]))
    return {
        "optimizer_step": best["optimizer_step"],
        "mean_cross_entropy": best["metrics"]["all"]["mean_cross_entropy"],
        "checkpoint": f"checkpoint-{best['optimizer_step']:06d}",
    }


def run_validation(
    runtime: dict[str, Any],
    static: dict[str, Any],
    plan_state: dict[str, Any],
    tokenizer: Any,
    model: Any,
    optimizer: Any,
    trainable: list[tuple[str, Any]],
    optimizer_step: int,
    run_dir: Path,
    run_manifest_sha256: str,
) -> dict[str, Any]:
    require(optimizer_step in VALIDATION_STEPS, f"unplanned validation step: {optimizer_step}")
    torch = runtime["torch"]
    before_adapter = adapter_digest(runtime, model)
    before_optimizer = optimizer_evidence(runtime, optimizer, trainable, optimizer_step)
    before_rng = capture_rng(runtime)
    before_rng_sha256 = rng_digest(runtime, before_rng)
    require_no_gradients(trainable, f"validation step {optimizer_step} entry")
    buckets = empty_loss_buckets()
    started = time.time()
    was_training = bool(model.training)
    require(was_training, "formal validation entered with model outside train mode")
    model.eval()
    try:
        with torch.inference_mode():
            for row_plan in static["loss_plan"]["splits"]["validation"]["row_plans"]:
                for window in row_plan["windows"]:
                    materialized = materialize_window(
                        static,
                        plan_state,
                        runtime["common"],
                        tokenizer,
                        "validation",
                        window["window_id"],
                    )
                    loss_sum, token_count = forward_loss_sum(
                        runtime,
                        model,
                        materialized,
                        backward_denominator=None,
                    )
                    require(token_count == window["shifted_supervised_tokens"], "validation token count drift")
                    add_loss_bucket(buckets, materialized, loss_sum)
    finally:
        model.train(was_training)
    require(bool(model.training) == was_training, "validation model-mode restore drift")
    require_no_gradients(trainable, f"validation step {optimizer_step} exit")
    metrics = finalize_loss_buckets(buckets)
    require(metrics["all"]["shifted_supervised_tokens"] == EXPECTED_VALIDATION_TOKENS, "validation all-token drift")
    require(metrics["all"]["micro_windows"] == EXPECTED_VALIDATION_WINDOWS, "validation window count drift")
    require(metrics["all"]["unique_tasks"] == EXPECTED_VALIDATION_ROWS, "validation task count drift")
    require(metrics["curated"]["shifted_supervised_tokens"] == EXPECTED_VALIDATION_CURATED_TOKENS, "validation curated-token drift")
    require(metrics["curated"]["unique_tasks"] == EXPECTED_VALIDATION_CURATED_ROWS, "validation curated-row drift")
    require(metrics["promoted"]["shifted_supervised_tokens"] == EXPECTED_VALIDATION_PROMOTED_TOKENS, "validation promoted-token drift")
    require(metrics["promoted"]["unique_tasks"] == EXPECTED_VALIDATION_PROMOTED_ROWS, "validation promoted-row drift")
    require(metrics["systemless"]["shifted_supervised_tokens"] == EXPECTED_VALIDATION_SYSTEMLESS_TOKENS, "validation systemless-token drift")
    require(metrics["systemless"]["micro_windows"] == EXPECTED_VALIDATION_SYSTEMLESS_WINDOWS, "validation systemless-window drift")
    require(metrics["long"]["shifted_supervised_tokens"] == EXPECTED_VALIDATION_LONG_TOKENS, "validation long-token drift")
    require(metrics["long"]["micro_windows"] == EXPECTED_VALIDATION_LONG_WINDOWS, "validation long-window drift")
    require(metrics["long"]["unique_tasks"] == EXPECTED_VALIDATION_LONG_ROWS, "validation long-row drift")
    require(metrics["promoted_long"] == metrics["long"], "validation promoted-long bucket drift")
    after_adapter = adapter_digest(runtime, model)
    after_optimizer = optimizer_evidence(runtime, optimizer, trainable, optimizer_step)
    after_rng = capture_rng(runtime)
    after_rng_sha256 = rng_digest(runtime, after_rng)
    require(after_adapter == before_adapter, "validation mutated adapter")
    require(after_optimizer == before_optimizer, "validation mutated optimizer")
    require(after_rng_sha256 == before_rng_sha256, "validation mutated RNG")
    require(random.getstate() == before_rng["python_random_state"], "validation mutated Python RNG")
    require(torch.equal(after_rng["torch_cpu_rng_state"], before_rng["torch_cpu_rng_state"]), "validation mutated CPU RNG")
    require(
        all(
            torch.equal(actual.cpu(), expected.cpu())
            for actual, expected in zip(
                after_rng["torch_cuda_rng_state_all"], before_rng["torch_cuda_rng_state_all"], strict=True
            )
        ),
        "validation mutated GPU RNG",
    )
    payload = {
        "schema_version": "qwen3_32b_agentic_validation.v1",
        "status": "PASS",
        "optimizer_step": optimizer_step,
        "run_manifest_sha256": run_manifest_sha256,
        "loss_plan_sha256": EXPECTED_LOSS_PLAN_SHA256,
        "metrics": metrics,
        "adapter": after_adapter,
        "optimizer": after_optimizer,
        "rng_sha256": after_rng_sha256,
        "elapsed_seconds": time.time() - started,
    }
    validation_path = run_dir / "validations" / f"validation-step-{optimizer_step:06d}.json"
    atomic_json_create(validation_path, payload)
    return payload


def require_result_target(args: argparse.Namespace) -> None:
    require(args.run_dir.is_dir() and not args.run_dir.is_symlink(), "shared run root missing or symlinked")
    require(RUN_ID_RE.fullmatch(args.run_dir.name) is not None, "shared run-root name is unsafe")
    require(args.result.parent.is_dir() and not args.result.parent.is_symlink(), "result parent missing or symlinked")
    require(not args.result.exists() and not args.result.is_symlink(), "result path already exists")
    run_root = args.run_dir.resolve(strict=True)
    result_parent = args.result.parent.resolve(strict=True)
    expected_parent = run_root / f"{args.phase}-controller"
    require(result_parent == expected_parent, "result parent is not the reserved phase-controller directory")
    require(args.result.name == "gate-result.json", "result filename drift")


def cleanup_current_process_staging(args: argparse.Namespace) -> list[str]:
    """Remove only unpublished staging trees owned by this exact process."""

    checkpoint_root = args.run_dir / "checkpoints"
    if not checkpoint_root.is_dir() or checkpoint_root.is_symlink():
        return []
    process = process_instance()
    pattern = re.compile(
        rf"\.checkpoint-[0-9]{{6}}\.{process['pid']}\.{process['start_ticks']}\.staging\Z"
    )
    removed: list[str] = []
    for staging in list(checkpoint_root.iterdir()):
        if pattern.fullmatch(staging.name) is None:
            continue
        require(staging.is_dir() and not staging.is_symlink(), f"owned staging target invalid: {staging}")
        for path in staging.rglob("*"):
            require(not path.is_symlink(), f"owned staging contains symlink: {path}")
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        os.chmod(staging, 0o700)
        shutil.rmtree(staging)
        removed.append(staging.name)
    if removed:
        fsync_directory(checkpoint_root)
    return removed


def prepare_phase1_layout(args: argparse.Namespace) -> None:
    require_result_target(args)
    formal_targets = (
        args.run_dir / "run-manifest.json",
        args.run_dir / "checkpoints",
        args.run_dir / "validations",
        args.run_dir / "resume-ack-phase2.json",
    )
    require(not any(path.exists() or path.is_symlink() for path in formal_targets), "formal run artifacts already exist")
    (args.run_dir / "checkpoints").mkdir(mode=0o755)
    (args.run_dir / "validations").mkdir(mode=0o755)
    fsync_directory(args.run_dir)


def verify_phase2_layout(args: argparse.Namespace) -> None:
    require_result_target(args)
    for name in ("checkpoints", "validations"):
        path = args.run_dir / name
        require(path.is_dir() and not path.is_symlink(), f"formal run directory invalid: {name}")
    require((args.run_dir / "run-manifest.json").is_file(), "run manifest missing")
    require(not (args.run_dir / "resume-ack-phase2.json").exists(), "phase2 resume acknowledgement already exists")


def run_bindings(static: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "trainer_path": static["trainer_path"],
        "trainer_sha256": static["trainer_sha256"],
        "original_plan_path": str(args.original_plan),
        "original_plan_sha256": EXPECTED_ORIGINAL_PLAN_SHA256,
        "loss_plan_path": str(args.loss_plan),
        "loss_plan_sha256": EXPECTED_LOSS_PLAN_SHA256,
        "common_script_path": str(args.common_script),
        "common_script_sha256": EXPECTED_COMMON_SHA256,
        "data_directory": str(args.data_dir),
        "train_sha256": EXPECTED_SPLIT_SHA256["train"],
        "validation_sha256": EXPECTED_SPLIT_SHA256["validation"],
        "model_path": str(args.model),
        "model_revision": EXPECTED_MODEL_REVISION,
        "model_verification_path": str(args.model_verification),
        "model_verification_sha256": EXPECTED_MODEL_VERIFICATION_SHA256,
        "fresh_model_sha256": static["fresh_model_sha256"],
    }


def hyperparameter_contract() -> dict[str, Any]:
    return {
        "epochs": 1,
        "optimizer_steps": OPTIMIZER_STEPS,
        "loss": "assistant-only shifted cross entropy",
        "micro_window_reduction": "sum",
        "optimizer_step_normalization": "divide each micro CE sum by frozen step supervised-token total",
        "max_window_tokens": MAX_WINDOW_TOKENS,
        "position_ids": "absolute source offsets",
        "packing": False,
        "padding": False,
        "optimizer": "torch.optim.AdamW",
        "learning_rate": LEARNING_RATE,
        "lr_schedule": LR_SCHEDULE,
        "betas": list(ADAM_BETAS),
        "epsilon": ADAM_EPS,
        "weight_decay": WEIGHT_DECAY,
        "foreach": False,
        "fused": False,
        "max_gradient_norm": MAX_GRAD_NORM,
        "lora": {
            "rank": 8,
            "alpha": 16,
            "dropout": 0.0,
            "bias": "none",
            "targets": list(LORA_TARGETS),
            "trainable_dtype": "float32",
        },
        "base_compute_dtype": "bfloat16",
        "attention_implementation": "sdpa",
        "gradient_checkpointing": {"enabled": True, "use_reentrant": False},
        "per_micro_allocator_cache_release": PER_MICRO_ALLOCATOR_CACHE_RELEASE,
        "validation_steps": list(VALIDATION_STEPS),
        "best_checkpoint_candidates": list(BEST_CANDIDATE_STEPS),
        "checkpoint_steps": list(CHECKPOINT_STEPS),
        "phase1_stop_step": PHASE1_STOP_STEP,
        "phase1_restart_exit_code": PHASE1_RESTART_EXIT_CODE,
    }


def create_run_manifest(
    runtime: dict[str, Any],
    static: dict[str, Any],
    args: argparse.Namespace,
    model_evidence: dict[str, Any],
    initial_adapter: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    manifest = {
        "schema_version": "qwen3_32b_agentic_formal_run.v1",
        "status": "PREPARED",
        "created_unix": time.time(),
        "hostname": socket.gethostname(),
        "machine_sha256": machine_sha256(),
        "phase1_process": static["process"],
        "phase1_result_path": str(args.result),
        "bindings": run_bindings(static, args),
        "hyperparameters": hyperparameter_contract(),
        "versions": runtime["versions"],
        "model_runtime_evidence": model_evidence,
        "initial_adapter": initial_adapter,
    }
    path = args.run_dir / "run-manifest.json"
    atomic_json_create(path, manifest)
    return manifest, sha256_file(path)


def read_run_manifest(static: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    path = args.run_dir / "run-manifest.json"
    require(path.is_file() and not path.is_symlink(), "run manifest invalid")
    require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, "run manifest writable")
    manifest = json.loads(path.read_bytes())
    require(manifest.get("schema_version") == "qwen3_32b_agentic_formal_run.v1", "run manifest schema drift")
    require(manifest.get("status") == "PREPARED", "run manifest status drift")
    require(manifest.get("hostname") == EXPECTED_HOSTNAME, "run manifest hostname drift")
    require(manifest.get("machine_sha256") == EXPECTED_MACHINE_SHA256, "run manifest machine drift")
    require(manifest.get("bindings") == run_bindings(static, args), "run manifest bindings drift")
    require(manifest.get("hyperparameters") == hyperparameter_contract(), "run hyperparameters drift")
    require(manifest.get("phase1_process") != static["process"], "phase2 is not a fresh process")
    require(not exact_process_is_alive(manifest.get("phase1_process", {})), "exact phase1 process is still alive")
    return manifest, sha256_file(path)


def prefix_checkpoint_names(checkpoint_root: Path) -> set[str]:
    names: set[str] = set()
    for path in checkpoint_root.iterdir():
        require(path.is_dir() and not path.is_symlink(), f"invalid checkpoint-root entry: {path.name}")
        require(re.fullmatch(r"checkpoint-[0-9]{6}", path.name) is not None, f"unexpected checkpoint-root entry: {path.name}")
        names.add(path.name)
    return names


def verify_checkpoint(checkpoint: Path, expected_step: int, run_manifest_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    require(checkpoint.is_dir() and not checkpoint.is_symlink(), "checkpoint directory invalid")
    require(stat.S_IMODE(checkpoint.stat().st_mode) & 0o222 == 0, "checkpoint directory writable")
    for path in checkpoint.rglob("*"):
        require(not path.is_symlink(), f"checkpoint symlink: {path}")
        require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"checkpoint entry writable: {path}")
    manifest_path = checkpoint / "manifest.json"
    complete_path = checkpoint / "COMPLETE"
    require(manifest_path.is_file() and complete_path.is_file(), "checkpoint publication markers missing")
    manifest = json.loads(manifest_path.read_bytes())
    complete = json.loads(complete_path.read_bytes())
    require(manifest.get("schema_version") == "qwen3_32b_agentic_checkpoint_manifest.v1", "checkpoint manifest schema drift")
    require(manifest.get("optimizer_step") == expected_step, "checkpoint manifest step drift")
    require(manifest.get("run_manifest_sha256") == run_manifest_sha256, "checkpoint run binding drift")
    require(complete.get("status") == "COMPLETE", "checkpoint is incomplete")
    require(complete.get("manifest_sha256") == sha256_file(manifest_path), "checkpoint manifest digest drift")
    actual_inventory = inventory_files(checkpoint, excluded={"manifest.json", "COMPLETE"})
    require(actual_inventory == manifest.get("files"), "checkpoint file inventory drift")
    for required_name in (
        "adapter_config.json",
        "adapter_model.safetensors",
        "optimizer.pt",
        "rng.pt",
        "original-plan.json",
        "loss-plan.json",
        "state.json",
    ):
        require(required_name in actual_inventory, f"checkpoint required file missing: {required_name}")
    require(actual_inventory["original-plan.json"]["sha256"] == EXPECTED_ORIGINAL_PLAN_SHA256, "checkpoint original-plan drift")
    require(actual_inventory["loss-plan.json"]["sha256"] == EXPECTED_LOSS_PLAN_SHA256, "checkpoint loss-plan drift")
    state = json.loads((checkpoint / "state.json").read_bytes())
    require(state.get("schema_version") == "qwen3_32b_agentic_checkpoint_state.v1", "checkpoint state schema drift")
    require(state.get("completed_optimizer_step") == expected_step, "checkpoint state step drift")
    require(state.get("next_optimizer_step") == expected_step + 1, "checkpoint next-step drift")
    require(state.get("run_manifest_sha256") == run_manifest_sha256, "checkpoint state run binding drift")
    return manifest, state


def publish_checkpoint(
    runtime: dict[str, Any],
    static: dict[str, Any],
    plan_state: dict[str, Any],
    args: argparse.Namespace,
    model: Any,
    optimizer: Any,
    trainable: list[tuple[str, Any]],
    completed_step: int,
    history: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    run_manifest_sha256: str,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    require(completed_step in CHECKPOINT_STEPS, f"unplanned checkpoint step: {completed_step}")
    require_no_gradients(trainable, f"checkpoint step {completed_step} entry")
    entry_training_mode = bool(model.training)
    require(entry_training_mode, "checkpoint entered with model outside train mode")
    checkpoints = args.run_dir / "checkpoints"
    final = checkpoints / f"checkpoint-{completed_step:06d}"
    require(not final.exists() and not final.is_symlink(), f"checkpoint already exists: {final.name}")
    process = process_instance()
    staging = checkpoints / f".{final.name}.{process['pid']}.{process['start_ticks']}.staging"
    require(not staging.exists() and not staging.is_symlink(), "checkpoint staging path exists")
    staging.mkdir(mode=0o700)

    progress = validate_progress(history, plan_state, completed_step)
    adapter = adapter_digest(runtime, model)
    optimizer_state = optimizer_evidence(runtime, optimizer, trainable, completed_step)
    rng = capture_rng(runtime)
    rng_sha256 = rng_digest(runtime, rng)
    model.save_pretrained(staging, safe_serialization=True)
    saved_adapter = runtime["load_safetensors_file"](str(staging / "adapter_model.safetensors"), device="cpu")
    saved_adapter_digest = adapter_state_digest(runtime, saved_adapter)
    del saved_adapter
    require(saved_adapter_digest == adapter, "serialized adapter differs from live adapter")
    torch_save_new(runtime["torch"], optimizer.state_dict(), staging / "optimizer.pt")
    torch_save_new(runtime["torch"], rng, staging / "rng.pt")
    write_new_bytes(staging / "original-plan.json", static["original_plan_bytes"])
    write_new_bytes(staging / "loss-plan.json", static["loss_plan_bytes"])
    state = {
        "schema_version": "qwen3_32b_agentic_checkpoint_state.v1",
        "completed_optimizer_step": completed_step,
        "next_optimizer_step": completed_step + 1,
        "run_manifest_sha256": run_manifest_sha256,
        "trainer_sha256": static["trainer_sha256"],
        "process": static["process"],
        "phase": args.phase,
        "phase_result_path": str(args.result),
        "progress": progress,
        "history": history,
        "validations": validations,
        "best_validation": select_best_validation(validations),
        "adapter": adapter,
        "optimizer": optimizer_state,
        "rng_sha256": rng_sha256,
        "trainable_signature": trainable_signature(trainable),
        "hyperparameters": hyperparameter_contract(),
    }
    write_new_bytes(staging / "state.json", json_bytes(state))
    files = inventory_files(staging)
    manifest = {
        "schema_version": "qwen3_32b_agentic_checkpoint_manifest.v1",
        "optimizer_step": completed_step,
        "run_manifest_sha256": run_manifest_sha256,
        "trainer_sha256": static["trainer_sha256"],
        "adapter": adapter,
        "optimizer": optimizer_state,
        "rng_sha256": rng_sha256,
        "file_cache_reclaim": "scoped POSIX_FADV_DONTNEED after publication verification",
        "files": files,
    }
    write_new_bytes(staging / "manifest.json", json_bytes(manifest))
    complete = {
        "schema_version": "qwen3_32b_agentic_checkpoint_complete.v1",
        "status": "COMPLETE",
        "optimizer_step": completed_step,
        "manifest_sha256": sha256_file(staging / "manifest.json"),
    }
    write_new_bytes(staging / "COMPLETE", json_bytes(complete))
    fsync_tree(staging)
    for path in staging.rglob("*"):
        if path.is_file():
            os.chmod(path, 0o444)
    for directory in sorted((path for path in staging.rglob("*") if path.is_dir()), key=lambda item: len(item.parts), reverse=True):
        os.chmod(directory, 0o555)
    os.chmod(staging, 0o555)
    fsync_tree(staging)
    require(adapter_digest(runtime, model) == adapter, "checkpoint staging mutated live adapter")
    require(
        optimizer_evidence(runtime, optimizer, trainable, completed_step) == optimizer_state,
        "checkpoint staging mutated live optimizer",
    )
    require(rng_digest(runtime, capture_rng(runtime)) == rng_sha256, "checkpoint staging mutated live RNG")
    require_no_gradients(trainable, f"checkpoint step {completed_step} pre-publish")
    require(bool(model.training) == entry_training_mode, "checkpoint staging mutated model mode")
    rename_noreplace(staging, final)
    fsync_directory(checkpoints)
    verified_manifest, verified_state = verify_checkpoint(final, completed_step, run_manifest_sha256)
    require(verified_manifest == manifest and verified_state == state, "published checkpoint content drift")
    require(adapter_digest(runtime, model) == adapter, "checkpoint publication mutated live adapter")
    require(
        optimizer_evidence(runtime, optimizer, trainable, completed_step) == optimizer_state,
        "checkpoint publication mutated live optimizer",
    )
    require(rng_digest(runtime, capture_rng(runtime)) == rng_sha256, "checkpoint publication mutated live RNG")
    require_no_gradients(trainable, f"checkpoint step {completed_step} post-publish")
    require(bool(model.training) == entry_training_mode, "checkpoint publication mutated model mode")
    reclaimed = reclaim_tree_page_cache(final)
    require(reclaimed["files"] == len(manifest["files"]) + 2, "checkpoint cache-reclaim file count drift")
    return final, manifest, state


def verify_validation_history(run_dir: Path, validations: list[dict[str, Any]]) -> None:
    observed_steps = [item.get("optimizer_step") for item in validations]
    require(observed_steps == sorted(set(observed_steps)), "validation history order/uniqueness drift")
    expected_files = {f"validation-step-{step:06d}.json" for step in observed_steps}
    validation_root = run_dir / "validations"
    actual_files = {path.name for path in validation_root.iterdir() if path.is_file() and not path.is_symlink()}
    require(actual_files == expected_files, "validation artifact inventory drift")
    require(all(not path.is_symlink() and not path.is_dir() for path in validation_root.iterdir()), "invalid validation entry")
    for payload in validations:
        path = validation_root / f"validation-step-{payload['optimizer_step']:06d}.json"
        require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"validation artifact writable: {path.name}")
        require(json.loads(path.read_bytes()) == payload, f"validation artifact content drift: {path.name}")


def run_phase1(
    runtime: dict[str, Any],
    static: dict[str, Any],
    plan_state: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], int]:
    tokenizer = load_tokenizer(runtime, args)
    model, trainable, model_evidence = build_model(runtime, args)
    initial_adapter = adapter_digest(runtime, model)
    optimizer = make_optimizer(runtime, trainable)
    require(optimizer_evidence(runtime, optimizer, trainable, 0)["state_count"] == 0, "fresh optimizer drift")
    _, run_manifest_sha256 = create_run_manifest(
        runtime,
        static,
        args,
        model_evidence,
        initial_adapter,
    )
    validations = [
        run_validation(
            runtime,
            static,
            plan_state,
            tokenizer,
            model,
            optimizer,
            trainable,
            0,
            args.run_dir,
            run_manifest_sha256,
        )
    ]
    history: list[dict[str, Any]] = []
    checkpoint: Path | None = None
    checkpoint_manifest: dict[str, Any] | None = None
    for optimizer_step in range(1, PHASE1_STOP_STEP + 1):
        history.append(
            train_optimizer_step(
                runtime,
                static,
                plan_state,
                tokenizer,
                model,
                optimizer,
                trainable,
                optimizer_step,
            )
        )
        if optimizer_step in VALIDATION_STEPS:
            validations.append(
                run_validation(
                    runtime,
                    static,
                    plan_state,
                    tokenizer,
                    model,
                    optimizer,
                    trainable,
                    optimizer_step,
                    args.run_dir,
                    run_manifest_sha256,
                )
            )
        if optimizer_step in CHECKPOINT_STEPS:
            checkpoint, checkpoint_manifest, _ = publish_checkpoint(
                runtime,
                static,
                plan_state,
                args,
                model,
                optimizer,
                trainable,
                optimizer_step,
                history,
                validations,
                run_manifest_sha256,
            )
    require(checkpoint is not None and checkpoint.name == "checkpoint-000010", "phase1 checkpoint drift")
    require(checkpoint_manifest is not None, "phase1 checkpoint manifest missing")
    require(prefix_checkpoint_names(args.run_dir / "checkpoints") == {"checkpoint-000010"}, "phase1 checkpoint inventory drift")
    verify_validation_history(args.run_dir, validations)
    require([item["optimizer_step"] for item in validations] == [0], "phase1 validation boundary drift")
    progress = validate_progress(history, plan_state, PHASE1_STOP_STEP)
    return {
        "schema_version": "qwen3_32b_agentic_formal_phase_result.v1",
        "status": "RESTART_READY",
        "phase": "phase1",
        "exit_code": PHASE1_RESTART_EXIT_CODE,
        "completed_optimizer_step": PHASE1_STOP_STEP,
        "next_optimizer_step": PHASE1_STOP_STEP + 1,
        "run_dir": str(args.run_dir),
        "run_manifest_sha256": run_manifest_sha256,
        "checkpoint": str(checkpoint),
        "checkpoint_manifest_sha256": sha256_file(checkpoint / "manifest.json"),
        "progress": progress,
        "process": static["process"],
        "gpu_memory": gpu_memory_evidence(runtime),
    }, PHASE1_RESTART_EXIT_CODE


def read_phase1_result(manifest: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    result_path = Path(manifest.get("phase1_result_path", ""))
    require(result_path.is_absolute(), "phase1 result path missing from run manifest")
    require(result_path.is_file() and not result_path.is_symlink(), "phase1 result artifact invalid")
    require(result_path.resolve().is_relative_to(args.run_dir.resolve()), "phase1 result escaped run root")
    require(stat.S_IMODE(result_path.stat().st_mode) & 0o222 == 0, "phase1 result artifact writable")
    payload = json.loads(result_path.read_bytes())
    require(payload.get("schema_version") == "qwen3_32b_agentic_formal_phase_result.v1", "phase1 result schema drift")
    require(payload.get("status") == "RESTART_READY", "phase1 result is not restart-ready")
    require(payload.get("phase") == "phase1" and payload.get("exit_code") == PHASE1_RESTART_EXIT_CODE, "phase1 result exit contract drift")
    require(payload.get("completed_optimizer_step") == PHASE1_STOP_STEP, "phase1 result step drift")
    return payload


def run_phase2(
    runtime: dict[str, Any],
    static: dict[str, Any],
    plan_state: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], int]:
    run_manifest, run_manifest_sha256 = read_run_manifest(static, args)
    require(run_manifest.get("versions") == runtime["versions"], "runtime versions differ from phase1")
    phase1_result = read_phase1_result(run_manifest, args)
    expected_checkpoint = args.run_dir / "checkpoints" / "checkpoint-000010"
    require(args.resume == expected_checkpoint, "phase2 may resume only the exact checkpoint-000010 path")
    require(prefix_checkpoint_names(args.run_dir / "checkpoints") == {"checkpoint-000010"}, "pre-resume checkpoint inventory drift")
    checkpoint_manifest, checkpoint_state = verify_checkpoint(
        expected_checkpoint,
        PHASE1_STOP_STEP,
        run_manifest_sha256,
    )
    require(
        phase1_result.get("checkpoint_manifest_sha256") == sha256_file(expected_checkpoint / "manifest.json"),
        "phase1 result/checkpoint binding drift",
    )
    require(phase1_result.get("run_manifest_sha256") == run_manifest_sha256, "phase1 result/run binding drift")
    require(phase1_result.get("process") == run_manifest.get("phase1_process"), "phase1 process evidence drift")
    require(checkpoint_state.get("process") == run_manifest.get("phase1_process"), "checkpoint phase1 process drift")
    require(checkpoint_state.get("phase") == "phase1", "checkpoint phase drift")
    require(checkpoint_state.get("phase_result_path") == run_manifest.get("phase1_result_path"), "checkpoint result-path drift")
    require(checkpoint_state.get("trainer_sha256") == static["trainer_sha256"], "checkpoint trainer drift")
    require(checkpoint_state.get("hyperparameters") == hyperparameter_contract(), "checkpoint hyperparameters drift")
    require(
        validate_progress(checkpoint_state["history"], plan_state, PHASE1_STOP_STEP) == checkpoint_state["progress"],
        "checkpoint progress reconstruction drift",
    )
    require([item["optimizer_step"] for item in checkpoint_state["validations"]] == [0], "checkpoint validation history drift")
    verify_validation_history(args.run_dir, checkpoint_state["validations"])

    tokenizer = load_tokenizer(runtime, args)
    model, trainable, model_evidence = build_model(runtime, args, expected_checkpoint)
    require(
        model_evidence["trainable_signature"] == run_manifest["model_runtime_evidence"]["trainable_signature"],
        "phase2 trainable signature differs from phase1",
    )
    require(trainable_signature(trainable) == checkpoint_state["trainable_signature"], "checkpoint trainable signature drift")
    reloaded_adapter = adapter_digest(runtime, model)
    require(reloaded_adapter == checkpoint_state["adapter"] == checkpoint_manifest["adapter"], "adapter reload digest drift")
    optimizer = make_optimizer(runtime, trainable)
    optimizer_payload = runtime["torch"].load(
        expected_checkpoint / "optimizer.pt",
        map_location="cpu",
        weights_only=True,
    )
    optimizer.load_state_dict(optimizer_payload)
    del optimizer_payload
    reloaded_optimizer = optimizer_evidence(runtime, optimizer, trainable, PHASE1_STOP_STEP)
    require(
        reloaded_optimizer == checkpoint_state["optimizer"] == checkpoint_manifest["optimizer"],
        "optimizer reload digest drift",
    )
    rng_payload = runtime["torch"].load(
        expected_checkpoint / "rng.pt",
        map_location="cpu",
        weights_only=False,
    )
    require(rng_digest(runtime, rng_payload) == checkpoint_state["rng_sha256"], "checkpoint RNG digest drift")
    require(checkpoint_state["rng_sha256"] == checkpoint_manifest["rng_sha256"], "checkpoint RNG manifest drift")

    # This must remain the final state-restoring operation before the resume ack.
    restore_rng_last(runtime, rng_payload)
    require(rng_digest(runtime, capture_rng(runtime)) == checkpoint_state["rng_sha256"], "post-restore RNG drift")
    resume_ack = {
        "schema_version": "qwen3_32b_agentic_resume_ack.v1",
        "status": "PASS",
        "fresh_process": static["process"],
        "phase1_process": run_manifest["phase1_process"],
        "checkpoint": str(expected_checkpoint),
        "checkpoint_manifest_sha256": sha256_file(expected_checkpoint / "manifest.json"),
        "completed_optimizer_step": PHASE1_STOP_STEP,
        "next_optimizer_step": PHASE1_STOP_STEP + 1,
        "adapter": reloaded_adapter,
        "optimizer": reloaded_optimizer,
        "rng_sha256": checkpoint_state["rng_sha256"],
    }
    atomic_json_create(args.run_dir / "resume-ack-phase2.json", resume_ack)
    require(rng_digest(runtime, capture_rng(runtime)) == checkpoint_state["rng_sha256"], "resume ack mutated RNG")
    require_no_gradients(trainable, "phase2 post-resume acknowledgement")
    require(model.training, "phase2 model is not in train mode after resume")
    reclaimed_resume = reclaim_tree_page_cache(expected_checkpoint)
    require(
        reclaimed_resume["files"] == len(checkpoint_manifest["files"]) + 2,
        "resume checkpoint cache-reclaim file count drift",
    )
    require(rng_digest(runtime, capture_rng(runtime)) == checkpoint_state["rng_sha256"], "cache reclaim mutated RNG")

    history = list(checkpoint_state["history"])
    validations = list(checkpoint_state["validations"])
    final_checkpoint: Path | None = None
    final_manifest: dict[str, Any] | None = None
    for optimizer_step in range(PHASE1_STOP_STEP + 1, OPTIMIZER_STEPS + 1):
        history.append(
            train_optimizer_step(
                runtime,
                static,
                plan_state,
                tokenizer,
                model,
                optimizer,
                trainable,
                optimizer_step,
            )
        )
        if optimizer_step in VALIDATION_STEPS:
            validations.append(
                run_validation(
                    runtime,
                    static,
                    plan_state,
                    tokenizer,
                    model,
                    optimizer,
                    trainable,
                    optimizer_step,
                    args.run_dir,
                    run_manifest_sha256,
                )
            )
        if optimizer_step in CHECKPOINT_STEPS:
            final_checkpoint, final_manifest, _ = publish_checkpoint(
                runtime,
                static,
                plan_state,
                args,
                model,
                optimizer,
                trainable,
                optimizer_step,
                history,
                validations,
                run_manifest_sha256,
            )
    require(final_checkpoint is not None and final_checkpoint.name == "checkpoint-000119", "final checkpoint drift")
    require(final_manifest is not None, "final checkpoint manifest missing")
    expected_checkpoint_names = {f"checkpoint-{step:06d}" for step in CHECKPOINT_STEPS}
    require(prefix_checkpoint_names(args.run_dir / "checkpoints") == expected_checkpoint_names, "final checkpoint inventory drift")
    require([item["optimizer_step"] for item in validations] == list(VALIDATION_STEPS), "final validation boundary drift")
    verify_validation_history(args.run_dir, validations)
    progress = validate_progress(history, plan_state, OPTIMIZER_STEPS)
    best = select_best_validation(validations)
    require(best is not None and (args.run_dir / "checkpoints" / best["checkpoint"]).is_dir(), "best checkpoint selection drift")
    return {
        "schema_version": "qwen3_32b_agentic_formal_phase_result.v1",
        "status": "PASS",
        "phase": "phase2",
        "exit_code": 0,
        "completed_optimizer_step": OPTIMIZER_STEPS,
        "next_optimizer_step": None,
        "run_dir": str(args.run_dir),
        "run_manifest_sha256": run_manifest_sha256,
        "checkpoint": str(final_checkpoint),
        "checkpoint_manifest_sha256": sha256_file(final_checkpoint / "manifest.json"),
        "progress": progress,
        "validation_steps": list(VALIDATION_STEPS),
        "best_validation": best,
        "process": static["process"],
        "gpu_memory": gpu_memory_evidence(runtime),
    }, 0


def failure_payload(args: argparse.Namespace, error: BaseException) -> dict[str, Any]:
    return {
        "schema_version": "qwen3_32b_agentic_formal_phase_result.v1",
        "status": "FAIL",
        "phase": args.phase,
        "exit_code": 1,
        "hostname": socket.gethostname(),
        "machine_sha256": machine_sha256(),
        "process": process_instance(),
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }


def main() -> None:
    args = parse_args()
    try:
        static = verify_static_environment(args)
        plan_state = validate_loss_plan(static)
        if args.phase == "phase1":
            prepare_phase1_layout(args)
        else:
            verify_phase2_layout(args)
        runtime = load_runtime(args)
        seed_runtime(runtime)
        if args.phase == "phase1":
            payload, exit_code = run_phase1(runtime, static, plan_state, args)
        else:
            payload, exit_code = run_phase2(runtime, static, plan_state, args)
    except BaseException as error:
        payload = failure_payload(args, error)
        try:
            payload["removed_unpublished_staging"] = cleanup_current_process_staging(args)
        except BaseException as cleanup_error:
            payload["staging_cleanup_error"] = f"{type(cleanup_error).__name__}: {cleanup_error}"
        exit_code = 1
    if args.result.parent.is_dir() and not args.result.exists() and not args.result.is_symlink():
        try:
            run_root = args.run_dir.resolve(strict=True)
            result_parent = args.result.parent.resolve(strict=True)
            require(result_parent.is_relative_to(run_root), "result escaped shared run root")
            atomic_json_create(args.result, payload)
        except BaseException as result_error:
            print(
                json.dumps(
                    {
                        "status": "FAIL",
                        "phase": args.phase,
                        "error": str(result_error),
                        "original_status": payload.get("status"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            raise SystemExit(1)
    else:
        print(
            json.dumps(
                {"status": "FAIL", "phase": args.phase, "error": "result target is unavailable"},
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "phase": args.phase,
                "result": str(args.result),
                "exit_code": exit_code,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
