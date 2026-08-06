#!/usr/bin/env python3
"""Result-only step-6 accumulation and allocator-cache gate for Qwen3-32B.

The gate independently re-materializes the exact eight frozen micro-windows of
optimizer step 6 or 32, accumulates their summed cross entropy with the same
frozen step denominator as the formal trainer, and performs exactly one
optimizer update.  It writes only the requested JSON result: no run, checkpoint,
adapter, optimizer, or RNG artifact is published.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import random
import socket
import stat
import struct
import sys
import time
import traceback
from pathlib import Path
from typing import Any


EXPECTED_HOSTNAME = "u-7701-ae3eba8a"
EXPECTED_MACHINE_SHA256 = "7c225d1717bb5f671c4bf071b1df172abdc72a50a3ed53e24de9ab724d35ad54"
EXPECTED_ORIGINAL_PLAN_SHA256 = "39d6ae20fcb566d6544049e2ea263c5bc64fe8ecd349c71b4a8ec58721134f25"
EXPECTED_LOSS_WINDOW_PLAN_SHA256 = "7ef449cb41f37f5d32d4562c336aba4e3cb8f01b506850a93d34bccef6260afb"
EXPECTED_FORMAL_TRAINER_SHA256 = "44978c4a386f638688a3ffdea30cf7595565489c1249a7d380343b26638a8edd"
EXPECTED_TRAIN_SHA256 = "707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58"
EXPECTED_COMMON_SHA256 = "d0159dd2ab96961ea116dc4264833a65a98d63421a21c798aa70dcc8bfcb9f7f"
EXPECTED_VERIFICATION_SHA256 = "5f8b675142ee4d2e6a968e756c1da6546f59dcfd34ed997ef23d95211feb7b0d"
EXPECTED_TEMPLATE_SHA256 = "96fd16d36fb085260f9eb1e717b2c4e6e8b9e75a5e6504f66c8d6b128d82784d"
EXPECTED_MODEL_INDEX_SHA256 = "2771f7e67bacc73ceb4ee0dfe6027d49fc9a4390d17eda517a4f7f48923d6a61"
EXPECTED_CONFIG_SHA256 = "918fe2d123e79abf8ed4688278cc7d9c6c54d25fbea35e5f0870985f4d663000"
EXPECTED_MODEL_REVISION = "7f721e74a6a8cc9ee352f7e49303a2c1705f9083"
EXPECTED_PYTHON_PREFIX = "3.12.3"
EXPECTED_TORCH = "2.9.1+rocm7.2.0.git7e1940d4"
EXPECTED_TORCH_HIP = "7.2.26015-fc0010cf6a"
EXPECTED_TRANSFORMERS = "5.5.0"
EXPECTED_PEFT = "0.19.1"
EXPECTED_BITSANDBYTES = "0.50.0"
EXPECTED_LINEAR4BIT = 448
EXPECTED_LORA_MODULES = 448
EXPECTED_TRAINABLE_TENSORS = 896
EXPECTED_TRAINABLE_ELEMENTS = 67_108_864
EXPECTED_RMSNORM = 257
EXPECTED_TOKENIZER_LENGTH = 151_669
EXPECTED_TRAIN_ROWS = 946
MAX_RENDER_TOKENS = 32_768
MAX_WINDOW_TOKENS = 8_192
SEED = 20260803
LORA_TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
ALLOWED_SCHEDULE_STEPS = (6, 32)
EXPECTED_STEP_CONTRACTS = {
    6: {
        "capacity": 8,
        "construction_bin": 100,
        "curated_micro_windows": 1,
        "promoted_micro_windows": 7,
        "input_tokens": 45_306,
        "shifted_supervised_tokens": 4_533,
        "step_plan_sha256": "26e0d547c448f1c7bb73950d6fbd6df6e1b026732e0eb87cc5087dcfcd896ec8",
        "micro_windows_sha256": "ff9c4774fc3b38eb3a192af45788e316ce1de32b6cc686eefa0dbc2ecc9f3b41",
        "window_ids": [
            "agent_101543#0",
            "agent_101808#0",
            "agent_101625#0",
            "agent_101730#0",
            "agent_102214#0",
            "agent_130025#0",
            "agent_101828#0",
            "agent_101901#0",
        ],
        "task_ids": [
            "agent_101543",
            "agent_101808",
            "agent_101625",
            "agent_101730",
            "agent_102214",
            "agent_130025",
            "agent_101828",
            "agent_101901",
        ],
        "maximum_input_tokens": 7_867,
        "maximum_window_id": "agent_101828#0",
    },
    32: {
        "capacity": 8,
        "construction_bin": 84,
        "curated_micro_windows": 2,
        "promoted_micro_windows": 6,
        "input_tokens": 44_008,
        "shifted_supervised_tokens": 4_437,
        "step_plan_sha256": "fd1689a0a23012632b0363ad6af0f588e69fbfa99c305ac98e99322cc88f7dc8",
        "micro_windows_sha256": "abb3b049681a25d3f400dd83dc2cfff640fb4eeb208c9bf6ea6eaad1e80c9de8",
        "window_ids": [
            "agent_101421#0",
            "agent_102417#0",
            "agent_101761#0",
            "agent_101769#0",
            "agent_101811#0",
            "agent_102003#0",
            "agent_102041#0",
            "agent_101768#0",
        ],
        "task_ids": [
            "agent_101421",
            "agent_102417",
            "agent_101761",
            "agent_101769",
            "agent_101811",
            "agent_102003",
            "agent_102041",
            "agent_101768",
        ],
        "maximum_input_tokens": 8_136,
        "maximum_window_id": "agent_102417#0",
    },
}
CONTROLLER_HARD_LIMIT_BYTES = 44 * 1024**3
INTERNAL_TARGET_BYTES = 42 * 1024**3
PER_MICRO_ALLOCATOR_CACHE_RELEASE = {
    "enabled": True,
    "scope": "every training micro-window",
    "placement": "after backward, CPU loss capture, metric update, and temporary GPU reference release",
    "sequence": ["torch.cuda.synchronize(0)", "gc.collect()", "torch.cuda.empty_cache()"],
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def sha256_i64(values: list[int]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(struct.pack("<q", int(value)))
    return digest.hexdigest()


def machine_sha256() -> str:
    return hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest()


def read_bound_bytes(path: Path, expected_sha256: str) -> bytes:
    require(path.is_absolute(), f"bound path is not absolute: {path}")
    require(path.is_file() and not path.is_symlink(), f"bound file invalid: {path}")
    require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"bound file writable: {path}")
    payload = path.read_bytes()
    require(sha256_bytes(payload) == expected_sha256, f"bound file hash drift: {path}")
    return payload


def torch_memory_evidence(torch: Any) -> dict[str, int]:
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


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        require(not path.exists(), f"result already exists: {path}")
        os.link(temporary, path)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def adapter_digest(torch: Any, model: Any) -> dict[str, Any]:
    from peft import get_peft_model_state_dict

    state = get_peft_model_state_dict(model, adapter_name="default")
    digest = hashlib.sha256()
    elements = 0
    for name in sorted(state):
        tensor = state[name].detach().contiguous().cpu()
        require(tensor.dtype == torch.float32, f"adapter state dtype drift: {name}={tensor.dtype}")
        require(torch.isfinite(tensor).all().item(), f"nonfinite adapter tensor: {name}")
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tuple(tensor.shape)).encode("ascii") + b"\0")
        digest.update(tensor.numpy().tobytes(order="C"))
        elements += tensor.numel()
    require(len(state) == EXPECTED_TRAINABLE_TENSORS, "adapter tensor inventory drift")
    require(elements == EXPECTED_TRAINABLE_ELEMENTS, "adapter element inventory drift")
    return {"sha256": digest.hexdigest(), "tensors": len(state), "elements": elements}


def optimizer_inventory(torch: Any, optimizer: Any, expected_step: int) -> dict[str, Any]:
    state_count = len(optimizer.state)
    exp_avg = 0
    exp_avg_sq = 0
    steps: set[float] = set()
    invalid: list[str] = []
    for parameter, state in optimizer.state.items():
        require(parameter.requires_grad, "optimizer contains frozen parameter")
        for name, value in state.items():
            if torch.is_tensor(value):
                if not torch.isfinite(value).all().item():
                    invalid.append(f"{name}:nonfinite")
                if name in ("exp_avg", "exp_avg_sq") and value.dtype != torch.float32:
                    invalid.append(f"{name}:dtype={value.dtype}")
                if name == "exp_avg":
                    exp_avg += value.numel()
                elif name == "exp_avg_sq":
                    exp_avg_sq += value.numel()
                elif name == "step":
                    steps.add(float(value.item()))
    require(not invalid, f"optimizer state invalid: {invalid[:8]}")
    require(steps == {float(expected_step)}, f"optimizer step drift: {steps}")
    return {
        "state_count": state_count,
        "exp_avg_elements": exp_avg,
        "exp_avg_sq_elements": exp_avg_sq,
        "steps": sorted(steps),
    }


def initialize_shape_equivalent_optimizer_state(
    torch: Any,
    optimizer: Any,
    trainable: list[tuple[str, Any]],
    completed_step: int,
) -> dict[str, Any]:
    """Make the optimizer-state footprint resident before the gated micros.

    AdamW normally creates moments lazily on its first update.  A fresh gate
    would therefore understate the memory of formal steps 6 and 32, where two
    FP32 moments per trainable parameter are already resident.  Zero moment
    values are sufficient for the memory/lifecycle gate; this does not claim to
    reproduce the numerical weights or moments of completed formal training.
    """

    require(completed_step >= 1, "shape-equivalent optimizer state requires a prior completed step")
    require(not optimizer.state, "optimizer state was not initially empty")
    for _, parameter in trainable:
        state = optimizer.state[parameter]
        state["step"] = torch.tensor(float(completed_step), dtype=torch.float32, device="cpu")
        state["exp_avg"] = torch.zeros_like(parameter, memory_format=torch.preserve_format)
        state["exp_avg_sq"] = torch.zeros_like(parameter, memory_format=torch.preserve_format)
    return optimizer_inventory(torch, optimizer, completed_step)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-step", type=int, choices=ALLOWED_SCHEDULE_STEPS, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--original-plan", type=Path, required=True)
    parser.add_argument("--loss-window-plan", type=Path, required=True)
    parser.add_argument("--formal-trainer", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--common-script", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    for name, path in vars(args).items():
        if name == "schedule_step":
            continue
        require(path.is_absolute(), f"--{name.replace('_', '-')} must be absolute")
    return args


def load_bound_schedule_step(
    args: argparse.Namespace,
    common: Any,
    tokenizer: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    read_bound_bytes(args.original_plan, EXPECTED_ORIGINAL_PLAN_SHA256)
    plan_bytes = read_bound_bytes(args.loss_window_plan, EXPECTED_LOSS_WINDOW_PLAN_SHA256)
    train_bytes = read_bound_bytes(args.train, EXPECTED_TRAIN_SHA256)
    plan = json.loads(plan_bytes)
    require(plan.get("schema_version") == "qwen3_32b_agentic_loss_window_plan.v1", "loss-window plan schema drift")
    require(plan.get("algorithm") == "semantic_boundary_loss_windows.v1", "loss-window algorithm drift")
    source = plan.get("source", {})
    require(source.get("original_plan_sha256") == EXPECTED_ORIGINAL_PLAN_SHA256, "derived plan source drift")
    require(source.get("common_script_sha256") == EXPECTED_COMMON_SHA256, "derived plan common binding drift")
    require(source.get("split_sha256", {}).get("train") == EXPECTED_TRAIN_SHA256, "derived plan train binding drift")
    require(source.get("split_rows", {}).get("train") == EXPECTED_TRAIN_ROWS, "derived plan train-row drift")
    execution = plan.get("execution_contract", {})
    require(execution.get("max_window_tokens") == MAX_WINDOW_TOKENS, "maximum window length drift")
    require(execution.get("assistant_labels_covered_exactly_once") is True, "assistant-label coverage drift")
    require(execution.get("context_assistant_labels_masked") is True, "context masking drift")
    require(execution.get("causal_predecessor_required") is True, "causal predecessor drift")
    require(
        execution.get("position_ids") == "absolute source offsets arange(source_start, source_end)",
        "position-id policy drift",
    )
    require(execution.get("packing") is False and execution.get("padding") is False, "packing/padding drift")
    schedule = plan.get("schedule", {})
    require(schedule.get("algorithm") == "capacity_constrained_lpt_micro_windows.v1", "schedule algorithm drift")
    require(schedule.get("optimizer_steps") == 119, "schedule optimizer-step count drift")
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
    require(isinstance(steps, list) and len(steps) == 119, "schedule step inventory drift")
    step_plan = steps[args.schedule_step - 1]
    expected = EXPECTED_STEP_CONTRACTS[args.schedule_step]
    require(canonical_json_sha256(step_plan) == expected["step_plan_sha256"], "selected step-plan digest drift")
    require(step_plan.get("optimizer_step") == args.schedule_step, "selected step ordinal drift")
    for field in (
        "capacity",
        "construction_bin",
        "curated_micro_windows",
        "promoted_micro_windows",
        "input_tokens",
        "shifted_supervised_tokens",
    ):
        require(step_plan.get(field) == expected[field], f"selected step {field} drift")
    micros = step_plan.get("micro_windows")
    require(isinstance(micros, list) and len(micros) == expected["capacity"] == 8, "selected micro inventory drift")
    require(canonical_json_sha256(micros) == expected["micro_windows_sha256"], "selected micro-plan digest drift")
    require([micro.get("window_id") for micro in micros] == expected["window_ids"], "selected window order drift")
    require([micro.get("task_id") for micro in micros] == expected["task_ids"], "selected task order drift")
    require(sum(int(micro["input_tokens"]) for micro in micros) == expected["input_tokens"], "selected input-token total drift")
    require(
        sum(int(micro["shifted_supervised_tokens"]) for micro in micros)
        == expected["shifted_supervised_tokens"],
        "selected supervised-token denominator drift",
    )
    largest = max(micros, key=lambda micro: (int(micro["input_tokens"]), micro["window_id"]))
    require(largest["input_tokens"] == expected["maximum_input_tokens"], "selected maximum input length drift")
    require(largest["window_id"] == expected["maximum_window_id"], "selected maximum window drift")

    train_plan = plan.get("splits", {}).get("train", {})
    row_plans = train_plan.get("row_plans")
    require(isinstance(row_plans, list) and len(row_plans) == EXPECTED_TRAIN_ROWS, "train row-plan inventory drift")
    windows_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row_plan in row_plans:
        for window in row_plan.get("windows", []):
            window_id = window.get("window_id")
            require(isinstance(window_id, str) and window_id not in windows_by_id, "duplicate or invalid window id")
            windows_by_id[window_id] = (row_plan, window)
    raw_lines = train_bytes.splitlines()
    require(len(raw_lines) == EXPECTED_TRAIN_ROWS, "train raw-row count drift")

    materialized: list[dict[str, Any]] = []
    for micro in micros:
        window_id = micro["window_id"]
        require(window_id in windows_by_id, f"unbound selected window: {window_id}")
        row_plan, window = windows_by_id[window_id]
        expected_schedule_fields = {
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
        require(
            all(micro.get(field) == value for field, value in expected_schedule_fields.items()),
            f"{window_id}: schedule binding drift",
        )
        raw = raw_lines[row_plan["line_number"] - 1]
        require(sha256_bytes(raw) == row_plan["line_sha256"], f"{window_id}: source line drift")
        row = json.loads(raw)
        require(row.get("task_id") == row_plan["task_id"], f"{window_id}: task-id drift")
        promoted = bool(row.get("metadata", {}).get("promoted_from_needs_review", False))
        require(promoted == row_plan["promoted"], f"{window_id}: promotion status drift")
        rendered = common.render_agentic_sample(tokenizer, row, max_sequence_length=MAX_RENDER_TOKENS)
        full_input_ids = list(map(int, rendered.input_ids))
        full_labels = list(map(int, rendered.labels))
        require(len(full_input_ids) == row_plan["full_input_tokens"], f"{window_id}: full input length drift")
        require(sha256_i64(full_input_ids) == row_plan["full_input_ids_sha256"], f"{window_id}: full input digest drift")
        require(sha256_i64(full_labels) == row_plan["full_labels_sha256"], f"{window_id}: full labels digest drift")
        require([list(span) for span in rendered.assistant_spans] == row_plan["assistant_spans"], f"{window_id}: assistant spans drift")
        require(rendered.shifted_supervised_tokens == row_plan["shifted_supervised_tokens"], f"{window_id}: full label count drift")
        source_start = int(window["source_start"])
        source_end = int(window["source_end"])
        input_ids = full_input_ids[source_start:source_end]
        labels = [-100] * len(input_ids)
        for span_start, span_end in window["assigned_source_label_spans"]:
            require(source_start <= span_start - 1 and span_end <= source_end, f"{window_id}: assigned span outside window")
            require(all(value != -100 for value in full_labels[span_start:span_end]), f"{window_id}: source label masked")
            labels[span_start - source_start : span_end - source_start] = full_labels[span_start:span_end]
        position_ids = list(range(source_start, source_end))
        require(labels[0] == -100, f"{window_id}: local first token supervised")
        require(len(input_ids) == window["input_tokens"] <= MAX_WINDOW_TOKENS, f"{window_id}: local input length drift")
        require(sum(value != -100 for value in labels[1:]) == window["shifted_supervised_tokens"], f"{window_id}: local token count drift")
        require(sha256_i64(input_ids) == window["input_ids_sha256"], f"{window_id}: local input digest drift")
        require(sha256_i64(labels) == window["labels_sha256"], f"{window_id}: local labels digest drift")
        require(sha256_i64(position_ids) == window["position_ids_sha256"], f"{window_id}: absolute position digest drift")
        materialized.append(
            {
                "window_id": window_id,
                "task_id": row_plan["task_id"],
                "input_ids": input_ids,
                "labels": labels,
                "position_ids": position_ids,
                "input_tokens": window["input_tokens"],
                "shifted_supervised_tokens": window["shifted_supervised_tokens"],
            }
        )
    return step_plan, materialized


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    started_unix = time.time()
    expected_step = EXPECTED_STEP_CONTRACTS[args.schedule_step]
    require(socket.gethostname() == EXPECTED_HOSTNAME, "hostname mismatch")
    require(machine_sha256() == EXPECTED_MACHINE_SHA256, "machine-id mismatch")
    require(sys.version.startswith(EXPECTED_PYTHON_PREFIX), f"Python version drift: {sys.version}")
    gate_path = Path(__file__).resolve()
    require(gate_path.is_file() and not Path(__file__).is_symlink(), "gate script invalid")
    require(stat.S_IMODE(gate_path.stat().st_mode) & 0o222 == 0, "gate script writable")
    gate_sha256 = sha256_file(gate_path)
    read_bound_bytes(args.formal_trainer, EXPECTED_FORMAL_TRAINER_SHA256)
    require(
        args.formal_trainer.name == "qwen3_32b_agentic_formal_trainer_v2_cachebounded.py",
        "formal trainer filename drift",
    )
    require(args.result.parent.is_dir() and not args.result.parent.is_symlink(), "result parent invalid")
    require(not args.result.exists() and not args.result.is_symlink(), "result already exists")
    require(args.model.is_dir() and not args.model.is_symlink(), "model directory invalid")
    require(stat.S_IMODE(args.model.stat().st_mode) & 0o222 == 0, "model directory writable")

    verification = json.loads(read_bound_bytes(args.verification, EXPECTED_VERIFICATION_SHA256))
    require(isinstance(verification, dict) and verification.get("status") == "PASS", "model verification did not pass")
    require(verification.get("model_path") == str(args.model), "verified model path drift")
    require(verification.get("revision") == EXPECTED_MODEL_REVISION, "verified model revision drift")
    verified_inventory = verification.get("file_sha256")
    require(isinstance(verified_inventory, dict) and len(verified_inventory) == 16, "verification inventory drift")
    require(
        verified_inventory.get("model.safetensors.index.json") == EXPECTED_MODEL_INDEX_SHA256,
        "verified index hash drift",
    )
    current_entries = list(args.model.iterdir())
    require(all(path.is_file() and not path.is_symlink() for path in current_entries), "model directory has non-file entry")
    require({path.name for path in current_entries} == set(verified_inventory), "model file inventory drift")
    fresh_snapshot_sha256: dict[str, str] = {}
    for name in sorted(verified_inventory):
        path = args.model / name
        require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"model file writable: {name}")
        actual_hash = sha256_file(path)
        require(actual_hash == verified_inventory[name], f"model file hash drift: {name}")
        fresh_snapshot_sha256[name] = actual_hash
    require(fresh_snapshot_sha256.get("model.safetensors.index.json") == EXPECTED_MODEL_INDEX_SHA256, "index hash drift")
    require(fresh_snapshot_sha256.get("config.json") == EXPECTED_CONFIG_SHA256, "config hash drift")
    require(fresh_snapshot_sha256.get("chat_template.jinja") == EXPECTED_TEMPLATE_SHA256, "template hash drift")
    read_bound_bytes(args.common_script, EXPECTED_COMMON_SHA256)
    require(args.common_script.name == "qwen3_agentic_common.py", "common script filename drift")

    sys.path.insert(0, str(args.common_script.parent))
    import bitsandbytes as bnb
    import peft
    import qwen3_agentic_common as common
    import torch
    import torch.nn.functional as functional
    import transformers
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    require(Path(common.__file__).resolve() == args.common_script.resolve(), "imported common module path drift")
    require(torch.__version__ == EXPECTED_TORCH, f"torch version drift: {torch.__version__}")
    require(torch.version.hip == EXPECTED_TORCH_HIP, f"torch HIP version drift: {torch.version.hip}")
    require(transformers.__version__ == EXPECTED_TRANSFORMERS, f"transformers version drift: {transformers.__version__}")
    require(peft.__version__ == EXPECTED_PEFT, f"peft version drift: {peft.__version__}")
    require(bnb.__version__ == EXPECTED_BITSANDBYTES, f"bitsandbytes version drift: {bnb.__version__}")
    require(torch.cuda.is_available(), "HIP device unavailable")
    require(torch.cuda.device_count() == 1, "accumulation gate requires exactly one visible GPU")
    torch.cuda.set_device(0)
    random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(0)

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False)
    require(len(tokenizer) == EXPECTED_TOKENIZER_LENGTH, "tokenizer length drift")
    require(tokenizer.chat_template == (args.model / "chat_template.jinja").read_text(), "active template drift")
    step_plan, materialized_micros = load_bound_schedule_step(args, common, tokenizer)

    load_started = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
        device_map={"": 0},
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    model_load_seconds = time.time() - load_started
    linear4 = {name: module for name, module in model.named_modules() if isinstance(module, bnb.nn.Linear4bit)}
    require(len(linear4) == EXPECTED_LINEAR4BIT, f"Linear4bit count drift: {len(linear4)}")
    require(not [name for name, parameter in model.named_parameters() if parameter.device.type == "meta"], "meta parameter")
    require(not [name for name, parameter in model.named_parameters() if parameter.device.type == "cpu"], "CPU parameter")
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    norm_modules = 0
    for module in model.modules():
        if module.__class__.__name__.endswith("RMSNorm"):
            module.to(torch.float32)
            norm_modules += 1
    require(norm_modules == EXPECTED_RMSNORM, f"RMSNorm inventory drift: {norm_modules}")
    model.config.use_cache = False
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})

    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.0,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=list(LORA_TARGETS),
        inference_mode=False,
        use_rslora=False,
    )
    model = get_peft_model(model, lora_config, autocast_adapter_dtype=False, low_cpu_mem_usage=False)
    for _, parameter in model.named_parameters():
        if parameter.requires_grad and parameter.dtype != torch.float32:
            parameter.data = parameter.data.to(torch.float32)
    model.train()
    lora_modules = {
        name: module
        for name, module in model.named_modules()
        if hasattr(module, "lora_A") and "default" in module.lora_A
    }
    require(len(lora_modules) == EXPECTED_LORA_MODULES, f"LoRA module count drift: {len(lora_modules)}")
    trainable = [(name, parameter) for name, parameter in model.named_parameters() if parameter.requires_grad]
    require(len(trainable) == EXPECTED_TRAINABLE_TENSORS, f"trainable tensor count drift: {len(trainable)}")
    require(
        all("lora_A.default.weight" in name or "lora_B.default.weight" in name for name, _ in trainable),
        "non-LoRA trainable",
    )
    require(all(parameter.dtype == torch.float32 for _, parameter in trainable), "trainable dtype is not FP32")
    trainable_elements = sum(parameter.numel() for _, parameter in trainable)
    require(trainable_elements == EXPECTED_TRAINABLE_ELEMENTS, "LoRA trainable element count drift")
    require(
        trainable_elements == sum(8 * (module.in_features + module.out_features) for module in lora_modules.values()),
        "LoRA shape-derived element count drift",
    )
    b_parameters = [(name, parameter) for name, parameter in trainable if "lora_B.default.weight" in name]
    require(len(b_parameters) == EXPECTED_LORA_MODULES, "LoRA-B tensor count drift")
    require(all(torch.count_nonzero(parameter).item() == 0 for _, parameter in b_parameters), "LoRA-B not zero initialized")

    optimizer = torch.optim.AdamW(
        [parameter for _, parameter in trainable],
        lr=1.0e-4,
        betas=(0.9, 0.999),
        eps=1.0e-8,
        weight_decay=0.0,
        foreach=False,
        fused=False,
    )
    require(len(optimizer.param_groups) == 1, "optimizer param-group count drift")
    require(
        len(optimizer.param_groups[0]["params"]) == len(trainable)
        and all(
            actual is expected
            for actual, (_, expected) in zip(optimizer.param_groups[0]["params"], trainable, strict=True)
        ),
        "optimizer parameter order drift",
    )
    optimizer_state_before = initialize_shape_equivalent_optimizer_state(
        torch,
        optimizer,
        trainable,
        args.schedule_step - 1,
    )
    require(optimizer_state_before["state_count"] == EXPECTED_TRAINABLE_TENSORS, "resident optimizer state count drift")
    require(
        optimizer_state_before["exp_avg_elements"] == EXPECTED_TRAINABLE_ELEMENTS,
        "resident optimizer first-moment size drift",
    )
    require(
        optimizer_state_before["exp_avg_sq_elements"] == EXPECTED_TRAINABLE_ELEMENTS,
        "resident optimizer second-moment size drift",
    )
    # The formal trainer reaches these steps with moments resident but the
    # allocator cache released at the preceding micro/step boundary.  Remove
    # only temporary cache created by the gate's state-inventory scan.
    torch.cuda.synchronize(0)
    gc.collect()
    torch.cuda.empty_cache()
    model_ready_memory = torch_memory_evidence(torch)
    optimizer.zero_grad(set_to_none=True)
    require(not [name for name, parameter in trainable if parameter.grad is not None], "entry residual gradient")
    adapter_before = adapter_digest(torch, model)

    denominator = int(step_plan["shifted_supervised_tokens"])
    require(denominator == expected_step["shifted_supervised_tokens"], "backward denominator drift")
    executed_window_ids: list[str] = []
    executed_task_ids: list[str] = []
    total_loss_sum = 0.0
    total_supervised_tokens = 0
    micro_evidence: list[dict[str, Any]] = []
    cache_releases = 0
    step_started = time.time()
    for micro_index, (micro_plan, materialized) in enumerate(
        zip(step_plan["micro_windows"], materialized_micros, strict=True),
        1,
    ):
        require(materialized["window_id"] == micro_plan["window_id"], "materialized window order drift")
        require(materialized["task_id"] == micro_plan["task_id"], "materialized task order drift")
        require(
            materialized["shifted_supervised_tokens"] == micro_plan["shifted_supervised_tokens"],
            "materialized supervised-token drift",
        )
        memory_before = torch_memory_evidence(torch)
        torch.cuda.reset_peak_memory_stats(0)
        micro_started = time.time()
        input_ids = torch.tensor([materialized["input_ids"]], dtype=torch.long, device="cuda:0")
        labels = torch.tensor([materialized["labels"]], dtype=torch.long, device="cuda:0")
        position_ids = torch.tensor([materialized["position_ids"]], dtype=torch.long, device="cuda:0")
        attention_mask = torch.ones_like(input_ids)
        supervised_mask = labels[0, 1:] != -100
        logit_positions = torch.arange(input_ids.shape[1] - 1, device="cuda:0")[supervised_mask]
        targets = labels[0, 1:][supervised_mask]
        expected_tokens = int(materialized["shifted_supervised_tokens"])
        require(logit_positions.numel() == expected_tokens > 0, "selective-logit count drift")
        require(targets.numel() == expected_tokens, "target-token count drift")
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
            "selective logits shape drift",
        )
        loss_sum = functional.cross_entropy(outputs.logits[0].float(), targets, reduction="sum")
        require(torch.isfinite(loss_sum).item(), f"{materialized['window_id']}: nonfinite loss")
        loss_value = float(loss_sum.detach().cpu())
        require(math.isfinite(loss_value) and loss_value >= 0.0, f"{materialized['window_id']}: invalid CPU loss")
        (loss_sum / denominator).backward()
        executed_window_ids.append(materialized["window_id"])
        executed_task_ids.append(materialized["task_id"])
        total_loss_sum += loss_value
        total_supervised_tokens += expected_tokens
        input_tokens = int(materialized["input_tokens"])
        window_id = materialized["window_id"]
        task_id = materialized["task_id"]
        del outputs, loss_sum, input_ids, labels, position_ids, attention_mask, supervised_mask, logit_positions, targets
        del materialized
        release_per_micro_allocator_cache(torch)
        cache_releases += 1
        memory_after = torch_memory_evidence(torch)
        require(memory_after["max_allocated"] >= memory_after["allocated"], "micro allocated-memory accounting drift")
        require(memory_after["max_reserved"] >= memory_after["reserved"], "micro reserved-memory accounting drift")
        micro_evidence.append(
            {
                "micro_index": micro_index,
                "window_id": window_id,
                "task_id": task_id,
                "input_tokens": input_tokens,
                "shifted_supervised_tokens": expected_tokens,
                "loss_sum": loss_value,
                "normalized_loss_contribution": loss_value / denominator,
                "elapsed_seconds": time.time() - micro_started,
                "torch_memory_before": memory_before,
                "torch_memory_after_cache_release": memory_after,
                "allocator_cache_release_completed": True,
            }
        )

    require(cache_releases == expected_step["capacity"], "per-micro allocator-cache release count drift")
    require(executed_window_ids == expected_step["window_ids"], "executed window order drift")
    require(executed_task_ids == expected_step["task_ids"], "executed task order drift")
    require(total_supervised_tokens == denominator, "executed supervised-token denominator coverage drift")
    require(math.isfinite(total_loss_sum) and total_loss_sum >= 0.0, "accumulated loss sum invalid")
    mean_loss = total_loss_sum / denominator
    require(math.isfinite(mean_loss) and mean_loss >= 0.0, "mean accumulated loss invalid")

    missing_gradients: list[str] = []
    nonfinite_gradients: list[str] = []
    nonzero_gradients = 0
    nonzero_b_gradients = 0
    for name, parameter in trainable:
        if parameter.grad is None:
            missing_gradients.append(name)
            continue
        if not torch.isfinite(parameter.grad).all().item():
            nonfinite_gradients.append(name)
        if torch.count_nonzero(parameter.grad).item() > 0:
            nonzero_gradients += 1
            if "lora_B.default.weight" in name:
                nonzero_b_gradients += 1
    require(not missing_gradients, f"missing accumulated gradients: {missing_gradients[:8]}")
    require(not nonfinite_gradients, f"nonfinite accumulated gradients: {nonfinite_gradients[:8]}")
    require(nonzero_gradients > 0, "all accumulated gradients are zero")
    require(nonzero_b_gradients == EXPECTED_LORA_MODULES, "not every LoRA-B tensor received nonzero accumulated gradient")
    grad_norm = torch.nn.utils.clip_grad_norm_(
        [parameter for _, parameter in trainable],
        max_norm=1.0,
        error_if_nonfinite=True,
        foreach=False,
    )
    grad_norm_value = float(grad_norm.detach().cpu())
    require(math.isfinite(grad_norm_value), "nonfinite accumulated gradient norm")
    del grad_norm

    optimizer_started = time.time()
    optimizer.step()
    torch.cuda.synchronize(0)
    optimizer_seconds = time.time() - optimizer_started
    optimizer_state = optimizer_inventory(torch, optimizer, args.schedule_step)
    require(optimizer_state["state_count"] == EXPECTED_TRAINABLE_TENSORS, "optimizer state count drift")
    require(optimizer_state["exp_avg_elements"] == EXPECTED_TRAINABLE_ELEMENTS, "optimizer first-moment size drift")
    require(optimizer_state["exp_avg_sq_elements"] == EXPECTED_TRAINABLE_ELEMENTS, "optimizer second-moment size drift")
    adapter_after = adapter_digest(torch, model)
    require(adapter_after["sha256"] != adapter_before["sha256"], "optimizer step did not change adapter")
    require(
        adapter_after["tensors"] == adapter_before["tensors"]
        and adapter_after["elements"] == adapter_before["elements"],
        "adapter inventory changed",
    )
    updated_b_tensors = sum(torch.count_nonzero(parameter).item() > 0 for _, parameter in b_parameters)
    require(updated_b_tensors == EXPECTED_LORA_MODULES, "not every LoRA-B tensor updated")
    optimizer.zero_grad(set_to_none=True)
    require(not [name for name, parameter in trainable if parameter.grad is not None], "exit residual gradient")
    torch.cuda.synchronize(0)
    gc.collect()
    torch.cuda.empty_cache()
    final_memory = torch_memory_evidence(torch)
    observed_torch_max_allocated = max(
        [model_ready_memory["max_allocated"]]
        + [item["torch_memory_before"]["max_allocated"] for item in micro_evidence]
        + [item["torch_memory_after_cache_release"]["max_allocated"] for item in micro_evidence]
        + [final_memory["max_allocated"]]
    )
    observed_torch_max_reserved = max(
        [model_ready_memory["max_reserved"]]
        + [item["torch_memory_before"]["max_reserved"] for item in micro_evidence]
        + [item["torch_memory_after_cache_release"]["max_reserved"] for item in micro_evidence]
        + [final_memory["max_reserved"]]
    )
    return {
        "schema_version": "qwen3_32b_cachebounded_accumulation_gate.v1",
        "status": "PASS",
        "status_semantics": (
            "frozen schedule-step math and PyTorch allocator checks passed; external controller evidence "
            "for both steps 6 and 32 is still required before formal restart"
        ),
        "gate": "cachebounded-frozen-accumulation",
        "schedule_step": args.schedule_step,
        "started_unix": started_unix,
        "completed_unix": time.time(),
        "hostname": socket.gethostname(),
        "machine_sha256": machine_sha256(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "gate_script_path": str(gate_path),
        "gate_script_sha256": gate_sha256,
        "versions": {
            "python": sys.version,
            "torch": torch.__version__,
            "torch_hip": torch.version.hip,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
            "bitsandbytes": bnb.__version__,
        },
        "bindings": {
            "model_path": str(args.model),
            "model_revision": EXPECTED_MODEL_REVISION,
            "model_verification_path": str(args.verification),
            "model_verification_sha256": EXPECTED_VERIFICATION_SHA256,
            "fresh_model_sha256": fresh_snapshot_sha256,
            "original_plan_path": str(args.original_plan),
            "original_plan_sha256": EXPECTED_ORIGINAL_PLAN_SHA256,
            "loss_window_plan_path": str(args.loss_window_plan),
            "loss_window_plan_sha256": EXPECTED_LOSS_WINDOW_PLAN_SHA256,
            "formal_trainer_path": str(args.formal_trainer),
            "formal_trainer_sha256": EXPECTED_FORMAL_TRAINER_SHA256,
            "train_path": str(args.train),
            "train_sha256": EXPECTED_TRAIN_SHA256,
            "common_script_path": str(args.common_script),
            "common_script_sha256": EXPECTED_COMMON_SHA256,
            "selected_step_plan_sha256": expected_step["step_plan_sha256"],
            "selected_micro_windows_sha256": expected_step["micro_windows_sha256"],
        },
        "frozen_contract": {
            "allowed_schedule_steps": list(ALLOWED_SCHEDULE_STEPS),
            "selected_step": args.schedule_step,
            "selected_step_contract": expected_step,
            "micro_window_reduction": "sum",
            "optimizer_step_normalization": (
                "divide each micro CE sum by frozen optimizer-step shifted-supervised-token total"
            ),
            "optimizer": {
                "class": "torch.optim.AdamW",
                "learning_rate": 1.0e-4,
                "betas": [0.9, 0.999],
                "epsilon": 1.0e-8,
                "weight_decay": 0.0,
                "foreach": False,
                "fused": False,
                "max_gradient_norm": 1.0,
                "resident_state_before_micros": {
                    "completed_step": args.schedule_step - 1,
                    "moment_initialization": "shape-equivalent zero FP32 tensors",
                    "numerical_formal_state_reproduction_claimed": False,
                    "inventory": optimizer_state_before,
                },
            },
            "per_micro_allocator_cache_release": PER_MICRO_ALLOCATOR_CACHE_RELEASE,
        },
        "execution": {
            "window_ids": executed_window_ids,
            "task_ids": executed_task_ids,
            "micro_windows": len(executed_window_ids),
            "input_tokens": sum(item["input_tokens"] for item in micro_evidence),
            "shifted_supervised_tokens": total_supervised_tokens,
            "denominator": denominator,
            "cross_entropy_sum": total_loss_sum,
            "mean_cross_entropy": mean_loss,
            "gradient_norm_before_clip": grad_norm_value,
            "nonzero_gradient_tensors": nonzero_gradients,
            "nonzero_lora_b_gradient_tensors": nonzero_b_gradients,
            "updated_lora_b_tensors": updated_b_tensors,
            "optimizer_step_seconds": optimizer_seconds,
            "elapsed_seconds": time.time() - step_started,
            "cache_release_executions": cache_releases,
        },
        "micro_evidence": micro_evidence,
        "adapter_before": adapter_before,
        "adapter_after": adapter_after,
        "optimizer": {
            "before_micros": optimizer_state_before,
            "after_single_step": optimizer_state,
        },
        "model_runtime": {
            "model_load_seconds": model_load_seconds,
            "linear4bit_modules": len(linear4),
            "rmsnorm_fp32_modules": norm_modules,
            "lora_modules": len(lora_modules),
            "trainable_tensors": len(trainable),
            "trainable_elements": trainable_elements,
            "trainable_dtype": "float32",
            "base_compute_dtype": "bfloat16",
            "attention_implementation": "sdpa",
            "gradient_checkpointing": {"enabled": True, "use_reentrant": False},
            "torch_memory_after_resident_optimizer_state": model_ready_memory,
        },
        "gpu_memory": {
            "allocated": final_memory["allocated"],
            "reserved": final_memory["reserved"],
            "max_allocated": observed_torch_max_allocated,
            "max_reserved": observed_torch_max_reserved,
        },
        "external_controller_contract": {
            "required_schedule_steps": list(ALLOWED_SCHEDULE_STEPS),
            "independent_result_per_step": True,
            "controller_hard_limit_bytes": CONTROLLER_HARD_LIMIT_BYTES,
            "internal_maximum_gpu_used_bytes_target": INTERNAL_TARGET_BYTES,
            "measurement_field": "controller-result.json:maximum_gpu_used_bytes",
            "all_steps_must_be_below_hard_limit": True,
            "all_steps_must_meet_internal_target_for_formal_restart": True,
            "this_result_alone_authorizes_formal_restart": False,
        },
        "writes": {
            "requested_result_only": True,
            "formal_run_written": False,
            "checkpoint_written": False,
            "adapter_written": False,
            "optimizer_state_written": False,
            "rng_state_written": False,
        },
        "forward_passed": True,
        "backward_accumulation_passed": True,
        "optimizer_step_passed": True,
        "adapter_changed": True,
        "nonfinite_detected": False,
    }

def main() -> None:
    args = parse_args()
    try:
        payload = run_gate(args)
        exit_code = 0
    except BaseException as error:
        payload = {
            "schema_version": "qwen3_32b_cachebounded_accumulation_gate.v1",
            "status": "FAIL",
            "gate": "cachebounded-frozen-accumulation",
            "schedule_step": args.schedule_step,
            "formal_restart_authorized": False,
            "hostname": socket.gethostname(),
            "machine_sha256": machine_sha256(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "error_type": type(error).__name__,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    atomic_json(args.result, payload)
    print(json.dumps({"status": payload["status"], "result": str(args.result)}, sort_keys=True), flush=True)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
