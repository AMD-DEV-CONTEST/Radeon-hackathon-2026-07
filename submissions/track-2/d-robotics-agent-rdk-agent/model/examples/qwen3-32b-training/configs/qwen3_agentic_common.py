#!/usr/bin/env python3
"""Shared, fail-closed rendering utilities for Qwen3 agentic SFT."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


IM_START = "<|im_start|>"
IM_END = "<|im_end|>"
ASSISTANT_ROLE_PREFIX = "assistant\n"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def token_ids(value: Any) -> list[int]:
    if hasattr(value, "input_ids"):
        value = value.input_ids
    elif isinstance(value, dict):
        value = value["input_ids"]
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value and isinstance(value[0], list):
        require(len(value) == 1, "unexpected batched tokenizer result")
        value = value[0]
    require(isinstance(value, list), f"unexpected tokenizer result: {type(value)!r}")
    return [int(token_id) for token_id in value]


@dataclass(frozen=True)
class RenderedSample:
    text: str
    input_ids: list[int]
    labels: list[int]
    assistant_spans: tuple[tuple[int, int], ...]
    shifted_supervised_tokens: int


def _source_blob(row: dict[str, Any]) -> str:
    return json.dumps(
        {"messages": row["messages"], "tools": row["tools"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _find_message_end(input_ids: list[int], start: int, im_start_id: int, im_end_id: int) -> int:
    for index in range(start, len(input_ids)):
        token_id = input_ids[index]
        require(token_id != im_start_id, "nested message-start token in rendered conversation")
        if token_id == im_end_id:
            return index
    raise RuntimeError("message-start token has no matching message-end token")


def render_agentic_sample(
    tokenizer: Any,
    row: dict[str, Any],
    *,
    max_sequence_length: int,
) -> RenderedSample:
    """Render one row with the untouched official template and mask assistant bodies.

    The role header itself is excluded. The assistant body, tool-call payload and
    closing ``<|im_end|>`` token are supervised. A causal trainer must use
    ``logits[..., :-1, :]`` against ``labels[..., 1:]``.
    """

    task_id = row.get("task_id", "<unknown>")
    messages = row.get("messages")
    tools = row.get("tools")
    require(isinstance(messages, list) and messages, f"{task_id}: messages missing")
    require(isinstance(tools, list) and tools, f"{task_id}: tools missing")
    source_blob = _source_blob(row)
    require(IM_START not in source_blob, f"{task_id}: reserved {IM_START} occurs in source")
    require(IM_END not in source_blob, f"{task_id}: reserved {IM_END} occurs in source")

    render_kwargs = {
        "tools": tools,
        "add_generation_prompt": False,
        "continue_final_message": False,
        "enable_thinking": True,
    }
    text = tokenizer.apply_chat_template(messages, tokenize=False, **render_kwargs)
    require(isinstance(text, str) and text, f"{task_id}: empty template render")
    templated_ids = token_ids(
        tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            padding=False,
            truncation=False,
            **render_kwargs,
        )
    )
    direct_ids = token_ids(tokenizer(text, add_special_tokens=False, padding=False, truncation=False))
    require(templated_ids == direct_ids, f"{task_id}: template tokenization mismatch")
    require(len(templated_ids) <= max_sequence_length, f"{task_id}: sequence exceeds contract")

    im_start_id = tokenizer.convert_tokens_to_ids(IM_START)
    im_end_id = tokenizer.convert_tokens_to_ids(IM_END)
    require(isinstance(im_start_id, int) and im_start_id >= 0, "invalid im_start token id")
    require(isinstance(im_end_id, int) and im_end_id >= 0, "invalid im_end token id")
    require(
        token_ids(tokenizer.encode(IM_START, add_special_tokens=False)) == [im_start_id],
        "im_start is not a singleton special token",
    )
    require(
        token_ids(tokenizer.encode(IM_END, add_special_tokens=False)) == [im_end_id],
        "im_end is not a singleton special token",
    )
    assistant_role_ids = token_ids(tokenizer.encode(ASSISTANT_ROLE_PREFIX, add_special_tokens=False))
    assistant_header = [im_start_id, *assistant_role_ids]
    require(assistant_role_ids, "empty assistant role encoding")

    labels = [-100] * len(templated_ids)
    spans: list[tuple[int, int]] = []
    message_count = 0
    cursor = 0
    while cursor < len(templated_ids):
        if templated_ids[cursor] != im_start_id:
            cursor += 1
            continue
        message_count += 1
        end_index = _find_message_end(templated_ids, cursor + 1, im_start_id, im_end_id)
        if templated_ids[cursor : cursor + len(assistant_header)] == assistant_header:
            body_start = cursor + len(assistant_header)
            body_end = end_index + 1
            require(body_start < body_end, f"{task_id}: empty assistant span")
            labels[body_start:body_end] = templated_ids[body_start:body_end]
            spans.append((body_start, body_end))
        cursor = end_index + 1

    expected_assistant = sum(message.get("role") == "assistant" for message in messages)
    require(expected_assistant > 0, f"{task_id}: no assistant message")
    require(len(spans) == expected_assistant, f"{task_id}: assistant span count mismatch")
    require(message_count >= expected_assistant, f"{task_id}: rendered message count mismatch")
    shifted_supervised = sum(label != -100 for label in labels[1:])
    require(shifted_supervised > 0, f"{task_id}: no shifted supervised token")
    require(labels[0] == -100, f"{task_id}: first token unexpectedly supervised")

    return RenderedSample(
        text=text,
        input_ids=templated_ids,
        labels=labels,
        assistant_spans=tuple(spans),
        shifted_supervised_tokens=shifted_supervised,
    )
