"""
THEMIS Docker Sandbox Runner
Executes static analysis tools in isolated containers with strict resource limits.
No network, read-only mounts, memory capped at 512MB, 30s hard timeout.
"""

import docker
import tempfile
import os
from typing import Optional
from docker.errors import DockerException, ContainerError, ImageNotFound

from backend.config import get_settings

settings = get_settings()

# Tool images (pinned versions for reproducibility)
SEMGREP_IMAGE = "returntocorp/semgrep:1.90.0"
BANDIT_IMAGE = "pycqa/bandit:latest"
PYLINT_IMAGE = "python:3.11-slim"
ESLINT_IMAGE = "node:20-alpine"


def _get_docker_client() -> Optional[docker.DockerClient]:
    """Return Docker client, or None if Docker isn't available."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception:
        return None


def run_sandboxed(
    image: str,
    command: str,
    code_path: str,
    timeout: Optional[int] = None,
) -> dict:
    """
    Run any analysis command in an isolated Docker container.

    Security guarantees:
    - No network access (network_mode='none')
    - Read-only filesystem
    - Memory limited to 512MB
    - CPU limited to 0.5 cores
    - Hard timeout (default 30s)
    - Container auto-removed after run

    Args:
        image: Docker image to use
        command: Shell command to run inside the container
        code_path: Local path to mount as /code (read-only)
        timeout: Override default timeout in seconds

    Returns:
        {"stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
    """
    client = _get_docker_client()
    if client is None:
        return {"stdout": "", "stderr": "Docker unavailable — skipping static container scan", "exit_code": -1, "timed_out": False}
    timeout = timeout or settings.sandbox_timeout
    result = {"stdout": "", "stderr": "", "exit_code": -1, "timed_out": False}

    try:
        container = client.containers.run(
            image=image,
            command=command,
            volumes={os.path.abspath(code_path): {"bind": "/code", "mode": "ro"}},
            network_mode=settings.sandbox_network,
            mem_limit=settings.sandbox_mem_limit,
            cpu_quota=settings.sandbox_cpu_quota,
            remove=True,
            read_only=True,
            tmpfs={"/tmp": "size=64m,exec"},  # Writable /tmp for tools that need it
            stdout=True,
            stderr=True,
            detach=False,
            timeout=timeout,
        )
        result["stdout"] = container.decode("utf-8") if isinstance(container, bytes) else str(container)
        result["exit_code"] = 0

    except ContainerError as e:
        result["stderr"] = e.stderr.decode("utf-8") if e.stderr else str(e)
        result["stdout"] = e.stdout.decode("utf-8") if e.stdout else ""
        result["exit_code"] = e.exit_status

    except Exception as e:
        if "timeout" in str(e).lower():
            result["timed_out"] = True
            result["stderr"] = f"Container timed out after {timeout}s"
        else:
            result["stderr"] = str(e)

    return result


def run_semgrep(code_path: str) -> dict:
    """
    Run Semgrep with OWASP Top 10 + Python rules.
    Returns parsed JSON findings or error dict.
    """
    result = run_sandboxed(
        image=SEMGREP_IMAGE,
        command=(
            "semgrep scan "
            "--config p/owasp-top-ten "
            "--config p/python "
            "--config p/javascript "
            "--json "
            "--no-git-ignore "
            "/code"
        ),
        code_path=code_path,
    )
    if result["timed_out"]:
        return {"error": "Semgrep timed out", "findings": []}

    import json
    try:
        data = json.loads(result["stdout"])
        return {"findings": data.get("results", []), "error": None}
    except json.JSONDecodeError:
        return {"error": f"Semgrep output parse error: {result['stderr'][:500]}", "findings": []}


def run_bandit(code_path: str) -> dict:
    """
    Run Bandit on Python code with medium+ severity filter.
    Returns parsed JSON findings.
    """
    result = run_sandboxed(
        image=BANDIT_IMAGE,
        command="bandit -r /code -f json -ll",  # -ll = medium+ severity only
        code_path=code_path,
    )
    if result["timed_out"]:
        return {"error": "Bandit timed out", "findings": []}

    import json
    try:
        # Bandit exits 1 when it finds issues — treat as normal
        raw = result["stdout"] or result["stderr"]
        data = json.loads(raw)
        return {"findings": data.get("results", []), "error": None}
    except json.JSONDecodeError:
        return {"error": f"Bandit output parse error", "findings": []}


def run_pylint(code_path: str) -> dict:
    """
    Run Pylint for style/quality checks on Python code.
    """
    result = run_sandboxed(
        image=PYLINT_IMAGE,
        command=(
            "python -m pylint /code "
            "--output-format=json "
            "--disable=C0114,C0115,C0116 "  # Skip docstring warnings
            "--exit-zero"
        ),
        code_path=code_path,
        timeout=60,
    )
    if result["timed_out"]:
        return {"error": "Pylint timed out", "findings": []}

    import json
    try:
        data = json.loads(result["stdout"])
        return {"findings": data, "error": None}
    except json.JSONDecodeError:
        return {"error": f"Pylint parse error", "findings": []}


def run_eslint(code_path: str) -> dict:
    """
    Run ESLint for JavaScript/TypeScript style and security checks.
    """
    result = run_sandboxed(
        image=ESLINT_IMAGE,
        command=(
            "npx eslint /code "
            "--ext .js,.jsx,.ts,.tsx "
            "--format json "
            "--no-eslintrc "
            "--rule 'no-eval: error' "
            "--rule 'no-implied-eval: error' "
            "--rule 'no-new-func: error' "
        ),
        code_path=code_path,
        timeout=60,
    )
    if result["timed_out"]:
        return {"error": "ESLint timed out", "findings": []}

    import json
    try:
        data = json.loads(result["stdout"])
        findings = []
        for file_result in data:
            for msg in file_result.get("messages", []):
                findings.append({
                    "file": file_result["filePath"],
                    "line": msg.get("line"),
                    "message": msg.get("message"),
                    "rule": msg.get("ruleId"),
                    "severity": msg.get("severity"),
                })
        return {"findings": findings, "error": None}
    except json.JSONDecodeError:
        return {"error": "ESLint parse error", "findings": []}


def write_code_to_tempdir(code_content: str, filename: str = "code.py") -> str:
    """
    Write code content to a secure temp directory for sandbox analysis.
    Returns the temp directory path (caller responsible for cleanup).
    """
    tmpdir = tempfile.mkdtemp(prefix="themis_sandbox_")
    filepath = os.path.join(tmpdir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code_content)
    return tmpdir
