from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import PRIVATE_DIRECTORY_MODE, PRIVATE_FILE_MODE, Settings

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$")
_MODEL_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SOCKET_INODE_RE = re.compile(r"^socket:\[(\d+)]$")
_MANIFEST_FIELDS = frozenset(
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


@dataclass(frozen=True, slots=True)
class RuntimeBindingResult:
    configured: bool
    valid: bool
    manifest_sha256: str | None = None
    error_code: str | None = None

    def public_report(self) -> dict[str, Any]:
        """Expose only the process verdict and opaque manifest digest."""

        return {
            "process_binding_valid": self.valid if self.configured else None,
            "runtime_instance_manifest_sha256": self.manifest_sha256,
        }


def _invalid(
    code: str,
    *,
    configured: bool = True,
    manifest_sha256: str | None = None,
) -> RuntimeBindingResult:
    return RuntimeBindingResult(
        configured=configured,
        valid=False,
        manifest_sha256=manifest_sha256,
        error_code=code,
    )


def _reject_nonstandard_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant: {value}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _observed_model_sha256(
    canonical_path: str,
    device: int,
    inode: int,
    size: int,
    modified_ns: int,
    changed_ns: int,
) -> str:
    """Hash a stable model-file identity once, then reuse the verified digest."""

    # The stat fields are deliberately part of the cache key. Any replacement
    # or in-place mutation forces a fresh multi-GB digest without charging that
    # I/O cost to every model call and distorting the A-H latency comparison.
    del device, inode, size, modified_ns, changed_ns
    return _sha256_file(Path(canonical_path))


def _model_sha256_matches(path: Path, expected_sha256: str) -> bool:
    try:
        resolved = path.resolve(strict=True)
        observed_stat = resolved.stat()
        if not stat.S_ISREG(observed_stat.st_mode) or observed_stat.st_size <= 0:
            return False
        observed_sha256 = _observed_model_sha256(
            str(resolved),
            observed_stat.st_dev,
            observed_stat.st_ino,
            observed_stat.st_size,
            observed_stat.st_mtime_ns,
            observed_stat.st_ctime_ns,
        )
    except (OSError, RuntimeError):
        return False
    return hmac.compare_digest(observed_sha256, expected_sha256)


def _model_port(settings: Settings) -> int | None:
    parsed = urlparse(settings.model_base_url)
    try:
        if parsed.port is not None:
            return parsed.port
    except ValueError:
        return None
    if parsed.scheme == "http":
        return 80
    if parsed.scheme == "https":
        return 443
    return None


def _model_host(settings: Settings) -> str | None:
    parsed = urlparse(settings.model_base_url)
    try:
        return parsed.hostname
    except ValueError:
        return None


def _proc_start_ticks(stat_text: str) -> int | None:
    # /proc/<pid>/stat field two is parenthesized and may contain spaces.
    closing = stat_text.rfind(")")
    if closing < 0:
        return None
    remaining = stat_text[closing + 1 :].strip().split()
    if len(remaining) < 20:
        return None
    try:
        return int(remaining[19])
    except ValueError:
        return None


def _command_value(arguments: list[bytes], flag: bytes) -> bytes | None:
    indices = [index for index, value in enumerate(arguments) if value == flag]
    if len(indices) != 1:
        return None
    index = indices[0]
    if index + 1 >= len(arguments):
        return None
    return arguments[index + 1]


def _command_count(arguments: list[bytes], flag: bytes) -> int:
    return sum(1 for value in arguments if value == flag)


def _effective_service_configuration(
    arguments: list[bytes],
) -> dict[str, int | str] | None:
    integer_flags = {
        "ctx": b"--ctx-size",
        "parallel": b"--parallel",
        "batch": b"--batch-size",
        "ubatch": b"--ubatch-size",
        "gpu_layers": b"--n-gpu-layers",
        "log_verbosity": b"--log-verbosity",
    }
    configuration: dict[str, int | str] = {}
    try:
        for field, flag in integer_flags.items():
            raw = _command_value(arguments, flag)
            if raw is None:
                return None
            text = raw.decode("ascii")
            if not text.isdigit() or int(text) <= 0:
                return None
            configuration[field] = int(text)
        for field, flag, default in (
            ("flash_attn", b"--flash-attn", "off"),
            ("cache_type_k", b"--cache-type-k", "f16"),
            ("cache_type_v", b"--cache-type-v", "f16"),
        ):
            if _command_count(arguments, flag) > 1:
                return None
            raw = _command_value(arguments, flag)
            configuration[field] = raw.decode("ascii") if raw is not None else default
    except (UnicodeError, ValueError):
        return None
    if configuration["flash_attn"] not in {"on", "off"}:
        return None
    if configuration["cache_type_k"] not in {"f16", "q8_0"}:
        return None
    if configuration["cache_type_v"] not in {"f16", "q8_0"}:
        return None
    return configuration


def _service_configuration_sha256(configuration: Mapping[str, int | str]) -> str:
    canonical = json.dumps(
        dict(configuration),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _process_socket_inodes(proc_root: Path) -> set[int]:
    inodes: set[int] = set()
    for descriptor in (proc_root / "fd").iterdir():
        try:
            target = os.readlink(descriptor)
        except (FileNotFoundError, OSError):
            continue
        match = _SOCKET_INODE_RE.fullmatch(target)
        if match is not None:
            inodes.add(int(match.group(1)))
    return inodes


def _listening_socket_inodes(
    proc_root: Path,
    port: int,
    host: str = "127.0.0.1",
) -> set[int]:
    listeners: set[int] = set()
    expected_port = f"{port:04X}"
    expected_addresses = {
        "127.0.0.1": {"tcp": {"0100007F"}},
        "::1": {"tcp6": {"00000000000000000000000001000000"}},
        "localhost": {
            "tcp": {"0100007F"},
            "tcp6": {"00000000000000000000000001000000"},
        },
    }.get(host, {})
    for table_name, allowed_addresses in expected_addresses.items():
        table = proc_root / "net" / table_name
        try:
            lines = table.read_text(encoding="ascii").splitlines()[1:]
        except FileNotFoundError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) <= 9 or fields[3] != "0A":
                continue
            local_address = fields[1]
            address, separator, local_port = local_address.rpartition(":")
            if (
                not separator
                or address.upper() not in allowed_addresses
                or local_port.upper() != expected_port
            ):
                continue
            try:
                listeners.add(int(fields[9]))
            except ValueError:
                continue
    return listeners


def verify_runtime_instance(
    settings: Settings,
    *,
    runtime_proof: Mapping[str, Any] | None = None,
) -> RuntimeBindingResult:
    """Bind the configured endpoint to one live Linux llama-server instance."""

    path = settings.runtime_instance_path
    if path is None:
        return _invalid(
            (
                "manifest_required"
                if settings.runtime_instance_required
                else "not_configured"
            ),
            configured=settings.runtime_instance_required,
        )

    digest: str | None = None
    try:
        parent_stat = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or path.parent.is_symlink()
            or stat.S_IMODE(parent_stat.st_mode) != PRIVATE_DIRECTORY_MODE
            or parent_stat.st_uid != os.geteuid()
        ):
            return _invalid("manifest_directory_not_private")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_flags |= getattr(os, "O_CLOEXEC", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            opened_parent_stat = os.fstat(directory_fd)
            if (
                opened_parent_stat.st_dev != parent_stat.st_dev
                or opened_parent_stat.st_ino != parent_stat.st_ino
            ):
                return _invalid("manifest_directory_changed")
            file_fd = os.open(path.name, file_flags, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
        with os.fdopen(file_fd, "rb") as handle:
            file_stat = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or stat.S_IMODE(file_stat.st_mode) != PRIVATE_FILE_MODE
                or file_stat.st_uid != os.geteuid()
            ):
                return _invalid("manifest_file_not_private")
            if not 1 <= file_stat.st_size <= 32 * 1024:
                return _invalid("manifest_size_invalid")
            raw_bytes = handle.read(32 * 1024 + 1)
        if (
            len(raw_bytes) != file_stat.st_size
            or len(raw_bytes) > 32 * 1024
        ):
            return _invalid("manifest_size_invalid")
        digest = hashlib.sha256(raw_bytes).hexdigest()
        payload = json.loads(
            raw_bytes.decode("utf-8"),
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (FileNotFoundError, OSError):
        return _invalid("manifest_unavailable")
    except (UnicodeError, ValueError):
        return _invalid("manifest_json_invalid", manifest_sha256=digest)

    if not isinstance(payload, dict) or set(payload) != _MANIFEST_FIELDS:
        return _invalid("manifest_schema_invalid", manifest_sha256=digest)
    if payload.get("schema_version") != 2:
        return _invalid("manifest_version_invalid", manifest_sha256=digest)

    run_id = payload.get("run_id")
    pid = payload.get("pid")
    start_ticks = payload.get("linux_start_ticks")
    executable_sha256 = payload.get("executable_sha256")
    command_sha256 = payload.get("command_config_sha256")
    service_configuration_sha256 = payload.get("service_configuration_sha256")
    port = payload.get("port")
    model_alias = payload.get("model_alias")
    model_sha256 = payload.get("model_sha256")
    if (
        not isinstance(run_id, str)
        or _RUN_ID_RE.fullmatch(run_id) is None
        or type(pid) is not int
        or pid <= 1
        or type(start_ticks) is not int
        or start_ticks <= 0
        or not isinstance(executable_sha256, str)
        or _SHA256_RE.fullmatch(executable_sha256) is None
        or not isinstance(command_sha256, str)
        or _SHA256_RE.fullmatch(command_sha256) is None
        or not isinstance(service_configuration_sha256, str)
        or _SHA256_RE.fullmatch(service_configuration_sha256) is None
        or type(port) is not int
        or not 1 <= port <= 65_535
        or not isinstance(model_alias, str)
        or _MODEL_ALIAS_RE.fullmatch(model_alias) is None
        or not isinstance(model_sha256, str)
        or _SHA256_RE.fullmatch(model_sha256) is None
    ):
        return _invalid("manifest_values_invalid", manifest_sha256=digest)

    expected_port = _model_port(settings)
    expected_host = _model_host(settings)
    if (
        (settings.demo_run_id is not None and run_id != settings.demo_run_id)
        or model_alias != settings.model_name
        or expected_host not in {"127.0.0.1", "localhost", "::1"}
        or expected_port is None
        or port != expected_port
    ):
        return _invalid("manifest_config_mismatch", manifest_sha256=digest)

    proof = runtime_proof or {}
    for field, value in (
        ("model_alias", model_alias),
        ("model_sha256", model_sha256),
        ("llama_server_sha256", executable_sha256),
        ("service_configuration_sha256", service_configuration_sha256),
    ):
        expected = proof.get(field)
        if isinstance(expected, str) and expected != value:
            return _invalid("manifest_proof_mismatch", manifest_sha256=digest)

    proc_root = Path("/proc") / str(pid)
    try:
        os.kill(pid, 0)
        observed_start_ticks = _proc_start_ticks(
            (proc_root / "stat").read_text(encoding="utf-8")
        )
        command_bytes = (proc_root / "cmdline").read_bytes()
        observed_executable_sha256 = _sha256_file(proc_root / "exe")
        process_socket_inodes = _process_socket_inodes(proc_root)
        listening_socket_inodes = _listening_socket_inodes(
            proc_root,
            port,
            expected_host,
        )
        final_start_ticks = _proc_start_ticks(
            (proc_root / "stat").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError):
        return _invalid("process_unavailable", manifest_sha256=digest)

    if observed_start_ticks != start_ticks or final_start_ticks != start_ticks:
        return _invalid("process_identity_mismatch", manifest_sha256=digest)
    if hashlib.sha256(command_bytes).hexdigest() != command_sha256:
        return _invalid("process_command_mismatch", manifest_sha256=digest)
    if observed_executable_sha256 != executable_sha256:
        return _invalid("process_executable_mismatch", manifest_sha256=digest)

    arguments = [item for item in command_bytes.split(b"\0") if item]
    effective_service_configuration = _effective_service_configuration(arguments)
    if (
        effective_service_configuration is None
        or not hmac.compare_digest(
            _service_configuration_sha256(effective_service_configuration),
            service_configuration_sha256,
        )
    ):
        return _invalid(
            "process_service_configuration_mismatch",
            manifest_sha256=digest,
        )
    model_argument = _command_value(arguments, b"--model")
    if (
        _command_value(arguments, b"--alias") != model_alias.encode("utf-8")
        or _command_value(arguments, b"--port") != str(port).encode("ascii")
        or _command_value(arguments, b"--host") != expected_host.encode("ascii")
        or model_argument is None
    ):
        return _invalid("process_arguments_mismatch", manifest_sha256=digest)
    model_path = Path(os.fsdecode(model_argument))
    if not model_path.is_absolute():
        return _invalid("process_model_path_invalid", manifest_sha256=digest)
    if not _model_sha256_matches(model_path, model_sha256):
        return _invalid("process_model_mismatch", manifest_sha256=digest)
    if not process_socket_inodes.intersection(listening_socket_inodes):
        return _invalid("process_listener_mismatch", manifest_sha256=digest)
    return RuntimeBindingResult(
        configured=True,
        valid=True,
        manifest_sha256=digest,
    )
