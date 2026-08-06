#!/usr/bin/env python3
"""Strict structural and causal validator for rdk_sft_sample.v1 JSONL."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


AGENT_SYSTEM = "你是 RDK Agent。需要外部信息时先调用工具，再依据工具结果回答。"
QA_SYSTEM = "你是 RDK 技术问答助手。"
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)(api[_-]?key|password|passwd)\s*[=:]\s*[^\s,]{4,}"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="JSONL files to validate")
    parser.add_argument("--schema", default="schemas/rdk_sft_sample.v1.schema.json")
    parser.add_argument("--audit", help="Optional audit JSON output path")
    return parser.parse_args()


def normalized_answer(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def semantic_errors(sample: dict) -> list[str]:
    errors: list[str] = []
    messages = sample.get("messages", [])
    profile = sample.get("profile")
    expected_system = AGENT_SYSTEM if profile == "agentic" else QA_SYSTEM
    if not messages or messages[0] != {"role": "system", "content": expected_system}:
        errors.append("first system message does not match the canonical prompt")
    if len(messages) < 2 or messages[1].get("role") != "user" or not messages[1].get("content", "").strip():
        errors.append("second message must be a non-empty user message")
    if not messages or messages[-1].get("role") != "assistant":
        errors.append("last message must be assistant")
        return errors
    final_answer = messages[-1].get("content", "")
    if not final_answer.strip():
        errors.append("final assistant answer is empty")
    if normalized_answer(final_answer) != normalized_answer(sample.get("outcome", {}).get("final_answer", "")):
        errors.append("outcome.final_answer differs from the final assistant message")

    serialized = json.dumps(sample, ensure_ascii=False)
    for pattern in SECRET_PATTERNS:
        if pattern.search(serialized):
            errors.append(f"possible secret matched: {pattern.pattern}")

    if profile == "qa":
        if [message.get("role") for message in messages] != ["system", "user", "assistant"]:
            errors.append("qa message order must be exactly system,user,assistant")
        for message in messages:
            forbidden = {"tool_calls", "tool_call_id", "name"}.intersection(message)
            if forbidden:
                errors.append(f"qa message contains tool fields: {sorted(forbidden)}")
        if sample.get("tools") != []:
            errors.append("qa tools must be []")
        return errors

    tool_definitions = {
        tool["function"]["name"]: tool["function"] for tool in sample.get("tools", [])
    }
    if len(tool_definitions) != len(sample.get("tools", [])):
        errors.append("duplicate tool definition name")
    call_ids: dict[str, str] = {}
    call_arguments: dict[str, dict] = {}
    results: Counter[str] = Counter()
    pending: set[str] = set()
    tool_call_count = 0
    for index, message in enumerate(messages[2:-1], start=2):
        role = message.get("role")
        if role == "assistant":
            if pending:
                errors.append(
                    f"assistant at index {index} starts before tool results complete: {sorted(pending)}"
                )
            calls = message.get("tool_calls", [])
            if not calls:
                errors.append(f"intermediate assistant at index {index} has no tool_calls")
                continue
            if message.get("content") != "":
                errors.append(f"assistant tool-call message at index {index} must have empty content")
            tool_call_count += len(calls)
            for call in calls:
                call_id = call["id"]
                name = call["function"]["name"]
                if call_id in call_ids:
                    errors.append(f"duplicate tool call id: {call_id}")
                call_ids[call_id] = name
                call_arguments[call_id] = call["function"]["arguments"]
                pending.add(call_id)
                if name not in tool_definitions:
                    errors.append(f"tool call references undeclared tool: {name}")
                else:
                    argument_validator = Draft202012Validator(tool_definitions[name]["parameters"])
                    for error in argument_validator.iter_errors(call["function"]["arguments"]):
                        errors.append(f"invalid arguments for {call_id}: {error.message}")
        elif role == "tool":
            call_id = message.get("tool_call_id")
            name = message.get("name")
            if call_id not in call_ids:
                errors.append(f"orphan tool result: {call_id}")
            elif call_ids[call_id] != name:
                errors.append(f"tool name mismatch for {call_id}: {name} != {call_ids[call_id]}")
            elif call_id not in pending:
                errors.append(f"duplicate or out-of-order tool result: {call_id}")
            else:
                pending.remove(call_id)
            results[call_id] += 1
            try:
                tool_payload = json.loads(message.get("content", ""))
            except json.JSONDecodeError:
                errors.append(f"tool result {call_id} content is not JSON")
                tool_payload = None
            if name == "knowledge_search" and isinstance(tool_payload, dict):
                arguments = call_arguments.get(call_id, {})
                if tool_payload.get("query") != arguments.get("query"):
                    errors.append(f"knowledge_search query mismatch for {call_id}")
                if tool_payload.get("knowledge_base") != arguments.get("knowledgeBase"):
                    errors.append(f"knowledge_search knowledge base mismatch for {call_id}")
                result_rows = tool_payload.get("results")
                if tool_payload.get("status") == "found" and not result_rows:
                    errors.append(f"knowledge_search found result is empty for {call_id}")
                if tool_payload.get("status") == "not_found" and result_rows:
                    errors.append(f"knowledge_search not_found result is non-empty for {call_id}")
        else:
            errors.append(f"unexpected intermediate role at index {index}: {role}")
    if tool_call_count == 0:
        errors.append("agentic sample has no structured tool call")
    for call_id in call_ids:
        if results[call_id] != 1:
            errors.append(f"tool call {call_id} has {results[call_id]} results, expected 1")
    if pending:
        errors.append(f"unresolved tool calls at end of trajectory: {sorted(pending)}")
    if "tool_calls" in messages[-1]:
        errors.append("final assistant message must not contain tool_calls")
    return errors


def main() -> int:
    args = parse_args()
    schema_path = Path(args.schema)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    all_errors: list[dict] = []
    task_ids: set[str] = set()
    semantic_group_splits: dict[str, set[str]] = {}
    counts: Counter[str] = Counter()

    for raw_path in args.paths:
        path = Path(raw_path)
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError as error:
                    all_errors.append({"path": str(path), "line": line_number, "error": str(error)})
                    continue
                sample_errors = [error.message for error in validator.iter_errors(sample)]
                sample_errors.extend(semantic_errors(sample))
                task_id = sample.get("task_id")
                if task_id in task_ids:
                    sample_errors.append(f"duplicate task_id across inputs: {task_id}")
                task_ids.add(task_id)
                group = sample.get("metadata", {}).get("semantic_group_id")
                if group:
                    semantic_group_splits.setdefault(group, set()).add(sample.get("split"))
                counts[f"profile:{sample.get('profile')}"] += 1
                counts[f"split:{sample.get('split')}"] += 1
                counts["rows"] += 1
                for error in sample_errors:
                    all_errors.append(
                        {"path": str(path), "line": line_number, "task_id": task_id, "error": error}
                    )

    for group, splits in sorted(semantic_group_splits.items()):
        if len(splits) > 1:
            all_errors.append(
                {
                    "semantic_group_id": group,
                    "error": f"semantic group crosses splits: {sorted(splits)}",
                }
            )

    audit = {
        "schema_version": "rdk_sft_validation_audit.v1",
        "valid": not all_errors,
        "counts": dict(sorted(counts.items())),
        "unique_task_ids": len(task_ids),
        "semantic_groups": len(semantic_group_splits),
        "error_count": len(all_errors),
        "errors": all_errors,
    }
    if args.audit:
        audit_path = Path(args.audit)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if not all_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
