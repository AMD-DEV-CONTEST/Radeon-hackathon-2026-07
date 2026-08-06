"""Fail-closed AetherDB entrypoint for the unprivileged core container."""

from __future__ import annotations

import os
import sys
from pathlib import Path


class ContainerConfigurationError(RuntimeError):
    pass


def _validated_port(environment: dict[str, str]) -> int:
    raw = environment.get("AETHERDB_CONTAINER_PORT", "").strip()
    if not raw:
        raise ContainerConfigurationError("AETHERDB_CONTAINER_PORT is required")
    try:
        port = int(raw)
    except ValueError as exc:
        raise ContainerConfigurationError("AETHERDB_CONTAINER_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ContainerConfigurationError("AETHERDB_CONTAINER_PORT is outside 1..65535")
    if port == 8000:
        raise ContainerConfigurationError("Fixed legacy port 8000 is not allowed")
    return port


def build_command(environment: dict[str, str] | None = None) -> list[str]:
    environment = environment or dict(os.environ)
    port = _validated_port(environment)
    runtime_root = Path(
        environment.get("AETHERDB_RUNTIME_ROOT", "/var/lib/aetherdb")
    ).expanduser()
    if not runtime_root.is_absolute():
        raise ContainerConfigurationError("AETHERDB_RUNTIME_ROOT must be absolute")
    runtime_root.mkdir(parents=True, exist_ok=True)
    if not os.access(runtime_root, os.W_OK):
        raise ContainerConfigurationError("AETHERDB_RUNTIME_ROOT is not writable")
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--workers",
        "1",
        "--no-access-log",
    ]


def main() -> int:
    if os.environ.get("AETHERDB_EXECUTION_MODE", "").strip().lower() == "competition":
        from scripts.verify_rocm import run_competition_probe

        report = run_competition_probe()
        if not report["platform_verified"]:
            raise ContainerConfigurationError(
                "ROCm competition platform verification failed"
            )

    from scripts.init_runtime import main as initialize_runtime_files

    initialize_runtime_files()
    command = build_command()
    os.chdir(os.environ.get("AETHERDB_RUNTIME_ROOT", "/var/lib/aetherdb"))
    os.execv(command[0], command)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
