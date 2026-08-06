#!/usr/bin/env python3
"""Build a deterministic Qwen3-32B agentic SFT plan from the frozen release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "qwen3_32b_agentic_train_plan.v1"
ALGORITHM = "capacity_constrained_lpt.v1"
MASK_ALGORITHM = "qwen3_special_token_assistant_segments.v1"
SEED = 20260803
MODEL_REPOSITORY = "unsloth/Qwen3-32B-bnb-4bit"
MODEL_REVISION = "7f721e74a6a8cc9ee352f7e49303a2c1705f9083"
EXPECTED_ROWS = {"train": 946, "validation": 116, "test": 113}
EXPECTED_SPLIT_SHA256 = {
    "train": "707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58",
    "validation": "d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f",
    "test": "d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283",
}
EXPECTED_COMMON_SHA256 = "d0159dd2ab96961ea116dc4264833a65a98d63421a21c798aa70dcc8bfcb9f7f"
EXPECTED_CURATED = 262
EXPECTED_PROMOTED = 684
EXPECTED_MODEL_FILES_SHA256 = {
    "chat_template.jinja": "96fd16d36fb085260f9eb1e717b2c4e6e8b9e75a5e6504f66c8d6b128d82784d",
    "config.json": "918fe2d123e79abf8ed4688278cc7d9c6c54d25fbea35e5f0870985f4d663000",
    "generation_config.json": "7995f74dd367a291e8a6209c8e8bd44653b3582f43908a5a113551fc18515105",
    "model.safetensors.index.json": "2771f7e67bacc73ceb4ee0dfe6027d49fc9a4390d17eda517a4f7f48923d6a61",
    "special_tokens_map.json": "b5acd1507cb3a3539e63369cb4a2b675a599cf13afe62282d371518288967797",
    "tokenizer.json": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
    "tokenizer_config.json": "5f95699c6cf42ee1e3ea6c468d6a1ad61fef4aadf5802b1b56fddbf68370a192",
}
EXPECTED_TOOLS = ("read", "grep", "find", "ls", "bash")
MAX_SEQUENCE_LENGTH = 32_768
EXPECTED_MODEL_CONTEXT = 40_960
EXPECTED_TOKENIZER_LENGTH = 151_669
WINDOWS = 119
SEVEN_SAMPLE_WINDOWS = 6
EIGHT_SAMPLE_WINDOWS = 113


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(*parts: Any) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def nearest(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * percentile)]


def summarize(values: list[int]) -> dict[str, Any]:
    return {
        "min": min(values),
        "mean": sum(values) / len(values),
        "p50": nearest(values, 0.50),
        "p95": nearest(values, 0.95),
        "max": max(values),
        "total": sum(values),
    }


def tool_names(row: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for tool in row.get("tools", []):
        require(tool.get("type") == "function", f"{row.get('task_id')}: non-function tool")
        function = tool.get("function")
        require(isinstance(function, dict), f"{row.get('task_id')}: malformed tool")
        names.append(function.get("name"))
    return tuple(names)


def validate_row(row: dict[str, Any], split: str, line_number: int) -> None:
    task_id = row.get("task_id")
    require(isinstance(task_id, str) and task_id, f"{split}:{line_number}: task_id missing")
    require(row.get("schema_version") == "rdk_sft_sample.v1", f"{task_id}: schema drift")
    require(row.get("profile") == "agentic", f"{task_id}: non-agentic row")
    require(row.get("split") == split, f"{task_id}: declared split drift")
    require(tool_names(row) == EXPECTED_TOOLS, f"{task_id}: native tool inventory drift")
    messages = row.get("messages")
    require(isinstance(messages, list) and messages, f"{task_id}: messages missing")
    require(messages[0].get("role") == "system", f"{task_id}: first message is not system")
    require(any(message.get("role") == "assistant" for message in messages), f"{task_id}: no assistant")


def read_split(path: Path, split: str) -> tuple[list[bytes], list[dict[str, Any]], set[str]]:
    require(path.is_file(), f"missing {split} file: {path}")
    require(not path.is_symlink(), f"{split} file is a symlink")
    require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"{split} file is writable")
    require(sha256_file(path) == EXPECTED_SPLIT_SHA256[split], f"{split} hash drift")
    raw_lines = path.read_bytes().splitlines()
    require(len(raw_lines) == EXPECTED_ROWS[split], f"{split} row count drift")
    rows: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    for line_number, raw in enumerate(raw_lines, 1):
        row = json.loads(raw)
        validate_row(row, split, line_number)
        task_id = row["task_id"]
        require(task_id not in task_ids, f"{split}: duplicate task_id {task_id}")
        task_ids.add(task_id)
        rows.append(row)
    return raw_lines, rows, task_ids


def build_bins(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    construction_order = sorted(range(WINDOWS), key=lambda index: stable_hash(SEED, "capacity", index))
    seven = set(construction_order[:SEVEN_SAMPLE_WINDOWS])
    bins = [
        {
            "construction_bin": index,
            "capacity": 7 if index in seven else 8,
            "shifted_supervised_tokens": 0,
            "samples": [],
        }
        for index in range(WINDOWS)
    ]
    ordered_samples = sorted(
        samples,
        key=lambda sample: (
            -sample["shifted_supervised_tokens"],
            stable_hash(SEED, "sample-order", sample["task_id"], sample["line_sha256"]),
        ),
    )
    tie_rank = {index: rank for rank, index in enumerate(construction_order)}
    for sample in ordered_samples:
        candidates = [item for item in bins if len(item["samples"]) < item["capacity"]]
        require(candidates, "no optimizer-window capacity remains")
        target = min(
            candidates,
            key=lambda item: (
                item["shifted_supervised_tokens"],
                len(item["samples"]),
                tie_rank[item["construction_bin"]],
            ),
        )
        target["samples"].append(sample)
        target["shifted_supervised_tokens"] += sample["shifted_supervised_tokens"]
    require(all(len(item["samples"]) == item["capacity"] for item in bins), "window not filled")
    execution = sorted(bins, key=lambda item: stable_hash(SEED, "window-order", item["construction_bin"]))
    for step, window in enumerate(execution, 1):
        window["optimizer_step"] = step
        window["samples"] = sorted(
            window["samples"],
            key=lambda sample: stable_hash(
                SEED,
                "within-window",
                window["construction_bin"],
                sample["task_id"],
                sample["line_sha256"],
            ),
        )
        window["input_tokens"] = sum(sample["input_tokens"] for sample in window["samples"])
        window["curated"] = sum(not sample["promoted"] for sample in window["samples"])
        window["promoted"] = sum(sample["promoted"] for sample in window["samples"])
    return execution


def atomic_create(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    require(not partial.exists(), f"partial output already exists: {partial}")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--common-script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require(sha256_file(args.common_script) == EXPECTED_COMMON_SHA256, "common script hash drift")
    require(args.model.is_dir() and not args.model.is_symlink(), "model directory invalid")
    require(stat.S_IMODE(args.model.stat().st_mode) & 0o222 == 0, "model directory is writable")
    model_hashes: dict[str, str] = {}
    for name, expected_hash in EXPECTED_MODEL_FILES_SHA256.items():
        path = args.model / name
        require(path.is_file() and not path.is_symlink(), f"model metadata invalid: {name}")
        require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"model metadata writable: {name}")
        actual_hash = sha256_file(path)
        require(actual_hash == expected_hash, f"model metadata hash drift: {name}")
        model_hashes[name] = actual_hash

    split_payload: dict[str, tuple[list[bytes], list[dict[str, Any]], set[str]]] = {}
    for split in ("train", "validation", "test"):
        split_payload[split] = read_split(args.data / f"{split}.jsonl", split)
    train_ids = split_payload["train"][2]
    validation_ids = split_payload["validation"][2]
    test_ids = split_payload["test"][2]
    require(not train_ids & validation_ids, "train/validation task leakage")
    require(not train_ids & test_ids, "train/test task leakage")
    require(not validation_ids & test_ids, "validation/test task leakage")

    sys.path.insert(0, str(args.common_script.parent))
    import qwen3_agentic_common as common
    import transformers
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False)
    require(len(tokenizer) == EXPECTED_TOKENIZER_LENGTH, "tokenizer vocabulary drift")
    require(tokenizer.model_max_length == EXPECTED_MODEL_CONTEXT, "tokenizer context drift")
    require(tokenizer.chat_template == (args.model / "chat_template.jinja").read_text(), "template load drift")
    config = json.loads((args.model / "config.json").read_text())
    require(config.get("model_type") == "qwen3", "model type drift")
    require(config.get("max_position_embeddings") == EXPECTED_MODEL_CONTEXT, "model context drift")
    quant = config.get("quantization_config", {})
    require(quant.get("load_in_4bit") is True, "model is not prequantized 4-bit")
    require(quant.get("bnb_4bit_quant_type") == "nf4", "quantization type drift")
    require(quant.get("bnb_4bit_use_double_quant") is True, "double quantization drift")
    require(quant.get("bnb_4bit_compute_dtype") == "bfloat16", "compute dtype drift")

    raw_lines, train_rows, _ = split_payload["train"]
    samples: list[dict[str, Any]] = []
    for line_number, (raw, row) in enumerate(zip(raw_lines, train_rows, strict=True), 1):
        promoted = bool(row["metadata"].get("promoted_from_needs_review", False))
        if promoted:
            for key in (
                "original_quality_status",
                "quality_score",
                "failed_checks",
                "promoted_at",
                "promotion_basis",
            ):
                require(key in row["metadata"], f"{row['task_id']}: promoted marker {key} missing")
        rendered = common.render_agentic_sample(
            tokenizer,
            row,
            max_sequence_length=MAX_SEQUENCE_LENGTH,
        )
        samples.append(
            {
                "line_number": line_number,
                "line_sha256": hashlib.sha256(raw).hexdigest(),
                "task_id": row["task_id"],
                "promoted": promoted,
                "input_tokens": len(rendered.input_ids),
                "assistant_turns": len(rendered.assistant_spans),
                "shifted_supervised_tokens": rendered.shifted_supervised_tokens,
            }
        )

    require(sum(not item["promoted"] for item in samples) == EXPECTED_CURATED, "curated count drift")
    require(sum(item["promoted"] for item in samples) == EXPECTED_PROMOTED, "promoted count drift")
    input_values = [item["input_tokens"] for item in samples]
    shifted_values = [item["shifted_supervised_tokens"] for item in samples]
    require(max(input_values) <= MAX_SEQUENCE_LENGTH, "maximum sequence exceeds training contract")

    windows = build_bins(samples)
    require(sum(len(window["samples"]) for window in windows) == EXPECTED_ROWS["train"], "schedule rows drift")
    require(sum(window["capacity"] == 7 for window in windows) == SEVEN_SAMPLE_WINDOWS, "7-row windows drift")
    require(sum(window["capacity"] == 8 for window in windows) == EIGHT_SAMPLE_WINDOWS, "8-row windows drift")
    scheduled = [sample["task_id"] for window in windows for sample in window["samples"]]
    require(len(scheduled) == len(set(scheduled)) == EXPECTED_ROWS["train"], "schedule duplication or omission")
    window_tokens = [window["shifted_supervised_tokens"] for window in windows]

    def gate_sample(target: int) -> dict[str, Any]:
        return min(samples, key=lambda item: (abs(item["input_tokens"] - target), item["task_id"]))

    gate_samples = {
        "short": gate_sample(4_600),
        "medium": gate_sample(8_192),
        "longest": max(samples, key=lambda item: (item["input_tokens"], item["task_id"])),
    }
    assistant_header = [
        tokenizer.convert_tokens_to_ids(common.IM_START),
        *tokenizer.encode(common.ASSISTANT_ROLE_PREFIX, add_special_tokens=False),
    ]
    plan = {
        "schema_version": SCHEMA_VERSION,
        "seed": SEED,
        "algorithm": ALGORITHM,
        "source": {
            "data_directory": str(args.data),
            "split_sha256": EXPECTED_SPLIT_SHA256,
            "split_rows": EXPECTED_ROWS,
            "common_script_path": str(args.common_script),
            "common_script_sha256": EXPECTED_COMMON_SHA256,
        },
        "model": {
            "path": str(args.model),
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "critical_file_sha256": model_hashes,
            "model_type": config["model_type"],
            "max_position_embeddings": config["max_position_embeddings"],
            "tokenizer_length": len(tokenizer),
            "transformers_version": transformers.__version__,
            "quantization": {
                "load_in_4bit": quant["load_in_4bit"],
                "type": quant["bnb_4bit_quant_type"],
                "double_quant": quant["bnb_4bit_use_double_quant"],
                "compute_dtype": quant["bnb_4bit_compute_dtype"],
            },
        },
        "render_contract": {
            "algorithm": MASK_ALGORITHM,
            "official_chat_template_unchanged": True,
            "chat_template_sha256": model_hashes["chat_template.jinja"],
            "enable_thinking": True,
            "add_generation_prompt": False,
            "assistant_only": True,
            "assistant_role_header_token_ids": assistant_header,
            "assistant_role_header_supervised": False,
            "assistant_body_and_im_end_supervised": True,
            "causal_shift": "logits[:-1] against labels[1:]",
            "max_sequence_length": MAX_SEQUENCE_LENGTH,
            "truncation": False,
            "padding": False,
            "packing": False,
        },
        "dataset": {
            "rows": EXPECTED_ROWS["train"],
            "curated": EXPECTED_CURATED,
            "promoted": EXPECTED_PROMOTED,
            "input_tokens": summarize(input_values),
            "shifted_supervised_tokens": summarize(shifted_values),
            "assistant_turns": summarize([item["assistant_turns"] for item in samples]),
            "argmax_input": max(samples, key=lambda item: (item["input_tokens"], item["task_id"])),
            "argmax_shifted_supervised": max(
                samples, key=lambda item: (item["shifted_supervised_tokens"], item["task_id"])
            ),
        },
        "gates": gate_samples,
        "schedule": {
            "optimizer_steps": WINDOWS,
            "seven_sample_windows": SEVEN_SAMPLE_WINDOWS,
            "eight_sample_windows": EIGHT_SAMPLE_WINDOWS,
            "window_shifted_supervised_tokens": summarize(window_tokens),
            "windows": windows,
        },
    }
    payload = (json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    atomic_create(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "rows": EXPECTED_ROWS["train"],
                "optimizer_steps": WINDOWS,
                "input_tokens": summarize(input_values),
                "shifted_supervised_tokens": summarize(shifted_values),
                "window_token_min": min(window_tokens),
                "window_token_max": max(window_tokens),
                "gates": gate_samples,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
