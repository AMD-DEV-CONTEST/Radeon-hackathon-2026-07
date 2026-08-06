#!/usr/bin/env python3
"""Run one fail-closed arm of the frozen Base/SFT replay evaluation.

The program appends one auditable JSON record per assistant turn and maintains
an atomic sidecar manifest. Successful records are resumable. Any service,
model-identity, input, or output-contract drift exits non-zero immediately.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import stat
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RECORD_SCHEMA = "rdk_model_ab_record.v2"
MANIFEST_SCHEMA = "rdk_model_ab_arm_manifest.v2"
FROZEN_TEST_SHA256 = "d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283"
FROZEN_TEST_BYTES = 3_562_357
FROZEN_TASKS = 113
FROZEN_RECORDS = 413
BASE_CONFIG_SHA256 = "918fe2d123e79abf8ed4688278cc7d9c6c54d25fbea35e5f0870985f4d663000"
BASE_INDEX_SHA256 = "2771f7e67bacc73ceb4ee0dfe6027d49fc9a4390d17eda517a4f7f48923d6a61"
ADAPTER_SHA256 = "4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf"
FROZEN_ARMS: dict[str, dict[str, Any]] = {
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


class EvaluationError(RuntimeError):
    """A fail-closed evaluation contract violation."""


class GracefulStop(RuntimeError):
    """A requested SIGINT/SIGTERM stop after the current record is durable."""

    def __init__(self, signum: int):
        super().__init__(signal.Signals(signum).name)
        self.signum = signum


STOP_SIGNAL: int | None = None


def request_stop(signum: int, _frame: Any) -> None:
    global STOP_SIGNAL
    STOP_SIGNAL = signum


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    body = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if created and temporary.exists():
            temporary.unlink()


def reject_symlink_ancestors(path: Path) -> None:
    absolute = path.absolute()
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise EvaluationError(f"path contains a symlink: {candidate}")


def parse_file_hash(spec: str) -> tuple[Path, str]:
    raw_path, separator, expected = spec.rpartition("=")
    if not separator or not raw_path or len(expected) != 64:
        raise argparse.ArgumentTypeError(f"expected PATH=SHA256, got {spec!r}")
    try:
        int(expected, 16)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid SHA-256 in {spec!r}") from error
    return Path(raw_path), expected.lower()


def read_api_key(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise EvaluationError(f"API key file is missing or unsafe: {path}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise EvaluationError(f"API key file must not be group/world accessible: {path}")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise EvaluationError("API key file is empty")
    return key


def verify_identity_files(specs: list[tuple[Path, str]]) -> dict[str, str]:
    verified: dict[str, str] = {}
    for path, expected in specs:
        if not path.is_absolute():
            raise EvaluationError(f"identity file path must be absolute: {path}")
        if not path.is_file() or path.is_symlink():
            raise EvaluationError(f"identity file is missing or unsafe: {path}")
        reject_symlink_ancestors(path)
        if path != path.resolve(strict=True):
            raise EvaluationError(f"identity file path must be canonical: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise EvaluationError(f"identity file hash drift: {path}: {actual} != {expected}")
        verified[str(path)] = expected
    return dict(sorted(verified.items()))


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
        raise EvaluationError("SFT identity must bind one canonical adapter file")
    return str(adapter_files[0].parent)


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise EvaluationError(f"blank input row at line {line_number}")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise EvaluationError(f"invalid JSON at line {line_number}: {error}") from error
            if not isinstance(row, dict):
                raise EvaluationError(f"input row {line_number} is not an object")
            rows.append(row)
    return rows


def to_openai(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    pending_ids: list[str] = []
    for message in messages:
        role = message["role"]
        if role == "assistant" and message.get("tool_calls"):
            if pending_ids:
                raise EvaluationError("new assistant tool call before prior results completed")
            tool_calls: list[dict[str, Any]] = []
            for tool_call in message["tool_calls"]:
                function = tool_call["function"]
                arguments = function["arguments"]
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                tool_calls.append(
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": function["name"],
                            "arguments": arguments,
                        },
                    }
                )
            pending_ids = [item["id"] for item in tool_calls]
            converted.append(
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": tool_calls,
                }
            )
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not call_id:
                raise EvaluationError("tool message has no tool_call_id")
            if call_id not in pending_ids:
                raise EvaluationError(f"tool message references unknown tool_call_id: {call_id}")
            pending_ids.remove(call_id)
            content = message.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            converted.append(
                {"role": "tool", "tool_call_id": call_id, "content": content}
            )
        else:
            if pending_ids:
                raise EvaluationError("conversation continued before all tool results arrived")
            converted.append({"role": role, "content": message.get("content")})
    if pending_ids:
        raise EvaluationError("conversation prefix ends before all tool results arrived")
    return converted


def normalize_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_tool_calls(tool_calls: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for tool_call in tool_calls:
        function = tool_call["function"]
        normalized.append(
            {
                "name": function["name"],
                "arguments": normalize_arguments(function["arguments"]),
            }
        )
    return normalized


def score_turn(
    reference: dict[str, Any],
    response_message: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    reference_calls = normalize_tool_calls(reference.get("tool_calls") or [])
    response_calls = normalize_tool_calls(response_message.get("tool_calls") or [])
    reference_content = reference.get("content") or ""
    response_content = response_message.get("content") or ""
    if reference_calls:
        names_exact = [item["name"] for item in response_calls] == [
            item["name"] for item in reference_calls
        ]
        arguments_exact = [item["arguments"] for item in response_calls] == [
            item["arguments"] for item in reference_calls
        ]
        count_exact = len(response_calls) == len(reference_calls)
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


def build_plan(rows: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    task_ids: set[str] = set()
    plan: list[dict[str, Any]] = []
    for task_index, row in enumerate(rows):
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise EvaluationError(f"task {task_index} has no task_id")
        if task_id in task_ids:
            raise EvaluationError(f"duplicate task_id: {task_id}")
        task_ids.add(task_id)
        messages = row.get("messages")
        if not isinstance(messages, list):
            raise EvaluationError(f"task {task_id} has no messages array")
        for turn_index, message in enumerate(messages):
            if message.get("role") != "assistant":
                continue
            plan.append(
                {
                    "key": f"{label}:{task_index}:{turn_index}",
                    "task_index": task_index,
                    "turn_index": turn_index,
                    "task_id": task_id,
                }
            )
    return plan


class JsonHttpClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise EvaluationError(
                f"HTTP {path} failed: {type(error).__name__}: {error}"
            ) from error
        if not isinstance(result, dict):
            raise EvaluationError(f"HTTP {path} returned a non-object JSON value")
        return result


def verify_health(client: JsonHttpClient, expected: dict[str, Any]) -> dict[str, Any]:
    health = client.request("/health")
    for key, expected_value in expected.items():
        if health.get(key) != expected_value:
            raise EvaluationError(
                f"health identity drift for {key}: {health.get(key)!r} != {expected_value!r}"
            )
    return {key: health[key] for key in expected}


def listener_socket_inodes(pid: int, port: int) -> list[int]:
    listening: set[int] = set()
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not table.is_file():
            continue
        for line in table.read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10:
                continue
            local_address, state, inode = fields[1], fields[3], fields[9]
            if state == "0A" and int(local_address.rsplit(":", 1)[1], 16) == port:
                listening.add(int(inode))
    owned: set[int] = set()
    for descriptor in (Path("/proc") / str(pid) / "fd").iterdir():
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inode = int(target[8:-1])
            if inode in listening:
                owned.add(inode)
    if not owned:
        raise EvaluationError(f"service pid {pid} does not own listening port {port}")
    return sorted(owned)


def verify_service_process(
    pid_file: Path,
    expected_arguments: list[str],
    forbidden_arguments: list[str],
    expected_adapter_path: str | None = None,
) -> dict[str, Any]:
    if not pid_file.is_file() or pid_file.is_symlink():
        raise EvaluationError(f"service PID file is missing or unsafe: {pid_file}")
    raw_pid = pid_file.read_text(encoding="utf-8").strip()
    if not raw_pid.isdecimal():
        raise EvaluationError(f"invalid service PID file: {pid_file}")
    pid = int(raw_pid)
    process_root = Path("/proc") / str(pid)
    cmdline_path = process_root / "cmdline"
    stat_path = process_root / "stat"
    if not cmdline_path.is_file() or not stat_path.is_file():
        raise EvaluationError(f"service process is not live: pid={pid}")
    cmdline_body = cmdline_path.read_bytes()
    arguments = [
        item.decode("utf-8", errors="strict")
        for item in cmdline_body.split(b"\0")
        if item
    ]
    for expected in expected_arguments:
        if expected not in arguments:
            raise EvaluationError(f"service process argument missing: {expected}")
    for forbidden in forbidden_arguments:
        if forbidden in arguments:
            raise EvaluationError(f"forbidden service process argument present: {forbidden}")
    if expected_adapter_path is not None:
        if arguments.count("--adapter") != 1:
            raise EvaluationError("service must have exactly one --adapter argument")
        adapter_index = arguments.index("--adapter")
        if (
            adapter_index + 1 >= len(arguments)
            or arguments[adapter_index + 1] != expected_adapter_path
        ):
            raise EvaluationError("service --adapter path does not match the frozen identity")
    stat_fields = stat_path.read_text(encoding="utf-8").rsplit(") ", 1)[1].split()
    start_ticks = int(stat_fields[19])
    return {
        "pid": pid,
        "start_ticks": start_ticks,
        "cmdline_sha256": hashlib.sha256(cmdline_body).hexdigest(),
        "listen_port": 8000,
        "listener_socket_inodes": listener_socket_inodes(pid, 8000),
    }


def load_resume_records(
    raw_path: Path,
    manifest_path: Path,
    contract_sha256: str,
    planned_keys: list[str],
) -> tuple[dict[str, Any] | None, set[str]]:
    if raw_path.exists() != manifest_path.exists():
        raise EvaluationError("raw output and manifest must either both exist or both be absent")
    if not raw_path.exists():
        return None, set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise EvaluationError("resume manifest schema mismatch")
    if manifest.get("contract_sha256") != contract_sha256:
        raise EvaluationError("resume contract mismatch")
    if manifest.get("status") not in {"RUNNING", "INTERRUPTED", "FAILED", "COMPLETE"}:
        raise EvaluationError("resume manifest status is invalid")
    completed: set[str] = set()
    with raw_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise EvaluationError(f"invalid resume JSONL line {line_number}") from error
            if record.get("schema_version") != RECORD_SCHEMA:
                raise EvaluationError(f"resume record schema mismatch at line {line_number}")
            if record.get("contract_sha256") != contract_sha256:
                raise EvaluationError(f"resume record contract mismatch at line {line_number}")
            key = record.get("key")
            if line_number > len(planned_keys) or key != planned_keys[line_number - 1]:
                raise EvaluationError(
                    f"resume records are not the strict plan prefix at line {line_number}: {key}"
                )
            if key in completed:
                raise EvaluationError(f"duplicate resume record key: {key}")
            completed.add(key)
    manifest_count = manifest.get("completed_records")
    if not isinstance(manifest_count, int) or not 0 <= manifest_count <= len(completed):
        raise EvaluationError("resume manifest count exceeds the durable raw prefix")
    if manifest.get("status") == "COMPLETE":
        if manifest_count != len(planned_keys) or len(completed) != len(planned_keys):
            raise EvaluationError("COMPLETE resume manifest has missing records")
        if manifest.get("raw_sha256") != sha256_file(raw_path):
            raise EvaluationError("COMPLETE raw SHA-256 drift; refusing to reseal")
    return manifest, completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--label", choices=("base", "sft"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--expect-file-sha256", action="append", default=[], type=parse_file_hash
    )
    parser.add_argument("--service-pid-file", type=Path, required=True)
    parser.add_argument("--expect-process-arg", action="append", default=[])
    parser.add_argument("--forbid-process-arg", action="append", default=[])
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.raw_out.resolve() == args.manifest_out.resolve():
        raise EvaluationError("raw output and manifest paths must differ")
    if not args.raw_out.parent.is_dir() or not args.manifest_out.parent.is_dir():
        raise EvaluationError("output parent directories must already exist")
    if args.raw_out.parent.resolve() != args.manifest_out.parent.resolve():
        raise EvaluationError("raw output and manifest must share one run directory")
    reject_symlink_ancestors(args.raw_out)
    reject_symlink_ancestors(args.manifest_out)
    if args.raw_out.is_symlink() or args.manifest_out.is_symlink():
        raise EvaluationError("output paths must not be symlinks")
    directory_fd = os.open(args.manifest_out.parent, os.O_RDONLY | os.O_DIRECTORY)
    service_lock_fd: int | None = None
    try:
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EvaluationError(
                f"evaluation run directory is locked: {args.manifest_out.parent}"
            ) from error
        service_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            service_flags |= os.O_NOFOLLOW
        try:
            service_lock_fd = os.open(args.service_pid_file, service_flags)
            fcntl.flock(service_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            if service_lock_fd is not None:
                os.close(service_lock_fd)
                service_lock_fd = None
            raise EvaluationError(
                f"service PID file is missing, unsafe, or locked: {args.service_pid_file}"
            ) from error
        return run_locked(args)
    finally:
        if service_lock_fd is not None:
            os.close(service_lock_fd)
        os.close(directory_fd)


def run_locked(args: argparse.Namespace) -> dict[str, Any]:
    if args.base_url.rstrip("/") != "http://127.0.0.1:8000":
        raise EvaluationError("base URL must remain host-local: http://127.0.0.1:8000")
    if not args.run_id.strip():
        raise EvaluationError("run ID must not be empty")
    if not args.expect_process_arg:
        raise EvaluationError("at least one --expect-process-arg is required")
    if not args.expect_file_sha256:
        raise EvaluationError("at least one --expect-file-sha256 is required")
    arm = FROZEN_ARMS[args.label]

    if not args.test.is_file() or args.test.is_symlink():
        raise EvaluationError(f"test file is missing or unsafe: {args.test}")
    test_sha256 = sha256_file(args.test)
    if test_sha256 != FROZEN_TEST_SHA256:
        raise EvaluationError(
            f"test SHA-256 drift: {test_sha256} != {FROZEN_TEST_SHA256}"
        )
    if args.test.stat().st_size != FROZEN_TEST_BYTES:
        raise EvaluationError(
            f"test byte-size drift: {args.test.stat().st_size} != {FROZEN_TEST_BYTES}"
        )
    evaluator_sha256 = sha256_file(Path(__file__).resolve())
    rows = load_rows(args.test)
    plan = build_plan(rows, args.label)
    if len(rows) != FROZEN_TASKS:
        raise EvaluationError(f"task count drift: {len(rows)} != {FROZEN_TASKS}")
    if len(plan) != FROZEN_RECORDS:
        raise EvaluationError(f"record count drift: {len(plan)} != {FROZEN_RECORDS}")

    expected_health = arm["health"]
    expected_file_hashes = verify_identity_files(args.expect_file_sha256)
    missing_hashes = arm["required_identity_sha256"] - set(expected_file_hashes.values())
    if missing_hashes:
        raise EvaluationError(
            "frozen arm identity hashes are missing: " + ",".join(sorted(missing_hashes))
        )
    missing_arguments = arm["required_process_arguments"] - set(args.expect_process_arg)
    if missing_arguments:
        raise EvaluationError(
            "frozen arm process arguments are missing: "
            + ",".join(sorted(missing_arguments))
        )
    missing_forbidden = arm["required_forbidden_arguments"] - set(
        args.forbid_process_arg
    )
    if missing_forbidden:
        raise EvaluationError(
            "frozen arm forbidden arguments are missing: "
            + ",".join(sorted(missing_forbidden))
        )
    if args.label == "base" and ADAPTER_SHA256 in expected_file_hashes.values():
        raise EvaluationError("Base arm must not bind the SFT adapter")
    expected_adapter_path: str | None = None
    if args.label == "sft":
        expected_adapter_path = adapter_runtime_path(expected_file_hashes)
        if expected_adapter_path not in args.expect_process_arg:
            raise EvaluationError("SFT adapter path is not bound to the service argv contract")

    protected_paths = {
        args.test.resolve(),
        args.api_key_file.resolve(),
        args.service_pid_file.resolve(),
        *(path.resolve() for path, _expected in args.expect_file_sha256),
    }
    if args.raw_out.resolve() in protected_paths or args.manifest_out.resolve() in protected_paths:
        raise EvaluationError("output path collides with a protected input or secret")

    config = {
        "run_id": args.run_id,
        "label": args.label,
        "base_url": args.base_url.rstrip("/"),
        "request_model": arm["request_model"],
        "expected_response_model": arm["response_model"],
        "expected_system_fingerprint": arm["system_fingerprint"],
        "expected_health": expected_health,
        "expected_file_sha256": dict(sorted(expected_file_hashes.items())),
        "service_pid_file": str(args.service_pid_file),
        "expected_process_arguments": sorted(args.expect_process_arg),
        "forbidden_process_arguments": sorted(args.forbid_process_arg),
        "expected_tasks": FROZEN_TASKS,
        "expected_records": FROZEN_RECORDS,
        "expected_test_sha256": FROZEN_TEST_SHA256,
        "expected_test_bytes": FROZEN_TEST_BYTES,
        "max_tokens": args.max_tokens,
        "temperature": 0,
        "timeout_seconds": args.timeout_seconds,
    }
    contract = {
        "config": config,
        "test_sha256": test_sha256,
        "evaluator_sha256": evaluator_sha256,
        "plan_sha256": canonical_digest(plan),
    }
    contract_sha256 = canonical_digest(contract)
    planned_keys = [item["key"] for item in plan]
    previous_manifest, completed = load_resume_records(
        args.raw_out, args.manifest_out, contract_sha256, planned_keys
    )
    if previous_manifest is not None and previous_manifest.get("status") == "COMPLETE":
        return previous_manifest

    key = read_api_key(args.api_key_file)
    client = JsonHttpClient(config["base_url"], key, args.timeout_seconds)
    initial_health = verify_health(client, expected_health)
    initial_service = verify_service_process(
        args.service_pid_file,
        args.expect_process_arg,
        args.forbid_process_arg,
        expected_adapter_path,
    )
    if previous_manifest is not None:
        if previous_manifest.get("initial_health") != initial_health:
            raise EvaluationError("service health identity changed across resume")
        if previous_manifest.get("initial_service") != initial_service:
            raise EvaluationError("service process identity changed across resume")

    created_raw = False
    if previous_manifest is None:
        try:
            raw_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                raw_flags |= os.O_NOFOLLOW
            raw_descriptor = os.open(args.raw_out, raw_flags, 0o600)
            os.close(raw_descriptor)
            created_raw = True
        except FileExistsError as error:
            raise EvaluationError(f"refusing unexpected raw output: {args.raw_out}") from error

    started_at = (
        previous_manifest.get("started_at_utc") if previous_manifest else utc_now()
    )
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "status": "RUNNING",
        "run_id": args.run_id,
        "label": args.label,
        "training_use": False,
        "api_key_persisted": False,
        "started_at_utc": started_at,
        "updated_at_utc": utc_now(),
        "completed_at_utc": None,
        "contract_sha256": contract_sha256,
        "contract": contract,
        "raw_file": args.raw_out.name,
        "raw_sha256": None,
        "completed_records": len(completed),
        "expected_records": len(plan),
        "last_error": None,
        "initial_health": initial_health,
        "initial_service": initial_service,
    }
    try:
        atomic_write_json(args.manifest_out, manifest)
    except Exception:
        if created_raw and args.raw_out.stat().st_size == 0:
            args.raw_out.unlink()
        raise

    try:
        with args.raw_out.open("a", encoding="utf-8", buffering=1) as output:
            for item in plan:
                if item["key"] in completed:
                    continue
                if STOP_SIGNAL is not None:
                    raise GracefulStop(STOP_SIGNAL)
                verify_health(client, expected_health)
                current_service = verify_service_process(
                    args.service_pid_file,
                    args.expect_process_arg,
                    args.forbid_process_arg,
                    expected_adapter_path,
                )
                if current_service != initial_service:
                    raise EvaluationError("service process identity changed during evaluation")
                row = rows[item["task_index"]]
                messages = row["messages"]
                reference = messages[item["turn_index"]]
                payload = {
                    "model": arm["request_model"],
                    "temperature": 0,
                    "max_tokens": args.max_tokens,
                    "messages": to_openai(messages[: item["turn_index"]]),
                    "tools": row.get("tools") or [],
                }
                started = time.monotonic()
                response = client.request("/v1/chat/completions", payload)
                latency_seconds = round(time.monotonic() - started, 3)
                response_model = response.get("model")
                if response_model != arm["response_model"]:
                    raise EvaluationError(
                        f"response model drift: {response_model!r} != "
                        f"{arm['response_model']!r}"
                    )
                system_fingerprint = response.get("system_fingerprint")
                if system_fingerprint != arm["system_fingerprint"]:
                    raise EvaluationError(
                        f"system fingerprint drift: {system_fingerprint!r} != "
                        f"{arm['system_fingerprint']!r}"
                    )
                choices = response.get("choices")
                if not isinstance(choices, list) or len(choices) != 1:
                    raise EvaluationError("response must contain exactly one choice")
                choice = choices[0]
                response_message = choice.get("message")
                if not isinstance(response_message, dict):
                    raise EvaluationError("response choice has no message object")
                metadata = row.get("metadata") or {}
                reference_calls = normalize_tool_calls(reference.get("tool_calls") or [])
                response_calls = normalize_tool_calls(response_message.get("tool_calls") or [])
                record = {
                    "schema_version": RECORD_SCHEMA,
                    "contract_sha256": contract_sha256,
                    "run_id": args.run_id,
                    "label": args.label,
                    "key": item["key"],
                    "task_index": item["task_index"],
                    "turn_index": item["turn_index"],
                    "task_id": item["task_id"],
                    "stratum": (
                        "promoted"
                        if metadata.get("promoted_from_needs_review") is True
                        else "curated"
                    ),
                    "task_kind": metadata.get("task_kind"),
                    "category": metadata.get("category"),
                    "failed_checks": metadata.get("failed_checks") or [],
                    "latency_seconds": latency_seconds,
                    "reference": {
                        "content": reference.get("content"),
                        "tool_calls": reference_calls,
                    },
                    "response": {
                        "model": response_model,
                        "system_fingerprint": system_fingerprint,
                        "finish_reason": choice.get("finish_reason"),
                        "message": response_message,
                        "tool_calls": response_calls,
                        "usage": response.get("usage"),
                    },
                    "scores": score_turn(
                        reference, response_message, choice.get("finish_reason")
                    ),
                }
                output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
                completed.add(item["key"])
                manifest["completed_records"] = len(completed)
                manifest["updated_at_utc"] = utc_now()
                if len(completed) % 10 == 0 or len(completed) == len(plan):
                    atomic_write_json(args.manifest_out, manifest)
                    print(
                        f"{args.label}: {len(completed)}/{len(plan)} records",
                        file=sys.stderr,
                        flush=True,
                    )

                if STOP_SIGNAL is not None:
                    raise GracefulStop(STOP_SIGNAL)

        final_health = verify_health(client, expected_health)
        final_service = verify_service_process(
            args.service_pid_file,
            args.expect_process_arg,
            args.forbid_process_arg,
            expected_adapter_path,
        )
        if final_service != initial_service:
            raise EvaluationError("service process identity changed before finalization")
        final_file_hashes = verify_identity_files(args.expect_file_sha256)
        if final_file_hashes != expected_file_hashes:
            raise EvaluationError("identity-file set changed before finalization")
        if len(completed) != len(planned_keys):
            raise EvaluationError("evaluation ended with missing records")
        manifest.update(
            {
                "status": "COMPLETE",
                "updated_at_utc": utc_now(),
                "completed_at_utc": utc_now(),
                "completed_records": len(completed),
                "final_health": final_health,
                "final_service": final_service,
                "final_file_sha256": final_file_hashes,
                "raw_sha256": sha256_file(args.raw_out),
                "last_error": None,
            }
        )
        atomic_write_json(args.manifest_out, manifest)
        return manifest
    except GracefulStop as error:
        manifest.update(
            {
                "status": "INTERRUPTED",
                "updated_at_utc": utc_now(),
                "completed_records": len(completed),
                "last_error": str(error),
            }
        )
        atomic_write_json(args.manifest_out, manifest)
        raise
    except KeyboardInterrupt:
        manifest.update(
            {
                "status": "INTERRUPTED",
                "updated_at_utc": utc_now(),
                "completed_records": len(completed),
                "last_error": "KeyboardInterrupt",
            }
        )
        atomic_write_json(args.manifest_out, manifest)
        raise
    except Exception as error:
        manifest.update(
            {
                "status": "FAILED",
                "updated_at_utc": utc_now(),
                "completed_records": len(completed),
                "last_error": f"{type(error).__name__}: {error}"[:500],
            }
        )
        atomic_write_json(args.manifest_out, manifest)
        raise


def main() -> int:
    args = parse_args()
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, request_stop)
    try:
        manifest = run(args)
    except GracefulStop as error:
        print(f"evaluation interrupted by {error}", file=sys.stderr)
        return 128 + error.signum
    except KeyboardInterrupt:
        print("evaluation interrupted", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"evaluation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "label": manifest["label"],
                "completed_records": manifest["completed_records"],
                "raw_sha256": manifest["raw_sha256"],
                "manifest": str(args.manifest_out),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
