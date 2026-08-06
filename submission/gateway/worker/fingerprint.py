from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


DEFAULT_COMMANDS = (
    "git",
    "python",
    "python3",
    "node",
    "npm",
    "pnpm",
    "pytest",
)


def detect_os() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "darwin"
    return "unknown"


def detect_shell() -> str | None:
    if os.environ.get("PSModulePath") and os.environ.get("ComSpec"):
        return "powershell"
    shell = os.environ.get("SHELL")
    if shell:
        return Path(shell).name
    comspec = os.environ.get("ComSpec")
    if comspec:
        return Path(comspec).name
    return None


def available_commands(candidates: tuple[str, ...] = DEFAULT_COMMANDS) -> list[str]:
    return [command for command in candidates if shutil.which(command)]


def collect_fingerprint(workspace_root: str | os.PathLike[str]) -> dict[str, Any]:
    return {
        "os": detect_os(),
        "shell": detect_shell(),
        "python_version": sys.version.split()[0],
        "available_commands": available_commands(),
        "workspace_root": str(Path(workspace_root).resolve()),
    }
