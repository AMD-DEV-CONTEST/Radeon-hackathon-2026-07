"""Minimal execution backends for the standalone Track 2 agent.

The benchmark runner intentionally exposes only the checked-out task repository
to a container and strips model/provider credentials from local subprocesses.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Any


_SECRET_MARKERS = (
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
)


def make_tool_result_message(name: str, content: Any, tool_call_id: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "name": name,
        "tool_name": name,
        "content": content,
        "tool_call_id": tool_call_id,
    }


def _safe_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SECRET_MARKERS)
    }


class LocalEnvironment:
    def __init__(self, cwd: str, timeout: int = 60, **_: Any) -> None:
        self.cwd = Path(cwd).resolve()
        self.timeout = timeout
        if not self.cwd.is_dir():
            raise ValueError(f"workspace does not exist: {self.cwd}")

    def execute(self, command: str, timeout: int | None = None) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=self.cwd,
                env=_safe_environment(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout or self.timeout,
                check=False,
            )
            return {"output": result.stdout, "returncode": result.returncode}
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return {"output": output, "returncode": 124}

    def cleanup(self) -> None:
        return None


class DockerEnvironment:
    def __init__(
        self,
        image: str,
        cwd: str = "/workspace",
        timeout: int = 60,
        host_cwd: str | None = None,
        network: bool = False,
        run_as_host_user: bool = True,
        **_: Any,
    ) -> None:
        if not host_cwd:
            raise ValueError("Docker benchmarks require host_cwd")
        self.timeout = timeout
        self.name = f"track2-{uuid.uuid4().hex[:12]}"
        host_path = Path(host_cwd).resolve()
        if not host_path.is_dir():
            raise ValueError(f"workspace does not exist: {host_path}")
        command = [
            "docker", "run", "-d", "--rm", "--name", self.name,
            "--mount", f"type=bind,src={host_path},dst=/workspace",
            "--workdir", cwd,
        ]
        if not network:
            command.extend(["--network", "none"])
        if run_as_host_user and hasattr(os, "getuid"):
            command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        command.extend([image, "tail", "-f", "/dev/null"])
        subprocess.run(command, check=True, text=True, capture_output=True)

    def execute(self, command: str, timeout: int | None = None) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["docker", "exec", self.name, "bash", "-lc", command],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout or self.timeout,
                check=False,
            )
            return {"output": result.stdout, "returncode": result.returncode}
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return {"output": output, "returncode": 124}

    def cleanup(self) -> None:
        subprocess.run(
            ["docker", "rm", "-f", self.name],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def create_environment(
    env_type: str = "local",
    image: str = "track2-python-agent:latest",
    cwd: str = "/tmp",
    timeout: int = 60,
    **kwargs: Any,
) -> LocalEnvironment | DockerEnvironment:
    if env_type == "local":
        return LocalEnvironment(cwd=cwd, timeout=timeout, **kwargs)
    if env_type == "docker":
        return DockerEnvironment(image=image, cwd=cwd, timeout=timeout, **kwargs)
    raise ValueError(f"Unknown environment type: {env_type}. Use 'local' or 'docker'.")
