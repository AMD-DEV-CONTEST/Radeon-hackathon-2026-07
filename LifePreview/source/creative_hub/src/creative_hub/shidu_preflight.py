from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener

from pydantic import BaseModel, Field


class PreflightCheck(BaseModel):
    status: Literal["available", "unavailable"]
    detail: str = Field(max_length=512)
    error_code: str | None = None


class PreflightResult(BaseModel):
    ready: bool
    runtime_root: str
    checks: dict[str, PreflightCheck]
    created_at: datetime


def _available(detail: str) -> PreflightCheck:
    return PreflightCheck(status="available", detail=detail)


def _unavailable(error_code: str, detail: str) -> PreflightCheck:
    return PreflightCheck(
        status="unavailable",
        detail=detail,
        error_code=error_code,
    )


def _artifact_root_check(runtime_root: Path) -> PreflightCheck:
    normalized = runtime_root.resolve(strict=False).as_posix().rstrip("/").casefold()
    legacy = "f:/douyi_mcp"
    if normalized == legacy or normalized.startswith(f"{legacy}/"):
        return _unavailable(
            "legacy_runtime_root",
            "The retired runtime root is not allowed.",
        )
    if not runtime_root.is_absolute():
        return _unavailable(
            "runtime_root_not_absolute",
            "The runtime root must be an absolute path.",
        )
    if runtime_root.is_symlink():
        return _unavailable(
            "runtime_root_symlink",
            "The runtime root must not be a symbolic link.",
        )
    if not runtime_root.exists():
        return _unavailable(
            "runtime_root_missing",
            "The configured runtime root does not exist.",
        )
    if not runtime_root.is_dir():
        return _unavailable(
            "runtime_root_not_directory",
            "The configured runtime root is not a directory.",
        )
    if not os.access(runtime_root, os.R_OK | os.W_OK):
        return _unavailable(
            "runtime_root_unusable",
            "The configured runtime root is not readable and writable.",
        )
    return _available("The configured runtime root is accessible.")


def _command_check(command: str, arguments: list[str], error_prefix: str) -> PreflightCheck:
    executable = shutil.which(command)
    if executable is None:
        return _unavailable(f"{error_prefix}_missing", f"{command} is not installed.")
    try:
        completed = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
    except (OSError, subprocess.SubprocessError):
        return _unavailable(
            f"{error_prefix}_unavailable",
            f"{command} could not be queried.",
        )
    if completed.returncode != 0:
        return _unavailable(
            f"{error_prefix}_unavailable",
            f"{command} returned a failing status.",
        )
    first_line = next(
        (
            line.strip()
            for line in (completed.stdout or completed.stderr).splitlines()
            if line.strip()
        ),
        f"{command} is available.",
    )
    return _available(first_line[:512])


