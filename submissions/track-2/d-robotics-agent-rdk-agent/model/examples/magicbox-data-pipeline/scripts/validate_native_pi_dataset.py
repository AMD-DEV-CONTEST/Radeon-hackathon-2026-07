#!/usr/bin/env python3
"""Independent fail-closed validator for native pi-coding-agent SFT JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ALLOWED_TOOLS = {"read", "grep", "find", "ls", "bash"}
HEX64 = re.compile(r"^[a-f0-9]{64}$")
SECRET_PATTERNS = [
    ("private_key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)),
    ("openai_style_key", re.compile(rb"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b")),
    ("bearer_token", re.compile(rb"\bBearer\s+[A-Za-z0-9._~+/\-]{12,}={0,2}\b", re.IGNORECASE)),
    (
        "credential_assignment",
        re.compile(
            rb"[\"']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)"
            rb"[\"']?\s*[:=]\s*[\"']?[^\s\"',}\]]{4,}",
            re.IGNORECASE,
        ),
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datasets", nargs="+", help="Native Pi JSONL (or single-sample JSON) files")
    parser.add_argument("--schema", default="schemas/rdk_sft_sample.v1.schema.json")
    parser.add_argument(
        "--scan-root",
        action="append",
        default=[],
        help="Recursively secret-scan every regular file below this root; repeatable",
    )
    parser.add_argument("--audit", help="Optional JSON path for the validation audit")
    return parser.parse_args()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def regular_files(path: Path) -> tuple[list[Path], list[str]]:
    errors: list[str] = []
    if path.is_symlink():
        return [], [f"secret scan target is a symlink: {path}"]
    try:
        mode = path.stat().st_mode
    except OSError as error:
        return [], [f"cannot stat secret scan target {path}: {error}"]
    if stat.S_ISREG(mode):
        return [path], []
    if not stat.S_ISDIR(mode):
        return [], [f"secret scan target is neither a regular file nor directory: {path}"]

    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(path, followlinks=False):
        base = Path(directory)
        kept_dirs: list[str] = []
        for name in dirnames:
            child = base / name
            if child.is_symlink():
                errors.append(f"symlink directory cannot be secret-scanned: {child}")
            else:
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in filenames:
            child = base / name
            if child.is_symlink():
                errors.append(f"symlink file cannot be secret-scanned: {child}")
                continue
            try:
                child_mode = child.stat().st_mode
            except OSError as error:
                errors.append(f"cannot stat secret scan file {child}: {error}")
                continue
            if not stat.S_ISREG(child_mode):
                errors.append(f"non-regular file cannot be secret-scanned: {child}")
                continue
            files.append(child)
    return files, errors


def scan_file_for_secrets(path: Path) -> tuple[int, list[str]]:
    findings: list[str] = []
    byte_count = 0
    tail = b""
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                byte_count += len(chunk)
                window = tail + chunk
                for name, pattern in SECRET_PATTERNS:
                    if pattern.search(window) and name not in findings:
                        findings.append(name)
                tail = window[-4096:]
    except OSError as error:
        return byte_count, [f"read_error:{error}"]
    return byte_count, findings


def secret_scan(paths: Iterable[Path]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    unique_files: dict[str, Path] = {}
    errors: list[dict[str, Any]] = []
    for target in paths:
        files, target_errors = regular_files(target)
        for message in target_errors:
            errors.append({"path": str(target), "error": message})
        for path in files:
            unique_files[str(path.absolute())] = path

    total_bytes = 0
    for absolute in sorted(unique_files):
        path = unique_files[absolute]
        byte_count, findings = scan_file_for_secrets(path)
        total_bytes += byte_count
        for finding in findings:
            if finding.startswith("read_error:"):
                errors.append({"path": str(path), "error": finding})
            else:
                errors.append({"path": str(path), "error": f"possible secret matched: {finding}"})
    return {"files": len(unique_files), "bytes": total_bytes}, errors


def metadata_errors(sample: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = sample.get("metadata", {})
    messages = sample.get("messages", [])
    tools = sample.get("tools", [])
    if metadata.get("behavior_origin") != "pi-coding-agent-native":
        errors.append("metadata.behavior_origin is not pi-coding-agent-native")
    if metadata.get("trace_contract_version") != "pi_native_export.v1":
        errors.append("metadata.trace_contract_version is not pi_native_export.v1")
    if metadata.get("provider_api") != "openai-completions":
        errors.append("metadata.provider_api is not openai-completions")

    hash_fields = [
        "provider_system_sha256",
        "provider_tools_sha256",
        "canonical_system_sha256",
        "canonical_tools_sha256",
        "pi_messages_sha256",
        "pi_events_sha256",
        "policy_audit_sha256",
        "board_evidence_sha256",
    ]
    for field in hash_fields:
        if not isinstance(metadata.get(field), str) or not HEX64.fullmatch(metadata[field]):
            errors.append(f"metadata.{field} is not a lowercase SHA-256")

    if messages and isinstance(messages[0].get("content"), str):
        if metadata.get("canonical_system_sha256") != sha256_text(messages[0]["content"]):
            errors.append("canonical system hash does not match messages[0].content")
    if metadata.get("canonical_tools_sha256") != sha256_canonical(tools):
        errors.append("canonical tools hash does not match tools")

    active_names = [tool.get("function", {}).get("name") for tool in tools]
    if metadata.get("active_tool_names") != active_names:
        errors.append("metadata.active_tool_names does not match exported tool order")
    provider_rounds = metadata.get("provider_round_count")
    provider_attempts = metadata.get("provider_request_attempt_count")
    provider_retries = metadata.get("provider_retry_attempt_count")
    request_hashes = metadata.get("provider_request_sha256")
    if not isinstance(provider_rounds, int) or provider_rounds < 1:
        errors.append("metadata.provider_round_count must be a positive integer")
    if not isinstance(provider_attempts, int) or provider_attempts < 1:
        errors.append("metadata.provider_request_attempt_count must be a positive integer")
    if not isinstance(provider_retries, int) or provider_retries < 0:
        errors.append("metadata.provider_retry_attempt_count must be a non-negative integer")
    if (
        isinstance(provider_rounds, int)
        and isinstance(provider_attempts, int)
        and provider_attempts < provider_rounds
    ):
        errors.append("provider request attempts cannot be fewer than causal rounds")
    if (
        isinstance(provider_rounds, int)
        and isinstance(provider_attempts, int)
        and isinstance(provider_retries, int)
        and provider_attempts - provider_rounds != provider_retries
    ):
        errors.append("provider retry count differs from attempts minus causal rounds")
    if not isinstance(request_hashes, list) or not all(
        isinstance(value, str) and HEX64.fullmatch(value) for value in request_hashes
    ):
        errors.append("metadata.provider_request_sha256 must be a SHA-256 list")
    elif provider_attempts != len(request_hashes):
        errors.append("provider request hash count differs from provider_request_attempt_count")
    return errors


def semantic_errors(sample: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if sample.get("profile") != "agentic":
        return ["native Pi dataset only accepts agentic samples"]
    messages = sample.get("messages", [])
    tools = sample.get("tools", [])
    if not messages or messages[0].get("role") != "system" or not messages[0].get("content", "").strip():
        errors.append("first message must be the non-empty effective provider system prompt")
    if len(messages) < 2 or messages[1].get("role") != "user" or not messages[1].get("content", "").strip():
        errors.append("second message must be the single non-empty user instruction")
    if sum(message.get("role") == "system" for message in messages) != 1:
        errors.append("trajectory must contain exactly one system message")
    if sum(message.get("role") == "user" for message in messages) != 1:
        errors.append("trajectory must contain exactly one user message")
    if not messages or messages[-1].get("role") != "assistant":
        errors.append("last message must be assistant")
        return errors + metadata_errors(sample)
    final_answer = messages[-1].get("content", "")
    if not isinstance(final_answer, str) or not final_answer.strip():
        errors.append("final assistant answer is empty")
    if normalized_text(final_answer) != normalized_text(sample.get("outcome", {}).get("final_answer", "")):
        errors.append("outcome.final_answer differs from final assistant content")
    if "tool_calls" in messages[-1]:
        errors.append("final assistant message contains tool_calls")

    definitions: dict[str, dict[str, Any]] = {}
    for tool in tools:
        fn = tool.get("function", {})
        name = fn.get("name")
        if name not in ALLOWED_TOOLS:
            errors.append(f"non-native tool definition: {name}")
        if name in definitions:
            errors.append(f"duplicate tool definition: {name}")
        else:
            definitions[name] = fn
    if not definitions:
        errors.append("native trajectory has no tool definitions")

    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    pending: set[str] = set()
    results: Counter[str] = Counter()
    call_count = 0
    bash_count = 0
    assistant_count = 0
    for index, message in enumerate(messages[2:], start=2):
        role = message.get("role")
        if role == "assistant":
            assistant_count += 1
            if index == len(messages) - 1:
                continue
            if pending:
                errors.append(f"assistant at index {index} starts before results complete: {sorted(pending)}")
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list) or not tool_calls:
                errors.append(f"intermediate assistant at index {index} has no tool calls")
                continue
            if not isinstance(message.get("content"), str):
                errors.append(f"assistant content at index {index} is not text")
            for call in tool_calls:
                call_id = call.get("id")
                function = call.get("function", {})
                name = function.get("name")
                arguments = function.get("arguments")
                call_count += 1
                bash_count += int(name == "bash")
                if not isinstance(call_id, str) or not call_id:
                    errors.append(f"tool call at index {index} has an empty id")
                    continue
                if call_id in calls:
                    errors.append(f"duplicate tool call id: {call_id}")
                if name not in ALLOWED_TOOLS:
                    errors.append(f"non-native tool call: {name}")
                if name not in definitions:
                    errors.append(f"tool call references undeclared tool: {name}")
                if not isinstance(arguments, dict):
                    errors.append(f"tool call arguments are not an object: {call_id}")
                    arguments = {}
                calls[call_id] = (name, arguments)
                pending.add(call_id)
                if name in definitions and isinstance(arguments, dict):
                    validator = Draft202012Validator(definitions[name]["parameters"])
                    for error in validator.iter_errors(arguments):
                        errors.append(f"invalid arguments for {call_id}: {error.message}")
        elif role == "tool":
            call_id = message.get("tool_call_id")
            name = message.get("name")
            if call_id not in calls:
                errors.append(f"orphan tool result: {call_id}")
            elif calls[call_id][0] != name:
                errors.append(f"tool name mismatch for {call_id}")
            elif call_id not in pending:
                errors.append(f"duplicate or out-of-order tool result: {call_id}")
            else:
                pending.remove(call_id)
            if not isinstance(message.get("content"), str):
                errors.append(f"tool result content is not original text: {call_id}")
            results[call_id] += 1
        else:
            errors.append(f"unexpected role at index {index}: {role}")

    if call_count == 0:
        errors.append("native agentic sample has no structured tool call")
    if pending:
        errors.append(f"unresolved tool calls: {sorted(pending)}")
    for call_id in calls:
        if results[call_id] != 1:
            errors.append(f"tool call {call_id} has {results[call_id]} results, expected 1")
    metadata = sample.get("metadata", {})
    if metadata.get("tool_call_count") != call_count:
        errors.append("metadata.tool_call_count differs from transcript")
    if metadata.get("bash_call_count") != bash_count:
        errors.append("metadata.bash_call_count differs from transcript")
    if metadata.get("provider_round_count") != assistant_count:
        errors.append("metadata.provider_round_count differs from assistant turn count")
    errors.extend(metadata_errors(sample))
    return errors


def read_samples(path: Path) -> Iterable[tuple[int, Any]]:
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, list):
            for index, sample in enumerate(value, start=1):
                yield index, sample
        else:
            yield 1, value
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                yield line_number, json.loads(line)


def main() -> int:
    args = parse_args()
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    schema_validator = Draft202012Validator(schema)
    dataset_paths = [Path(value) for value in args.datasets]
    scan_targets = [*dataset_paths, *(Path(value) for value in args.scan_root)]
    scan_counts, scan_errors = secret_scan(scan_targets)

    errors: list[dict[str, Any]] = list(scan_errors)
    counts: Counter[str] = Counter()
    task_ids: set[str] = set()
    semantic_group_splits: dict[str, set[str]] = {}
    for path in dataset_paths:
        try:
            rows = read_samples(path)
            for line_number, sample in rows:
                counts["rows"] += 1
                if not isinstance(sample, dict):
                    errors.append({"path": str(path), "line": line_number, "error": "sample is not an object"})
                    continue
                task_id = sample.get("task_id")
                sample_errors = [error.message for error in schema_validator.iter_errors(sample)]
                sample_errors.extend(semantic_errors(sample))
                if task_id in task_ids:
                    sample_errors.append(f"duplicate task_id across inputs: {task_id}")
                task_ids.add(task_id)
                group = sample.get("metadata", {}).get("semantic_group_id")
                if group:
                    semantic_group_splits.setdefault(group, set()).add(sample.get("split"))
                counts[f"split:{sample.get('split')}"] += 1
                for message in sample_errors:
                    errors.append(
                        {"path": str(path), "line": line_number, "task_id": task_id, "error": message}
                    )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors.append({"path": str(path), "error": f"cannot parse dataset: {error}"})

    for group, splits in sorted(semantic_group_splits.items()):
        if len(splits) > 1:
            errors.append(
                {"semantic_group_id": group, "error": f"semantic group crosses splits: {sorted(splits)}"}
            )

    audit = {
        "schema_version": "pi_native_dataset_validation.v1",
        "valid": not errors,
        "counts": dict(sorted(counts.items())),
        "unique_task_ids": len(task_ids),
        "semantic_groups": len(semantic_group_splits),
        "secret_scan": scan_counts,
        "error_count": len(errors),
        "errors": errors,
    }
    if args.audit:
        audit_path = Path(args.audit)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
