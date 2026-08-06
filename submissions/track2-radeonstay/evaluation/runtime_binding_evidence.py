#!/usr/bin/env python3
"""Validate one live llama-server instance and its per-call evidence binding."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import stat
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$")
MODEL_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "pid",
        "linux_start_ticks",
        "executable_sha256",
        "command_config_sha256",
        "service_configuration_sha256",
        "port",
        "model_alias",
        "model_sha256",
    }
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _reject_nonstandard_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant is forbidden: {value}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeInstanceEvidence:
    path: Path
    manifest_sha256: str
    payload: dict[str, Any]

    @property
    def run_id(self) -> str:
        return str(self.payload["run_id"])

    @property
    def pid(self) -> int:
        return int(self.payload["pid"])

    @property
    def port(self) -> int:
        return int(self.payload["port"])


def load_runtime_instance(
    path: Path | None,
    *,
    expected_run_id: str | None = None,
    expected_sha256: str | None = None,
) -> RuntimeInstanceEvidence:
    """Load the private schema-v2 manifest without trusting substring matches."""

    if path is None:
        raise ValueError("A runtime-instance manifest is required for formal evidence")
    resolved = path.expanduser().resolve()
    if path.is_symlink() or not resolved.is_file():
        raise ValueError("Runtime-instance manifest must be a regular non-symlink file")
    file_stat = resolved.stat()
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ValueError("Runtime-instance manifest must have mode 0600")
    if file_stat.st_uid != os.geteuid():
        raise ValueError("Runtime-instance manifest must be owned by the current user")
    if not 1 <= file_stat.st_size <= 32 * 1024:
        raise ValueError("Runtime-instance manifest has an invalid size")
    raw_bytes = resolved.read_bytes()
    if len(raw_bytes) != file_stat.st_size:
        raise ValueError("Runtime-instance manifest changed while it was read")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Runtime-instance manifest SHA256 does not match evidence")
    try:
        payload = json.loads(
            raw_bytes.decode("utf-8"),
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Runtime-instance manifest is not strict UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != MANIFEST_FIELDS:
        raise ValueError("Runtime-instance manifest fields do not match schema v2")
    if payload.get("schema_version") != 2:
        raise ValueError("Runtime-instance manifest schema_version must be 2")

    run_id = payload.get("run_id")
    pid = payload.get("pid")
    start_ticks = payload.get("linux_start_ticks")
    port = payload.get("port")
    alias = payload.get("model_alias")
    if not isinstance(run_id, str) or RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("Runtime-instance run_id is invalid")
    if expected_run_id is not None and run_id != expected_run_id:
        raise ValueError("Runtime-instance run_id does not match the evidence run")
    if type(pid) is not int or pid <= 1:
        raise ValueError("Runtime-instance PID is invalid")
    if type(start_ticks) is not int or start_ticks <= 0:
        raise ValueError("Runtime-instance Linux start ticks are invalid")
    if type(port) is not int or not 1 <= port <= 65_535:
        raise ValueError("Runtime-instance port is invalid")
    if not isinstance(alias, str) or MODEL_ALIAS_RE.fullmatch(alias) is None:
        raise ValueError("Runtime-instance model alias is invalid")
    for field in (
        "executable_sha256",
        "command_config_sha256",
        "service_configuration_sha256",
        "model_sha256",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"Runtime-instance {field} is invalid")
    return RuntimeInstanceEvidence(
        path=resolved,
        manifest_sha256=digest,
        payload=dict(payload),
    )


def _proc_start_ticks(stat_text: str) -> int:
    closing = stat_text.rfind(")")
    fields = stat_text[closing + 1 :].strip().split() if closing >= 0 else []
    if len(fields) < 20:
        raise ValueError("Process stat does not contain Linux start ticks")
    return int(fields[19])


def _command_value(arguments: Sequence[bytes], flag: bytes) -> bytes | None:
    indices = [index for index, value in enumerate(arguments) if value == flag]
    if len(indices) != 1:
        return None
    index = indices[0]
    return arguments[index + 1] if index + 1 < len(arguments) else None


def _command_count(arguments: Sequence[bytes], flag: bytes) -> int:
    return sum(1 for value in arguments if value == flag)


def _effective_service_configuration(
    arguments: Sequence[bytes],
) -> dict[str, int | str]:
    integer_flags = {
        "ctx": b"--ctx-size",
        "parallel": b"--parallel",
        "batch": b"--batch-size",
        "ubatch": b"--ubatch-size",
        "gpu_layers": b"--n-gpu-layers",
        "log_verbosity": b"--log-verbosity",
    }
    configuration: dict[str, int | str] = {}
    for field, flag in integer_flags.items():
        raw = _command_value(arguments, flag)
        if raw is None:
            raise ValueError(f"Runtime-instance process lacks {flag.decode('ascii')}")
        try:
            text = raw.decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Runtime-instance service integer is not ASCII") from exc
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Runtime-instance service integer is invalid")
        configuration[field] = int(text)
    for field, flag, default in (
        ("flash_attn", b"--flash-attn", "off"),
        ("cache_type_k", b"--cache-type-k", "f16"),
        ("cache_type_v", b"--cache-type-v", "f16"),
    ):
        if _command_count(arguments, flag) > 1:
            raise ValueError("Runtime-instance service option is duplicated")
        raw = _command_value(arguments, flag)
        try:
            configuration[field] = raw.decode("ascii") if raw is not None else default
        except UnicodeError as exc:
            raise ValueError("Runtime-instance service option is not ASCII") from exc
    if configuration["flash_attn"] not in {"on", "off"}:
        raise ValueError("Runtime-instance flash attention option is invalid")
    for field in ("cache_type_k", "cache_type_v"):
        if configuration[field] not in {"f16", "q8_0"}:
            raise ValueError("Runtime-instance cache type is invalid")
    return configuration


def _service_configuration_sha256(configuration: Mapping[str, int | str]) -> str:
    canonical = json.dumps(
        dict(configuration),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _proc_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if isinstance(address, ipaddress.IPv4Address):
        return address.packed[::-1].hex().upper()
    packed = address.packed
    return "".join(
        packed[index : index + 4][::-1].hex().upper()
        for index in range(0, len(packed), 4)
    )


def _expected_proc_addresses(host: str) -> set[tuple[Path, str]]:
    proc_root = Path("/proc/net")
    if host == "127.0.0.1":
        return {(proc_root / "tcp", _proc_address(ipaddress.ip_address(host)))}
    if host == "::1":
        return {(proc_root / "tcp6", _proc_address(ipaddress.ip_address(host)))}
    if host == "localhost":
        return {
            (proc_root / "tcp", _proc_address(ipaddress.ip_address("127.0.0.1"))),
            (proc_root / "tcp6", _proc_address(ipaddress.ip_address("::1"))),
        }
    raise ValueError("Formal runtime listener must use a real loopback host")


def _pid_socket_inodes(pid: int) -> set[str]:
    inodes: set[str] = set()
    for descriptor in (Path("/proc") / str(pid) / "fd").iterdir():
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        match = re.fullmatch(r"socket:\[([1-9][0-9]*)\]", target)
        if match is not None:
            inodes.add(match.group(1))
    return inodes


def _listening_socket_inodes(host: str, port: int) -> set[str]:
    expected_port = f"{port:04X}"
    matches: set[str] = set()
    for table_path, expected_address in _expected_proc_addresses(host):
        try:
            lines = table_path.read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            try:
                local_address, local_port = fields[1].split(":", 1)
            except ValueError:
                continue
            if local_address == expected_address and local_port.upper() == expected_port:
                inode = fields[9]
                if inode.isdigit() and int(inode) > 0:
                    matches.add(inode)
    return matches


def verify_live_listener(instance: RuntimeInstanceEvidence) -> dict[str, Any]:
    """Prove the manifest PID owns the declared loopback LISTEN socket."""

    proc_root = Path("/proc") / str(instance.pid)
    try:
        os.kill(instance.pid, 0)
        stat_text = (proc_root / "stat").read_text(encoding="utf-8")
        command_bytes = (proc_root / "cmdline").read_bytes()
        executable_sha256 = file_sha256(proc_root / "exe")
    except OSError as exc:
        raise ValueError("Runtime-instance process is unavailable") from exc
    if _proc_start_ticks(stat_text) != instance.payload["linux_start_ticks"]:
        raise ValueError("Runtime-instance process start ticks changed")
    if hashlib.sha256(command_bytes).hexdigest() != instance.payload[
        "command_config_sha256"
    ]:
        raise ValueError("Runtime-instance process command changed")
    if executable_sha256 != instance.payload["executable_sha256"]:
        raise ValueError("Runtime-instance executable changed")

    arguments = [item for item in command_bytes.split(b"\0") if item]
    effective_service_configuration = _effective_service_configuration(arguments)
    if _service_configuration_sha256(effective_service_configuration) != instance.payload[
        "service_configuration_sha256"
    ]:
        raise ValueError(
            "Runtime-instance process service configuration differs from the manifest"
        )
    expected_alias = str(instance.payload["model_alias"]).encode("utf-8")
    expected_port = str(instance.port).encode("ascii")
    host_bytes = _command_value(arguments, b"--host")
    if (
        _command_value(arguments, b"--alias") != expected_alias
        or _command_value(arguments, b"--port") != expected_port
        or _command_value(arguments, b"--model") is None
        or host_bytes is None
    ):
        raise ValueError("Runtime-instance process arguments do not match the manifest")
    try:
        host = host_bytes.decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Runtime-instance host argument is invalid") from exc
    if host not in LOOPBACK_HOSTS:
        raise ValueError("Runtime-instance listener is not loopback-only")
    owned_inodes = _pid_socket_inodes(instance.pid)
    listener_inodes = _listening_socket_inodes(host, instance.port)
    matching_inodes = owned_inodes & listener_inodes
    if not matching_inodes:
        raise ValueError(
            "Runtime-instance PID does not own the declared loopback LISTEN socket"
        )
    return {
        "process_binding_valid": True,
        "listen_socket_binding_valid": True,
        "runtime_instance_manifest_sha256": instance.manifest_sha256,
        "listener_host": host,
        "listener_port": instance.port,
    }


def wait_for_live_listener(
    instance: RuntimeInstanceEvidence,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.1,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Listener timeout must be positive and finite")
    deadline = time.monotonic() + timeout_seconds
    last_error: ValueError | None = None
    while time.monotonic() < deadline:
        try:
            return verify_live_listener(instance)
        except ValueError as exc:
            last_error = exc
        time.sleep(poll_seconds)
    raise ValueError(
        f"Timed out waiting for the bound loopback listener: {last_error}"
    )


def validate_model_call_bindings(
    model_calls: Iterable[Mapping[str, Any]],
    *,
    expected_manifest_sha256: str,
    label: str,
) -> dict[str, Any]:
    calls = list(model_calls)
    if not calls:
        raise ValueError(f"{label} contains no model calls to bind")
    invalid = [
        index
        for index, call in enumerate(calls)
        if call.get("process_binding_valid") is not True
        or call.get("runtime_instance_manifest_sha256")
        != expected_manifest_sha256
    ]
    if invalid:
        raise ValueError(
            f"{label} model calls are not bound to one runtime manifest: {invalid[:8]}"
        )
    observed = {
        str(call.get("runtime_instance_manifest_sha256")) for call in calls
    }
    if observed != {expected_manifest_sha256}:
        raise ValueError(f"{label} contains mixed runtime manifest digests")
    return {
        "runtime_instance_manifest_sha256": expected_manifest_sha256,
        "process_binding_valid_for_all_model_calls": True,
        "bound_model_call_count": len(calls),
    }


def quality_model_calls(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    calls: list[Mapping[str, Any]] = []
    for case in report.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        for trace in case.get("trace", []):
            if not isinstance(trace, Mapping):
                continue
            response = trace.get("response")
            if not isinstance(response, Mapping):
                continue
            raw_calls = response.get("model_calls", [])
            if not isinstance(raw_calls, list):
                raise ValueError("Quality/stress trace contains invalid model_calls")
            if not all(isinstance(call, Mapping) for call in raw_calls):
                raise ValueError("Quality/stress trace contains invalid model-call rows")
            calls.extend(raw_calls)
    return calls


def benchmark_model_calls(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    calls: list[Mapping[str, Any]] = []
    for run in report.get("runs", []):
        if not isinstance(run, Mapping):
            continue
        for request in run.get("requests", []):
            if not isinstance(request, Mapping) or request.get("ok") is not True:
                continue
            raw_calls = request.get("model_calls", [])
            if not isinstance(raw_calls, list):
                raise ValueError("Benchmark request contains invalid model_calls")
            if not all(isinstance(call, Mapping) for call in raw_calls):
                raise ValueError("Benchmark request contains invalid model-call rows")
            calls.extend(raw_calls)
    return calls


def validate_report_runtime_binding(
    report: Mapping[str, Any],
    *,
    expected_manifest_sha256: str,
    report_kind: str,
    label: str,
) -> dict[str, Any]:
    declared = report.get("runtime_instance")
    if not isinstance(declared, Mapping):
        raise ValueError(f"{label} is missing runtime_instance evidence")
    calls = (
        benchmark_model_calls(report)
        if report_kind == "benchmark"
        else quality_model_calls(report)
    )
    evidence = validate_model_call_bindings(
        calls,
        expected_manifest_sha256=expected_manifest_sha256,
        label=label,
    )
    expected = {
        "manifest_sha256": expected_manifest_sha256,
        "process_binding_valid_for_all_model_calls": True,
        "bound_model_call_count": evidence["bound_model_call_count"],
    }
    if dict(declared) != expected:
        raise ValueError(f"{label} runtime_instance summary does not match raw calls")
    return expected


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--verify-listener", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    instance = load_runtime_instance(
        args.manifest,
        expected_run_id=args.run_id,
        expected_sha256=args.expected_sha256,
    )
    report: dict[str, Any] = {
        "runtime_instance_manifest_sha256": instance.manifest_sha256,
        "manifest_schema_valid": True,
    }
    if args.verify_listener:
        report.update(
            wait_for_live_listener(
                instance,
                timeout_seconds=args.timeout_seconds or 1.0,
            )
        )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