def _nvidia_gpu_check() -> PreflightCheck:
    result = _command_check(
        "nvidia-smi",
        ["--query-gpu=name,driver_version", "--format=csv,noheader"],
        "gpu_nvidia",
    )
    if result.status == "available":
        return _available(f"NVIDIA: {result.detail}"[:512])
    return result


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def _bounded_command_output(
    executable: str,
    arguments: list[str],
    *,
    timeout_seconds: float,
    maximum_output_bytes: int,
) -> tuple[int, str] | None:
    if timeout_seconds <= 0 or maximum_output_bytes <= 0:
        return None
    try:
        process = subprocess.Popen(
            [executable, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
    except OSError:
        return None
    if process.stdout is None:
        _terminate_process(process)
        return None

    output = bytearray()
    output_exceeded = threading.Event()
    read_failed = threading.Event()

    def read_output() -> None:
        try:
            while True:
                remaining = maximum_output_bytes + 1 - len(output)
                if remaining <= 0:
                    output_exceeded.set()
                    return
                chunk = process.stdout.read(min(8192, remaining))
                if not chunk:
                    return
                output.extend(chunk)
                if len(output) > maximum_output_bytes:
                    output_exceeded.set()
                    return
        except OSError:
            read_failed.set()

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + timeout_seconds
        while True:
            if output_exceeded.is_set() or read_failed.is_set():
                return None
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                return None
            try:
                process.wait(timeout=min(0.1, remaining_seconds))
                break
            except subprocess.TimeoutExpired:
                continue
            except OSError:
                return None
        reader.join(timeout=1)
        if (
            reader.is_alive()
            or output_exceeded.is_set()
            or read_failed.is_set()
        ):
            return None
        return process.returncode, bytes(output).decode(
            "utf-8", errors="replace"
        )
    finally:
        try:
            _terminate_process(process)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            process.stdout.close()
        except OSError:
            pass
        reader.join(timeout=1)


_ROCMINFO_AGENT = re.compile(r"^\s*Agent\s+\d+\s*$", re.IGNORECASE)
_ROCMINFO_FIELD = re.compile(r"^\s*([^:]+):\s*(.*?)\s*$")
_ROCMINFO_GFX_NAME = re.compile(r"gfx[0-9][0-9a-z._:+-]{0,63}")


def _parse_rocminfo_gpu_name(output: str) -> str | None:
    blocks: list[list[str]] = []
    active: list[str] | None = None
    for line in output.splitlines():
        if _ROCMINFO_AGENT.fullmatch(line):
            if active is not None:
                blocks.append(active)
            active = []
        elif active is not None:
            active.append(line)
    if active is not None:
        blocks.append(active)

    for block in blocks:
        names: list[str] = []
        device_types: list[str] = []
        for line in block:
            match = _ROCMINFO_FIELD.fullmatch(line)
            if match is None:
                continue
            key, value = match.groups()
            if key.strip().casefold() == "name":
                names.append(value.strip().casefold())
            elif key.strip().casefold() == "device type":
                device_types.append(value.strip().casefold())
        if "gpu" not in device_types:
            continue
        for name in names:
            if _ROCMINFO_GFX_NAME.fullmatch(name):
                return name
    return None


def _rocminfo_gpu_check() -> PreflightCheck:
    executable = shutil.which("rocminfo")
    if executable is None:
        return _unavailable(
            "gpu_rocminfo_missing",
            "rocminfo is not installed.",
        )
    completed = _bounded_command_output(
        executable,
        [],
        timeout_seconds=10,
        maximum_output_bytes=65_536,
    )
    if completed is None or completed[0] != 0:
        return _unavailable(
            "gpu_rocminfo_unavailable",
            "rocminfo could not be queried safely.",
        )
    gpu_name = _parse_rocminfo_gpu_name(completed[1])
    if gpu_name is None:
        return _unavailable(
            "gpu_rocminfo_unavailable",
            "rocminfo did not report a supported GPU agent.",
        )
    return _available(f"ROCm: {gpu_name}")


def _rocm_gpu_check() -> PreflightCheck:
    result = _command_check(
        "rocm-smi",
        ["--showproductname", "--showdriverversion"],
        "gpu_rocm_smi",
    )
    if result.status == "available":
        return _available(f"ROCm: {result.detail}"[:512])
    fallback = _rocminfo_gpu_check()
    if fallback.status == "available":
        return fallback
    return _unavailable(
        "gpu_rocm_unavailable",
        "ROCm GPU tools are unavailable.",
    )


def _gpu_check() -> PreflightCheck:
    backend = os.getenv("SHIDU_GPU_BACKEND", "auto").casefold()
    if backend not in {"auto", "nvidia", "rocm"}:
        return _unavailable(
            "gpu_backend_invalid",
            "SHIDU_GPU_BACKEND must be auto, nvidia, or rocm.",
        )
    if backend == "nvidia":
        return _nvidia_gpu_check()
    if backend == "rocm":
        return _rocm_gpu_check()

    nvidia = _nvidia_gpu_check()
    if nvidia.status == "available":
        return nvidia
    rocm = _rocm_gpu_check()
    if rocm.status == "available":
        return rocm
    return _unavailable(
        "gpu_unavailable",
        "No supported NVIDIA or AMD ROCm GPU was detected.",
    )


def _configured_service_check(
    *,
    environment_names: tuple[str, ...],
    service_label: str,
    live: bool,
) -> PreflightCheck:
    configured = any(os.getenv(name) for name in environment_names)
    if not configured:
        return _unavailable(
            f"{service_label}_not_configured",
            f"{service_label} connection is not configured.",
        )
    if not live:
        return _unavailable(
            f"{service_label}_live_check_disabled",
            f"{service_label} is configured but has not been verified live.",
        )
    return _unavailable(
        f"{service_label}_discovery_pending",
        f"{service_label} discovery is not yet verified.",
    )


def _load_json_url(url: str, timeout_seconds: float = 5.0) -> dict[str, object]:
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > 65_536:
                raise ValueError
            raw = response.read(65_537)
    except (HTTPError, URLError, OSError, TypeError, ValueError):
        raise RuntimeError("service discovery failed") from None
    if len(raw) > 65_536:
        raise RuntimeError("service discovery failed")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise RuntimeError("service discovery failed") from None
    if not isinstance(payload, dict):
        raise RuntimeError("service discovery failed")
    return payload


def _discovery_url(endpoint: str, path: str) -> str:
    if not isinstance(endpoint, str) or any(
        character.isspace() or ord(character) < 32 for character in endpoint
    ):
        raise ValueError
    try:
        parts = urlsplit(endpoint)
        _ = parts.port
    except ValueError:
        raise ValueError from None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/", "/invoke", "/mcp"}
    ):
        raise ValueError
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _postgres_live_check() -> tuple[bool, str]:
    url = os.getenv("SHIDU_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        return False, "PostgreSQL connection is not configured."
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as connection:
                ready = connection.execute(text("SELECT 1")).scalar_one() == 1
        finally:
            engine.dispose()
    except Exception:
        return False, "PostgreSQL round trip failed."
    if not ready:
        return False, "PostgreSQL round trip failed."
    return True, "PostgreSQL round trip succeeded."


def _postgres_check(*, live: bool) -> PreflightCheck:
    configured = bool(
        os.getenv("SHIDU_DATABASE_URL") or os.getenv("DATABASE_URL")
    )
    if not configured:
        return _unavailable(
            "postgres_not_configured",
            "PostgreSQL connection is not configured.",
        )
    if not live:
        return _unavailable(
            "postgres_live_check_disabled",
            "PostgreSQL is configured but has not been verified live.",
        )
    ready, detail = _postgres_live_check()
    if not ready:
        return _unavailable("postgres_unavailable", detail)
    return _available(detail)


def _mcp_discovery_check(
    *,
    environment_name: str,
    service_label: str,
    live: bool,
    discovery_path: str,
    expected_tool: str,
    expected_schema: str,
) -> PreflightCheck:
    endpoint = os.getenv(environment_name, "").strip()
    if not endpoint:
        return _unavailable(
            f"{service_label}_not_configured",
            f"{service_label} connection is not configured.",
        )
    if not live:
        return _unavailable(
            f"{service_label}_live_check_disabled",
            f"{service_label} is configured but has not been verified live.",
        )
    try:
        payload = _load_json_url(
            _discovery_url(endpoint, discovery_path)
        )
    except (RuntimeError, ValueError):
        return _unavailable(
            f"{service_label}_unavailable",
            f"{service_label} discovery failed.",
        )
    if (
        not isinstance(payload.get("service_version"), str)
        or not str(payload["service_version"]).strip()
        or payload.get("tool_name") != expected_tool
        or payload.get("schema_digest") != expected_schema
    ):
        return _unavailable(
            f"{service_label}_contract_mismatch",
            f"{service_label} discovery contract did not match.",
        )
    if service_label == "reader_mcp" and payload.get(
        "security_capabilities"
    ) != {
        "address_binding": "caller-pinned-ip-v1",
        "redirect_handling": "forbidden",
        "prefetch_validation": "required",
    }:
        return _unavailable(
            "reader_mcp_security_mismatch",
            "reader_mcp security contract did not match.",
        )
    if service_label == "tts_mcp":
        speakers = payload.get("speakers")
        if (
            payload.get("model_id")
            != "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
            or not isinstance(speakers, list)
            or not {"Serena", "Uncle_Fu"}.issubset(speakers)
        ):
            return _unavailable(
                "tts_mcp_capability_mismatch",
                "tts_mcp capability contract did not match.",
            )
    return _available(f"{service_label} discovery contract matched.")


def run_preflight(*, runtime_root: Path, live: bool = False) -> PreflightResult:
    runtime_root = Path(runtime_root)
    checks = {
        "postgres": _postgres_check(live=live),
        "ffmpeg": _command_check("ffmpeg", ["-version"], "ffmpeg"),
        "gpu": _gpu_check(),
        "artifact_root": _artifact_root_check(runtime_root),
        "search_mcp": _mcp_discovery_check(
            environment_name="SHIDU_SEARCH_MCP_ENDPOINT",
            service_label="search_mcp",
            live=live,
            discovery_path="/discover",
            expected_tool="coding_plan.search",
            expected_schema=(
                "6f5b772b2612821f6290ec65f784bc6b8fd9ce6fd3e6c80164cbb5eca2c54c8f"
            ),
        ),
        "reader_mcp": _mcp_discovery_check(
            environment_name="SHIDU_READER_MCP_ENDPOINT",
            service_label="reader_mcp",
            live=live,
            discovery_path="/discover",
            expected_tool="coding_plan.read_page",
            expected_schema=(
                "e498bbc04216f04c3c991ed99dbd14eb16a161d4f33c3d97ff34cf943f313e13"
            ),
        ),
        "tts_mcp": _mcp_discovery_check(
            environment_name="SHIDU_TTS_MCP_ENDPOINT",
            service_label="tts_mcp",
            live=live,
            discovery_path="/phase2/discover",
            expected_tool="qwen_tts.custom_voice",
            expected_schema=(
                "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
            ),
        ),
    }
    return PreflightResult(
        ready=all(check.status == "available" for check in checks.values()),
        runtime_root=runtime_root.resolve(strict=False).as_posix(),
        checks=checks,
        created_at=datetime.now(timezone.utc),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fail-closed Shidu preflight.")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    arguments = parser.parse_args(argv)

    result = run_preflight(runtime_root=arguments.runtime_root, live=arguments.live)
    arguments.report_path.parent.mkdir(parents=True, exist_ok=True)
    arguments.report_path.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
