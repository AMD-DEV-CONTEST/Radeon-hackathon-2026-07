#!/usr/bin/env python3
"""Validate two A/B arms and emit one auditable JSON summary."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval_ab import (
    MANIFEST_SCHEMA,
    RECORD_SCHEMA,
    atomic_write_json,
    canonical_digest,
    sha256_file,
)


SUMMARY_SCHEMA = "rdk_model_ab_summary.v2"
RECOVERY_SEAL_SCHEMA = "rdk_model_ab_interrupted_recovery_seal.v1"
FROZEN_EVALUATOR_SHA256 = (
    "645f29a31afa510c313f8e979507babf5037446d33da6b67d486c452024f5012"
)
FROZEN_SEALER_SHA256 = (
    "bf1abe356b1f1acdddca88738e3506709b9eae0cd4cc0d4f69ed905fa769a29d"
)
FROZEN_TEST_SHA256 = "d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283"
FROZEN_TEST_BYTES = 3_562_357
FROZEN_TASKS = 113
FROZEN_RECORDS = 413
CAPPED_RECORDS = 170
CAPPED_TASKS = 49
CAPPED_MAX_CAPTURED_RECORDS = 171
BASE_CONFIG_SHA256 = "918fe2d123e79abf8ed4688278cc7d9c6c54d25fbea35e5f0870985f4d663000"
BASE_INDEX_SHA256 = "2771f7e67bacc73ceb4ee0dfe6027d49fc9a4390d17eda517a4f7f48923d6a61"
ADAPTER_SHA256 = "4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf"
ARM_IDENTITIES: dict[str, dict[str, Any]] = {
    "base": {
        "request_model": "Qwen3-32B-Base-bnb-4bit",
        "response_model": "Qwen3-32B-Base-bnb-4bit",
        "system_fingerprint": "base-338aed015d36",
        "health": {
            "status": "ok",
            "model": "Qwen3-32B-Base-bnb-4bit",
            "revision": "Qwen3-32B-bnb-4bit-7f721e74",
            "adapter_loaded": False,
        },
        "required_identity_sha256": {
            BASE_CONFIG_SHA256,
            BASE_INDEX_SHA256,
            "f0bf8c732e026a033bfcf6d6930ff6a956f81342f8148aaec5a9b61e19ab9d2c",
            "1441be0b50d968791af1938e3f8f7593c808eb511e29388b2c9c4722dbe1132e",
            "70e4262be112c1ed56b0c09c6a3c46c9d131eff24daa42a16154753e63256647",
        },
        "required_process_arguments": {"Qwen3-32B-Base-bnb-4bit"},
        "required_forbidden_arguments": {"--adapter"},
    },
    "sft": {
        "request_model": "Qwen3-32B-Agentic-SFT-r1-v3",
        "response_model": "Qwen3-32B-Agentic-SFT-r1-v3",
        "system_fingerprint": "checkpoint-000119-f314593d3a1f",
        "health": {
            "status": "ok",
            "model": "Qwen3-32B-Agentic-SFT-r1-v3",
            "checkpoint": "checkpoint-000119",
        },
        "required_identity_sha256": {
            BASE_CONFIG_SHA256,
            BASE_INDEX_SHA256,
            ADAPTER_SHA256,
            "95d5c1391c281a85e4b39005618db5effa59f3e5804121f9cbdbcc23aab3d187",
            "5fe9e647444af15ca49e35820c328b33486d56761e15d3c548ba8dc712bd838c",
            "90964e5bff04a2c9bd064223bb1789ccefbbd6d8bacfcc04ffc4430a6dd04085",
            "8e21e476dc8d756804425d1f863fd7308ca4712c666c431fd74e026322522481",
        },
        "required_process_arguments": {"Qwen3-32B-Agentic-SFT-r1-v3", "--adapter"},
        "required_forbidden_arguments": set(),
    },
}


class SummaryError(RuntimeError):
    """An incomplete or inconsistent A/B evidence bundle."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reject_symlink_ancestors(path: Path) -> None:
    absolute = path.absolute()
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise SummaryError(f"path contains a symlink: {candidate}")


def load_frozen_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise SummaryError(f"frozen Test is missing or unsafe: {path}")
    if path.stat().st_size != FROZEN_TEST_BYTES or sha256_file(path) != FROZEN_TEST_SHA256:
        raise SummaryError("frozen Test identity mismatch")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise SummaryError(f"blank frozen Test row: {line_number}")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise SummaryError(f"frozen Test row is not an object: {line_number}")
            rows.append(row)
    if len(rows) != FROZEN_TASKS:
        raise SummaryError(f"frozen Test task count mismatch: {len(rows)}")
    return rows


