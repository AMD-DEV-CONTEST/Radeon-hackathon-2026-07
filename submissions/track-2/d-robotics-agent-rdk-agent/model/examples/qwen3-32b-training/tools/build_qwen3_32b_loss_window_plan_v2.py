#!/usr/bin/env python3
"""Build a deterministic <=8192-token execution plan for Qwen3 agentic SFT."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import struct
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "qwen3_32b_agentic_loss_window_plan.v1"
ALGORITHM = "semantic_boundary_loss_windows.v1"
SCHEDULE_ALGORITHM = "capacity_constrained_lpt_micro_windows.v1"
DIGEST_ALGORITHM = "sha256_le_i64.v1"
SEED = 20260803
MAX_RENDER_TOKENS = 32_768
MAX_WINDOW_TOKENS = 8_192
OPTIMIZER_STEPS = 119
EXPECTED_ORIGINAL_PLAN_SHA256 = "39d6ae20fcb566d6544049e2ea263c5bc64fe8ecd349c71b4a8ec58721134f25"
EXPECTED_COMMON_SHA256 = "d0159dd2ab96961ea116dc4264833a65a98d63421a21c798aa70dcc8bfcb9f7f"
EXPECTED_TEMPLATE_SHA256 = "96fd16d36fb085260f9eb1e717b2c4e6e8b9e75a5e6504f66c8d6b128d82784d"
EXPECTED_ROWS = {"train": 946, "validation": 116, "test": 113}
EXPECTED_SPLIT_SHA256 = {
    "train": "707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58",
    "validation": "d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f",
    "test": "d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283",
}
EXPECTED_SHIFTED_TOKENS = {"train": 534_734, "validation": 66_181, "test": 67_472}
EXPECTED_LONG_ROWS = {"train": 23, "validation": 4, "test": 7}
EXPECTED_WINDOWS = {"train": 948, "validation": 116, "test": 113}
EXPECTED_MODEL_FILES_SHA256 = {
    "chat_template.jinja": EXPECTED_TEMPLATE_SHA256,
    "config.json": "918fe2d123e79abf8ed4688278cc7d9c6c54d25fbea35e5f0870985f4d663000",
    "tokenizer.json": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
    "tokenizer_config.json": "5f95699c6cf42ee1e3ea6c468d6a1ad61fef4aadf5802b1b56fddbf68370a192",
}
EXPECTED_TOKENIZER_LENGTH = 151_669
TOOL_RESPONSE_MARKER_IDS = [151_665, 198]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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


def stable_hash(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def nearest(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * percentile)]


def summarize(values: list[int]) -> dict[str, Any]:
    require(bool(values), "cannot summarize empty values")
    return {
        "min": min(values),
        "mean": sum(values) / len(values),
        "p50": nearest(values, 0.50),
        "p95": nearest(values, 0.95),
        "max": max(values),
        "total": sum(values),
    }


def find_subsequence(values: list[int], needle: list[int]) -> list[int]:
    require(bool(needle), "empty subsequence")
    return [
        index
        for index in range(0, len(values) - len(needle) + 1)
        if values[index : index + len(needle)] == needle
    ]


def atomic_create(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}.partial")
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
    parser.add_argument("--original-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_rows(path: Path, split: str) -> tuple[list[bytes], list[dict[str, Any]]]:
    require(path.is_file() and not path.is_symlink(), f"{split}: source file invalid")
    require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"{split}: source file writable")
    require(sha256_file(path) == EXPECTED_SPLIT_SHA256[split], f"{split}: source hash drift")
    raw_lines = path.read_bytes().splitlines()
    require(len(raw_lines) == EXPECTED_ROWS[split], f"{split}: row count drift")
    rows = [json.loads(raw) for raw in raw_lines]
    task_ids: set[str] = set()
    for line_number, row in enumerate(rows, 1):
        task_id = row.get("task_id")
        require(isinstance(task_id, str) and task_id, f"{split}:{line_number}: task id missing")
        require(task_id not in task_ids, f"{split}: duplicate task id {task_id}")
        task_ids.add(task_id)
        require(row.get("schema_version") == "rdk_sft_sample.v1", f"{task_id}: schema drift")
        require(row.get("profile") == "agentic", f"{task_id}: profile drift")
        require(row.get("split") == split, f"{task_id}: split drift")
    return raw_lines, rows


def build_span_groups(spans: list[tuple[int, int]], assistant_header_tokens: int) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    first = 0
    while first < len(spans):
        first_header = spans[first][0] - assistant_header_tokens
        require(first_header >= 0, "assistant header underflow")
        last = first
        while last + 1 < len(spans) and spans[last + 1][1] - first_header <= MAX_WINDOW_TOKENS:
            last += 1
        require(spans[last][1] - first_header <= MAX_WINDOW_TOKENS, "assistant span cannot fit in one window")
        groups.append((first, last))
        first = last + 1
    return groups


def make_row_plan(
    *,
    split: str,
    line_number: int,
    raw: bytes,
    row: dict[str, Any],
    rendered: Any,
    im_start_id: int,
    assistant_header_tokens: int,
    role_prefix_ids: dict[str, list[int]],
) -> dict[str, Any]:
    input_ids = list(rendered.input_ids)
    labels = list(rendered.labels)
    spans = [tuple(map(int, span)) for span in rendered.assistant_spans]
    task_id = row["task_id"]
    require(len(input_ids) == len(labels), f"{task_id}: render length mismatch")
    require(sum(value != -100 for value in labels[1:]) == rendered.shifted_supervised_tokens, f"{task_id}: label drift")

    message_starts = [index for index, token_id in enumerate(input_ids) if token_id == im_start_id]
    message_roles: dict[int, str] = {}
    for message_start in message_starts:
        matches = [
            role
            for role, prefix in role_prefix_ids.items()
            if input_ids[message_start + 1 : message_start + 1 + len(prefix)] == prefix
        ]
        require(len(matches) == 1, f"{task_id}: rendered role at {message_start} is ambiguous")
        message_roles[message_start] = matches[0]
    tool_boundaries = find_subsequence(input_ids, TOOL_RESPONSE_MARKER_IDS)
    source_tool_messages = sum(message.get("role") == "tool" for message in row["messages"])
    require(len(tool_boundaries) == source_tool_messages, f"{task_id}: tool-response marker count drift")
    semantic_boundaries = sorted(set(message_starts + tool_boundaries))
    assistant_headers = [start - assistant_header_tokens for start, _ in spans]
    require(all(header in message_starts for header in assistant_headers), f"{task_id}: assistant header boundary drift")

    windows: list[dict[str, Any]] = []
    if len(input_ids) <= MAX_WINDOW_TOKENS:
        groups = [(0, len(spans) - 1)]
        complete_sequence = True
    else:
        groups = build_span_groups(spans, assistant_header_tokens)
        complete_sequence = False

    covered_positions: set[int] = set()
    for part_index, (first_span, last_span) in enumerate(groups):
        assigned = list(range(first_span, last_span + 1))
        if complete_sequence:
            source_start = 0
            source_end = len(input_ids)
            start_policy = "intact"
            start_boundary_role = message_roles[0]
        else:
            source_end = spans[last_span][1]
            lower_bound = max(0, source_end - MAX_WINDOW_TOKENS)
            first_header = assistant_headers[first_span]
            if lower_bound == 0:
                source_start = 0
                start_policy = "full_prefix"
                start_boundary_role = message_roles[0]
            else:
                candidates = [
                    boundary
                    for boundary in semantic_boundaries
                    if lower_bound <= boundary < first_header
                ]
                require(bool(candidates), f"{task_id}#{part_index}: no semantic context boundary")
                source_start = candidates[0]
                if source_start in message_starts:
                    start_policy = "chat_message"
                    start_boundary_role = message_roles[source_start]
                else:
                    start_policy = "tool_response"
                    start_boundary_role = "tool"
        require(0 <= source_start < source_end <= len(input_ids), f"{task_id}#{part_index}: invalid slice")
        require(source_end - source_start <= MAX_WINDOW_TOKENS, f"{task_id}#{part_index}: window too long")

        local_labels = [-100] * (source_end - source_start)
        assigned_ranges: list[list[int]] = []
        assigned_positions: list[int] = []
        for span_index in assigned:
            span_start, span_end = spans[span_index]
            require(source_start <= span_start - 1, f"{task_id}#{part_index}: causal predecessor missing")
            require(span_end <= source_end, f"{task_id}#{part_index}: assigned span exceeds slice")
            for source_position in range(span_start, span_end):
                require(labels[source_position] != -100, f"{task_id}: nonsupervised token inside assistant span")
                local_labels[source_position - source_start] = labels[source_position]
                assigned_positions.append(source_position)
            assigned_ranges.append([span_start, span_end])
        require(local_labels[0] == -100, f"{task_id}#{part_index}: first local token supervised")
        shifted_tokens = sum(value != -100 for value in local_labels[1:])
        require(shifted_tokens == len(assigned_positions) > 0, f"{task_id}#{part_index}: shifted label drift")
        require(not covered_positions.intersection(assigned_positions), f"{task_id}: duplicated supervised position")
        covered_positions.update(assigned_positions)
        local_input_ids = input_ids[source_start:source_end]
        position_ids = list(range(source_start, source_end))
        windows.append(
            {
                "window_id": f"{task_id}#{part_index}",
                "part_index": part_index,
                "part_count": len(groups),
                "original_input_tokens": len(input_ids),
                "source_start": source_start,
                "source_end": source_end,
                "position_id_start": source_start,
                "position_id_end_exclusive": source_end,
                "position_ids_mode": "absolute_source_offsets",
                "start_policy": start_policy,
                "start_boundary_role": start_boundary_role,
                "assigned_assistant_span_indices": assigned,
                "assigned_source_label_spans": assigned_ranges,
                "input_tokens": len(local_input_ids),
                "shifted_supervised_tokens": shifted_tokens,
                "input_ids_sha256": sha256_i64(local_input_ids),
                "labels_sha256": sha256_i64(local_labels),
                "position_ids_sha256": sha256_i64(position_ids),
            }
        )

    original_positions = {index for index, value in enumerate(labels) if index > 0 and value != -100}
    require(covered_positions == original_positions, f"{task_id}: supervised coverage mismatch")
    promoted = bool(row["metadata"].get("promoted_from_needs_review", False))
    system_in_all_windows = all(window["source_start"] == 0 for window in windows)
    return {
        "line_number": line_number,
        "line_sha256": hashlib.sha256(raw).hexdigest(),
        "task_id": task_id,
        "promoted": promoted,
        "full_input_tokens": len(input_ids),
        "full_input_ids_sha256": sha256_i64(input_ids),
        "full_labels_sha256": sha256_i64(labels),
        "assistant_spans": [list(span) for span in spans],
        "assistant_turns": len(spans),
        "shifted_supervised_tokens": rendered.shifted_supervised_tokens,
        "source_tool_messages": source_tool_messages,
        "tool_response_boundaries": tool_boundaries,
        "message_starts": message_starts,
        "longer_than_window": len(input_ids) > MAX_WINDOW_TOKENS,
        "system_context_in_all_windows": system_in_all_windows,
        "windows": windows,
    }


def build_schedule(train_rows: list[dict[str, Any]]) -> dict[str, Any]:
    micro_windows: list[dict[str, Any]] = []
    for row in train_rows:
        for window in row["windows"]:
            micro_windows.append(
                {
                    "window_id": window["window_id"],
                    "task_id": row["task_id"],
                    "line_number": row["line_number"],
                    "line_sha256": row["line_sha256"],
                    "part_index": window["part_index"],
                    "promoted": row["promoted"],
                    "input_tokens": window["input_tokens"],
                    "shifted_supervised_tokens": window["shifted_supervised_tokens"],
                    "input_ids_sha256": window["input_ids_sha256"],
                    "labels_sha256": window["labels_sha256"],
                }
            )
    require(len(micro_windows) == EXPECTED_WINDOWS["train"], "train micro-window count drift")
    base_capacity = len(micro_windows) // OPTIMIZER_STEPS
    eight_count = len(micro_windows) - base_capacity * OPTIMIZER_STEPS
    seven_count = OPTIMIZER_STEPS - eight_count
    require((base_capacity, seven_count, eight_count) == (7, 4, 115), "optimizer capacities drift")
    construction_order = sorted(range(OPTIMIZER_STEPS), key=lambda index: stable_hash(SEED, "capacity", index))
    seven_bins = set(construction_order[:seven_count])
    tie_rank = {index: rank for rank, index in enumerate(construction_order)}
    bins = [
        {
            "construction_bin": index,
            "capacity": 7 if index in seven_bins else 8,
            "shifted_supervised_tokens": 0,
            "micro_windows": [],
        }
        for index in range(OPTIMIZER_STEPS)
    ]
    ordered = sorted(
        micro_windows,
        key=lambda item: (
            -item["shifted_supervised_tokens"],
            stable_hash(SEED, "micro-window-order", item["window_id"], item["line_sha256"]),
        ),
    )
    for item in ordered:
        candidates = [bucket for bucket in bins if len(bucket["micro_windows"]) < bucket["capacity"]]
        require(bool(candidates), "optimizer capacity exhausted")
        target = min(
            candidates,
            key=lambda bucket: (
                bucket["shifted_supervised_tokens"],
                len(bucket["micro_windows"]),
                tie_rank[bucket["construction_bin"]],
            ),
        )
        target["micro_windows"].append(item)
        target["shifted_supervised_tokens"] += item["shifted_supervised_tokens"]
    require(all(len(bucket["micro_windows"]) == bucket["capacity"] for bucket in bins), "unfilled optimizer bin")
    execution = sorted(bins, key=lambda bucket: stable_hash(SEED, "window-order", bucket["construction_bin"]))
    for optimizer_step, bucket in enumerate(execution, 1):
        bucket["optimizer_step"] = optimizer_step
        bucket["micro_windows"] = sorted(
            bucket["micro_windows"],
            key=lambda item: stable_hash(
                SEED,
                "within-window",
                bucket["construction_bin"],
                item["window_id"],
                item["line_sha256"],
            ),
        )
        bucket["input_tokens"] = sum(item["input_tokens"] for item in bucket["micro_windows"])
        bucket["curated_micro_windows"] = sum(not item["promoted"] for item in bucket["micro_windows"])
        bucket["promoted_micro_windows"] = sum(item["promoted"] for item in bucket["micro_windows"])
    totals = [bucket["shifted_supervised_tokens"] for bucket in execution]
    require(sum(totals) == EXPECTED_SHIFTED_TOKENS["train"], "schedule token total drift")
    return {
        "algorithm": SCHEDULE_ALGORITHM,
        "optimizer_steps": OPTIMIZER_STEPS,
        "seven_micro_window_steps": seven_count,
        "eight_micro_window_steps": eight_count,
        "token_weighting": "sum_cross_entropy_per_micro_window_divided_by_optimizer_step_supervised_tokens",
        "micro_window_loss_reduction": "sum",
        "optimizer_window_normalization": "optimizer_window_shifted_supervised_tokens",
        "optimizer_step_shifted_supervised_tokens": summarize(totals),
        "steps": execution,
    }


def main() -> None:
    args = parse_args()
    builder_path = Path(__file__).resolve()
    require(builder_path.is_file() and not Path(__file__).is_symlink(), "builder script invalid")
    require(stat.S_IMODE(builder_path.stat().st_mode) & 0o222 == 0, "builder script writable")
    builder_sha256 = sha256_file(builder_path)
    require(sha256_file(args.common_script) == EXPECTED_COMMON_SHA256, "common script hash drift")
    require(sha256_file(args.original_plan) == EXPECTED_ORIGINAL_PLAN_SHA256, "original plan hash drift")
    require(args.model.is_dir() and not args.model.is_symlink(), "model directory invalid")
    require(stat.S_IMODE(args.model.stat().st_mode) & 0o222 == 0, "model directory writable")
    model_hashes: dict[str, str] = {}
    for name, expected in EXPECTED_MODEL_FILES_SHA256.items():
        path = args.model / name
        require(path.is_file() and not path.is_symlink(), f"model metadata invalid: {name}")
        require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"model metadata writable: {name}")
        actual = sha256_file(path)
        require(actual == expected, f"model metadata hash drift: {name}")
        model_hashes[name] = actual

    sys.path.insert(0, str(args.common_script.parent))
    import qwen3_agentic_common as common
    import transformers
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False)
    require(len(tokenizer) == EXPECTED_TOKENIZER_LENGTH, "tokenizer length drift")
    require(tokenizer.chat_template == (args.model / "chat_template.jinja").read_text(), "active template drift")
    require(tokenizer.encode("<tool_response>\n", add_special_tokens=False) == TOOL_RESPONSE_MARKER_IDS, "tool marker token drift")
    im_start_id = tokenizer.convert_tokens_to_ids(common.IM_START)
    assistant_header = [im_start_id, *tokenizer.encode(common.ASSISTANT_ROLE_PREFIX, add_special_tokens=False)]
    require(assistant_header == [151_644, 77_091, 198], "assistant header drift")
    role_prefix_ids = {
        role: tokenizer.encode(f"{role}\n", add_special_tokens=False)
        for role in ("system", "user", "assistant")
    }

    split_plans: dict[str, Any] = {}
    split_task_ids: dict[str, set[str]] = {}
    for split in ("train", "validation", "test"):
        raw_lines, rows = read_rows(args.data / f"{split}.jsonl", split)
        split_task_ids[split] = {row["task_id"] for row in rows}
        row_plans: list[dict[str, Any]] = []
        for line_number, (raw, row) in enumerate(zip(raw_lines, rows, strict=True), 1):
            rendered = common.render_agentic_sample(tokenizer, row, max_sequence_length=MAX_RENDER_TOKENS)
            row_plans.append(
                make_row_plan(
                    split=split,
                    line_number=line_number,
                    raw=raw,
                    row=row,
                    rendered=rendered,
                    im_start_id=im_start_id,
                    assistant_header_tokens=len(assistant_header),
                    role_prefix_ids=role_prefix_ids,
                )
            )
        all_windows = [window for row_plan in row_plans for window in row_plan["windows"]]
        long_rows = [row_plan for row_plan in row_plans if row_plan["longer_than_window"]]
        shifted_total = sum(window["shifted_supervised_tokens"] for window in all_windows)
        require(shifted_total == EXPECTED_SHIFTED_TOKENS[split], f"{split}: shifted token total drift")
        require(len(long_rows) == EXPECTED_LONG_ROWS[split], f"{split}: long row count drift")
        require(len(all_windows) == EXPECTED_WINDOWS[split], f"{split}: window count drift")
        split_plans[split] = {
            "rows": len(row_plans),
            "windows": len(all_windows),
            "long_rows": len(long_rows),
            "curated_rows": sum(not row_plan["promoted"] for row_plan in row_plans),
            "promoted_rows": sum(row_plan["promoted"] for row_plan in row_plans),
            "full_input_tokens": summarize([row_plan["full_input_tokens"] for row_plan in row_plans]),
            "window_input_tokens": summarize([window["input_tokens"] for window in all_windows]),
            "shifted_supervised_tokens": summarize([window["shifted_supervised_tokens"] for window in all_windows]),
            "systemless_windows": sum(window["source_start"] > 0 for window in all_windows),
            "systemless_shifted_supervised_tokens": sum(
                window["shifted_supervised_tokens"]
                for window in all_windows
                if window["source_start"] > 0
            ),
            "start_policy_counts": {
                policy: sum(window["start_policy"] == policy for window in all_windows)
                for policy in ("intact", "full_prefix", "chat_message", "tool_response")
            },
            "row_plans": row_plans,
        }

    require(not split_task_ids["train"] & split_task_ids["validation"], "train/validation leakage")
    require(not split_task_ids["train"] & split_task_ids["test"], "train/test leakage")
    require(not split_task_ids["validation"] & split_task_ids["test"], "validation/test leakage")
    schedule = build_schedule(split_plans["train"]["row_plans"])
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
            "builder_script_path": str(builder_path),
            "builder_script_sha256": builder_sha256,
            "original_plan_path": str(args.original_plan),
            "original_plan_sha256": EXPECTED_ORIGINAL_PLAN_SHA256,
        },
        "model": {
            "path": str(args.model),
            "critical_file_sha256": model_hashes,
            "tokenizer_length": len(tokenizer),
            "transformers_version": transformers.__version__,
        },
        "execution_contract": {
            "max_window_tokens": MAX_WINDOW_TOKENS,
            "continuous_source_token_slices": True,
            "semantic_start_boundaries": ["chatml_im_start", "qwen3_tool_response_marker"],
            "tool_response_marker_token_ids": TOOL_RESPONSE_MARKER_IDS,
            "arbitrary_token_fallback": False,
            "assistant_spans_atomic": True,
            "assistant_labels_covered_exactly_once": True,
            "context_assistant_labels_masked": True,
            "causal_predecessor_required": True,
            "causal_shift": "logits[:-1] against labels[1:]",
            "position_ids": "absolute source offsets arange(source_start, source_end)",
            "digest_algorithm": DIGEST_ALGORITHM,
            "padding": False,
            "packing": False,
            "objective_equivalence": "not equivalent to full-context SFT for source rows longer than 8192 tokens",
        },
        "splits": split_plans,
        "schedule": schedule,
    }
    payload = (json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    atomic_create(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "split_summary": {
                    split: {
                        key: split_plans[split][key]
                        for key in (
                            "rows",
                            "windows",
                            "long_rows",
                            "systemless_windows",
                            "systemless_shifted_supervised_tokens",
                            "start_policy_counts",
                        )
                    }
                    for split in ("train", "validation", "test")
                },
                "schedule_tokens": schedule["optimizer_step_shifted_supervised_tokens"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
