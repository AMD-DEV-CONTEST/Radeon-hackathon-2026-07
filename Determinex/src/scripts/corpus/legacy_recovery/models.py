from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

LegacyBucket = Literal[
    "unrecoverable",
    "recoverable_metadata",
    "reconstructable_verifier_row",
    "high_value_failure_cluster",
]


FAILURE_PATTERNS: dict[str, tuple[str, ...]] = {
    "date_time_nondeterminism": (
        "timestamp",
        "timezone",
        "source_date_epoch",
        "creation_timestamp",
        "date/time",
    ),
    "path_env_dependency": ("/workspace", "path", "cwd", "env", "home", "tmp"),
    "stdout_stderr_mismatch": ("stdout", "stderr", "output", "expected", "actual"),
    "exit_code_mismatch": (
        "returncode",
        "exit code",
        "assert 0",
        "assert 1",
        "assert 2",
        "assert 127",
    ),
    "argv0_alias_regression": ("argv[0]", "argv0", "/workspace/executable", "usage:"),
    "missing_asset": ("no such file", "missing", "asset", "fixture", "not found"),
    "locale_encoding_issue": ("utf-8", "unicode", "encoding", "locale", "decode"),
    "progress_output_noise": ("progress", "%", "eta", "elapsed"),
    "wrapper_churn_risk": ("wrapper", "shellout", "subprocess", "launcher"),
    "native_required": ("segfault", "signal", "overflow", "mmap", "byte", "binary"),
}


@dataclass(slots=True)
class LegacyScanItem:
    legacy_row_hash: str
    path: str
    line_number: int
    bucket: LegacyBucket
    parse_error: str = ""
    tool: str = ""
    language_guess: str = "unknown"
    benchmark: str = "programbench"
    verdict: str = "unknown"
    test_id: str = ""
    eval_json: str = ""
    gate_result_path: str = ""
    failure_classes: list[str] = field(default_factory=list)
    replayable: bool = False
    training_eligible: bool = False
    promotion_reason: str = "legacy_rows_are_never_promoted_in_place"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stable_hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def stable_hash_obj(obj: Any) -> str:
    return stable_hash_text(
        json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    )


def compact_text(record: dict[str, Any], limit: int = 12000) -> str:
    parts: list[str] = []
    for key in ("meta", "metadata", "payload", "failure_output", "stderr", "stdout", "test_id"):
        value = record.get(key)
        if value:
            parts.append(
                json.dumps(value, ensure_ascii=True) if not isinstance(value, str) else value
            )
    for msg in record.get("messages") or []:
        if isinstance(msg, dict):
            parts.append(str(msg.get("content") or ""))
    for msg in record.get("conversations") or []:
        if isinstance(msg, dict):
            parts.append(str(msg.get("value") or ""))
    return "\n".join(parts)[:limit]


def compact_failure_evidence(record: dict[str, Any], limit: int = 12000) -> str:
    """Text used for failure taxonomy.

    This intentionally avoids assistant/generated implementation bodies because
    generic wrappers contain words like stdout, date, executable, and subprocess
    that would make every row look like every failure class.
    """
    parts: list[str] = []
    for key in ("failure_output", "stderr", "stdout", "test_id"):
        value = record.get(key)
        if value:
            parts.append(
                json.dumps(value, ensure_ascii=True) if not isinstance(value, str) else value
            )
    for container_key in ("meta", "metadata"):
        meta = record.get(container_key)
        if isinstance(meta, dict):
            bounded = {
                key: meta.get(key)
                for key in ("slug", "tool", "module", "test_id", "test_name", "verdict")
                if meta.get(key) is not None
            }
            if bounded:
                parts.append(json.dumps(bounded, ensure_ascii=True))
    for msg in record.get("messages") or []:
        if isinstance(msg, dict) and str(msg.get("role") or "").lower() in {"user", "human"}:
            parts.append(str(msg.get("content") or ""))
    for msg in record.get("conversations") or []:
        if isinstance(msg, dict) and str(msg.get("from") or "").lower() in {"human", "user"}:
            parts.append(str(msg.get("value") or ""))
    return "\n".join(parts)[:limit]


def extract_tool(record: dict[str, Any], text: str) -> str:
    for container_key in ("metadata", "meta"):
        meta = record.get(container_key)
        if isinstance(meta, dict):
            for key in ("slug", "tool", "instance_id", "task_id"):
                value = str(meta.get(key) or "")
                if "__" in value:
                    return value
    for key in ("slug", "tool", "instance_id", "task_id"):
        value = str(record.get(key) or "")
        if "__" in value:
            return value
    match = re.search(
        r"(?:# Tool:|tool\s*[=:])\s*([A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)", text
    )
    return match.group(1) if match else ""


def extract_metadata(record: dict[str, Any], key: str) -> str:
    for container_key in ("metadata", "meta", "payload"):
        meta = record.get(container_key)
        if isinstance(meta, dict) and meta.get(key) is not None:
            return str(meta.get(key) or "")
    return str(record.get(key) or "")


def infer_language(record: dict[str, Any], text: str) -> str:
    explicit = extract_metadata(record, "language") or extract_metadata(record, "lang")
    if explicit:
        return explicit.lower()
    lower = text.lower()
    if "cargo.toml" in lower or "rustc" in lower or "cargo test" in lower:
        return "rust"
    if "go.mod" in lower or "go test" in lower or "package main" in lower:
        return "go"
    if "tsc" in lower or "typescript" in lower or "package.json" in lower:
        return "typescript"
    if "javac" in lower or "mvn test" in lower or "junit" in lower:
        return "java"
    if "gcc" in lower or "clang" in lower or "makefile" in lower:
        return "c"
    if "g++" in lower or "cmake" in lower:
        return "cpp"
    if "python" in lower or "pytest" in lower or "main.py" in lower:
        return "python"
    return "unknown"


def classify_failure_text(text: str) -> list[str]:
    lower = text.lower()
    labels = [
        label
        for label, needles in FAILURE_PATTERNS.items()
        if any(needle in lower for needle in needles)
    ]
    return labels or ["uncategorized"]


def is_replayable(record: dict[str, Any]) -> bool:
    eval_json = extract_metadata(record, "eval_json")
    gate_result = extract_metadata(record, "gate_result_path")
    test_id = extract_metadata(record, "test_id") or extract_metadata(record, "test_name")
    verdict = extract_metadata(record, "verdict")
    return bool((eval_json or gate_result) and test_id and verdict)


def choose_bucket(record: dict[str, Any], text: str, parse_error: str = "") -> LegacyBucket:
    if parse_error:
        return "unrecoverable"
    labels = classify_failure_text(text)
    if is_replayable(record):
        return "reconstructable_verifier_row"
    if len(labels) >= 2 and labels != ["uncategorized"]:
        return "high_value_failure_cluster"
    tool = extract_tool(record, text)
    if tool:
        return "recoverable_metadata"
    return "unrecoverable"


def iter_jsonl_paths(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".jsonl":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.jsonl")))
    return files