def build_frozen_plan(rows: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    task_ids: set[str] = set()
    plan: list[dict[str, Any]] = []
    for task_index, row in enumerate(rows):
        task_id = row.get("task_id")
        messages = row.get("messages")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise SummaryError(f"invalid frozen task id at index {task_index}")
        if not isinstance(messages, list):
            raise SummaryError(f"frozen task has no messages: {task_id}")
        task_ids.add(task_id)
        for turn_index, message in enumerate(messages):
            if message.get("role") == "assistant":
                plan.append(
                    {
                        "key": f"{label}:{task_index}:{turn_index}",
                        "task_index": task_index,
                        "turn_index": turn_index,
                        "task_id": task_id,
                    }
                )
    if len(plan) != FROZEN_RECORDS:
        raise SummaryError(f"frozen Test record count mismatch: {len(plan)}")
    return plan


def normalize_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_tool_calls(tool_calls: Any) -> list[dict[str, str]]:
    if not isinstance(tool_calls, list):
        raise SummaryError("tool_calls is not an array")
    normalized: list[dict[str, str]] = []
    for tool_call in tool_calls:
        try:
            function = tool_call["function"]
            normalized.append(
                {
                    "name": function["name"],
                    "arguments": normalize_arguments(function["arguments"]),
                }
            )
        except (KeyError, TypeError) as error:
            raise SummaryError("malformed tool call in frozen evidence") from error
    return normalized


def independently_score(
    reference: dict[str, Any], response_message: dict[str, Any], finish_reason: Any
) -> dict[str, Any]:
    reference_calls = normalize_tool_calls(reference.get("tool_calls") or [])
    response_calls = normalize_tool_calls(response_message.get("tool_calls") or [])
    if reference_calls:
        count_exact = len(response_calls) == len(reference_calls)
        names_exact = [item["name"] for item in response_calls] == [
            item["name"] for item in reference_calls
        ]
        arguments_exact = [item["arguments"] for item in response_calls] == [
            item["arguments"] for item in reference_calls
        ]
        finish_reason_exact = finish_reason == "tool_calls"
        return {
            "reference_kind": "tool_calls",
            "structured": bool(response_calls),
            "reference_tool_call_count": len(reference_calls),
            "response_tool_call_count": len(response_calls),
            "tool_call_count_exact": count_exact,
            "tool_names_exact": names_exact,
            "tool_arguments_exact": arguments_exact,
            "tool_finish_reason_exact": finish_reason_exact,
            "tool_calls_exact": (
                count_exact and names_exact and arguments_exact and finish_reason_exact
            ),
            "final_clean": None,
            "final_text_exact": None,
        }
    reference_content = reference.get("content") or ""
    response_content = response_message.get("content") or ""
    if not isinstance(reference_content, str) or not isinstance(response_content, str):
        raise SummaryError("final-answer content is not text")
    clean_content = response_content.strip()
    final_clean = bool(clean_content) and not response_calls and finish_reason == "stop"
    return {
        "reference_kind": "final",
        "structured": None,
        "reference_tool_call_count": None,
        "response_tool_call_count": None,
        "tool_call_count_exact": None,
        "tool_names_exact": None,
        "tool_arguments_exact": None,
        "tool_finish_reason_exact": None,
        "tool_calls_exact": None,
        "final_clean": final_clean,
        "final_text_exact": final_clean and clean_content == reference_content.strip(),
    }


def adapter_runtime_path(file_hashes: dict[str, str]) -> str:
    adapter_files = [
        Path(path) for path, digest in file_hashes.items() if digest == ADAPTER_SHA256
    ]
    if (
        len(adapter_files) != 1
        or not adapter_files[0].is_absolute()
        or adapter_files[0] != Path(os.path.normpath(adapter_files[0]))
        or adapter_files[0].name != "adapter_model.safetensors"
    ):
        raise SummaryError("SFT identity must bind one canonical adapter file")
    return str(adapter_files[0].parent)


def load_arm(
    manifest_path: Path,
    capped_prefix: bool = False,
    recovery_raw_sha256: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise SummaryError(f"manifest is missing or unsafe: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise SummaryError(f"manifest schema mismatch: {manifest_path}")
    if capped_prefix:
        if manifest.get("status") != "INTERRUPTED" or manifest.get("last_error") != "SIGTERM":
            raise SummaryError(f"capped arm was not cleanly stopped: {manifest_path}")
    elif manifest.get("status") != "COMPLETE":
        raise SummaryError(f"arm is not COMPLETE: {manifest_path}")
    if manifest.get("training_use") is not False:
        raise SummaryError(f"arm is not marked training_use=false: {manifest_path}")
    if manifest.get("api_key_persisted") is not False:
        raise SummaryError(f"arm does not prove api_key_persisted=false: {manifest_path}")
    contract = manifest.get("contract")
    if not isinstance(contract, dict) or canonical_digest(contract) != manifest.get(
        "contract_sha256"
    ):
        raise SummaryError(f"manifest contract digest mismatch: {manifest_path}")
    config = contract.get("config")
    if not isinstance(config, dict):
        raise SummaryError(f"manifest has no evaluation config: {manifest_path}")
    label = manifest.get("label")
    run_id = manifest.get("run_id")
    raw_name = manifest.get("raw_file")
    if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
        raise SummaryError(f"unsafe raw_file in {manifest_path}")
    raw_path = manifest_path.parent / raw_name
    if not raw_path.is_file() or raw_path.is_symlink():
        raise SummaryError(f"raw file is missing or unsafe: {raw_path}")
    actual_sha = sha256_file(raw_path)
    if not capped_prefix and actual_sha != manifest.get("raw_sha256"):
        raise SummaryError(f"raw SHA-256 drift: {raw_path}")
    if capped_prefix:
        if recovery_raw_sha256 is None or actual_sha != recovery_raw_sha256:
            raise SummaryError(f"capped raw is not bound by its recovery seal: {raw_path}")
        if manifest.get("raw_sha256") not in (None, actual_sha):
            raise SummaryError(f"capped raw SHA-256 conflicts with manifest: {raw_path}")
    records: list[dict[str, Any]] = []
    keys: set[str] = set()
    with raw_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise SummaryError(f"blank raw record: {raw_path}:{line_number}")
            record = json.loads(line)
            if record.get("schema_version") != RECORD_SCHEMA:
                raise SummaryError(f"record schema mismatch: {raw_path}:{line_number}")
            if record.get("contract_sha256") != manifest.get("contract_sha256"):
                raise SummaryError(f"record contract mismatch: {raw_path}:{line_number}")
            if record.get("label") != label or record.get("run_id") != run_id:
                raise SummaryError(f"record arm identity mismatch: {raw_path}:{line_number}")
            response = record.get("response")
            if not isinstance(response, dict):
                raise SummaryError(f"record has no response: {raw_path}:{line_number}")
            if response.get("model") != config.get("expected_response_model"):
                raise SummaryError(f"record model identity mismatch: {raw_path}:{line_number}")
            if response.get("system_fingerprint") != config.get(
                "expected_system_fingerprint"
            ):
                raise SummaryError(
                    f"record fingerprint identity mismatch: {raw_path}:{line_number}"
                )
            key = record.get("key")
            if key in keys:
                raise SummaryError(f"duplicate record key: {raw_path}:{line_number}")
            keys.add(key)
            records.append(record)
    if not capped_prefix and len(records) != manifest.get("expected_records"):
        raise SummaryError(f"record completeness failure: {raw_path}")
    if len(records) != manifest.get("completed_records"):
        raise SummaryError(f"manifest completed count drift: {manifest_path}")
    return manifest, records, raw_path


def raw_path_from_manifest(manifest_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_name = manifest.get("raw_file")
    if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
        raise SummaryError(f"unsafe raw_file in {manifest_path}")
    return manifest_path.parent / raw_name


def snapshot_inputs(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        if not path.is_file() or path.is_symlink():
            raise SummaryError(f"summary input is missing or unsafe: {path}")
        reject_symlink_ancestors(path)
        details = path.stat()
        snapshots[name] = {
            "file": path.name,
            "sha256": sha256_file(path),
            "bytes": details.st_size,
            "mode": f"{details.st_mode & 0o7777:04o}",
            "device": details.st_dev,
            "inode": details.st_ino,
            "links": details.st_nlink,
            "uid": details.st_uid,
            "gid": details.st_gid,
            "mtime_ns": details.st_mtime_ns,
            "ctime_ns": details.st_ctime_ns,
        }
    return snapshots


def load_recovery_seal(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SummaryError(f"recovery seal is missing or unsafe: {path}")
    if path.stat().st_mode & 0o222:
        raise SummaryError(f"recovery seal remains writable: {path}")
    seal = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version": RECOVERY_SEAL_SCHEMA,
        "status": "RECOVERY_SEALED",
        "evidence_class": "post_stop_recovery_snapshot",
        "label": label,
        "training_use": False,
        "api_key_persisted": False,
        "collector_evaluator_sha256": FROZEN_EVALUATOR_SHA256,
        "sealer_sha256": FROZEN_SEALER_SHA256,
        "validator_sha256": sha256_file(Path(__file__).resolve()),
    }
    for field, expected in required.items():
        if seal.get(field) != expected:
            raise SummaryError(f"{label} recovery seal mismatch: {field}")
    raw = seal.get("raw")
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("sha256"), str)
        or len(raw["sha256"]) != 64
    ):
        raise SummaryError(f"{label} recovery seal has no raw SHA-256")
    return seal


def capped_composition(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    task_records: dict[str, dict[str, Any]] = {}
    for record in records:
        task_records.setdefault(record["task_id"], record)

    def key(record: dict[str, Any]) -> str:
        return f"{record['stratum']}|{record.get('task_kind') or 'unspecified'}"

    return {
        "tasks_by_stratum_and_kind": dict(
            sorted(Counter(key(record) for record in task_records.values()).items())
        ),
        "turns_by_stratum_and_kind": dict(
            sorted(Counter(key(record) for record in records).items())
        ),
    }


def jsonl_prefix_snapshot(path: Path, records: int) -> dict[str, Any]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        for line_number in range(1, records + 1):
            line = handle.readline()
            if not line or not line.endswith(b"\n"):
                raise SummaryError(f"raw prefix is truncated at record {line_number}")
            digest.update(line)
            byte_count += len(line)
    return {"records": records, "bytes": byte_count, "sha256": digest.hexdigest()}


def plan_prefix_sha256(records: list[dict[str, Any]]) -> str:
    fields = ("key", "task_index", "turn_index", "task_id")
    return canonical_digest(
        [{field: record[field] for field in fields} for record in records]
    )


def validate_recovery_seal(
    seal: dict[str, Any],
    manifest: dict[str, Any],
    manifest_snapshot: dict[str, Any],
    raw_snapshot: dict[str, Any],
    raw_path: Path,
    captured: list[dict[str, Any]],
    selected: list[dict[str, Any]],
) -> None:
    label = manifest["label"]
    if seal.get("run_id") != manifest.get("run_id"):
        raise SummaryError(f"{label} recovery seal run ID mismatch")
    original_manifest = seal.get("original_manifest")
    raw = seal.get("raw")
    selection = seal.get("selection")
    identity = seal.get("identity_at_seal")
    closure = seal.get("closure")
    if not all(
        isinstance(value, dict)
        for value in (original_manifest, raw, selection, identity, closure)
    ):
        raise SummaryError(f"{label} recovery seal is incomplete")
    expected_manifest = {
        **manifest_snapshot,
        "status": "INTERRUPTED",
        "last_error": "SIGTERM",
        "raw_sha256_field": None,
        "contract_sha256": manifest["contract_sha256"],
    }
    if original_manifest != expected_manifest:
        raise SummaryError(f"{label} recovery seal manifest snapshot mismatch")
    expected_raw = {**raw_snapshot, "captured_records": len(captured)}
    if raw != expected_raw:
        raise SummaryError(f"{label} recovery seal raw snapshot mismatch")
    expected_selection = {
        "method": "deterministic_ordered_frozen_prefix",
        "selected_records": CAPPED_RECORDS,
        "selected_tasks": CAPPED_TASKS,
        "first_task_index": 0,
        "last_task_index": 48,
        "optional_excluded_record_key": (
            captured[CAPPED_RECORDS]["key"]
            if len(captured) == CAPPED_MAX_CAPTURED_RECORDS
            else None
        ),
        "raw_prefix": jsonl_prefix_snapshot(raw_path, CAPPED_RECORDS),
        "plan_prefix_sha256": plan_prefix_sha256(selected),
    }
    for field, expected in expected_selection.items():
        if selection.get(field) != expected:
            raise SummaryError(f"{label} recovery seal selection mismatch: {field}")
    if selection.get("composition") != capped_composition(selected):
        raise SummaryError(f"{label} recovery seal composition mismatch")
    if identity.get("health") != manifest.get("initial_health"):
        raise SummaryError(f"{label} seal-time health does not match initial identity")
    if identity.get("service") != manifest.get("initial_service"):
        raise SummaryError(f"{label} seal-time service does not match initial identity")
    if identity.get("identity_file_sha256") != manifest["contract"]["config"].get(
        "expected_file_sha256"
    ):
        raise SummaryError(f"{label} seal-time identity files mismatch")
    if identity.get("matches_initial_health") is not True:
        raise SummaryError(f"{label} recovery seal lacks health closure")
    if identity.get("matches_initial_service") is not True:
        raise SummaryError(f"{label} recovery seal lacks service closure")
    if closure != {
        "kind": "POST_STOP_RECOVERY_ONLY",
        "stop_time_closure_proven": False,
    }:
        raise SummaryError(f"{label} recovery seal overstates stop-time closure")
    if len(selected) != CAPPED_RECORDS:
        raise SummaryError(f"{label} recovery selection length mismatch")


def select_capped_prefix(records: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    if not CAPPED_RECORDS <= len(records) <= CAPPED_MAX_CAPTURED_RECORDS:
        raise SummaryError(
            f"{label} capped capture must contain 170 or 171 durable records"
        )
    selected = records[:CAPPED_RECORDS]
    if len({record["task_id"] for record in selected}) != CAPPED_TASKS:
        raise SummaryError(f"{label} capped prefix does not contain 49 complete tasks")
    if selected[-1].get("task_index") != 48:
        raise SummaryError(f"{label} capped prefix does not end at task index 48")
    if len(records) == CAPPED_MAX_CAPTURED_RECORDS and records[-1].get("task_index") != 49:
        raise SummaryError(f"{label} optional drain record is not the next frozen task")
    return selected


def validate_arm_identity(manifest: dict[str, Any], label: str) -> None:
    identity = ARM_IDENTITIES[label]
    contract = manifest["contract"]
    if contract.get("evaluator_sha256") != FROZEN_EVALUATOR_SHA256:
        raise SummaryError(f"{label} evaluator SHA-256 is not the reviewed collector")
    config = contract["config"]
    required_config = {
        "label": label,
        "request_model": identity["request_model"],
        "expected_response_model": identity["response_model"],
        "expected_system_fingerprint": identity["system_fingerprint"],
        "expected_health": identity["health"],
        "expected_tasks": FROZEN_TASKS,
        "expected_records": FROZEN_RECORDS,
        "expected_test_sha256": FROZEN_TEST_SHA256,
        "expected_test_bytes": FROZEN_TEST_BYTES,
        "temperature": 0,
    }
    for field, expected in required_config.items():
        if config.get(field) != expected:
            raise SummaryError(f"{label} frozen identity mismatch: {field}")
    if contract.get("test_sha256") != FROZEN_TEST_SHA256:
        raise SummaryError(f"{label} contract does not bind the frozen Test")
    file_hashes = config.get("expected_file_sha256")
    if not isinstance(file_hashes, dict):
        raise SummaryError(f"{label} arm has no identity-file contract")
    for path, digest in file_hashes.items():
        candidate = Path(path) if isinstance(path, str) else Path()
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or not candidate.is_absolute()
            or candidate != Path(os.path.normpath(candidate))
        ):
            raise SummaryError(f"{label} arm has a non-canonical identity-file path")
    missing_hashes = identity["required_identity_sha256"] - set(file_hashes.values())
    if missing_hashes:
        raise SummaryError(f"{label} arm is missing frozen identity hashes")
    process_arguments = config.get("expected_process_arguments")
    forbidden_arguments = config.get("forbidden_process_arguments")
    if not isinstance(process_arguments, list) or not isinstance(forbidden_arguments, list):
        raise SummaryError(f"{label} arm has no process-argument contract")
    if identity["required_process_arguments"] - set(process_arguments):
        raise SummaryError(f"{label} arm is missing required process arguments")
    if identity["required_forbidden_arguments"] - set(forbidden_arguments):
        raise SummaryError(f"{label} arm is missing forbidden-process gates")
    if label == "base" and ADAPTER_SHA256 in file_hashes.values():
        raise SummaryError("Base arm unexpectedly binds the SFT adapter")
    if label == "sft":
        expected_adapter_path = adapter_runtime_path(file_hashes)
        if expected_adapter_path not in process_arguments:
            raise SummaryError("SFT adapter hash is not bound to the process contract")


def validate_records_against_test(
    manifest: dict[str, Any], records: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    label = manifest["label"]
    plan = build_frozen_plan(rows, label)
    if manifest["contract"].get("plan_sha256") != canonical_digest(plan):
        raise SummaryError(f"{label} frozen plan digest mismatch")
    for line_number, (record, item) in enumerate(zip(records, plan), 1):
        for field in ("key", "task_index", "turn_index", "task_id"):
            if record.get(field) != item[field]:
                raise SummaryError(f"{label} frozen plan mismatch at record {line_number}")
        row = rows[item["task_index"]]
        reference = row["messages"][item["turn_index"]]
        metadata = row.get("metadata") or {}
        expected_stratum = (
            "promoted"
            if metadata.get("promoted_from_needs_review") is True
            else "curated"
        )
        expected_fields = {
            "stratum": expected_stratum,
            "task_kind": metadata.get("task_kind"),
            "category": metadata.get("category"),
            "failed_checks": metadata.get("failed_checks") or [],
        }
        for field, expected in expected_fields.items():
            if record.get(field) != expected:
                raise SummaryError(
                    f"{label} frozen metadata mismatch at record {line_number}: {field}"
                )
        expected_reference = {
            "content": reference.get("content"),
            "tool_calls": normalize_tool_calls(reference.get("tool_calls") or []),
        }
        if record.get("reference") != expected_reference:
            raise SummaryError(f"{label} frozen reference mismatch at record {line_number}")
        response = record.get("response")
        response_message = response.get("message") if isinstance(response, dict) else None
        if not isinstance(response_message, dict):
            raise SummaryError(f"{label} response message missing at record {line_number}")
        normalized_response_calls = normalize_tool_calls(
            response_message.get("tool_calls") or []
        )
        if response.get("tool_calls") != normalized_response_calls:
            raise SummaryError(f"{label} stored response drift at record {line_number}")
        rescored = independently_score(
            reference, response_message, response.get("finish_reason")
        )
        if record.get("scores") != rescored:
            raise SummaryError(f"{label} stored score drift at record {line_number}")


def rate(records: list[dict[str, Any]], score: str, kind: str) -> dict[str, Any]:
    values = [
        record["scores"].get(score)
        for record in records
        if record["scores"].get("reference_kind") == kind
        and isinstance(record["scores"].get(score), bool)
    ]
    passed = sum(values)
    return {
        "passed": passed,
        "total": len(values),
        "rate": (passed / len(values)) if values else None,
    }


def boolean_rate(values: list[bool]) -> dict[str, Any]:
    passed = sum(values)
    return {
        "passed": passed,
        "total": len(values),
        "rate": (passed / len(values)) if values else None,
    }


def turn_contract_pass(record: dict[str, Any]) -> bool:
    scores = record["scores"]
    if scores["reference_kind"] == "tool_calls":
        return scores["tool_calls_exact"] is True
    return scores["final_clean"] is True


def task_contract_pass(records: list[dict[str, Any]]) -> dict[str, bool]:
    grouped: dict[str, list[bool]] = {}
    for record in records:
        grouped.setdefault(record["task_id"], []).append(turn_contract_pass(record))
    return {task_id: all(values) for task_id, values in grouped.items()}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    tool_records = [r for r in records if r["scores"]["reference_kind"] == "tool_calls"]
    final_records = [r for r in records if r["scores"]["reference_kind"] == "final"]
    latencies = [float(r["latency_seconds"]) for r in records]
    prompt_tokens = 0
    completion_tokens = 0
    for record in records:
        usage = record["response"].get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
    task_passes = task_contract_pass(records)
    return {
        "records": len(records),
        "tasks": len({record["task_id"] for record in records}),
        "tool_turns": len(tool_records),
        "final_turns": len(final_records),
        "reference_tool_calls": sum(
            len(record["reference"]["tool_calls"]) for record in tool_records
        ),
        "response_models": dict(
            sorted(Counter(record["response"]["model"] for record in records).items())
        ),
        "system_fingerprints": dict(
            sorted(
                Counter(
                    record["response"]["system_fingerprint"] for record in records
                ).items()
            )
        ),
        "scores": {
            "structured": rate(records, "structured", "tool_calls"),
            "tool_call_count_exact": rate(records, "tool_call_count_exact", "tool_calls"),
            "tool_names_exact": rate(records, "tool_names_exact", "tool_calls"),
            "tool_arguments_exact": rate(records, "tool_arguments_exact", "tool_calls"),
            "tool_finish_reason_exact": rate(
                records, "tool_finish_reason_exact", "tool_calls"
            ),
            "tool_calls_exact": rate(records, "tool_calls_exact", "tool_calls"),
            "final_clean": rate(records, "final_clean", "final"),
            "final_text_exact": rate(records, "final_text_exact", "final"),
            "task_all_turns_contract": boolean_rate(list(task_passes.values())),
        },
        "latency_seconds": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


def comparable_key(record: dict[str, Any]) -> tuple[int, int, str]:
    return record["task_index"], record["turn_index"], record["task_id"]


def score_deltas(base: dict[str, Any], sft: dict[str, Any]) -> dict[str, float | None]:
    deltas: dict[str, float | None] = {}
    for score, base_value in base["scores"].items():
        sft_value = sft["scores"][score]
        if base_value["rate"] is None or sft_value["rate"] is None:
            deltas[score] = None
        else:
            deltas[score] = sft_value["rate"] - base_value["rate"]
    return deltas


def paired_counts(base_values: list[bool], sft_values: list[bool]) -> dict[str, int]:
    if len(base_values) != len(sft_values):
        raise SummaryError("paired metric lengths differ")
    return {
        "both": sum(base and sft for base, sft in zip(base_values, sft_values)),
        "sft_only": sum((not base) and sft for base, sft in zip(base_values, sft_values)),
        "base_only": sum(base and (not sft) for base, sft in zip(base_values, sft_values)),
        "neither": sum((not base) and (not sft) for base, sft in zip(base_values, sft_values)),
        "total": len(base_values),
    }


def paired_outcomes(
    base_records: list[dict[str, Any]], sft_records: list[dict[str, Any]]
) -> dict[str, Any]:
    base_by_key = {comparable_key(record): record for record in base_records}
    sft_by_key = {comparable_key(record): record for record in sft_records}
    if set(base_by_key) != set(sft_by_key):
        raise SummaryError("paired group record-key sets differ")
    ordered_keys = sorted(base_by_key)
    outcomes: dict[str, Any] = {}
    for score in (
        "structured",
        "tool_call_count_exact",
        "tool_names_exact",
        "tool_arguments_exact",
        "tool_finish_reason_exact",
        "tool_calls_exact",
        "final_clean",
        "final_text_exact",
    ):
        pairs = [
            (base_by_key[key]["scores"].get(score), sft_by_key[key]["scores"].get(score))
            for key in ordered_keys
        ]
        boolean_pairs = [pair for pair in pairs if all(isinstance(value, bool) for value in pair)]
        outcomes[score] = paired_counts(
            [pair[0] for pair in boolean_pairs], [pair[1] for pair in boolean_pairs]
        )
    base_tasks = task_contract_pass(base_records)
    sft_tasks = task_contract_pass(sft_records)
    if set(base_tasks) != set(sft_tasks):
        raise SummaryError("paired group task sets differ")
    task_ids = sorted(base_tasks)
    outcomes["task_all_turns_contract"] = paired_counts(
        [base_tasks[task_id] for task_id in task_ids],
        [sft_tasks[task_id] for task_id in task_ids],
    )
    return outcomes


def group_summary(
    base_records: list[dict[str, Any]], sft_records: list[dict[str, Any]]
) -> dict[str, Any]:
    base_aggregate = aggregate(base_records)
    sft_aggregate = aggregate(sft_records)
    return {
        "base": base_aggregate,
        "sft": sft_aggregate,
        "sft_minus_base": score_deltas(base_aggregate, sft_aggregate),
        "paired": paired_outcomes(base_records, sft_records),
    }


def summarize_locked(
    base_manifest_path: Path,
    sft_manifest_path: Path,
    test_path: Path,
    capped_prefix: bool = False,
    base_seal_path: Path | None = None,
    sft_seal_path: Path | None = None,
) -> dict[str, Any]:
    reject_symlink_ancestors(test_path)
    reject_symlink_ancestors(base_manifest_path)
    reject_symlink_ancestors(sft_manifest_path)
    base_raw_path = raw_path_from_manifest(base_manifest_path)
    sft_raw_path = raw_path_from_manifest(sft_manifest_path)
    input_paths = {
        "base_manifest": base_manifest_path,
        "base_raw": base_raw_path,
        "sft_manifest": sft_manifest_path,
        "sft_raw": sft_raw_path,
        "frozen_test": test_path,
    }
    base_seal = None
    sft_seal = None
    if capped_prefix:
        if base_seal_path is None or sft_seal_path is None:
            raise SummaryError("capped summary requires both recovery seals")
        input_paths["base_recovery_seal"] = base_seal_path
        input_paths["sft_recovery_seal"] = sft_seal_path
    elif base_seal_path is not None or sft_seal_path is not None:
        raise SummaryError("recovery seals are only valid with --capped-prefix-170")
    snapshots_before = snapshot_inputs(input_paths)
    if capped_prefix:
        base_seal = load_recovery_seal(base_seal_path, "base")
        sft_seal = load_recovery_seal(sft_seal_path, "sft")

    frozen_rows = load_frozen_rows(test_path)
    base_manifest, base_captured, base_raw = load_arm(
        base_manifest_path,
        capped_prefix,
        base_seal["raw"]["sha256"] if base_seal else None,
    )
    sft_manifest, sft_captured, sft_raw = load_arm(
        sft_manifest_path,
        capped_prefix,
        sft_seal["raw"]["sha256"] if sft_seal else None,
    )
    if base_raw != base_raw_path or sft_raw != sft_raw_path:
        raise SummaryError("manifest raw path changed during summary validation")
    if base_manifest.get("label") != "base" or sft_manifest.get("label") != "sft":
        raise SummaryError("manifests must be passed as Base then SFT")
    if base_manifest.get("run_id") != sft_manifest.get("run_id"):
        raise SummaryError("Base/SFT run IDs differ")
    validate_arm_identity(base_manifest, "base")
    validate_arm_identity(sft_manifest, "sft")
    validate_records_against_test(base_manifest, base_captured, frozen_rows)
    validate_records_against_test(sft_manifest, sft_captured, frozen_rows)
    if capped_prefix:
        base_records = select_capped_prefix(base_captured, "base")
        sft_records = select_capped_prefix(sft_captured, "sft")
        validate_recovery_seal(
            base_seal,
            base_manifest,
            snapshots_before["base_manifest"],
            snapshots_before["base_raw"],
            base_raw,
            base_captured,
            base_records,
        )
        validate_recovery_seal(
            sft_seal,
            sft_manifest,
            snapshots_before["sft_manifest"],
            snapshots_before["sft_raw"],
            sft_raw,
            sft_captured,
            sft_records,
        )
    else:
        base_records = base_captured
        sft_records = sft_captured
    base_test = base_manifest["contract"]["test_sha256"]
    sft_test = sft_manifest["contract"]["test_sha256"]
    if base_test != sft_test:
        raise SummaryError("Base/SFT test SHA-256 mismatch")
    if (
        base_manifest["contract"]["evaluator_sha256"]
        != sft_manifest["contract"]["evaluator_sha256"]
    ):
        raise SummaryError("Base/SFT evaluator SHA-256 mismatch")
    comparison_fields = (
        "base_url",
        "expected_tasks",
        "expected_records",
        "expected_test_sha256",
        "expected_test_bytes",
        "max_tokens",
        "temperature",
        "timeout_seconds",
    )
    base_config = base_manifest["contract"]["config"]
    sft_config = sft_manifest["contract"]["config"]
    for field in comparison_fields:
        if base_config.get(field) != sft_config.get(field):
            raise SummaryError(f"Base/SFT comparison contract differs: {field}")

    base_by_key = {comparable_key(record): record for record in base_records}
    sft_by_key = {comparable_key(record): record for record in sft_records}
    if set(base_by_key) != set(sft_by_key):
        raise SummaryError("Base/SFT record-key sets differ")
    for key in base_by_key:
        base_record = base_by_key[key]
        sft_record = sft_by_key[key]
        if base_record["stratum"] != sft_record["stratum"]:
            raise SummaryError(f"Base/SFT stratum mismatch: {key}")
        if base_record["reference"] != sft_record["reference"]:
            raise SummaryError(f"Base/SFT reference mismatch: {key}")

    groups: dict[str, Any] = {"all": {"all": group_summary(base_records, sft_records)}}
    group_fields = {
        "quality": "stratum",
        "task_kind": "task_kind",
        "category": "category",
    }
    for group_name, field in group_fields.items():
        values = sorted({record[field] for record in base_records if record.get(field)})
        groups[group_name] = {}
        for value in values:
            selected_base = [record for record in base_records if record.get(field) == value]
            selected_sft = [record for record in sft_records if record.get(field) == value]
            groups[group_name][value] = group_summary(selected_base, selected_sft)

    snapshots_after = snapshot_inputs(input_paths)
    if snapshots_after != snapshots_before:
        raise SummaryError("summary inputs changed while they were being validated")

    return {
        "schema_version": SUMMARY_SCHEMA,
        "status": "CAPPED_RECOVERY_SEALED" if capped_prefix else "COMPLETE",
        "created_at_utc": utc_now(),
        "run_id": base_manifest["run_id"],
        "training_use": False,
        "api_key_persisted": False,
        "test_sha256": base_test,
        "evaluator_sha256": {
            "base": base_manifest["contract"]["evaluator_sha256"],
            "sft": sft_manifest["contract"]["evaluator_sha256"],
        },
        "summarizer_sha256": sha256_file(Path(__file__).resolve()),
        "inputs": snapshots_before,
        "scope": {
            "mode": (
                "user_capped_recovery_sealed_ordered_prefix"
                if capped_prefix
                else "full_frozen_test"
            ),
            "selected_records_per_arm": len(base_records),
            "selected_tasks": len({record["task_id"] for record in base_records}),
            "base_captured_records": len(base_captured),
            "sft_captured_records": len(sft_captured),
            "composition": capped_composition(base_records) if capped_prefix else None,
        },
        "groups": groups,
        "boundary": (
            "Post-stop recovery-sealed deterministic ordered prefix: first 49 complete "
            "frozen tasks / 170 assistant turns. The cap was not bound in the original "
            "evaluator contract. It contains 28 curated live-diagnostic, 5 curated "
            "controlled-actuation, and 16 promoted live-diagnostic tasks; it omits all "
            "15 promoted controlled-actuation tasks. It is not a random or "
            "representative sample of the full 113-task Test. The original "
            "SIGTERM manifests did not hash raw output or capture stop-time final "
            "identity; the sidecars seal and identity-check the later read-only "
            "snapshots only. Teacher-trajectory replay agreement does not prove Agent "
            "end-to-end success, board execution, or physical effect."
            if capped_prefix
            else "Teacher-trajectory replay agreement only; this summary does not "
            "prove end-to-end Agent success, board execution, or physical effect."
        ),
    }


def summarize(
    base_manifest_path: Path,
    sft_manifest_path: Path,
    test_path: Path,
    capped_prefix: bool = False,
    base_seal_path: Path | None = None,
    sft_seal_path: Path | None = None,
) -> dict[str, Any]:
    paths = (base_manifest_path, sft_manifest_path, test_path)
    for path in paths:
        reject_symlink_ancestors(path)
    arm_directory = base_manifest_path.parent.resolve()
    if sft_manifest_path.parent.resolve() != arm_directory:
        raise SummaryError("Base/SFT manifests must share one locked arm directory")
    if capped_prefix:
        if base_seal_path is None or sft_seal_path is None:
            raise SummaryError("capped summary requires both recovery seals")
        if (
            base_seal_path.parent.resolve() != arm_directory
            or sft_seal_path.parent.resolve() != arm_directory
        ):
            raise SummaryError("recovery seals must share the locked arm directory")
    directory_fd = os.open(arm_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SummaryError("arm directory is locked by an evaluator or sealer") from error
        return summarize_locked(
            base_manifest_path,
            sft_manifest_path,
            test_path,
            capped_prefix,
            base_seal_path,
            sft_seal_path,
        )
    finally:
        os.close(directory_fd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_manifest", type=Path)
    parser.add_argument("sft_manifest", type=Path)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument(
        "--capped-prefix-170",
        action="store_true",
        help="compare recovery-sealed first 49 tasks / 170 turns",
    )
    parser.add_argument("--base-recovery-seal", type=Path)
    parser.add_argument("--sft-recovery-seal", type=Path)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = summarize(
            args.base_manifest,
            args.sft_manifest,
            args.test,
            capped_prefix=args.capped_prefix_170,
            base_seal_path=args.base_recovery_seal,
            sft_seal_path=args.sft_recovery_seal,
        )
        if args.out:
            reject_symlink_ancestors(args.out)
            if args.out.exists() or args.out.is_symlink():
                raise SummaryError(f"refusing to overwrite output: {args.out}")
            if not args.out.parent.is_dir():
                raise SummaryError("summary output parent must already exist")
            atomic_write_json(args.out, summary)
        else:
            json.dump(summary, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
            sys.stdout.write("\n")
    except Exception as error:
        print(f"summary failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
