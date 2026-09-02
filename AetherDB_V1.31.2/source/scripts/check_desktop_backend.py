"""Smoke-test the dynamic loopback contract used by the Tauri desktop app."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


HOST = "127.0.0.1"
LEGACY_PORT = 8000
REPORTED_CONFLICT_PORT = 1042
ROOT = Path(__file__).resolve().parents[1]


def _expected_version() -> str:
    config_path = ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    version = str(payload.get("version", "")).strip()
    if not version:
        raise RuntimeError(f"Desktop version is missing from {config_path}")
    return version


EXPECTED_VERSION = _expected_version()
_SECRET_REDACTIONS = (
    (re.compile(r"nvk_(?:admin_)?[a-f0-9]{32}", re.IGNORECASE), "[REDACTED_LOCAL_KEY]"),
    (re.compile(r"aether_owner_[a-f0-9]{64}", re.IGNORECASE), "[REDACTED_OWNER_TOKEN]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
)


def _read_handshake(
    port: int,
    token: str,
    expected_build_id: str,
    timeout: float = 1.0,
) -> dict | None:
    request = urllib.request.Request(
        f"http://{HOST}:{port}/.well-known/aetherdb-desktop",
        headers={"X-AetherDB-Desktop-Handshake": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError, urllib.error.HTTPError):
        return None
    if (
        payload.get("product") != "AetherDB"
        or payload.get("service") != "aetherdb-backend"
        or payload.get("version") != EXPECTED_VERSION
        or payload.get("build_id") != expected_build_id
        or payload.get("status") != "ok"
        or payload.get("database_ready") is not True
        or not str(payload.get("instance_id", "")).startswith("aether_runtime_")
        or payload.get("transport") != "dynamic_loopback"
    ):
        return None
    return payload


def _read_auth_status(port: int, token: str, timeout: float = 1.0) -> dict | None:
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/auth/status",
        headers={"X-API-Key": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (OSError, ValueError, urllib.error.HTTPError):
        return None


def _start_backend(
    handshake_token: str,
    owner_token: str,
    startup_descriptor: Path,
    build_id: str,
    executable: Path | None = None,
    resource_root: Path | None = None,
    runtime_root: Path | None = None,
) -> subprocess.Popen:
    environment = os.environ.copy()
    environment.update(
        {
            "AETHERDB_HOST": HOST,
            "AETHERDB_PORT": "0",
            "AETHERDB_STARTUP_DESCRIPTOR": str(startup_descriptor),
            "AETHERDB_BUILD_ID": build_id,
            "AETHERDB_DESKTOP_HANDSHAKE": handshake_token,
            "AETHERDB_DESKTOP_OWNER_TOKEN": owner_token,
            "AETHERDB_DEPLOYMENT_MODE": "local_desktop",
            "WORLDVIEW_CORS": "desktop",
            "AETHERDB_ENV": "test",
            "AETHERDB_EMBEDDING_PROVIDER": "mock",
        }
    )
    if executable is not None:
        if resource_root is None or runtime_root is None:
            raise ValueError("Packaged smoke tests require resource and runtime roots")
        runtime_root.mkdir(parents=True, exist_ok=True)
        environment["AETHERDB_RESOURCE_ROOT"] = str(resource_root)
        environment["AETHERDB_RUNTIME_ROOT"] = str(runtime_root)
        command = [str(executable)]
        working_directory = runtime_root
    else:
        if runtime_root is None:
            raise ValueError("Source smoke tests require an isolated runtime root")
        runtime_root.mkdir(parents=True, exist_ok=True)
        environment["AETHERDB_RESOURCE_ROOT"] = str(ROOT)
        environment["AETHERDB_RUNTIME_ROOT"] = str(runtime_root)
        command = [sys.executable, "main.py"]
        working_directory = ROOT
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=working_directory,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )


def _wait_ready(
    process: subprocess.Popen,
    descriptor_path: Path,
    token: str,
    expected_build_id: str,
    require_exact_pid: bool,
) -> dict:
    started_at = time.monotonic()
    while time.monotonic() - started_at < 45:
        exit_code = process.poll()
        if exit_code is not None:
            stdout, stderr = process.communicate(timeout=1)
            diagnostic = (stdout + "\n" + stderr).strip()[-4000:]
            for pattern, replacement in _SECRET_REDACTIONS:
                diagnostic = pattern.sub(replacement, diagnostic)
            raise RuntimeError(
                f"AetherDB backend exited during startup with code {exit_code}:\n{diagnostic}"
            )
        try:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            descriptor = None
        if descriptor is not None and (
            (require_exact_pid and descriptor.get("pid") != process.pid)
            or descriptor.get("build_id") != expected_build_id
            or descriptor.get("service") != "aetherdb-backend"
            or descriptor.get("protocol_version") != "1.0"
            or not isinstance(descriptor.get("port"), int)
            or descriptor["port"] <= 0
        ):
            raise RuntimeError(
                "AetherDB backend published an invalid startup descriptor: "
                + json.dumps(descriptor, ensure_ascii=True, sort_keys=True)
                + f" expected_pid={process.pid} expected_build_id={expected_build_id}"
            )
        port = descriptor["port"] if descriptor else 0
        identity = (
            _read_handshake(port, token, expected_build_id)
            if port
            else None
        )
        if identity is not None:
            identity["startup_ms"] = int((time.monotonic() - started_at) * 1000)
            identity["port"] = port
            return identity
        time.sleep(0.25)
    raise RuntimeError("AetherDB backend readiness timeout after 45 seconds")


def _stop_backend(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-executable", type=Path)
    parser.add_argument("--resource-root", type=Path)
    parser.add_argument("--runtime-parent", type=Path)
    args = parser.parse_args()
    executable = args.backend_executable.resolve() if args.backend_executable else None
    resource_root = args.resource_root.resolve() if args.resource_root else None
    if executable is not None and not executable.is_file():
        parser.error(f"backend executable is missing: {executable}")
    if executable is not None and (resource_root is None or not resource_root.is_dir()):
        parser.error("--resource-root must identify the packaged backend directory")
    if executable is not None:
        manifest_path = resource_root / "build-manifest.json"
        if not manifest_path.is_file():
            parser.error(f"packaged build manifest is missing: {manifest_path}")
        expected_build_id = str(
            json.loads(manifest_path.read_text(encoding="utf-8")).get("build_id", "")
        ).strip()
    else:
        expected_build_id = f"smoke-{EXPECTED_VERSION}-{secrets.token_hex(6)}"
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,128}", expected_build_id):
        parser.error("packaged build identity is missing or malformed")

    occupied_guards = {}
    for guarded_port in (LEGACY_PORT, REPORTED_CONFLICT_PORT):
        guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            guard.bind((HOST, guarded_port))
            guard.listen(1)
            occupied_guards[guarded_port] = guard
        except OSError:
            guard.close()
            occupied_guards[guarded_port] = None

    with tempfile.TemporaryDirectory(
        prefix="aetherdb-packaged-smoke-",
        dir=args.runtime_parent,
    ) as runtime_parent_value:
        runtime_parent = Path(runtime_parent_value)
        handshake_tokens = (secrets.token_hex(32), secrets.token_hex(32))
        owner_tokens = (
            f"aether_owner_{secrets.token_hex(32)}",
            f"aether_owner_{secrets.token_hex(32)}",
        )
        descriptors = (
            runtime_parent / "instance-1" / "backend-startup-instance-1.json",
            runtime_parent / "instance-2" / "backend-startup-instance-2.json",
        )
        processes = (
            _start_backend(
                handshake_tokens[0],
                owner_tokens[0],
                descriptors[0],
                expected_build_id,
                executable,
                resource_root,
                runtime_parent / "instance-1",
            ),
            _start_backend(
                handshake_tokens[1],
                owner_tokens[1],
                descriptors[1],
                expected_build_id,
                executable,
                resource_root,
                runtime_parent / "instance-2",
            ),
        )
        try:
            identities = (
                _wait_ready(
                    processes[0],
                    descriptors[0],
                    handshake_tokens[0],
                    expected_build_id,
                    executable is not None,
                ),
                _wait_ready(
                    processes[1],
                    descriptors[1],
                    handshake_tokens[1],
                    expected_build_id,
                    executable is not None,
                ),
            )
            ports = (identities[0]["port"], identities[1]["port"])
            if ports[0] == ports[1]:
                raise RuntimeError("independent sidecars reported the same dynamic port")
            if _read_handshake(ports[0], handshake_tokens[1], expected_build_id) is not None:
                raise RuntimeError("first sidecar accepted the second sidecar handshake")
            if _read_handshake(ports[1], handshake_tokens[0], expected_build_id) is not None:
                raise RuntimeError("second sidecar accepted the first sidecar handshake")
            owner_statuses = (
                _read_auth_status(ports[0], owner_tokens[0]),
                _read_auth_status(ports[1], owner_tokens[1]),
            )
            if any(
                status is None
                or status.get("deployment_mode") != "local_desktop"
                or status.get("effective_role") != "owner"
                or "manage_system" not in status.get("capabilities", [])
                for status in owner_statuses
            ):
                raise RuntimeError("desktop owner session did not receive local Owner capabilities")
            foreign_first = _read_auth_status(ports[0], owner_tokens[1])
            foreign_second = _read_auth_status(ports[1], owner_tokens[0])
            if foreign_first is None or foreign_first.get("valid") is not False:
                raise RuntimeError("first sidecar accepted the second sidecar owner token")
            if foreign_second is None or foreign_second.get("valid") is not False:
                raise RuntimeError("second sidecar accepted the first sidecar owner token")
            for index, name in enumerate(("instance-1", "instance-2")):
                instance = runtime_parent / name
                key_file = instance / ".api_keys.json"
                if key_file.is_file() and owner_tokens[index] in key_file.read_text(
                    encoding="utf-8"
                ):
                    raise RuntimeError(f"{name} persisted its desktop owner token")
                if executable is not None:
                    if not (instance / ".api_keys.json").is_file():
                        raise RuntimeError(f"{name} did not create its local API keys")
                    if not (instance / "app_data" / "registry.db").is_file():
                        raise RuntimeError(f"{name} did not create its runtime registry")

            print(f"backend_version={identities[0]['version']}")
            print(f"backend_build_id={expected_build_id}")
            print(f"backend_mode={'packaged' if executable else 'source'}")
            print(f"backend_host={HOST}")
            print(f"backend_dynamic_ports={ports[0]},{ports[1]}")
            print(f"startup_ms={identities[0]['startup_ms']},{identities[1]['startup_ms']}")
            print(
                f"legacy_port_guarded={str(occupied_guards[LEGACY_PORT] is not None).lower()}"
            )
            print(
                "reported_conflict_port_1042_guarded="
                f"{str(occupied_guards[REPORTED_CONFLICT_PORT] is not None).lower()}"
            )
            print("reported_conflict_port_1042_bypassed=true")
            print("multi_instance_isolated=true")
            print("managed_processes=true")
            print("identity_verified=true")
            print("cross_instance_tokens_rejected=true")
            print("owner_capabilities_verified=true")
            print("owner_tokens_ephemeral=true")
            print("runtime_roots_isolated=true")
            return 0
        finally:
            for process in processes:
                _stop_backend(process)
            for guard in occupied_guards.values():
                if guard is not None:
                    guard.close()


if __name__ == "__main__":
    raise SystemExit(main())
